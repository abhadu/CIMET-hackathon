from __future__ import annotations

from pydantic import BaseModel

from app.models import CheckOutcome, GateDecision
from app.services.scoring import CheckEvaluation


class GateResult(BaseModel):
    decision: GateDecision
    reasons: list[str]
    score_with_fatal: float
    score_without_fatal: float
    critical_fail_count: int
    uncertain_count: int


def compute_scores(evaluations: list[CheckEvaluation]) -> tuple[float, float]:
    total = sum(e.weight for e in evaluations)
    if total <= 0:
        return 0.0, 0.0
    passed = sum(e.weight for e in evaluations if e.result == CheckOutcome.PASS)
    without_fatal = round(100.0 * passed / total, 1)
    with_fatal = 0.0 if any(e.blocks_sale for e in evaluations) else without_fatal
    return with_fatal, without_fatal


def decide_gate(
    evaluations: list[CheckEvaluation],
    consent_codes: set[str],
    sample_draw: float,
    sample_rate: float,
) -> GateResult:
    with_fatal, without_fatal = compute_scores(evaluations)
    critical_fails = [e for e in evaluations if e.blocks_sale]
    uncertain = [e for e in evaluations if e.result == CheckOutcome.UNCERTAIN]
    reasons: list[str] = []

    consent_results = [e for e in evaluations if e.check_code in consent_codes]
    if not consent_codes or not consent_results:
        reasons.append("No recording-consent check is configured for this retailer; consent cannot be assumed.")
    else:
        for e in consent_results:
            if e.result != CheckOutcome.PASS:
                reasons.append(f"Consent check '{e.check_name}' did not pass ({e.result}); consent is never assumed.")

    for e in critical_fails:
        reasons.append(f"Critical fail: {e.check_name}.")

    if reasons:
        decision = GateDecision.HOLD
    elif uncertain:
        decision = GateDecision.QA_REVIEW
        reasons = [f"Low confidence: {e.check_name}." for e in uncertain]
    elif sample_draw < sample_rate:
        decision = GateDecision.QA_SAMPLE
        reasons = [f"Clean call selected for the {sample_rate:.0%} human calibration sample."]
    else:
        decision = GateDecision.AUTO_SUBMIT
        reasons = ["All critical checks passed."]

    return GateResult(
        decision=decision,
        reasons=reasons,
        score_with_fatal=with_fatal,
        score_without_fatal=without_fatal,
        critical_fail_count=len(critical_fails),
        uncertain_count=len(uncertain),
    )
