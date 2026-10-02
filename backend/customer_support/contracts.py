"""Strict domain records for the synthetic camera retailer."""

from datetime import date
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Any, Literal, Union, cast, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    create_model,
    model_validator,
)

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


class PolicyRules(Record):
    return_window_days: int = Field(strict=True, ge=1, le=365)
    warranty_review_days: int = Field(strict=True, ge=1, le=3650)
    cancellation_states: tuple[Literal["unfulfilled"], ...] = Field(
        min_length=1, max_length=1
    )
    address_change_states: tuple[Literal["unfulfilled"], ...] = Field(
        min_length=1, max_length=1
    )
    ai_refund_execution: Literal[False] = False


class StoreFixture(Record):
    version: Identifier
    scenario_date: date
    rules: PolicyRules
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


class OrderReview(Record):
    days_since_delivery: int | None = Field(default=None, ge=0)
    return_within_review_window: bool | None
    warranty_within_review_window: bool | None
    cancellation_state_eligible: bool
    address_change_state_eligible: bool
    human_review_required_for_return_or_refund: Literal[True] = True
    action_executed: Literal[False] = False


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


class DemoSignIn(Record):
    customer_id: Identifier


class MessageRequest(Record):
    message: Text
    task_id: Identifier | None = None


class PolicySearchArgs(Record):
    query: Annotated[str, Field(min_length=1, max_length=500)]


class OrderArgs(Record):
    order_id: Identifier


class ProductArgs(Record):
    product_id: Identifier


class EmptyArgs(Record):
    pass


class Intent(StrEnum):
    INFORMATION = "information"
    ACTION = "action"
    HUMAN = "human"
    UNSUPPORTED = "unsupported"


class Judgment(Record):
    probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    model: Text
    usage: dict[str, Any] = Field(default_factory=dict)


class IntentJudgment(Record):
    intent: Intent
    probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    model: Text
    usage: dict[str, Any] = Field(default_factory=dict)


class Evidence(Record):
    evidence_id: Identifier
    kind: Literal["policy", "order", "catalog", "compatibility", "case"]
    source_id: Text
    locator: Text
    text: Annotated[str, Field(min_length=1, max_length=6000)]


class Claim(Record):
    text: Annotated[str, Field(min_length=1, max_length=1200)]
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=6)


class AnswerDraft(Record):
    format: Literal["paragraph", "bullet_list", "numbered_list"] = "paragraph"
    claims: tuple[Claim, ...] = Field(min_length=1, max_length=5)


class ToolCall(Record):
    name: Literal[
        "policy_search",
        "order_list",
        "order_detail",
        "catalog_list",
        "product_detail",
        "compatibility",
        "case_detail",
    ]
    arguments: dict = Field(default_factory=dict)


class ActionKind(StrEnum):
    CANCEL_ORDER = "cancel_order"
    CHANGE_ADDRESS = "change_address"


class CaseCategory(StrEnum):
    REFUND = "refund_review"
    RETURN = "return_review"
    WARRANTY = "warranty_review"
    DAMAGE = "damage_review"
    GENERAL = "general_support"


class CancelProposal(Record):
    kind: Literal["cancel_order"]
    order_id: Identifier
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=6)


class AddressProposal(Record):
    kind: Literal["change_address"]
    order_id: Identifier
    address: Address
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=6)


class CaseRequest(Record):
    kind: Literal["create_case"]
    category: CaseCategory
    order_id: Identifier | None = None
    customer_statement: Annotated[str, Field(min_length=1, max_length=1000)]
    evidence_ids: tuple[Identifier, ...] = Field(default=(), max_length=6)

    @model_validator(mode="after")
    def order_required(self):
        if self.category != CaseCategory.GENERAL and self.order_id is None:
            raise ValueError("Order-specific review requires an owned order")
        return self


OperationProposal = Annotated[
    CancelProposal | AddressProposal | CaseRequest, Field(discriminator="kind")
]


class ConfirmationRequest(Record):
    decision: Literal["confirm", "reject"]


class PendingAction(Record):
    proposal_id: Identifier
    kind: ActionKind
    order_id: Identifier
    address: Address | None = None
    state: Literal["pending", "confirmed", "rejected", "blocked"]
    expected_order_version: int = Field(ge=1)


