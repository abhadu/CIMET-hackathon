from fastapi.testclient import TestClient

from tests.conftest import StubScorer, text_payload


def _score(client: TestClient, seeded: list[dict], lead_id: str) -> dict:
    response = client.post("/api/dialler/transcripts/text", json=text_payload(seeded, lead_id))
    assert response.status_code == 202, response.text
    detail = client.get(f"/api/leads/{lead_id}")
    assert detail.status_code == 200
    return detail.json()


def _result(detail: dict, code: str) -> dict:
    return next(r for r in detail["run"]["results"] if r["check_code"] == code)


def test_worked_example_is_held_with_traceable_evidence(client, seeded, scorer: StubScorer):
    scorer.overrides = {
        "RATE_PEAK": {
            "result": "FAIL", "confidence": 0.97, "utterance_index": 20,
            "quote": "The peak usage rate is twenty eight point six cents per kilowatt hour",
            "observed_value": "28.6 cents", "expected_value": "31.9",
            "reasoning": "Agent quoted 28.6 cents; plan is 31.9 cents.",
        },
        "EMAIL": {
            "result": "FAIL", "confidence": 0.95, "utterance_index": 29,
            "observed_value": "j.smith@gmail.com", "expected_value": "j.smith@gmial.com",
            "reasoning": "Read back gmail.com; CRM has gmial.com.",
        },
        "REC_DISCLAIMER": {
            "utterance_index": 2,
            "quote": "This call is being recorded for quality, training and compliance purposes. Are you happy to continue?",
        },
        "DEAD_AIR": {"result": "NOTE", "utterance_index": 31, "reasoning": "47 seconds of silence after the email read-back."},
    }
    detail = _score(client, seeded, "3613790")

    assert detail["status"] == "HELD"
    assert detail["run"]["gate_decision"] == "HOLD"
    assert detail["run"]["library_version"] == "2026.2"
    assert detail["run"]["critical_fail_count"] == 2
    assert detail["run"]["score_with_fatal"] == 0.0
    assert detail["can_submit"] is False

    rate = _result(detail, "RATE_PEAK")
    assert rate["result"] == "FAIL" and rate["is_critical"]
    assert rate["expected_value"] == "31.9" and rate["observed_value"] == "28.6 cents"
    assert rate["start_ms"] is not None and rate["speaker"] == "agent"

    disclaimer = _result(detail, "REC_DISCLAIMER")
    assert disclaimer["result"] == "PASS"
    assert "similarity" in disclaimer["reasoning"].lower()
    assert disclaimer["start_ms"] is not None

    assert _result(detail, "DEAD_AIR")["result"] == "NOTE"
    assert detail["recording"]["timing"] == "estimated"
    text = " ".join(u["text"] for u in detail["recording"]["utterances"])
    assert "[REDACTED]" in text and "four five three two" not in text


def test_submit_blocked_until_overrides_clear_criticals(client, seeded, scorer: StubScorer):
    scorer.overrides = {"RATE_PEAK": {"result": "FAIL"}, "EMAIL": {"result": "FAIL"}}
    detail = _score(client, seeded, "3613790")
    assert client.post("/api/leads/3613790/submit").status_code == 409

    for code in ("RATE_PEAK", "EMAIL"):
        rid = _result(detail, code)["id"]
        response = client.post(
            f"/api/leads/3613790/results/{rid}/override",
            json={"auditor": "tl-01", "new_result": "PASS", "reason": "Re-confirmed with customer on callback."},
        )
        assert response.status_code == 200, response.text
        detail = response.json()

    assert detail["status"] == "RELEASED"
    assert len(detail["overrides"]) == 2
    assert _result(detail, "RATE_PEAK")["result"] == "FAIL"
    assert _result(detail, "RATE_PEAK")["effective_result"] == "PASS"
    assert client.post("/api/leads/3613790/submit").json()["status"] == "SUBMITTED"


def test_clean_call_auto_submits(client, seeded):
    detail = _score(client, seeded, "3613791")
    assert detail["status"] == "AUTO_SUBMITTED"
    assert detail["run"]["score_with_fatal"] == 100.0
    assert client.post("/api/leads/3613791/submit").status_code == 200


def test_missing_disclaimer_holds_on_consent(client, seeded, scorer: StubScorer):
    scorer.overrides = {"REC_DISCLAIMER": {"result": "FAIL", "utterance_index": None}}
    payload = text_payload(seeded, "3613791")
    payload["text"] = payload["text"].replace(
        "This call is being recorded for quality, training and compliance purposes. Are you happy to continue?", ""
    )
    assert client.post("/api/dialler/transcripts/text", json=payload).status_code == 202
    detail = client.get("/api/leads/3613791").json()
    assert detail["status"] == "HELD"
    assert any("consent" in r.lower() for r in detail["run"]["gate_reasons"])


def test_low_confidence_routes_to_qa_instead_of_passing(client, seeded, scorer: StubScorer):
    scorer.overrides = {"DOB": {"result": "PASS", "confidence": 0.4}}
    detail = _score(client, seeded, "3613791")
    assert detail["status"] == "QA_REVIEW"
    assert _result(detail, "DOB")["result"] == "UNCERTAIN"
    assert "3613791" in [lead["id"] for lead in client.get("/api/queue/qa").json()]


def test_behaviour_can_never_block(client, seeded, scorer: StubScorer):
    scorer.overrides = {"RAPPORT": {"result": "FAIL"}}
    detail = _score(client, seeded, "3613791")
    assert _result(detail, "RAPPORT")["result"] == "NOTE"
    assert detail["status"] == "AUTO_SUBMITTED"


