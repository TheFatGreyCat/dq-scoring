"""Pure helpers for text quality assessment: encoding anomalies, control characters, mojibake, length."""

import re

# C0 controls excluding Tab (\t = 0x09), LF (\n = 0x0A), CR (\r = 0x0D), plus DEL (0x7F) and C1 controls (0x80-0x9F)
CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x80-\x9f]")

MOJIBAKE_SIGNALS = ("Ã", "Â", "â€", "ðŸ")


def contains_replacement_character(text: str) -> bool:
    """Return True if text contains Unicode replacement character U+FFFD."""
    return "\ufffd" in text


def contains_control_characters(text: str) -> bool:
    """Return True if text contains disallowed C0/C1 control characters or DEL."""
    return bool(CONTROL_CHARS_PATTERN.search(text))


def contains_mojibake(text: str) -> bool:
    """Return True if text exhibits common mojibake corruption patterns."""
    return any(signal in text for signal in MOJIBAKE_SIGNALS)


def evaluate_text_length(text: str, min_length: int | None = None, max_length: int | None = None) -> bool:
    """Evaluate codepoint length of text against optional min/max bounds."""
    length = len(text)
    if min_length is not None and length < min_length:
        return False
    return max_length is None or length <= max_length
