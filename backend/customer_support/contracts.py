"""Strict domain records for the synthetic camera retailer."""

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

Identifier = Annotated[
    str, Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
]
Text = Annotated[str, Field(min_length=1, max_length=2000)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SupportRequest(Record):
    conversation_id: Identifier
    message: Text


class Principal(Record):
    """Server-owned identity; never accepted as an agent tool argument."""

    customer_id: Identifier


class Customer(Record):
    customer_id: Identifier
    display_name: Annotated[str, Field(min_length=1, max_length=80)]


class Provenance(Record):
    source_url: HttpUrl
    checked_on: date
    locator: Text


class Product(Record):
    product_id: Identifier
    name: Text
    kind: Literal["body", "lens", "accessory"]
    mount: Identifier | None = None
    provenance: Provenance

    @model_validator(mode="after")
    def camera_mount(self):
        if self.kind in {"body", "lens"} and self.mount is None:
            raise ValueError("Camera bodies and lenses require a mount")
        return self


class CompatibilityStatus(StrEnum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


class Compatibility(Record):
    body_id: Identifier
    lens_id: Identifier
    status: CompatibilityStatus
    explanation: Text
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def evidence_required(self):
        if self.status != CompatibilityStatus.UNKNOWN and self.provenance is None:
            raise ValueError("Established compatibility requires provenance")
        return self


class Address(Record):
    line1: Text
    city: Text
    postal_code: Annotated[str, Field(min_length=1, max_length=20)]
    country: Literal["US"]


class OrderState(StrEnum):
    PAID = "paid"
    CANCELLED = "cancelled"


class FulfillmentState(StrEnum):
    UNFULFILLED = "unfulfilled"
    LABEL_CREATED = "label_created"
    SHIPPED = "shipped"
    DELIVERED = "delivered"


class OrderLine(Record):
    product_id: Identifier
    quantity: int = Field(strict=True, ge=1, le=10)
    unit_price_cents: int = Field(strict=True, ge=0)


class Order(Record):
    order_id: Identifier
    customer_id: Identifier
    state: OrderState
    fulfillment: FulfillmentState
    placed_on: date
    delivered_on: date | None = None
    address: Address
    lines: tuple[OrderLine, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def valid_dates(self):
        if (self.fulfillment == FulfillmentState.DELIVERED) != (
            self.delivered_on is not None
        ):
            raise ValueError("Only delivered orders require a delivery date")
        if self.delivered_on and self.delivered_on < self.placed_on:
            raise ValueError("Delivery cannot precede placement")
        if (
            self.state == OrderState.CANCELLED
            and self.fulfillment != FulfillmentState.UNFULFILLED
        ):
            raise ValueError("Cancelled fixture orders must be unfulfilled")
        return self


class PolicyPassage(Record):
    policy_id: Identifier
    revision: Identifier
    locator: Identifier
    title: Text
    text: Text
    effective_on: date


class StoreFixture(Record):
    version: Identifier
    scenario_date: date
    customers: tuple[Customer, ...] = Field(min_length=1, max_length=10)
    products: tuple[Product, ...] = Field(min_length=1, max_length=30)
    orders: tuple[Order, ...] = Field(min_length=1, max_length=30)
    policies: tuple[PolicyPassage, ...] = Field(min_length=1, max_length=30)
    compatibility: tuple[Compatibility, ...] = Field(max_length=100)

    @model_validator(mode="after")
    def references(self):
        def unique(items, key):
            values = [key(item) for item in items]
            if len(values) != len(set(values)):
                raise ValueError("Duplicate fixture identifiers")
            return set(values)

        customers = unique(self.customers, lambda x: x.customer_id)
        products = unique(self.products, lambda x: x.product_id)
        unique(self.orders, lambda x: x.order_id)
        unique(self.policies, lambda x: (x.policy_id, x.revision, x.locator))
        unique(self.compatibility, lambda x: (x.body_id, x.lens_id))
        catalog = {x.product_id: x for x in self.products}
        for order in self.orders:
            if order.customer_id not in customers or any(
                x.product_id not in products for x in order.lines
            ):
                raise ValueError("Unknown order customer or product")
            if order.placed_on > self.scenario_date or (
                order.delivered_on and order.delivered_on > self.scenario_date
            ):
                raise ValueError("Order dates exceed fixture scenario date")
        for policy in self.policies:
            if policy.effective_on > self.scenario_date:
                raise ValueError("Policy not yet effective")
        for pair in self.compatibility:
            if pair.body_id not in products or pair.lens_id not in products:
                raise ValueError("Unknown compatibility product")
            if (
                catalog[pair.body_id].kind != "body"
                or catalog[pair.lens_id].kind != "lens"
            ):
                raise ValueError("Compatibility requires a body and lens")
        return self


class OrderLookup(Record):
    status: Literal["found", "not_found"]
    order: Order | None = None

    @model_validator(mode="after")
    def consistent(self):
        if (self.status == "found") != (self.order is not None):
            raise ValueError("Order lookup status disagrees with payload")
        return self


class RecordLookupRequest(Record):
    record_id: Identifier


class CompatibilityRequest(Record):
    body_id: Identifier
    lens_id: Identifier