def test_verbatim_pass_needs_the_cited_line_to_resemble_the_script(client, seeded, scorer: StubScorer):
    scorer.overrides = {"EIC": {"result": "PASS", "utterance_index": 1, "quote": "Yes, that's me."}}
    detail = _score(client, seeded, "3613791")
    assert _result(detail, "EIC")["result"] == "UNCERTAIN"
    assert detail["status"] == "QA_REVIEW"


def test_verbatim_fail_is_overruled_when_line_matches_script(client, seeded, scorer: StubScorer):
    scorer.overrides = {"TCS": {"result": "FAIL", "utterance_index": 22, "reasoning": "Wording differs."}}
    detail = _score(client, seeded, "3613791")
    tcs = _result(detail, "TCS")
    assert tcs["result"] == "PASS" and "word for word" in tcs["reasoning"]
    assert detail["status"] == "AUTO_SUBMITTED"


def test_scorer_outage_routes_everything_to_qa(client, seeded, pipeline):
    from app.services.scoring import UnavailableScorer

    pipeline.scorer = UnavailableScorer()
    detail = _score(client, seeded, "3613791")
    assert detail["status"] == "HELD"
    assert all(r["result"] == "UNCERTAIN" for r in detail["run"]["results"])


def test_real_redacted_transcript_scores_against_provider_a(client, seeded, scorer: StubScorer):
    scorer.overrides = {
        "COOLING_OFF": {"result": "FAIL", "confidence": 0.98, "utterance_index": None, "reasoning": "Never disclosed."},
        "CIS_PROVIDED": {"result": "FAIL", "confidence": 0.9, "utterance_index": None},
        "REC_DISCLAIMER": {"utterance_index": 3, "quote": "please be advised that this call will be recorded for quality assurance and, training purposes"},
    }
    detail = _score(client, seeded, "4001001")
    assert detail["status"] == "HELD"
    assert detail["run"]["library_version"] == "2026.1"
    assert _result(detail, "COOLING_OFF")["result"] == "FAIL"
    assert _result(detail, "REC_DISCLAIMER")["result"] == "PASS"
    assert _result(detail, "REC_DISCLAIMER")["speaker"] == "agent"
    assert detail["recording"]["utterances"][0]["role"] == "customer"
    prompt = scorer.prompts[-1]
    assert "[u3 AGENT" in prompt and 'expected="[EMAIL]"' in prompt


def test_crm_correction_rescores(client, seeded, scorer: StubScorer):
    scorer.overrides = {"EMAIL": {"result": "FAIL"}}
    _score(client, seeded, "3613790")
    scorer.overrides = {}
    response = client.patch(
        "/api/leads/3613790/crm", json={"actor": "tl-01", "fields": {"customer.email": "j.smith@gmail.com"}}
    )
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["crm_fields"]["customer"]["email"] == "j.smith@gmail.com"
    assert 'expected="j.smith@gmail.com"' in scorer.prompts[-1]
    assert detail["status"] == "AUTO_SUBMITTED"


def test_repeat_offence_alerts_tl_after_three_fails(client, seeded, scorer: StubScorer, session):
    from datetime import date

    from app.models import Lead

    for i in range(3):
        session.add(
            Lead(
                id=f"77000{i}", retailer_id="R1", agent_id="AG-A", plan_id="R1-SAVER", campaign="owned_site",
                site="Jaipur", tl_id="TL-01", call_date=date(2026, 9, 18), last_completed_step="x",
                crm_fields=seeded[0]["crm_fields"],
            )
        )
    session.commit()
    scorer.overrides = {"RATE_PEAK": {"result": "FAIL"}}
    text = text_payload(seeded, "3613790")["text"]
    for i in range(3):
        client.post("/api/dialler/transcripts/text", json={"lead_id": f"77000{i}", "text": text, "speaker_roles": {"1": "agent", "2": "customer"}})
    alerts = client.get("/api/alerts", params={"tl_id": "TL-01"}).json()
    assert len(alerts) == 1 and alerts[0]["check_code"] == "RATE_PEAK"


def test_human_review_and_dashboard(client, seeded, scorer: StubScorer):
    scorer.overrides = {"RATE_PEAK": {"result": "FAIL"}}
    _score(client, seeded, "3613790")
    scorer.overrides = {}
    _score(client, seeded, "3613791")
    assert client.post("/api/leads/3613791/review", json={"reviewer": "qa-1", "decision": "approve"}).json()["status"] == "RELEASED"

    dash = client.get("/api/dashboard", params={"period": "daily", "group_by": "tl"}).json()
    tl = next(g for g in dash["groups"] if g["key"] == "TL-01")
    assert tl["sales_scored"] == 2 and tl["held"] == 1 and tl["first_pass_yield"] == 50.0
    assert tl["top_failing_checks"][0]["code"] == "RATE_PEAK"
    assert tl["auditor_agreement_rate"] == 100.0


def test_library_versions_listed(client, seeded):
    versions = client.get("/api/library").json()
    assert {(v["retailer_id"], v["version"]) for v in versions} == {("R1", "2026.1"), ("R1", "2026.2"), ("PA", "2026.1")}


def test_unknown_lead_rejected(client, seeded):
    assert client.post("/api/dialler/transcripts/text", json={"lead_id": "nope", "text": "Speaker 1: hi"}).status_code == 404