class ReviewCase(Record):
    ticket_number: int | None = Field(default=None, ge=1)
    case_id: Identifier
    category: CaseCategory
    order_id: Identifier | None
    customer_statement: Text
    status: Literal["pending_review"] = "pending_review"
    human_decision: Literal["not_decided"] = "not_decided"
    customer_statement_is_verified: Literal[False] = False


class ActionReceipt(Record):
    receipt_id: Identifier
    proposal_id: Identifier
    kind: ActionKind
    order_id: Identifier
    outcome: Literal["executed", "rejected", "blocked"]
    reason: Identifier
    order_version: int = Field(ge=1)
    refund_executed: Literal[False] = False
    case_id: Identifier | None = None


class ModelTurn(Record):
    decision: Annotated[str, Field(min_length=1, max_length=500)]
    tool: ToolCall | None = None
    answer: AnswerDraft | None = None
    proposal: OperationProposal | None = None
    clarification: Annotated[str, Field(min_length=1, max_length=500)] | None = None

    @model_validator(mode="after")
    def one_output(self):
        if (
            sum(
                x is not None
                for x in (self.tool, self.answer, self.clarification, self.proposal)
            )
            != 1
        ):
            raise ValueError(
                "Choose exactly one tool, answer, clarification, or proposal"
            )
        return self


class ToolDecision(Record):
    kind: Literal["tool"]
    decision: Annotated[str, Field(min_length=1, max_length=500)]
    tool: ToolCall


class AnswerDecision(Record):
    kind: Literal["answer"]
    decision: Annotated[str, Field(min_length=1, max_length=500)]
    answer: AnswerDraft


class ClarificationDecision(Record):
    kind: Literal["clarification"]
    decision: Annotated[str, Field(min_length=1, max_length=500)]
    clarification: Annotated[
        str,
        Field(
            min_length=1,
            max_length=500,
            description="One concise question only, ending with ?, without an explanation or factual assertions.",
        ),
    ]

    @model_validator(mode="after")
    def question_only(self):
        if (
            not self.clarification.endswith("?")
            or self.clarification.count("?") != 1
            or "\n" in self.clarification
        ):
            raise ValueError(
                "Clarification must be one question ending in ?, without appended explanations"
            )
        return self


class ProposalDecision(Record):
    kind: Literal["proposal"]
    decision: Annotated[str, Field(min_length=1, max_length=500)]
    proposal: OperationProposal


class DecisionEnvelope(Record):
    action: Annotated[
        ToolDecision | AnswerDecision | ClarificationDecision | ProposalDecision,
        Field(discriminator="kind"),
    ]

    def as_turn(self) -> ModelTurn:
        return ModelTurn.model_validate(self.action.model_dump(exclude={"kind"}))


class FinalDecisionEnvelope(Record):
    """A terminal decision after the harness closes source selection."""

    action: Annotated[
        AnswerDecision | ClarificationDecision | ProposalDecision,
        Field(discriminator="kind"),
    ]

    def as_turn(self) -> ModelTurn:
        return ModelTurn.model_validate(self.action.model_dump(exclude={"kind"}))


@lru_cache(maxsize=128)
def scoped_decision_envelope(names: tuple[str, ...]) -> type[DecisionEnvelope]:
    """Expose only tools that the harness has made available for this turn."""
    if not names or not set(names) <= set(
        get_args(ToolCall.model_fields["name"].annotation)
    ):
        raise ValueError("Invalid available tool names")
    name_type: Any = cast(Any, Literal)[names]
    call = create_model("AvailableToolCall", __base__=ToolCall, name=(name_type, ...))
    decision = create_model(
        "AvailableToolDecision", __base__=ToolDecision, tool=(call, ...)
    )
    branches: Any = cast(Any, Union)[
        decision, AnswerDecision, ClarificationDecision, ProposalDecision
    ]
    return cast(
        type[DecisionEnvelope],
        create_model(
            "AvailableDecisionEnvelope",
            __base__=DecisionEnvelope,
            action=(Annotated[branches, Field(discriminator="kind")], ...),
        ),
    )


class ConversationTurn(Record):
    stop_reason: Identifier | None = None
    task_id: Identifier | None = None
    case_ids: tuple[Identifier, ...] = Field(default=(), max_length=10)
    proposal_ids: tuple[Identifier, ...] = Field(default=(), max_length=10)
    order_ids: tuple[Identifier, ...] = Field(default=(), max_length=10)
    product_ids: tuple[Identifier, ...] = Field(default=(), max_length=10)
    question: Text
    answer: Annotated[str, Field(max_length=6500)]


