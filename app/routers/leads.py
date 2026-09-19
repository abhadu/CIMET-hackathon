from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.db import get_session
from app.deps import get_pipeline
from app.models import (
    Alert,
    CheckResult,
    Lead,
    LeadStatus,
    Override,
    Plan,
    Recording,
    ScoreRun,
)
from app.schemas import (
    ActionOut,
    AlertOut,
    CheckResultOut,
    CrmPatch,
    LeadDetail,
    LeadSummary,
    OverrideIn,
    OverrideOut,
    RecordingOut,
    ReviewIn,
    ScoreRunOut,
    UtteranceOut,
)
from app.services.pipeline import SUBMITTABLE, PipelineError, ScoringPipeline
from app.transcript import Transcript

router = APIRouter(prefix="/api", tags=["leads"])


def _current_run(session: Session, lead_id: str) -> ScoreRun | None:
    return session.exec(
        select(ScoreRun).where(ScoreRun.lead_id == lead_id, ScoreRun.is_current.is_(True))  # type: ignore[union-attr]
    ).first()


def _summary(lead: Lead, run: ScoreRun | None) -> LeadSummary:
    return LeadSummary(
        id=lead.id,
        retailer_id=lead.retailer_id,
        agent_id=lead.agent_id,
        campaign=lead.campaign,
        site=lead.site,
        tl_id=lead.tl_id,
        call_date=lead.call_date,
        status=lead.status,
        status_reason=lead.status_reason,
        gate_decision=run.gate_decision if run else None,
        critical_fail_count=run.critical_fail_count if run else None,
        score_with_fatal=run.score_with_fatal if run else None,
        updated_at=lead.updated_at,
    )


def _detail(session: Session, lead: Lead) -> LeadDetail:
    run = _current_run(session, lead.id)
    plan = session.get(Plan, lead.plan_id) if lead.plan_id else None
    overrides = session.exec(
        select(Override).where(Override.lead_id == lead.id).order_by(Override.created_at)  # type: ignore[arg-type]
    ).all()
    overridden_ids = {o.check_result_id for o in overrides}

    run_out = None
    if run and run.id is not None:
        rows = session.exec(select(CheckResult).where(CheckResult.run_id == run.id).order_by(CheckResult.id)).all()
        run_out = ScoreRunOut(
            id=run.id,
            library_version=run.library_version,
            gate_decision=run.gate_decision,
            gate_reasons=run.gate_reasons,
            score_with_fatal=run.score_with_fatal,
            score_without_fatal=run.score_without_fatal,
            critical_fail_count=run.critical_fail_count,
            uncertain_count=run.uncertain_count,
            created_at=run.created_at,
            results=[
                CheckResultOut(**r.model_dump(exclude={"run_id", "check_id"}), overridden=r.id in overridden_ids)
                for r in rows
            ],
        )

    recording = session.exec(
        select(Recording).where(Recording.lead_id == lead.id).order_by(Recording.id.desc())  # type: ignore[union-attr]
    ).first()
    recording_out = None
    if recording and recording.id is not None:
        transcript = Transcript.model_validate(recording.transcript)
        has_audio = bool(recording.audio_path and Path(recording.audio_path).exists())
        recording_out = RecordingOut(
            id=recording.id,
            source=recording.source,
            has_audio=has_audio,
            audio_url=f"/api/leads/{lead.id}/audio" if has_audio else None,
            duration_s=recording.duration_s,
            timing=transcript.timing,
            utterances=[
                UtteranceOut(index=u.index, role=u.role, start=u.start, end=u.end, text=u.text)
                for u in transcript.utterances
            ],
            redactions=recording.redactions,
        )

    base = _summary(lead, run)
    return LeadDetail(
        **base.model_dump(),
        plan_id=lead.plan_id,
        plan_name=plan.name if plan else None,
        last_completed_step=lead.last_completed_step,
        crm_fields=lead.crm_fields,
        run=run_out,
        recording=recording_out,
        overrides=[OverrideOut.model_validate(o, from_attributes=True) for o in overrides],
        can_submit=lead.status in SUBMITTABLE,
    )


def _load_lead(session: Session, lead_id: str) -> Lead:
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown lead {lead_id}")
    return lead


@router.get("/leads", response_model=list[LeadSummary])
def list_leads(
    lead_status: LeadStatus | None = Query(default=None, alias="status"),
    retailer_id: str | None = None,
    agent_id: str | None = None,
    tl_id: str | None = None,
    session: Session = Depends(get_session),
) -> list[LeadSummary]:
    query = select(Lead)
    if lead_status:
        query = query.where(Lead.status == lead_status)
    if retailer_id:
        query = query.where(Lead.retailer_id == retailer_id)
    if agent_id:
        query = query.where(Lead.agent_id == agent_id)
    if tl_id:
        query = query.where(Lead.tl_id == tl_id)
    leads = session.exec(query.order_by(Lead.updated_at.desc())).all()  # type: ignore[union-attr]
    return [_summary(lead, _current_run(session, lead.id)) for lead in leads]


