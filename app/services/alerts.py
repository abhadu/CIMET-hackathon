from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, select

from app.config import Settings
from app.models import Alert, CheckOutcome, CheckResult, Lead, ScoreRun


def detect_repeat_offences(session: Session, lead: Lead, settings: Settings) -> list[Alert]:
    window_end = date.today()
    window_start = window_end - timedelta(days=settings.repeat_offence_window_days - 1)
    since = datetime.combine(window_start, datetime.min.time(), tzinfo=timezone.utc)

    rows = session.exec(
        select(CheckResult.check_code, CheckResult.check_name, ScoreRun.lead_id)
        .join(ScoreRun, ScoreRun.id == CheckResult.run_id)  # type: ignore[arg-type]
        .join(Lead, Lead.id == ScoreRun.lead_id)  # type: ignore[arg-type]
        .where(
            Lead.agent_id == lead.agent_id,
            ScoreRun.is_current.is_(True),  # type: ignore[union-attr]
            ScoreRun.created_at >= since,
            CheckResult.is_critical.is_(True),  # type: ignore[union-attr]
            CheckResult.effective_result == CheckOutcome.FAIL,
        )
    ).all()

    per_code: dict[str, tuple[str, set[str]]] = {}
    for code, name, lead_id in rows:
        per_code.setdefault(code, (name, set()))[1].add(lead_id)

    created: list[Alert] = []
    for code, (name, lead_ids) in per_code.items():
        if len(lead_ids) < settings.repeat_offence_threshold:
            continue
        already = session.exec(
            select(Alert).where(
                Alert.agent_id == lead.agent_id,
                Alert.check_code == code,
                Alert.kind == "repeat_offence",
                Alert.window_end >= window_end,
            )
        ).first()
        if already:
            continue
        alert = Alert(
            agent_id=lead.agent_id,
            tl_id=lead.tl_id,
            check_code=code,
            kind="repeat_offence",
            message=(
                f"'{name}' failed on {len(lead_ids)} sales in the last {settings.repeat_offence_window_days} days. "
                f"Performance-policy warning triggered."
            ),
            window_start=window_start,
            window_end=window_end,
        )
        session.add(alert)
        created.append(alert)
    if created:
        session.commit()
    return created
