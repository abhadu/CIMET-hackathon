import os
import random

import pytest

from app.config import Settings
from app.services.pipeline import ScoringPipeline
from app.services.scoring import OpenAIScorer

pytestmark = pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")


@pytest.fixture
def live_pipeline(settings: Settings) -> ScoringPipeline:
    live = settings.model_copy(update={"openai_api_key": os.environ["OPENAI_API_KEY"]})
    return ScoringPipeline(live, OpenAIScorer(live), None, rng=random.Random(1))


def test_redacted_broadband_call_is_held_for_missing_cooling_off(client, seeded, pipeline, live_pipeline):
    pipeline.scorer = live_pipeline.scorer
    from tests.conftest import text_payload

    assert client.post("/api/dialler/transcripts/text", json=text_payload(seeded, "4001001")).status_code == 202
    detail = client.get("/api/leads/4001001").json()
    results = {r["check_code"]: r for r in detail["run"]["results"]}

    assert results["REC_DISCLAIMER"]["result"] == "PASS"
    assert results["COOLING_OFF"]["result"] == "FAIL"
    assert results["PAYMENT_OFF_RECORDING"]["result"] == "PASS"
    assert results["PLAN_PRICE_PROMO"]["result"] == "PASS"
    assert detail["status"] == "HELD"


def test_worked_example_energy_call(client, seeded, pipeline, live_pipeline):
    pipeline.scorer = live_pipeline.scorer
    from tests.conftest import text_payload

    client.post("/api/dialler/transcripts/text", json=text_payload(seeded, "3613790"))
    detail = client.get("/api/leads/3613790").json()
    results = {r["check_code"]: r for r in detail["run"]["results"]}

    assert results["RATE_PEAK"]["result"] == "FAIL"
    assert results["EMAIL"]["result"] == "FAIL"
    assert results["REC_DISCLAIMER"]["result"] == "PASS"
    assert results["DMO_STATEMENT"]["result"] == "PASS"
    assert results["DEAD_AIR"]["result"] == "NOTE"
    assert results["CARD_DATA"]["result"] == "NOTE"
    assert detail["status"] == "HELD"
