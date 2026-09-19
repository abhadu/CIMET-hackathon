from __future__ import annotations

from typing import Any, Protocol

import httpx

from app.config import Settings
from app.transcript import Transcript, Word

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


class TranscriptionError(RuntimeError):
    pass


class Transcriber(Protocol):
    def transcribe(self, audio: bytes, content_type: str) -> Transcript: ...


class DeepgramTranscriber:
    def __init__(self, api_key: str, model: str, timeout_s: float = 300.0) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_s

    def transcribe(self, audio: bytes, content_type: str) -> Transcript:
        params = {
            "model": self._model,
            "diarize": "true",
            "smart_format": "true",
            "punctuate": "true",
            "utterances": "true",
            "language": "en-AU",
        }
        headers = {"Authorization": f"Token {self._api_key}", "Content-Type": content_type}
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(DEEPGRAM_URL, params=params, headers=headers, content=audio)
        if response.status_code != 200:
            raise TranscriptionError(f"Deepgram returned {response.status_code}: {response.text[:300]}")
        return parse_deepgram_response(response.json())


def parse_deepgram_response(payload: dict[str, Any]) -> Transcript:
    try:
        channel = payload["results"]["channels"][0]
        alternative = channel["alternatives"][0]
        raw_words = alternative["words"]
    except (KeyError, IndexError) as exc:
        raise TranscriptionError("Unexpected Deepgram payload shape") from exc
    words = [
        Word(
            text=w.get("punctuated_word") or w["word"],
            start=float(w["start"]),
            end=float(w["end"]),
            speaker=int(w.get("speaker", 0)),
            confidence=float(w.get("confidence", 1.0)),
        )
        for w in raw_words
    ]
    duration = float(payload.get("metadata", {}).get("duration") or (words[-1].end if words else 0.0))
    return Transcript.from_words(words, duration=duration)


def transcript_from_payload(
    words: list[dict[str, Any]], duration: float | None = None, roles: dict[int, str] | None = None
) -> Transcript:
    if not words:
        raise TranscriptionError("Transcript payload has no words")
    parsed = [
        Word(
            text=str(w["text"]),
            start=float(w["start"]),
            end=float(w["end"]),
            speaker=int(w.get("speaker", 0)),
            confidence=float(w.get("confidence", 1.0)),
        )
        for w in words
    ]
    return Transcript.from_words(parsed, roles=roles, duration=duration)


def build_transcriber(settings: Settings) -> Transcriber | None:
    if not settings.deepgram_api_key:
        return None
    return DeepgramTranscriber(settings.deepgram_api_key, settings.deepgram_model)