class SupportStep(Record):
    sequence: int = Field(ge=1)
    stage: Identifier
    details: dict = Field(default_factory=dict)


TaskKind = Literal["cancel_order", "change_address", "human_review"]


class TaskRoute(Record):
    route: Literal["new", "resume", "correct", "abandon", "clarify"]
    task_id: Identifier | None = None
    task_kind: TaskKind | None = None
    probability: float = Field(default=1, ge=0, le=1)
    confidence_gap: float | None = Field(default=None, ge=0, le=1)
    usage: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def target_required(self):
        if self.route in {"resume", "correct", "abandon"} and self.task_id is None:
            raise ValueError("Continuation requires a task target")
        if self.route in {"new", "clarify"} and self.task_id is not None:
            raise ValueError("New or ambiguous route cannot select a task")
        return self


class TaskResources(Record):
    executions: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)


class TaskResourceLimits(Record):
    executions: int = Field(default=12, ge=1)
    tokens: int = Field(default=60000, ge=1)
    tool_calls: int = Field(default=24, ge=1)


class SavedPolicyEvidence(Record):
    source_run_id: Identifier
    evidence: Evidence

    @model_validator(mode="after")
    def policy_only(self):
        if self.evidence.kind != "policy":
            raise ValueError("Only policy passages may be reused")
        return self


class TaskCheckpoint(Record):
    task_id: Identifier
    kind: TaskKind = "cancel_order"
    status: Literal[
        "active",
        "awaiting_clarification",
        "awaiting_customer_decision",
        "awaiting_approval",
        "completed",
        "failed",
        "abandoned",
    ] = "active"
    goal: Annotated[str, Field(min_length=1, max_length=1000)]
    selected_order_ids: tuple[Identifier, ...] = Field(default=(), max_length=10)
    pending_proposal_id: Identifier | None = None
    pending_question: Annotated[str, Field(max_length=6500)] | None = None
    last_answer: Annotated[str, Field(max_length=6500)] = ""
    version: int = Field(default=1, ge=1)
    completed_steps: tuple[Identifier, ...] = Field(default=(), max_length=40)
    evidence_run_id: Identifier | None = None
    evidence_ids: tuple[Identifier, ...] = Field(default=(), max_length=30)
    case_ids: tuple[Identifier, ...] = Field(default=(), max_length=10)
    resources: TaskResources = Field(default_factory=TaskResources)
    saved_policy: tuple[SavedPolicyEvidence, ...] = Field(default=(), max_length=12)


class SupportResponse(Record):
    run_id: Identifier
    conversation_id: Identifier
    disposition: Literal[
        "answered",
        "clarification",
        "handoff_needed",
        "awaiting_confirmation",
        "case_created",
        "action_completed",
        "action_blocked",
        "action_rejected",
    ]
    answer: Annotated[str, Field(max_length=6500)]
    stop_reason: Identifier
    approved_operation: OperationProposal | None = Field(default=None, exclude=True)
    pending_action: PendingAction | None = None
    review_case: ReviewCase | None = None
    receipt: ActionReceipt | None = None
    evidence: tuple[Evidence, ...] = ()
    steps: tuple[SupportStep, ...] = ()
    usage: dict[str, dict[str, Any]] = Field(default_factory=dict)
    embedding_model: str | None = None
    fixture_version: Identifier
    task: TaskCheckpoint | None = None


class PolicyVector(Record):
    policy_id: Identifier
    locator: Identifier
    text: Text
    vector: tuple[float, ...] = Field(min_length=1, max_length=4096)


class PolicyIndex(Record):
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    embedding_model: Text
    passages: tuple[PolicyVector, ...] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def valid_vectors(self):
        import math

        dimensions = {len(x.vector) for x in self.passages}
        keys = [(x.policy_id, x.locator) for x in self.passages]
        if len(dimensions) != 1 or len(keys) != len(set(keys)):
            raise ValueError("Index vectors/keys are inconsistent")
        if any(not math.isfinite(v) for x in self.passages for v in x.vector):
            raise ValueError("Nonfinite embedding")
        return self
