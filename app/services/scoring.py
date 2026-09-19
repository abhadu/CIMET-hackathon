from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal, Protocol

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from app.config import Settings
from app.models import Check, CheckOutcome, CheckType, Lead, Plan
from app.transcript import Transcript

log = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"\{[^}]*\}|\[[^\]]*\]")


class CheckVerdict(BaseModel):
    code: str
    result: Literal["PASS", "FAIL", "NOTE", "UNCERTAIN"]
    confidence: float = Field(ge=0.0, le=1.0)
    quote: str | None = Field(description="Verbatim excerpt from one utterance that is the evidence, or null.")
    utterance_index: int | None = Field(description="The N in [uN ...] that the quote comes from, or null.")
    observed_value: str | None = Field(description="What was actually said, normalised (email, number, date).")
    expected_value: str | None = Field(description="The CRM or plan value it was compared to, if any.")
    reasoning: str


class ScoringOutput(BaseModel):
    verdicts: list[CheckVerdict]


class Evidence(BaseModel):
    quote: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None


class CheckEvaluation(BaseModel):
    check_id: int
    check_code: str
    check_name: str
    check_type: CheckType
    is_critical: bool
    weight: float
    result: CheckOutcome
    confidence: float
    evidence: Evidence = Field(default_factory=Evidence)
    expected_value: str | None = None
    observed_value: str | None = None
    reasoning: str

    @property
    def blocks_sale(self) -> bool:
        return self.is_critical and self.result == CheckOutcome.FAIL


class Scorer(Protocol):
    def score(self, system_prompt: str, user_prompt: str) -> ScoringOutput: ...


class ScorerError(RuntimeError):
    pass


class OpenAIScorer:
    def __init__(self, settings: Settings) -> None:
        self._llm = ChatOpenAI(
            model=settings.openai_model, api_key=settings.openai_api_key, temperature=0, timeout=180
        ).with_structured_output(ScoringOutput)

    def score(self, system_prompt: str, user_prompt: str) -> ScoringOutput:
        try:
            result = self._llm.invoke([("system", system_prompt), ("human", user_prompt)])
        except Exception as exc:  # noqa: BLE001
            raise ScorerError(str(exc)) from exc
        if not isinstance(result, ScoringOutput):
            raise ScorerError("model returned no structured output")
        return result


class UnavailableScorer:
    def score(self, system_prompt: str, user_prompt: str) -> ScoringOutput:
        raise ScorerError("OPENAI_API_KEY is not configured")


def build_scorer(settings: Settings) -> Scorer:
    if not settings.openai_api_key:
        log.warning("OPENAI_API_KEY not set; every check will route to QA")
        return UnavailableScorer()
    return OpenAIScorer(settings)


SYSTEM_PROMPT = """You are the automated QA auditor for a regulated Australian energy and broadband sales floor.
You receive one diarised call transcript with numbered utterances "[uN ROLE mm:ss] text", the retailer's checklist,
and the values recorded in the CRM for this sale. Return exactly one verdict per checklist code.

Check types:
- verbatim: PASS only if the AGENT read the approved script essentially word for word. Small speech-to-text
  errors and filler words are fine. A paraphrase, a partial read, or a missing statement is FAIL. If crosstalk or
  garbled transcription makes it genuinely unclear whether it was read, return UNCERTAIN.
- factual: compare what the agent stated or the customer confirmed against the expected value. Normalise spoken
  forms first ("j dot smith at gmail dot com" -> j.smith@gmail.com, "twenty eight point six cents" -> 28.6 cents,
  spoken dates -> YYYY-MM-DD, "month to month" -> 0 months). A different value is FAIL. Never discussed is FAIL,
  unless the guidance says the field only applies in some situations and it clearly does not apply here, which is
  PASS with reasoning "not applicable". If the value is redacted with a placeholder like [EMAIL] on both sides,
  treat it as matching. If the spoken value is garbled, interrupted or looks like a mishear, return UNCERTAIN.
- behaviour: coaching only. Return PASS or NOTE, never FAIL. NOTE means the team lead should look at it.
  "[silence Ns]" lines mark measured dead air.

Rules:
- Only the transcript is evidence. Do not assume anything was said because the CRM contains it.
- Never manufacture a critical FAIL from ambiguous evidence; that is what UNCERTAIN is for.
- The transcript comes from speech-to-text. The agent speaks; the transcription engine spells. The agent cannot
  misspell a spoken word, so never FAIL a name, street, suburb or word on spelling alone: "Waddle Street" for
  "Wattle Street" is the same address and is a PASS. Numbers may be formatted ("$1,800", "12%", "28.6").
  A FAIL needs a difference in substance: different digits, a different email domain, a different suburb or street
  number, a different answer. Only when you genuinely cannot tell is it UNCERTAIN.- quote must be copied verbatim from a single utterance and utterance_index must point to that utterance.
- confidence is your belief that the verdict is correct, 0 to 1.
- reasoning is one or two sentences a team lead can act on, quoting the specific values that differ."""


