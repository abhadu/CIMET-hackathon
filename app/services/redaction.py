from __future__ import annotations

import re

from pydantic import BaseModel

from app.transcript import Transcript, Word

REDACTED = "[REDACTED]"
MIN_CARD_DIGITS = 13
MAX_CARD_DIGITS = 19

_NUMBER_WORDS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}
_DIGITS_ONLY = re.compile(r"^[\d\-\s]+$")


class Redaction(BaseModel):
    kind: str
    start_ms: int
    end_ms: int
    speaker: int
    word_start: int
    word_end: int
    digit_count: int


def luhn_valid(digits: str) -> bool:
    if not digits.isdigit() or len(digits) < 2:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _digits_of(word: str) -> str | None:
    cleaned = word.lower().strip(".,;:!?")
    if cleaned == "double":
        return ""
    if cleaned in _NUMBER_WORDS:
        return _NUMBER_WORDS[cleaned]
    if _DIGITS_ONLY.match(cleaned):
        return re.sub(r"\D", "", cleaned)
    return None


def _expand_doubles(tokens: list[tuple[int, str]]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    i = 0
    while i < len(tokens):
        idx, digits = tokens[i]
        if digits == "" and i + 1 < len(tokens):
            out.append((idx, tokens[i + 1][1] * 2))
            i += 2
            continue
        if digits:
            out.append((idx, digits))
        i += 1
    return out


def find_card_runs(words: list[Word]) -> list[tuple[int, int, int]]:
    runs: list[tuple[int, int, int]] = []
    i = 0
    while i < len(words):
        if _digits_of(words[i].text) is None:
            i += 1
            continue
        j = i
        tokens: list[tuple[int, str]] = []
        while j < len(words) and _digits_of(words[j].text) is not None:
            tokens.append((j, _digits_of(words[j].text) or ""))
            j += 1
        tokens = _expand_doubles(tokens)
        runs.extend(_scan_run(tokens))
        i = j
    return runs


def _scan_run(tokens: list[tuple[int, str]]) -> list[tuple[int, int, int]]:
    hits: list[tuple[int, int, int]] = []
    digit_owner: list[int] = []
    digits = ""
    for idx, d in tokens:
        digits += d
        digit_owner.extend([idx] * len(d))
    n = len(digits)
    pos = 0
    while pos < n:
        matched = False
        for length in range(MAX_CARD_DIGITS, MIN_CARD_DIGITS - 1, -1):
            if pos + length <= n and luhn_valid(digits[pos : pos + length]):
                hits.append((digit_owner[pos], digit_owner[pos + length - 1], length))
                pos += length
                matched = True
                break
        if not matched:
            pos += 1
    return hits


def redact_card_numbers(transcript: Transcript) -> tuple[Transcript, list[Redaction]]:
    words = [w.model_copy() for w in transcript.words]
    redactions: list[Redaction] = []
    for start, end, count in find_card_runs(words):
        for k in range(start, end + 1):
            words[k].text = REDACTED
        redactions.append(
            Redaction(
                kind="card_number",
                start_ms=int(words[start].start * 1000),
                end_ms=int(words[end].end * 1000),
                speaker=words[start].speaker,
                word_start=start,
                word_end=end,
                digit_count=count,
            )
        )
    if not redactions:
        return transcript, []
    clean = Transcript.from_words(
        words, roles=transcript.speaker_roles, duration=transcript.duration, timing=transcript.timing
    )
    return clean, redactions
