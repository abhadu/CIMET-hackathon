from __future__ import annotations

import argparse
import copy
import json
import logging
import random
from datetime import date
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.db import init_db, session_scope
from app.deps import get_pipeline
from app.models import Agent, Lead, LeadStatus, Plan, Retailer
from app.services.check_library import LibraryExport, import_library
from app.transcript import transcript_from_text

log = logging.getLogger("seed")
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "synthetic"


def load_json(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def import_libraries(session: Session) -> None:
    r1 = LibraryExport.model_validate(load_json("check_library_R1_2026.1.json"))
    import_library(session, r1)

    r1_v2 = copy.deepcopy(r1)
    r1_v2.version = "2026.2"
    r1_v2.effective_from = date(2026, 9, 1)
    r1_v2.notes = "September revision: gift card disclosure made critical."
    for check in r1_v2.checks:
        if check.code == "GIFT_CARD":
            check.critical = True
    import_library(session, r1_v2)

    import_library(session, LibraryExport.model_validate(load_json("check_library_PA_2026.1.json")))


def import_reference(session: Session) -> list[dict]:
    ref = load_json("reference.json")
    for model, rows in ((Retailer, ref["retailers"]), (Agent, ref["agents"]), (Plan, ref["plans"])):
        for row in rows:
            if session.get(model, row["id"]) is None:
                session.add(model(**row))
    session.commit()
    for lead in ref["leads"]:
        if session.get(Lead, lead["id"]) is None:
            fields = {k: v for k, v in lead.items() if k != "transcript"}
            fields["call_date"] = date.fromisoformat(fields["call_date"])
            session.add(Lead(**fields))
    session.commit()
    return ref["leads"]


def load_transcript(spec: dict):
    source = spec["transcript"]
    roles = {int(k): v for k, v in source.get("speaker_roles", {}).items()} or None
    return transcript_from_text((ROOT / source["file"]).read_text(encoding="utf-8"), roles)


def ingest(session: Session, leads: list[dict]) -> None:
    pipeline = get_pipeline()
    pipeline.rng = random.Random(42)
    for spec in leads:
        lead = session.get(Lead, spec["id"])
        if lead is None or lead.status != LeadStatus.PENDING_RECORDING or "transcript" not in spec:
            continue
        run = pipeline.store_and_score(session, lead, load_transcript(spec), source="transcript_file", audio_path=None)
        log.info("lead %s -> %s (%s)", lead.id, lead.status, run.gate_decision if run else "no run")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed retailers, check libraries, leads and transcripts.")
    parser.add_argument("--reset", action="store_true", help="delete the SQLite database before seeding")
    parser.add_argument("--pending", action="store_true", help="create leads only; score them live with scripts/push_transcript.py")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = get_settings()
    if args.reset and settings.database_url.startswith("sqlite:///"):
        db_path = Path(settings.database_url.removeprefix("sqlite:///"))
        if db_path.exists():
            db_path.unlink()
    init_db()
    with session_scope() as session:
        leads = import_reference(session)
        import_libraries(session)
        if not args.pending:
            ingest(session, leads)
        for lead in session.exec(select(Lead)):
            log.info("%s %s %s", lead.id, lead.status, lead.status_reason or "")


if __name__ == "__main__":
    main()
