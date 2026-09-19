from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel
from sqlmodel import Session, select

from app.models import Alert, CheckOutcome, CheckResult, GateDecision, HumanReview, Lead, ScoreRun

Period = Literal["daily", "weekly", "monthly"]
GroupBy = Literal["agent", "retailer", "campaign", "site", "tl"]

_PERIOD_DAYS: dict[str, int] = {"daily": 1, "weekly": 7, "monthly": 30}
_GROUP_ATTR: dict[str, str] = {
    "agent": "agent_id",
    "retailer": "retailer_id",
    "campaign": "campaign",
    "site": "site",
    "tl": "tl_id",
}


class FailingCheck(BaseModel):
    code: str
    name: str
    count: int


class GroupStats(BaseModel):
    key: str
    sales_scored: int
    auto_submitted: int
    held: int
    qa_review: int
    qa_sampled: int
    first_pass_yield: float
    critical_fail_rate: float
    avg_score_with_fatal: float
    avg_score_without_fatal: float
    top_failing_checks: list[FailingCheck]
    auditor_agreement_rate: float | None
    human_reviews: int
    repeat_offence_alerts: int


class DailyPoint(BaseModel):
    day: date
    scored: int
    held: int


class Dashboard(BaseModel):
    period: str
    group_by: str
    window_start: date
    window_end: date
    groups: list[GroupStats]
    series: list[DailyPoint]


def build_dashboard(session: Session, period: Period, group_by: GroupBy) -> Dashboard:
    days = _PERIOD_DAYS[period]
    window_end = date.today()
    window_start = window_end - timedelta(days=days - 1)
    since = datetime.combine(window_start, datetime.min.time(), tzinfo=timezone.utc)

    runs = session.exec(
        select(ScoreRun, Lead)
        .join(Lead, Lead.id == ScoreRun.lead_id)  # type: ignore[arg-type]
        .where(ScoreRun.is_current.is_(True), ScoreRun.created_at >= since)  # type: ignore[union-attr]
    ).all()
    run_ids = [r.id for r, _ in runs if r.id is not None]
    results = (
        session.exec(
            select(CheckResult).where(
                CheckResult.run_id.in_(run_ids),  # type: ignore[union-attr]
                CheckResult.is_critical.is_(True),  # type: ignore[union-attr]
                CheckResult.effective_result == CheckOutcome.FAIL,
            )
        ).all()
        if run_ids
        else []
    )
    reviews = (
        session.exec(select(HumanReview).where(HumanReview.run_id.in_(run_ids))).all()  # type: ignore[union-attr]
        if run_ids
        else []
    )
    alerts = session.exec(select(Alert).where(Alert.created_at >= since)).all()

    attr = _GROUP_ATTR[group_by]
    run_group: dict[int, str] = {}
    grouped: dict[str, list[tuple[ScoreRun, Lead]]] = defaultdict(list)
    for run, lead in runs:
        key = str(getattr(lead, attr))
        grouped[key].append((run, lead))
        if run.id is not None:
            run_group[run.id] = key

    fails_by_group: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
    for res in results:
        fails_by_group[run_group.get(res.run_id, "?")][(res.check_code, res.check_name)] += 1
    reviews_by_group: dict[str, list[HumanReview]] = defaultdict(list)
    for rev in reviews:
        reviews_by_group[run_group.get(rev.run_id, "?")].append(rev)
    alerts_by_group: Counter[str] = Counter()
    for alert in alerts:
        alerts_by_group[_alert_key(alert, group_by, session)] += 1

    groups: list[GroupStats] = []
    for key, items in sorted(grouped.items()):
        n = len(items)
        decisions = Counter(run.gate_decision for run, _ in items)
        clean = decisions[GateDecision.AUTO_SUBMIT] + decisions[GateDecision.QA_SAMPLE]
        with_crit = sum(1 for run, _ in items if run.critical_fail_count > 0)
        revs = reviews_by_group.get(key, [])
        groups.append(
            GroupStats(
                key=key,
                sales_scored=n,
                auto_submitted=decisions[GateDecision.AUTO_SUBMIT],
                held=decisions[GateDecision.HOLD],
                qa_review=decisions[GateDecision.QA_REVIEW],
                qa_sampled=decisions[GateDecision.QA_SAMPLE],
                first_pass_yield=round(100.0 * clean / n, 1),
                critical_fail_rate=round(100.0 * with_crit / n, 1),
                avg_score_with_fatal=round(sum(r.score_with_fatal for r, _ in items) / n, 1),
                avg_score_without_fatal=round(sum(r.score_without_fatal for r, _ in items) / n, 1),
                top_failing_checks=[
                    FailingCheck(code=c, name=nm, count=cnt)
                    for (c, nm), cnt in fails_by_group.get(key, Counter()).most_common(5)
                ],
                auditor_agreement_rate=(
                    round(100.0 * sum(1 for r in revs if r.agreed) / len(revs), 1) if revs else None
                ),
                human_reviews=len(revs),
                repeat_offence_alerts=alerts_by_group.get(key, 0),
            )
        )

    per_day: dict[date, DailyPoint] = {
        window_start + timedelta(days=i): DailyPoint(day=window_start + timedelta(days=i), scored=0, held=0)
        for i in range(days)
    }
    for run, _ in runs:
        day = run.created_at.date()
        if day in per_day:
            per_day[day].scored += 1
            if run.gate_decision == GateDecision.HOLD:
                per_day[day].held += 1

    return Dashboard(
        period=period,
        group_by=group_by,
        window_start=window_start,
        window_end=window_end,
        groups=groups,
        series=list(per_day.values()),
    )


def _alert_key(alert: Alert, group_by: str, session: Session) -> str:
    if group_by == "agent":
        return alert.agent_id
    if group_by == "tl":
        return alert.tl_id
    lead = session.exec(select(Lead).where(Lead.agent_id == alert.agent_id)).first()
    return str(getattr(lead, _GROUP_ATTR[group_by])) if lead else "?"
