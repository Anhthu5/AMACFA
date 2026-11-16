"""Schemas shared by the API, evidence tools and report renderer."""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9._/-]{0,63}$")]
Currency = Literal["USD", "VND", "EUR"]
Role = Literal["analyst", "reviewer"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_digest(data: object) -> str:
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256(encoded.encode("utf-8"))


class EvidenceBackendError(RuntimeError):
    """An explicitly selected evidence service failed."""


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Invoice(Schema):
    vendor_id: Identifier
    invoice_number: Identifier
    issued_on: date
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    currency: Currency
    requested_by: Identifier
    approved_by: Identifier | None
    account_token: Identifier | None


class Evidence(Schema):
    line: int = Field(ge=2)
    row_sha256: str
    invoice: Invoice


class Rule(StrEnum):
    DUPLICATE = "DUPLICATE_INVOICE"
    MISSING_APPROVAL = "MISSING_APPROVAL"
    SELF_APPROVAL = "SELF_APPROVAL"
    SPLIT = "POTENTIAL_SPLIT"
    SHARED_ACCOUNT = "SHARED_ACCOUNT"


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"


class Control(Schema):
    id: str
    title: str
    clause: str
    action: str
    severity: Severity
    rule: Rule


class Policy(Schema):
    version: str
    split_window_days: int = Field(ge=2, le=31)
    approval_thresholds: dict[Currency, Decimal]
    controls: list[Control]


class Citation(Schema):
    id: str
    version: str
    title: str
    clause: str


class Signal(Schema):
    rule: Rule
    lines: list[int]
    metrics: dict[str, str | int] = Field(default_factory=dict)


class Finding(Signal):
    id: str
    severity: Severity
    control: Citation
    related_controls: list[Citation]
    action: str


class StageEvent(Schema):
    stage: str
    count: int = Field(ge=0)
    elapsed_ms: int = Field(ge=0)


class ReviewRequest(Schema):
    decision: Literal["approve", "return"]
    note: str = Field(min_length=3, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class Review(ReviewRequest):
    actor: Role
    reviewed_at: datetime
    packet_sha256: str


class AuditPacket(Schema):
    audit_id: str
    input_sha256: str
    policy_sha256: str
    policy_version: str
    graph_backend: str
    vector_backend: str
    rows: list[Evidence]
    findings: list[Finding]


class ExecutiveReport(Schema):
    summary: str
    priority_finding_ids: list[str]
    ranking_source: Literal["offline", "openai", "anthropic", "fallback"]
    ranking_model: str | None
    markdown: str
    sha256: str


class AuditView(Schema):
    audit_id: str
    status: Literal["processing", "awaiting_review", "returned", "completed"]
    input_sha256: str
    policy_version: str
    packet_sha256: str | None = None
    packet: AuditPacket | None = None
    events: list[StageEvent]
    review: Review | None = None
    report: ExecutiveReport | None = None
