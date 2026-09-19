from __future__ import annotations

import random
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app import db as app_db
from app.config import Settings
from app.deps import get_pipeline
from app.main import app
from app.seed import ROOT, import_libraries, import_reference
from app.services.pipeline import ScoringPipeline
from app.services.scoring import CheckVerdict, ScoringOutput

DEFAULT_VERDICT = {
    "result": "PASS", "confidence": 0.95, "quote": None, "utterance_index": None,
    "observed_value": None, "expected_value": None,
}


class StubScorer:
    """Returns canned verdicts; anything not listed passes. Tests set `overrides` before ingesting."""

    def __init__(self) -> None:
        self.overrides: dict[str, dict] = {}
        self.prompts: list[str] = []

    def score(self, system_prompt: str, user_prompt: str) -> ScoringOutput:
        self.prompts.append(user_prompt)
        codes = [line.split("code=")[1].split(" |")[0] for line in user_prompt.splitlines() if line.startswith("- code=")]
        verdicts = []
        for code in codes:
            data = {**DEFAULT_VERDICT, "code": code, "reasoning": f"stub {code}", **self.overrides.get(code, {})}
            verdicts.append(CheckVerdict(**data))
        return ScoringOutput(verdicts=verdicts)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}", storage_dir=tmp_path / "storage",
        qa_sample_rate=0.0, openai_api_key=None, deepgram_api_key=None,
    )


@pytest.fixture
def engine(settings: Settings):
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    app_db.set_engine(engine)
    import app.models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    yield engine
    app_db.set_engine(None)  # type: ignore[arg-type]


@pytest.fixture
def session(engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


@pytest.fixture
def scorer() -> StubScorer:
    return StubScorer()


@pytest.fixture
def pipeline(settings: Settings, scorer: StubScorer) -> ScoringPipeline:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return ScoringPipeline(settings, scorer, None, rng=random.Random(7))


@pytest.fixture
def seeded(session: Session) -> list[dict]:
    leads = import_reference(session)
    import_libraries(session)
    return leads


@pytest.fixture
def client(engine, pipeline: ScoringPipeline) -> Iterator[TestClient]:
    app.dependency_overrides[get_pipeline] = lambda: pipeline
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def text_payload(seeded: list[dict], lead_id: str) -> dict:
    spec = next(lead for lead in seeded if lead["id"] == lead_id)
    return {
        "lead_id": lead_id,
        "text": (ROOT / spec["transcript"]["file"]).read_text(encoding="utf-8"),
        "speaker_roles": spec["transcript"].get("speaker_roles"),
    }
