"""Turn a 'Speaker N: ...' transcript into a mono WAV call recording with OpenAI text-to-speech.

    python scripts/make_audio.py data/samples/lead-3613790.txt data/samples/audio/lead-3613790.wav --agent 1

Placeholders such as [EMAIL] are replaced with fixed fake values so the audio sounds like a real call.
'[silence 47s]' lines become real silence so dead-air detection can be tested from audio.
"""

from __future__ import annotations

import argparse
import io
import re
import wave
from pathlib import Path

from openai import OpenAI

from app.config import get_settings
from app.transcript import _SILENCE_LINE, _SPEAKER_LINE

TURN_GAP_S = 0.8
VOICES = {"agent": "ash", "customer": "coral"}
STYLE = {
    "agent": "Australian call-centre sales agent. Friendly, clear, slightly brisk when reading disclosures.",
    "customer": "Older Australian woman on a home phone. Relaxed, a little hesitant, natural pauses.",
}
PLACEHOLDERS = {
    "[CUSTOMER_NAME]": "Margaret",
    "[CUSTOMER_FULL_NAME]": "Margaret Wilson",
    "[AGENT_NAME]": "Daniel",
    "[UNCLEAR_NAME]": "Margaret",
    "[SERVICE_ADDRESS]": "unit 12, 45 Pacific Parade, Dee Why, New South Wales, 2099",
    "[DELIVERY_ADDRESS]": "the Oaks Avenue entrance of 45 Pacific Parade",
    "[STREET_NAME]": "Pacific Parade",
    "[RESIDENTIAL_COMPLEX]": "retirement village",
    "[PHONE]": "0 4 1 2, 3 4 5, 6 7 8",
    "[EMAIL]": "margaret dot wilson at bigpond dot com",
    "[DOB]": "the fourteenth of June, nineteen fifty two",
    "[ACCOUNT_NUMBER]": "account number 2 2 4 5 8 9 1",
    "[OTP_CODE]": "four seven two nine one three",
    "[REFERENCE_NUMBER]": "A P P 7 7 3 1 0 2",
    "[PROVIDER_A]": "Provider A",
}


def substitute(text: str) -> str:
    for tag, value in PLACEHOLDERS.items():
        text = text.replace(tag, value)
    return re.sub(r"\[[A-Z_]+\]", "", text)


def parse(path: Path) -> list[tuple[str, str]]:
    """Returns (speaker_id | 'silence', text | seconds) in order."""
    items: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if silence := _SILENCE_LINE.match(line):
            items.append(("silence", silence.group(1)))
        elif spoken := _SPEAKER_LINE.match(line):
            items.append((spoken.group(1), spoken.group(2)))
    return items


def synth(client: OpenAI, role: str, text: str) -> tuple[bytes, wave._wave_params]:
    response = client.audio.speech.create(
        model="gpt-4o-mini-tts", voice=VOICES[role], input=text, instructions=STYLE[role], response_format="wav"
    )
    with wave.open(io.BytesIO(response.content), "rb") as clip:
        return clip.readframes(clip.getnframes()), clip.getparams()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--agent", type=int, required=True, help="speaker number that is the agent")
    args = parser.parse_args()

    client = OpenAI(api_key=get_settings().openai_api_key)
    frames: list[bytes] = []
    params = None
    for speaker, payload in parse(args.transcript):
        if speaker == "silence":
            assert params is not None
            frames.append(b"\x00" * int(float(payload) * params.framerate * params.sampwidth))
            continue
        role = "agent" if int(speaker) == args.agent else "customer"
        audio, params = synth(client, role, substitute(payload))
        frames.append(audio)
        frames.append(b"\x00" * int(TURN_GAP_S * params.framerate * params.sampwidth))
        print(f"{role:8} {payload[:70]}")

    assert params is not None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.output), "wb") as out:
        out.setnchannels(params.nchannels)
        out.setsampwidth(params.sampwidth)
        out.setframerate(params.framerate)
        out.writeframes(b"".join(frames))
    seconds = sum(len(f) for f in frames) / (params.framerate * params.sampwidth * params.nchannels)
    print(f"wrote {args.output} ({seconds / 60:.1f} min)")


if __name__ == "__main__":
    main()
