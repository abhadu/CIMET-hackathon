from pathlib import Path

from app.transcript import transcript_from_text

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "samples" / "call-transcript-redacted.txt"


def test_parses_speaker_lines_with_estimated_timing():
    transcript = transcript_from_text("Speaker 1: Hello there.\nSpeaker 2: Hi, this is Sam.\n[silence 47s]\nSpeaker 2: Still there?")
    assert transcript.timing == "estimated"
    assert [u.speaker for u in transcript.utterances] == [1, 2, 2]
    assert transcript.utterances[2].start - transcript.utterances[1].end >= 47
    assert "[silence 47s]" in transcript.numbered_text(20)
    assert transcript.numbered_text(20).startswith("[u0 CUSTOMER 00:00] Hello there.")


def test_explicit_roles_win_over_talk_time():
    transcript = transcript_from_text("Speaker 1: one two three four five six seven\nSpeaker 2: ok", roles={1: "customer", 2: "agent"})
    assert transcript.speaker_roles == {1: "customer", 2: "agent"}


def test_redacted_sample_parses_end_to_end():
    transcript = transcript_from_text(SAMPLE.read_text(encoding="utf-8"), roles={1: "customer", 2: "agent"})
    assert len(transcript.utterances) > 100
    assert transcript.utterances[0].role == "customer"
    agent_text = " ".join(u.text for u in transcript.utterances if u.role == "agent")
    assert "this call will be recorded" in agent_text
    assert "cooling off" not in agent_text
