"""Read-only mock authoritative store. No provider or model calls."""

import json
from pathlib import Path
from string import Formatter

from .contracts import (
    Compatibility,
    CompatibilityRequest,
    CompatibilityStatus,
    Order,
    OrderLookup,
    OrderReview,
    OrderState,
    PolicyPassage,
    Principal,
    Product,
    RecordLookupRequest,
    StoreFixture,
)

DEFAULT_FIXTURE = Path(__file__).parent / "fixtures" / "store_v1.json"


class FixtureError(ValueError):
    """Fixture unavailable or invalid; callers must not silently continue."""


class MockStore:
    def __init__(self, fixture: StoreFixture):
        values = fixture.rules.model_dump()
        values["cancellation_states"] = ", ".join(fixture.rules.cancellation_states)
        values["address_change_states"] = ", ".join(fixture.rules.address_change_states)
        passages = []
        for passage in fixture.policies:
            if any(
                field and field not in values
                for _, field, _, _ in Formatter().parse(passage.text)
            ):
                raise ValueError("Unknown policy rule placeholder")
            passages.append(
                passage.model_copy(update={"text": passage.text.format(**values)})
            )
        self.fixture = fixture.model_copy(update={"policies": tuple(passages)})

    @classmethod
    def load(cls, path: Path = DEFAULT_FIXTURE):
        try:
            return cls(StoreFixture.model_validate_json(path.read_text()))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise FixtureError(
                f"Could not load store fixture: {type(exc).__name__}"
            ) from exc

    def sign_in(self, customer_id: str) -> "CustomerStore":
        """Demo server session creation, not a tool exposed to the model."""
        principal = Principal(customer_id=customer_id)
        if not any(
            c.customer_id == principal.customer_id for c in self.fixture.customers
        ):
            raise ValueError("Unknown demo identity")
        return CustomerStore(self, principal)

    def product(self, product_id: str) -> Product | None:
        product_id = RecordLookupRequest(record_id=product_id).record_id
        return next(
            (p for p in self.fixture.products if p.product_id == product_id), None
        )

    def policies(self, policy_id: str | None = None) -> tuple[PolicyPassage, ...]:
        if policy_id is not None:
            policy_id = RecordLookupRequest(record_id=policy_id).record_id
        return tuple(
            p
            for p in self.fixture.policies
            if policy_id is None or p.policy_id == policy_id
        )

    def compatibility(self, body_id: str, lens_id: str) -> Compatibility:
        args = CompatibilityRequest(body_id=body_id, lens_id=lens_id)
        body_id, lens_id = args.body_id, args.lens_id
        for pair in self.fixture.compatibility:
            if pair.body_id == body_id and pair.lens_id == lens_id:
                return pair
        return Compatibility(
            body_id=body_id,
            lens_id=lens_id,
            status=CompatibilityStatus.UNKNOWN,
            explanation="This exact body/lens combination has not been established in the catalog. Adapter compatibility and feature support are outside this lookup.",
        )


class CustomerStore:
    """Bind identity once; order methods accept no customer argument."""

    def __init__(self, store: MockStore, principal: Principal):
        self._store = store
        self._principal = principal

    def orders(self) -> tuple[Order, ...]:
        return tuple(
            o
            for o in self._store.fixture.orders
            if o.customer_id == self._principal.customer_id
        )

    def order(self, order_id: str) -> OrderLookup:
        order_id = RecordLookupRequest(record_id=order_id).record_id
        order = next((o for o in self.orders() if o.order_id == order_id), None)
        return OrderLookup(status="found" if order else "not_found", order=order)


def review_order(order: Order, store: MockStore) -> OrderReview:
    """Read-only rule evaluation. These flags are not approval or execution."""
    rules = store.fixture.rules
    days = (
        (store.fixture.scenario_date - order.delivered_on).days
        if order.delivered_on
        else None
    )
    return OrderReview(
        days_since_delivery=days,
        return_within_review_window=days <= rules.return_window_days
        if days is not None
        else None,
        warranty_within_review_window=days <= rules.warranty_review_days
        if days is not None
        else None,
        cancellation_state_eligible=order.state == OrderState.PAID
        and order.fulfillment.value in rules.cancellation_states,
        address_change_state_eligible=order.state == OrderState.PAID
        and order.fulfillment.value in rules.address_change_states,
    )
