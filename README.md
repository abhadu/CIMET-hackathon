# QA Gate — score the sale before it ships

Every sale is scored against its retailer's checklist from the call transcript before it can be submitted.
All critical checks pass: the sale auto-submits. Any critical fail: it is held, and the team lead sees the exact
failing line, the quote, the timestamp, and why. Low confidence never auto-passes; it goes to QA.

## How it works

```
dialler / transcript  ->  redact card numbers  ->  one LLM call (checklist + CRM values + transcript)
                      ->  gate (critical fail = HOLD, low confidence = QA, else AUTO_SUBMIT, 5% sampled)
                      ->  lead page: pass/fail per check with quote + timestamp, override log, dashboard
```

- `app/transcript.py` — transcript model. Accepts Deepgram-style words or plain `Speaker N: ...` text
  (timestamps estimated when no audio exists). `[silence 47s]` lines mark dead air.
- `app/services/scoring.py` — the checklist, CRM/plan values and numbered transcript go to
  `ChatOpenAI(...).with_structured_output(...)`; one verdict per check comes back. Code then enforces the rules:
  behaviour never blocks, low confidence becomes UNCERTAIN, a verbatim PASS must cite a line that resembles the script.
- `app/services/gate.py` — gate decision and score with/without fatal factors.
- `app/services/redaction.py` — spoken or typed card numbers (Luhn-valid) are replaced before storage.
- `app/services/check_library.py` — versioned checklists; a call is scored against the version live on its call date.
- `app/services/pipeline.py` — ingestion, scoring, overrides (logged, never dropped), CRM correction + rescore, submit gate.
- `app/services/metrics.py` — agent / TL / retailer / campaign / site rollups, first-pass yield, repeat offences, auditor agreement.

## Run it

```bash
python -m venv .venv && .venv/Scripts/activate      # Windows
pip install -e ".[dev]"
copy .env.example .env                              # put OPENAI_API_KEY in .env
python -m app.seed --reset                          # loads checklists, leads and the sample transcripts, scores them
uvicorn app.main:app --reload                       # API on http://127.0.0.1:8000, docs at /docs

cd frontend && npm install && npm run build         # then open http://127.0.0.1:8000
cd frontend && npm run dev                          # or hot-reload UI on http://localhost:5173
```

Tests: `pytest` (stubbed scorer, no key needed). `OPENAI_API_KEY=... pytest tests/test_integration_openai.py` scores
the real redacted transcript live.

## Feeding a transcript

```bash
curl -X POST http://127.0.0.1:8000/api/dialler/transcripts/text -H "Content-Type: application/json" \
  -d '{"lead_id": "4001001", "text": "Speaker 1: Hello...\nSpeaker 2: Hi, this is...", "speaker_roles": {"1": "customer", "2": "agent"}}'
```

Deepgram-shaped word lists go to `/api/dialler/transcripts`; audio files go to `/api/dialler/recordings`
(needs `DEEPGRAM_API_KEY`).

## Sample data

- `data/samples/call-transcript-redacted.txt` — the real redacted broadband call (lead `4001001`, Provider A).
  Expected: HELD, cooling-off rights never disclosed; recording disclaimer and payment-off-recording pass.
- `data/samples/lead-3613790.txt` — the worked example from the brief (lead `3613790`, Retailer 1).
  Expected: HELD, rate quoted 28.6c vs 31.9c on plan, email gmail vs gmial in CRM, 47s dead air note, card number redacted.
- `data/samples/lead-3613791.txt` — clean energy call. Expected: AUTO_SUBMITTED.

Checklists live in `data/synthetic/check_library_*.json` and import via `POST /api/library/import`.
