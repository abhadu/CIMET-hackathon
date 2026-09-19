from __future__ import annotations

import copy
import logging
import random
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.config import Settings
from app.db import session_scope
from app.models import (
    Check,
    CheckResult,
    GateDecision,
    HumanReview,
    Lead,
    LeadStatus,
    Override,
    Plan,
    Recording,
    ScoreRun,
    utcnow,
)
from app.schemas import CrmPatch, OverrideIn, ReviewIn
from app.services.alerts import detect_repeat_offences
from app.services.check_library import load_checks, resolve_version
from app.services.gate import GateResult, decide_gate
from app.services.redaction import redact_card_numbers
from app.services.scoring import CheckEvaluation, Evidence, Scorer, score_call
from app.services.transcription import Transcriber, TranscriptionError
from app.transcript import Transcript

log = logging.getLogger(__name__)

_DECISION_TO_STATUS = {
    GateDecision.AUTO_SUBMIT: LeadStatus.AUTO_SUBMITTED,
    GateDecision.HOLD: LeadStatus.HELD,
    GateDecision.QA_REVIEW: LeadStatus.QA_REVIEW,
    GateDecision.QA_SAMPLE: LeadStatus.QA_SAMPLED,
}

SUBMITTABLE = {LeadStatus.AUTO_SUBMITTED, LeadStatus.RELEASED}


class PipelineError(RuntimeError):
    pass


