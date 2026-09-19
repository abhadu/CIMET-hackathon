from app.models import CheckOutcome, CheckType, GateDecision
from app.services.gate import compute_scores, decide_gate
from app.services.scoring import CheckEvaluation


def _ev(code: str, result: CheckOutcome, critical: bool = True, weight: float = 10, ctype=CheckType.FACTUAL):
    return CheckEvaluation(
        check_id=1,
        check_code=code,
        check_name=code.title(),
        check_type=ctype,
        is_critical=critical,
        weight=weight,
        result=result,
        confidence=0.9,
        reasoning="test",
    )


CONSENT = {"REC_DISCLAIMER"}


def test_all_pass_auto_submits():
    evs = [_ev("REC_DISCLAIMER", CheckOutcome.PASS), _ev("EMAIL", CheckOutcome.PASS)]
    gate = decide_gate(evs, CONSENT, sample_draw=0.5, sample_rate=0.05)
    assert gate.decision == GateDecision.AUTO_SUBMIT
    assert gate.score_with_fatal == 100.0


def test_critical_fail_holds_and_zeroes_fatal_score():
    evs = [_ev("REC_DISCLAIMER", CheckOutcome.PASS), _ev("EMAIL", CheckOutcome.FAIL)]
    gate = decide_gate(evs, CONSENT, sample_draw=0.5, sample_rate=0.05)
    assert gate.decision == GateDecision.HOLD
    assert gate.critical_fail_count == 1
    assert gate.score_with_fatal == 0.0
    assert gate.score_without_fatal == 50.0


def test_uncertain_routes_to_qa_even_when_non_critical():
    evs = [
        _ev("REC_DISCLAIMER", CheckOutcome.PASS),
        _ev("RAPPORT", CheckOutcome.UNCERTAIN, critical=False, weight=2, ctype=CheckType.BEHAVIOUR),
    ]
    assert decide_gate(evs, CONSENT, 0.5, 0.05).decision == GateDecision.QA_REVIEW


def test_missing_consent_check_never_auto_passes():
    evs = [_ev("EMAIL", CheckOutcome.PASS)]
    gate = decide_gate(evs, set(), 0.5, 0.05)
    assert gate.decision == GateDecision.HOLD
    assert "consent" in gate.reasons[0].lower()


def test_uncertain_consent_holds_rather_than_routes():
    evs = [_ev("REC_DISCLAIMER", CheckOutcome.UNCERTAIN)]
    assert decide_gate(evs, CONSENT, 0.5, 0.05).decision == GateDecision.HOLD


def test_clean_call_is_sampled():
    evs = [_ev("REC_DISCLAIMER", CheckOutcome.PASS)]
    assert decide_gate(evs, CONSENT, sample_draw=0.01, sample_rate=0.05).decision == GateDecision.QA_SAMPLE


def test_behaviour_note_lowers_score_but_never_blocks():
    evs = [
        _ev("REC_DISCLAIMER", CheckOutcome.PASS, weight=10),
        _ev("DEAD_AIR", CheckOutcome.NOTE, critical=False, weight=2, ctype=CheckType.BEHAVIOUR),
    ]
    with_fatal, without_fatal = compute_scores(evs)
    assert with_fatal == without_fatal == 83.3
    assert decide_gate(evs, CONSENT, 0.5, 0.0).decision == GateDecision.AUTO_SUBMIT
