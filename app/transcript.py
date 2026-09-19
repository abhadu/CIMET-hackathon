from __future__ import annotations

import re
from collections import Counter

from pydantic import BaseModel, Field

AGENT = "agent"
CUSTOMER = "customer"
TIMING_MEASURED = "measured"
TIMING_ESTIMATED = "estimated"

_SPEAKER_LINE = re.compile(r"^\s*(?:speaker\s*)?(\d+)\s*[:\t]\s*(.*)$", re.IGNORECASE)
_SILENCE_LINE = re.compile(r"^\s*\[silence\s+(\d+(?:\.\d+)?)\s*s\]\s*$", re.IGNORECASE)
WORDS_PER_SECOND = 2.6
TURN_GAP_S = 0.7


class Word(BaseModel):
    text: str
    start: float
    end: float
    speaker: int
    confidence: float = 1.0


class Utterance(BaseModel):
    index: int
    speaker: int
    role: str
    start: float
    end: float
    text: str


class Transcript(BaseModel):
    words: list[Word]
    utterances: list[Utterance] = Field(default_factory=list)
    duration: float
    speaker_roles: dict[int, str] = Field(default_factory=dict)
    timing: str = TIMING_MEASURED

    @classmethod
    def from_words(
        cls,
        words: list[Word],
        roles: dict[int, str] | None = None,
        duration: float | None = None,
        timing: str = TIMING_MEASURED,
    ) -> Transcript:
        resolved = dict(roles) if roles else default_roles(words)
        return cls(
            words=words,
            utterances=build_utterances(words, resolved),
            duration=duration if duration is not None else (words[-1].end if words else 0.0),
            speaker_roles=resolved,
            timing=timing,
        )

    def numbered_text(self, silence_threshold_s: float) -> str:
        lines: list[str] = []
        previous_end: float | None = None
        for utt in self.utterances:
            if previous_end is not None and utt.start - previous_end >= silence_threshold_s:
                lines.append(f"[silence {utt.start - previous_end:.0f}s]")
            lines.append(f"[u{utt.index} {utt.role.upper()} {fmt_ts(utt.start)}] {utt.text}")
            previous_end = utt.end
        return "\n".join(lines)


def fmt_ts(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def default_roles(words: list[Word]) -> dict[int, str]:
    counts = Counter(w.speaker for w in words)
    if not counts:
        return {}
    agent = counts.most_common(1)[0][0]
    return {s: (AGENT if s == agent else CUSTOMER) for s in counts}


def build_utterances(words: list[Word], roles: dict[int, str], max_gap_s: float = 1.5, max_words: int = 60) -> list[Utterance]:
    utterances: list[Utterance] = []
    start_idx = 0
    for i in range(1, len(words) + 1):
        boundary = (
            i == len(words)
            or words[i].speaker != words[start_idx].speaker
            or words[i].start - words[i - 1].end > max_gap_s
            or i - start_idx >= max_words
        )
        if not boundary:
            continue
        chunk = words[start_idx:i]
        utterances.append(
            Utterance(
                index=len(utterances),
                speaker=chunk[0].speaker,
                role=roles.get(chunk[0].speaker, f"speaker_{chunk[0].speaker}"),
                start=chunk[0].start,
                end=chunk[-1].end,
                text=" ".join(w.text for w in chunk),
            )
        )
        start_idx = i
    return utterances


def parse_text(text: str) -> list[Word]:
    """Turn 'Speaker N: ...' lines into words with estimated timings. '[silence 47s]' lines insert a gap."""
    words: list[Word] = []
    clock = 0.0
    per_word = 1.0 / WORDS_PER_SECOND
    current: tuple[int, list[str]] | None = None

    def flush() -> None:
        nonlocal clock, current
        if current is None:
            return
        speaker, tokens = current
        for i, token in enumerate(tokens):
            start = clock + i * per_word
            words.append(Word(text=token, start=round(start, 2), end=round(start + per_word * 0.85, 2), speaker=speaker))
        clock += len(tokens) * per_word + TURN_GAP_S
        current = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        silence = _SILENCE_LINE.match(line)
        if silence:
            flush()
            clock += float(silence.group(1)) - TURN_GAP_S
            continue
        spoken = _SPEAKER_LINE.match(line)
        if spoken:
            flush()
            current = (int(spoken.group(1)), spoken.group(2).split())
        elif current is not None:
            current[1].extend(line.split())
    flush()
    if not words:
        raise ValueError("No 'Speaker N: text' lines found")
    return words


def transcript_from_text(text: str, roles: dict[int, str] | None = None) -> Transcript:
    words = parse_text(text)
    return Transcript.from_words(words, roles=roles, duration=words[-1].end + 1.0, timing=TIMING_ESTIMATED)