class ScoringPipeline:
    def __init__(
        self, settings: Settings, scorer: Scorer, transcriber: Transcriber | None, rng: random.Random | None = None
    ) -> None:
        self.settings = settings
        self.scorer = scorer
        self.transcriber = transcriber
        self.rng = rng or random.Random()

    def accept_audio(self, session: Session, lead: Lead, audio: bytes, content_type: str, filename: str) -> Path:
        if self.transcriber is None:
            raise PipelineError("No transcription provider configured (set DEEPGRAM_API_KEY).")
        target = self.settings.storage_dir / "audio" / f"{lead.id}{Path(filename).suffix or '.wav'}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(audio)
        self._set_status(session, lead, LeadStatus.TRANSCRIBING, "Recording received from dialler")
        return target

    def process_audio(self, lead_id: str, audio_path: Path, content_type: str) -> None:
        with session_scope() as session:
            lead = session.get(Lead, lead_id)
            if lead is None or self.transcriber is None:
                return
            try:
                transcript = self.transcriber.transcribe(audio_path.read_bytes(), content_type)
            except TranscriptionError as exc:
                log.exception("transcription failed for lead %s", lead_id)
                self._set_status(session, lead, LeadStatus.FAILED, f"Transcription failed: {exc}")
                return
            self.store_and_score(session, lead, transcript, source="dialler_audio", audio_path=str(audio_path))

    def process_transcript(self, lead_id: str, transcript: Transcript, source: str) -> None:
        with session_scope() as session:
            lead = session.get(Lead, lead_id)
            if lead is not None:
                self.store_and_score(session, lead, transcript, source=source, audio_path=None)

    def store_and_score(
        self, session: Session, lead: Lead, transcript: Transcript, source: str, audio_path: str | None
    ) -> ScoreRun | None:
        clean, redactions = redact_card_numbers(transcript)
        recording = Recording(
            lead_id=lead.id,
            source=source,
            audio_path=audio_path,
            duration_s=clean.duration,
            transcript=clean.model_dump(),
            redactions=[r.model_dump() for r in redactions],
        )
        session.add(recording)
        session.commit()
        session.refresh(recording)
        return self.score_recording(session, lead, recording)

    def rescore(self, session: Session, lead: Lead) -> ScoreRun | None:
        recording = session.exec(
            select(Recording).where(Recording.lead_id == lead.id).order_by(Recording.id.desc())  # type: ignore[union-attr]
        ).first()
        if recording is None:
            raise PipelineError("Lead has no transcript to score yet.")
        return self.score_recording(session, lead, recording)

    def score_recording(self, session: Session, lead: Lead, recording: Recording) -> ScoreRun | None:
        self._set_status(session, lead, LeadStatus.SCORING, None)
        version = resolve_version(session, lead.retailer_id, lead.call_date)
        if version is None or version.id is None:
            self._set_status(
                session, lead, LeadStatus.HELD,
                f"No check library in effect for {lead.retailer_id} on {lead.call_date}; cannot score, so held.",
            )
            return None
        checks = load_checks(session, version.id)
        plan = session.get(Plan, lead.plan_id) if lead.plan_id else None
        transcript = Transcript.model_validate(recording.transcript)

        evaluations = score_call(checks, transcript, lead, plan, self.scorer, self.settings)
        gate = decide_gate(
            evaluations,
            consent_codes={c.code for c in checks if "consent" in c.tags},
            sample_draw=self.rng.random(),
            sample_rate=self.settings.qa_sample_rate,
        )
        run = self._persist_run(session, lead, recording, version.id, version.version, evaluations, gate)
        self._set_status(session, lead, _DECISION_TO_STATUS[gate.decision], "; ".join(gate.reasons))
        detect_repeat_offences(session, lead, self.settings)
        return run

    def _persist_run(
        self, session: Session, lead: Lead, recording: Recording, version_id: int, version_label: str,
        evaluations: list[CheckEvaluation], gate: GateResult,
    ) -> ScoreRun:
        for old in session.exec(select(ScoreRun).where(ScoreRun.lead_id == lead.id, ScoreRun.is_current.is_(True))):  # type: ignore[union-attr]
            old.is_current = False
            session.add(old)
        run = ScoreRun(
            lead_id=lead.id,
            recording_id=recording.id or 0,
            library_version_id=version_id,
            library_version=version_label,
            gate_decision=gate.decision,
            gate_reasons=gate.reasons,
            score_with_fatal=gate.score_with_fatal,
            score_without_fatal=gate.score_without_fatal,
            critical_fail_count=gate.critical_fail_count,
            uncertain_count=gate.uncertain_count,
        )
        session.add(run)
        session.flush()
        for ev in evaluations:
            session.add(
                CheckResult(
                    run_id=run.id or 0,
                    check_id=ev.check_id,
                    check_code=ev.check_code,
                    check_name=ev.check_name,
                    check_type=ev.check_type,
                    is_critical=ev.is_critical,
                    weight=ev.weight,
                    result=ev.result,
                    effective_result=ev.result,
                    confidence=ev.confidence,
                    quote=ev.evidence.quote,
                    start_ms=ev.evidence.start_ms,
                    end_ms=ev.evidence.end_ms,
                    speaker=ev.evidence.speaker,
                    expected_value=ev.expected_value,
                    observed_value=ev.observed_value,
                    reasoning=ev.reasoning,
                )
            )
        session.commit()
        session.refresh(run)
        return run

    def apply_override(self, session: Session, lead: Lead, result: CheckResult, payload: OverrideIn) -> ScoreRun:
        run = session.get(ScoreRun, result.run_id)
        if run is None or not run.is_current:
            raise PipelineError("Overrides can only be applied to the current score run.")
        session.add(
            Override(
                check_result_id=result.id or 0,
                lead_id=lead.id,
                auditor=payload.auditor,
                original_result=result.effective_result,
                new_result=payload.new_result,
                reason=payload.reason,
            )
        )
        result.effective_result = payload.new_result
        session.add(result)
        session.flush()
        self._recompute_run(session, run)
        if run.gate_decision in (GateDecision.AUTO_SUBMIT, GateDecision.QA_SAMPLE):
            self._set_status(session, lead, LeadStatus.RELEASED, f"Cleared by {payload.auditor} override")
        else:
            self._set_status(session, lead, _DECISION_TO_STATUS[run.gate_decision], "; ".join(run.gate_reasons))
        return run

    def _recompute_run(self, session: Session, run: ScoreRun) -> None:
        rows = session.exec(select(CheckResult).where(CheckResult.run_id == run.id)).all()
        checks = session.exec(select(Check).where(Check.library_version_id == run.library_version_id)).all()
        evaluations = [
            CheckEvaluation(
                check_id=r.check_id, check_code=r.check_code, check_name=r.check_name, check_type=r.check_type,
                is_critical=r.is_critical, weight=r.weight, result=r.effective_result, confidence=r.confidence,
                evidence=Evidence(), reasoning=r.reasoning,
            )
            for r in rows
        ]
        keep_sample = run.gate_decision == GateDecision.QA_SAMPLE
        gate = decide_gate(
            evaluations, {c.code for c in checks if "consent" in c.tags},
            sample_draw=0.0 if keep_sample else 1.0, sample_rate=1.0,
        )
        run.gate_decision = gate.decision
        run.gate_reasons = gate.reasons
        run.score_with_fatal = gate.score_with_fatal
        run.score_without_fatal = gate.score_without_fatal
        run.critical_fail_count = gate.critical_fail_count
        run.uncertain_count = gate.uncertain_count
        session.add(run)
        session.commit()

    def record_review(self, session: Session, lead: Lead, payload: ReviewIn) -> HumanReview:
        run = session.exec(select(ScoreRun).where(ScoreRun.lead_id == lead.id, ScoreRun.is_current.is_(True))).first()  # type: ignore[union-attr]
        if run is None or run.id is None:
            raise PipelineError("Lead has not been scored yet.")
        model_clean = run.gate_decision in (GateDecision.AUTO_SUBMIT, GateDecision.QA_SAMPLE)
        review = HumanReview(
            lead_id=lead.id, run_id=run.id, reviewer=payload.reviewer, model_decision=run.gate_decision,
            human_decision=payload.decision, agreed=(payload.decision == "approve") == model_clean, notes=payload.notes,
        )
        session.add(review)
        if payload.decision == "approve":
            self._set_status(session, lead, LeadStatus.RELEASED, f"Approved by {payload.reviewer}")
        else:
            self._set_status(session, lead, LeadStatus.CANCELLED, f"Rejected by {payload.reviewer}")
        session.commit()
        session.refresh(review)
        return review

    def patch_crm(self, session: Session, lead: Lead, payload: CrmPatch) -> ScoreRun | None:
        merged = copy.deepcopy(lead.crm_fields)
        for path, value in payload.fields.items():
            _set_path(merged, path, value)
        lead.crm_fields = merged
        lead.updated_at = utcnow()
        session.add(lead)
        session.commit()
        return self.rescore(session, lead) if payload.rescore else None

    def submit(self, session: Session, lead: Lead) -> Lead:
        if lead.status not in SUBMITTABLE:
            raise PipelineError(
                f"Sale cannot be submitted while status is {lead.status}. "
                "Every critical check must pass, or a human must release it."
            )
        self._set_status(session, lead, LeadStatus.SUBMITTED, "Submitted to retailer")
        return lead

    def _set_status(self, session: Session, lead: Lead, status: LeadStatus, reason: str | None) -> None:
        lead.status = status
        lead.status_reason = reason
        lead.updated_at = utcnow()
        session.add(lead)
        session.commit()
        session.refresh(lead)


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = data
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value
