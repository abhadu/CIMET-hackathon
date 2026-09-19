from app.services.redaction import REDACTED, luhn_valid, redact_card_numbers
from app.transcript import Transcript, Word


def _words(text: str, speaker: int = 1) -> list[Word]:
    return [Word(text=t, start=i * 0.4, end=i * 0.4 + 0.3, speaker=speaker) for i, t in enumerate(text.split())]


def test_luhn():
    assert luhn_valid("4532015112830366")
    assert not luhn_valid("4532015112830367")


def test_spoken_card_number_is_redacted_and_flagged():
    words = _words("sure it's four five three two zero one five one one two eight three zero three six six thanks")
    transcript = Transcript.from_words(words)
    clean, redactions = redact_card_numbers(transcript)
    assert len(redactions) == 1
    assert redactions[0].digit_count == 16
    redacted = [w.text for w in clean.words if w.text == REDACTED]
    assert len(redacted) == 16
    assert "four" not in " ".join(w.text for w in clean.words)
    assert clean.words[0].text == "sure"
    assert redactions[0].start_ms == int(clean.words[2].start * 1000)


def test_digit_tokens_with_double_are_redacted():
    words = _words("card is 4532 0151 1283 0366 okay")
    clean, redactions = redact_card_numbers(Transcript.from_words(words))
    assert len(redactions) == 1
    assert [w.text for w in clean.words[2:6]] == [REDACTED] * 4


def test_phone_and_nmi_are_not_redacted():
    words = _words("my number is 0412 345 678 and the NMI is 4 1 0 2 3 4 5 6 7 8 9")
    clean, redactions = redact_card_numbers(Transcript.from_words(words))
    assert redactions == []
    assert REDACTED not in [w.text for w in clean.words]
