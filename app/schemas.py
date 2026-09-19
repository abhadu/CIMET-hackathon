from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models import CheckOutcome, CheckType, GateDecision, LeadStatus


class WordIn(BaseModel):
    text: str
    start: float
    end: float
    speaker: int = 0
    confidence: float = 1.0


class TranscriptIngest(BaseModel):
    lead_id: str
    words: list[WordIn] = Field(min_length=1)
    duration: float | None = None
    speaker_roles: dict[int, str] | None = None
    source: str = "dialler_transcript"


class TranscriptTextIngest(BaseModel):
    lead_id: str
    text: str = Field(min_length=1, description="Lines of 'Speaker N: ...'; '[silence 47s]' lines mark dead air")
    speaker_roles: dict[int, str] | None = None
    source: str = "transcript_text"


class IngestAccepted(BaseModel):
    lead_id: str
    status: LeadStatus
    message: str


class CheckResultOut(BaseModel):
    id: int
    check_code: str
    check_name: str
    check_type: CheckType
    is_critical: bool
    weight: float
    result: CheckOutcome
    effective_result: CheckOutcome
    confidence: float
    quote: str | None
    start_ms: int | None
    end_ms: int | None
    speaker: str | None
    expected_value: str | None
    observed_value: str | None
    reasoning: str
    overridden: bool


class ScoreRunOut(BaseModel):
    id: int
    library_version: str
    gate_decision: GateDecision
    gate_reasons: list[str]
    score_with_fatal: float
    score_without_fatal: float
    critical_fail_count: int
    uncertain_count: int
    created_at: datetime
    results: list[CheckResultOut]


class UtteranceOut(BaseModel):
    index: int
    role: str
    start: float
    end: float
    text: str


class RecordingOut(BaseModel):
    id: int
    source: str
    has_audio: bool
    audio_url: str | None
    duration_s: float
    timing: str
    utterances: list[UtteranceOut]
    redactions: list[dict[str, Any]]


class OverrideOut(BaseModel):
    id: int
    check_result_id: int
    auditor: str
    original_result: CheckOutcome
    new_result: CheckOutcome
    reason: str
    created_at: datetime


class LeadSummary(BaseModel):
    id: str
    retailer_id: str
    agent_id: str
    campaign: str
    site: str
    tl_id: str
    call_date: date
    status: LeadStatus
    status_reason: str | None
    gate_decision: GateDecision | None
    critical_fail_count: int | None
    score_with_fatal: float | None
    updated_at: datetime


class LeadDetail(LeadSummary):
    plan_id: str | None
    plan_name: str | None
    last_completed_step: str
    crm_fields: dict[str, Any]
    run: ScoreRunOut | None
    recording: RecordingOut | None
    overrides: list[OverrideOut]
    can_submit: bool


class OverrideIn(BaseModel):
    auditor: str = Field(min_length=1)
    new_result: CheckOutcome
    reason: str = Field(min_length=3)


class ReviewIn(BaseModel):
    reviewer: str = Field(min_length=1)
    decision: str = Field(pattern="^(approve|reject)$")
    notes: str | None = None


class CrmPatch(BaseModel):
    actor: str = Field(min_length=1)
    fields: dict[str, Any]
    rescore: bool = True


class ActionOut(BaseModel):
    lead_id: str
    status: LeadStatus
    message: str


class AlertOut(BaseModel):
    id: int
    agent_id: str
    tl_id: str
    check_code: str
    kind: str
    message: str
    window_start: date
    window_end: date
    created_at: datetime


class LibraryVersionOut(BaseModel):
    id: int
    retailer_id: str
    version: str
    effective_from: date
    notes: str | None
    check_count: int
