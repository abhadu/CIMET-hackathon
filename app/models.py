from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LeadStatus(StrEnum):
    PENDING_RECORDING = "PENDING_RECORDING"
    TRANSCRIBING = "TRANSCRIBING"
    SCORING = "SCORING"
    AUTO_SUBMITTED = "AUTO_SUBMITTED"
    HELD = "HELD"
    QA_REVIEW = "QA_REVIEW"
    QA_SAMPLED = "QA_SAMPLED"
    RELEASED = "RELEASED"
    SUBMITTED = "SUBMITTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class GateDecision(StrEnum):
    AUTO_SUBMIT = "AUTO_SUBMIT"
    HOLD = "HOLD"
    QA_REVIEW = "QA_REVIEW"
    QA_SAMPLE = "QA_SAMPLE"


class CheckType(StrEnum):
    VERBATIM = "verbatim"
    FACTUAL = "factual"
    BEHAVIOUR = "behaviour"


class CheckOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOTE = "NOTE"
    UNCERTAIN = "UNCERTAIN"


class Retailer(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    vertical: str


class Plan(SQLModel, table=True):
    id: str = Field(primary_key=True)
    retailer_id: str = Field(foreign_key="retailer.id", index=True)
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class Agent(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    tl_id: str = Field(index=True)
    site: str


class Lead(SQLModel, table=True):
    id: str = Field(primary_key=True)
    retailer_id: str = Field(foreign_key="retailer.id", index=True)
    agent_id: str = Field(foreign_key="agent.id", index=True)
    plan_id: str | None = Field(default=None, foreign_key="plan.id")
    campaign: str
    site: str
    tl_id: str = Field(index=True)
    call_date: date = Field(index=True)
    last_completed_step: str
    crm_fields: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    status: LeadStatus = Field(default=LeadStatus.PENDING_RECORDING, index=True)
    status_reason: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Recording(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    lead_id: str = Field(foreign_key="lead.id", index=True)
    source: str
    audio_path: str | None = None
    duration_s: float
    transcript: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    redactions: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class CheckLibraryVersion(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    retailer_id: str = Field(foreign_key="retailer.id", index=True)
    version: str
    effective_from: date = Field(index=True)
    notes: str | None = None


class Check(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    library_version_id: int = Field(foreign_key="checklibraryversion.id", index=True)
    code: str = Field(index=True)
    name: str
    check_type: CheckType
    is_critical: bool
    weight: float
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class ScoreRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    lead_id: str = Field(foreign_key="lead.id", index=True)
    recording_id: int = Field(foreign_key="recording.id")
    library_version_id: int = Field(foreign_key="checklibraryversion.id")
    library_version: str
    gate_decision: GateDecision
    gate_reasons: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    score_with_fatal: float
    score_without_fatal: float
    critical_fail_count: int
    uncertain_count: int
    is_current: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)


class CheckResult(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="scorerun.id", index=True)
    check_id: int = Field(foreign_key="check.id")
    check_code: str = Field(index=True)
    check_name: str
    check_type: CheckType
    is_critical: bool
    weight: float
    result: CheckOutcome
    effective_result: CheckOutcome
    confidence: float
    quote: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None
    expected_value: str | None = None
    observed_value: str | None = None
    reasoning: str


class Override(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    check_result_id: int = Field(foreign_key="checkresult.id", index=True)
    lead_id: str = Field(foreign_key="lead.id", index=True)
    auditor: str
    original_result: CheckOutcome
    new_result: CheckOutcome
    reason: str
    created_at: datetime = Field(default_factory=utcnow)


class HumanReview(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    lead_id: str = Field(foreign_key="lead.id", index=True)
    run_id: int = Field(foreign_key="scorerun.id")
    reviewer: str
    model_decision: GateDecision
    human_decision: str
    agreed: bool
    notes: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Alert(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    agent_id: str = Field(foreign_key="agent.id", index=True)
    tl_id: str = Field(index=True)
    check_code: str
    kind: str
    message: str
    window_start: date
    window_end: date
    created_at: datetime = Field(default_factory=utcnow)