@router.get("/queue/tl", response_model=list[LeadSummary])
def tl_queue(tl_id: str | None = None, session: Session = Depends(get_session)) -> list[LeadSummary]:
    query = select(Lead).where(Lead.status == LeadStatus.HELD)
    if tl_id:
        query = query.where(Lead.tl_id == tl_id)
    return [_summary(lead, _current_run(session, lead.id)) for lead in session.exec(query).all()]


@router.get("/queue/qa", response_model=list[LeadSummary])
def qa_queue(session: Session = Depends(get_session)) -> list[LeadSummary]:
    query = select(Lead).where(Lead.status.in_([LeadStatus.QA_REVIEW, LeadStatus.QA_SAMPLED]))  # type: ignore[union-attr]
    return [_summary(lead, _current_run(session, lead.id)) for lead in session.exec(query).all()]


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(tl_id: str | None = None, session: Session = Depends(get_session)) -> list[AlertOut]:
    query = select(Alert)
    if tl_id:
        query = query.where(Alert.tl_id == tl_id)
    alerts = session.exec(query.order_by(Alert.created_at.desc())).all()  # type: ignore[union-attr]
    return [AlertOut.model_validate(a, from_attributes=True) for a in alerts]


@router.get("/leads/{lead_id}", response_model=LeadDetail)
def get_lead(lead_id: str, session: Session = Depends(get_session)) -> LeadDetail:
    return _detail(session, _load_lead(session, lead_id))


@router.get("/leads/{lead_id}/audio")
def get_audio(lead_id: str, session: Session = Depends(get_session)) -> FileResponse:
    recording = session.exec(
        select(Recording).where(Recording.lead_id == lead_id).order_by(Recording.id.desc())  # type: ignore[union-attr]
    ).first()
    if recording is None or not recording.audio_path or not Path(recording.audio_path).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No audio stored for this lead")
    return FileResponse(recording.audio_path)


@router.post("/leads/{lead_id}/results/{result_id}/override", response_model=LeadDetail)
def override_result(
    lead_id: str,
    result_id: int,
    payload: OverrideIn,
    session: Session = Depends(get_session),
    pipeline: ScoringPipeline = Depends(get_pipeline),
) -> LeadDetail:
    lead = _load_lead(session, lead_id)
    result = session.get(CheckResult, result_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown check result")
    run = session.get(ScoreRun, result.run_id)
    if run is None or run.lead_id != lead.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Result does not belong to this lead")
    try:
        pipeline.apply_override(session, lead, result, payload)
    except PipelineError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _detail(session, lead)


@router.post("/leads/{lead_id}/review", response_model=LeadDetail)
def review_lead(
    lead_id: str,
    payload: ReviewIn,
    session: Session = Depends(get_session),
    pipeline: ScoringPipeline = Depends(get_pipeline),
) -> LeadDetail:
    lead = _load_lead(session, lead_id)
    try:
        pipeline.record_review(session, lead, payload)
    except PipelineError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _detail(session, lead)


@router.patch("/leads/{lead_id}/crm", response_model=LeadDetail)
def patch_crm(
    lead_id: str,
    payload: CrmPatch,
    session: Session = Depends(get_session),
    pipeline: ScoringPipeline = Depends(get_pipeline),
) -> LeadDetail:
    lead = _load_lead(session, lead_id)
    try:
        pipeline.patch_crm(session, lead, payload)
    except PipelineError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _detail(session, lead)


@router.post("/leads/{lead_id}/rescore", response_model=LeadDetail)
def rescore_lead(
    lead_id: str,
    session: Session = Depends(get_session),
    pipeline: ScoringPipeline = Depends(get_pipeline),
) -> LeadDetail:
    lead = _load_lead(session, lead_id)
    try:
        pipeline.rescore(session, lead)
    except PipelineError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _detail(session, lead)


@router.post("/leads/{lead_id}/submit", response_model=ActionOut)
def submit_lead(
    lead_id: str,
    session: Session = Depends(get_session),
    pipeline: ScoringPipeline = Depends(get_pipeline),
) -> ActionOut:
    lead = _load_lead(session, lead_id)
    try:
        pipeline.submit(session, lead)
    except PipelineError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return ActionOut(lead_id=lead.id, status=lead.status, message="Sale submitted")
