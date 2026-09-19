from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlmodel import Session

from app.db import get_session
from app.deps import get_pipeline
from app.models import Lead, LeadStatus
from app.schemas import IngestAccepted, TranscriptIngest, TranscriptTextIngest
from app.services.pipeline import PipelineError, ScoringPipeline
from app.services.transcription import TranscriptionError, transcript_from_payload
from app.transcript import Transcript, transcript_from_text

router = APIRouter(prefix="/api/dialler", tags=["dialler"])


def _lead(session: Session, lead_id: str) -> Lead:
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown lead {lead_id}")
    return lead


def _queue(session: Session, lead: Lead, transcript: Transcript, source: str, background: BackgroundTasks, pipeline: ScoringPipeline) -> IngestAccepted:
    lead.status = LeadStatus.SCORING
    session.add(lead)
    session.commit()
    background.add_task(pipeline.process_transcript, lead.id, transcript, source)
    return IngestAccepted(lead_id=lead.id, status=LeadStatus.SCORING, message="Transcript accepted; scoring queued")


@router.post("/recordings", response_model=IngestAccepted, status_code=status.HTTP_202_ACCEPTED)
async def push_recording(
    background: BackgroundTasks,
    lead_id: str = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    pipeline: ScoringPipeline = Depends(get_pipeline),
) -> IngestAccepted:
    lead = _lead(session, lead_id)
    audio = await file.read()
    if not audio:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Empty recording")
    content_type = file.content_type or "audio/wav"
    try:
        path = pipeline.accept_audio(session, lead, audio, content_type, file.filename or "recording.wav")
    except PipelineError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    background.add_task(pipeline.process_audio, lead.id, path, content_type)
    return IngestAccepted(lead_id=lead.id, status=LeadStatus.TRANSCRIBING, message="Recording accepted; scoring queued")


@router.post("/transcripts", response_model=IngestAccepted, status_code=status.HTTP_202_ACCEPTED)
def push_transcript(
    payload: TranscriptIngest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    pipeline: ScoringPipeline = Depends(get_pipeline),
) -> IngestAccepted:
    lead = _lead(session, payload.lead_id)
    try:
        transcript = transcript_from_payload([w.model_dump() for w in payload.words], payload.duration, payload.speaker_roles)
    except TranscriptionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _queue(session, lead, transcript, payload.source, background, pipeline)


@router.post("/transcripts/text", response_model=IngestAccepted, status_code=status.HTTP_202_ACCEPTED)
def push_transcript_text(
    payload: TranscriptTextIngest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    pipeline: ScoringPipeline = Depends(get_pipeline),
) -> IngestAccepted:
    lead = _lead(session, payload.lead_id)
    try:
        transcript = transcript_from_text(payload.text, payload.speaker_roles)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _queue(session, lead, transcript, payload.source, background, pipeline)