def _dig(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def expected_value(check: Check, lead: Lead, plan: Plan | None) -> Any:
    path = check.config.get("field")
    if not path:
        return None
    source = check.config.get("source", "crm")
    return _dig(plan.attributes, path) if source == "plan" and plan else _dig(lead.crm_fields, path)


def filled_script(check: Check, lead: Lead, plan: Plan | None) -> str:
    """Script with {placeholders} replaced by this sale's values (config.values maps them to crm:/plan: paths)."""
    values: dict[str, Any] = check.config.get("values", {})

    def fill(match: re.Match[str]) -> str:
        key = match.group(0).strip("{}")
        source = values.get(key)
        if source is None:
            return ""
        if isinstance(source, str) and source.startswith(("crm:", "plan:")):
            prefix, path = source.split(":", 1)
            resolved = _dig(plan.attributes, path) if prefix == "plan" and plan else _dig(lead.crm_fields, path)
            return "" if resolved is None else str(resolved)
        return str(source)

    return re.sub(r"\s+", " ", _PLACEHOLDER.sub(fill, str(check.config.get("script", "")))).strip()


def checklist_text(checks: list[Check], lead: Lead, plan: Plan | None) -> str:
    lines = []
    for c in checks:
        parts = [f"code={c.code}", f"type={c.check_type}", f"critical={'yes' if c.is_critical else 'no'}", f"name={c.name}"]
        if c.check_type == CheckType.VERBATIM:
            parts.append(f'script="{filled_script(c, lead, plan)}"')
        if c.check_type == CheckType.FACTUAL:
            parts.append(f"expected={json.dumps(expected_value(c, lead, plan))}")
        if c.config.get("guidance"):
            parts.append(f"guidance={c.config['guidance']}")
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines)


def user_prompt(checks: list[Check], transcript: Transcript, lead: Lead, plan: Plan | None, settings: Settings) -> str:
    context = {
        "lead_id": lead.id,
        "retailer": lead.retailer_id,
        "plan": plan.name if plan else None,
        "call_date": lead.call_date.isoformat(),
        "timing": transcript.timing,
    }
    return (
        f"Sale context: {json.dumps(context)}\n\nChecklist:\n{checklist_text(checks, lead, plan)}\n\n"
        f"Transcript:\n{transcript.numbered_text(settings.dead_air_threshold_s)}"
    )


def score_call(
    checks: list[Check], transcript: Transcript, lead: Lead, plan: Plan | None, scorer: Scorer, settings: Settings
) -> list[CheckEvaluation]:
    try:
        output = scorer.score(SYSTEM_PROMPT, user_prompt(checks, transcript, lead, plan, settings))
        verdicts = {v.code: v for v in output.verdicts}
    except ScorerError as exc:
        log.warning("scoring unavailable for lead %s: %s", lead.id, exc)
        verdicts = {}
    return [_evaluate(c, verdicts.get(c.code), transcript, lead, plan, settings) for c in checks]


def _evaluate(
    check: Check, verdict: CheckVerdict | None, transcript: Transcript, lead: Lead, plan: Plan | None, settings: Settings
) -> CheckEvaluation:
    expected = expected_value(check, lead, plan)
    base = dict(
        check_id=check.id or 0,
        check_code=check.code,
        check_name=check.name,
        check_type=check.check_type,
        is_critical=check.is_critical,
        weight=check.weight,
        expected_value=None if expected is None else str(expected),
    )
    if verdict is None:
        return CheckEvaluation(
            **base, result=CheckOutcome.UNCERTAIN, confidence=0.0, reasoning="No verdict produced; routed to QA."
        )

    result = CheckOutcome(verdict.result)
    reasoning = verdict.reasoning
    evidence = _evidence(transcript, verdict)

    if check.check_type == CheckType.BEHAVIOUR:
        if result in (CheckOutcome.FAIL, CheckOutcome.UNCERTAIN):
            result = CheckOutcome.NOTE
    elif result in (CheckOutcome.PASS, CheckOutcome.FAIL) and verdict.confidence < settings.min_confidence:
        result = CheckOutcome.UNCERTAIN
        reasoning = f"{reasoning} Confidence {verdict.confidence:.2f} is below {settings.min_confidence:.2f}; routed to QA."

    if check.check_type == CheckType.VERBATIM:
        similarity = _similarity(filled_script(check, lead, plan), transcript, verdict)
        reasoning = f"{reasoning} Script similarity {similarity:.0f}%."
        if result == CheckOutcome.PASS and similarity < 60:
            result = CheckOutcome.UNCERTAIN
            reasoning += " Cited line does not resemble the script; routed to QA."
        elif result != CheckOutcome.PASS and similarity >= 90:
            result = CheckOutcome.PASS
            reasoning += " Cited line matches the script word for word after speech-to-text formatting; passed."

    return CheckEvaluation(
        **base,
        result=result,
        confidence=round(verdict.confidence, 3),
        evidence=evidence,
        observed_value=verdict.observed_value,
        reasoning=reasoning,
    )


def _evidence(transcript: Transcript, verdict: CheckVerdict) -> Evidence:
    idx = verdict.utterance_index
    if idx is None or not 0 <= idx < len(transcript.utterances):
        return Evidence(quote=verdict.quote)
    utt = transcript.utterances[idx]
    return Evidence(
        quote=verdict.quote or utt.text[:200],
        start_ms=int(utt.start * 1000),
        end_ms=int(utt.end * 1000),
        speaker=utt.role,
    )


def _similarity(script: str, transcript: Transcript, verdict: CheckVerdict) -> float:
    idx = verdict.utterance_index
    if idx is not None and 0 <= idx < len(transcript.utterances):
        window = " ".join(u.text for u in transcript.utterances[max(0, idx - 1) : idx + 2])
    else:
        window = " ".join(u.text for u in transcript.utterances if u.role == "agent")
    return float(fuzz.token_set_ratio(script.lower(), window.lower())) if script and window else 0.0
