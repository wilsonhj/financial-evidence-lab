"""Closed extraction transport types; no persistence or financial computation."""

from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    TypeAdapter,
    field_validator,
    model_validator,
)

Action = Literal["create", "cancel", "rerun", "accept", "edit", "reject", "merge", "correct"]
RunStatus = Literal["queued", "running", "waiting_review", "succeeded", "failed", "cancelled"]
Mode = Literal["kpi", "guidance", "revenue_driver"]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractionPermissions(ClosedModel):
    workspace_id: UUID
    allowed_actions: list[Action]


class RunLimits(ClosedModel):
    max_calls: int = Field(ge=1, le=10)
    max_input_tokens: int = Field(ge=1, le=100000)
    max_output_tokens: int = Field(ge=1, le=20000)
    max_cost_usd: str
    max_wall_seconds: int = Field(ge=1, le=600)


class RunUsage(ClosedModel):
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: str


class ExtractionRun(ClosedModel):
    id: UUID
    workspace_id: UUID
    entity_id: UUID
    parent_run_id: UUID | None
    status: RunStatus
    modes: list[Mode]
    as_of: AwareDatetime
    corpus_version_id: UUID
    ontology_version: str
    workflow_version: str
    provider: str
    model: str
    limits: RunLimits
    usage: RunUsage
    version: int = Field(ge=1)
    error: dict[str, Any] | None
    created_at: AwareDatetime
    cancel_requested_at: AwareDatetime | None


DecimalString = Annotated[StrictStr, Field(pattern=r"^-?\d+(\.\d+)?$")]
NonemptyString = Annotated[StrictStr, Field(min_length=1)]
Currency = Annotated[StrictStr, Field(pattern=r"^[A-Z]{3}$")]


class Period(ClosedModel):
    type: Literal["instant", "duration", "trailing_window", "forecast"]
    instant: date | None = None
    start: date | None = None
    end: date | None = None
    fiscal_period: StrictStr | None = None

    @model_validator(mode="before")
    @classmethod
    def exact_dates(cls, value: Any) -> Any:
        if isinstance(value, dict):
            for key in ("instant", "start", "end"):
                if key in value:
                    item = value[key]
                    if not isinstance(item, str) or len(item) != 10:
                        raise ValueError("Expected an ISO date string.")
                    date.fromisoformat(item)
        return value


class PayloadCommon(ClosedModel):
    schema_version: Literal["extraction-payload/v1"]
    entity_id: UUID
    issuer_label: NonemptyString
    metric_id: NonemptyString
    raw_value: StrictStr
    period: Period
    dimensions: dict[str, StrictStr]
    definition: StrictStr | None = None
    qualifiers: dict[str, Any]

    @field_validator("entity_id", mode="before")
    @classmethod
    def uuid_string(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError("Expected a UUID string.")
        return value


class NumericPayload(PayloadCommon):
    unit: NonemptyString
    currency: Currency | None = None
    scale: StrictInt
    sign: Literal["positive", "negative", "zero"]


class KpiPayload(NumericPayload):
    kind: Literal["kpi"]
    reported_or_derived: Literal["reported", "derived"]
    value: DecimalString


class GuidanceNumeric(NumericPayload):
    kind: Literal["guidance"]
    reported_or_derived: Literal["management_assertion"]


class GuidancePoint(GuidanceNumeric):
    shape: Literal["point"]
    value: DecimalString


class GuidanceRange(GuidanceNumeric):
    shape: Literal["range"]
    low: DecimalString
    high: DecimalString


class GuidanceFloor(GuidanceNumeric):
    shape: Literal["floor"]
    low: DecimalString


class GuidanceCeiling(GuidanceNumeric):
    shape: Literal["ceiling"]
    high: DecimalString


class GuidanceQualitative(PayloadCommon):
    kind: Literal["guidance"]
    reported_or_derived: Literal["management_assertion"]
    shape: Literal["qualitative"]
    text: NonemptyString


class DriverPayload(PayloadCommon):
    kind: Literal["revenue_driver"]
    reported_or_derived: Literal["management_assertion"]
    category: Literal[
        "price",
        "volume",
        "mix",
        "acquisition",
        "retention",
        "usage",
        "seats",
        "fx",
        "services",
        "cost",
        "other",
    ]
    description: NonemptyString
    direction: Literal["positive", "negative", "mixed", "unknown"]
    target_metric_ids: list[StrictStr] = Field(min_length=1)

    @field_validator("target_metric_ids")
    @classmethod
    def distinct_targets(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Target metric IDs must be unique.")
        return value


Payload = (
    KpiPayload
    | GuidancePoint
    | GuidanceRange
    | GuidanceFloor
    | GuidanceCeiling
    | GuidanceQualitative
    | DriverPayload
)
PAYLOAD_ADAPTER: TypeAdapter[Payload] = TypeAdapter(Payload)
