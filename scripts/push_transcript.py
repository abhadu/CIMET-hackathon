"""Simulate the dialler handing a finished call to the CRM.

    python scripts/push_transcript.py 3613793 data/samples/lead-3613790.txt --agent 1
    python scripts/push_transcript.py 4001002 data/samples/audio/call-redacted.wav
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("lead_id")
parser.add_argument("file", type=Path, help=".txt transcript ('Speaker N: ...') or .wav recording")
parser.add_argument("--agent", type=int, default=1, help="speaker number that is the agent (text only)")
parser.add_argument("--base", default="http://127.0.0.1:8010")
args = parser.parse_args()

with httpx.Client(base_url=args.base, timeout=120) as client:
    if args.file.suffix.lower() == ".wav":
        response = client.post(
            "/api/dialler/recordings",
            data={"lead_id": args.lead_id},
            files={"file": (args.file.name, args.file.read_bytes(), "audio/wav")},
        )
    else:
        roles = {str(args.agent): "agent", str(3 - args.agent): "customer"}
        response = client.post(
            "/api/dialler/transcripts/text",
            json={"lead_id": args.lead_id, "text": args.file.read_text(encoding="utf-8"), "speaker_roles": roles},
        )
    if response.status_code != 202:
        sys.exit(f"{response.status_code}: {response.text}")
    print(f"accepted -> {response.json()['status']}")

    started = time.time()
    while True:
        lead = client.get(f"/api/leads/{args.lead_id}").json()
        if lead["status"] not in ("TRANSCRIBING", "SCORING"):
            break
        print(f"  {lead['status'].lower()}... {time.time() - started:.0f}s", end="\r")
        time.sleep(2)

    run = lead["run"] or {}
    print(f"\n{args.lead_id}: {lead['status']}  (scored in {time.time() - started:.0f}s, library v{run.get('library_version')})")
    print(f"  {lead['status_reason']}")
    for r in run.get("results", []):
        if r["result"] != "PASS":
            ts = "" if r["start_ms"] is None else f"@{r['start_ms'] // 60000:02d}:{(r['start_ms'] // 1000) % 60:02d}"
            print(f"  {r['result']:9} {'*' if r['is_critical'] else ' '} {r['check_name']} {ts}")
    print(f"  open {args.base}/leads/{args.lead_id}")
