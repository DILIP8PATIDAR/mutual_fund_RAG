"""Input guard: PII detection + length limit (Phase 3.1).

Runs before any classification/retrieval. Rejects messages that are empty,
too long, or that contain personal / sensitive identifiers (PAN, Aadhaar,
account numbers, OTPs, email, phone). Blocking (rather than silently
sanitising) keeps sensitive data out of logs and out of the Groq prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_MESSAGE_CHARS = 500
MIN_MESSAGE_CHARS = 2

EMPTY_MESSAGE = "Please enter a question."
TOO_LONG_MESSAGE = f"Question is too long (max {MAX_MESSAGE_CHARS} characters)."
PII_MESSAGE = (
    "For your safety, please don't share personal or sensitive information "
    "(such as PAN, Aadhaar, account numbers, OTPs, email, or phone numbers). "
    "Ask a factual question about an HDFC scheme instead."
)

# name -> compiled pattern. Word boundaries keep short patterns (phone, OTP)
# from matching inside unrelated tokens. All matching is case-insensitive.
_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "pan": re.compile(r"\b[A-Za-z]{5}[0-9]{4}[A-Za-z]\b"),
    "aadhaar": re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    "phone": re.compile(r"\b(?:\+?91[\s-]?)?[6-9]\d{9}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    "account_number": re.compile(r"\b\d{11,18}\b"),
    "otp": re.compile(r"\b(?:otp|one[\s-]?time[\s-]?password)\b", re.IGNORECASE),
}


@dataclass(frozen=True)
class GuardResult:
    """Outcome of the input guard. ``ok=False`` means the request is rejected."""

    ok: bool
    message: str = ""
    pii_types: tuple[str, ...] = ()


def detect_pii(text: str) -> list[str]:
    """Return the sorted names of PII patterns found in ``text`` (may be empty)."""
    found = [name for name, pattern in _PII_PATTERNS.items() if pattern.search(text)]
    return sorted(found)


def check_input(message: str) -> GuardResult:
    """Validate a user message for length and PII before it enters the pipeline."""
    stripped = message.strip()

    if len(stripped) < MIN_MESSAGE_CHARS:
        return GuardResult(ok=False, message=EMPTY_MESSAGE)
    if len(stripped) > MAX_MESSAGE_CHARS:
        return GuardResult(ok=False, message=TOO_LONG_MESSAGE)

    pii_types = detect_pii(stripped)
    if pii_types:
        return GuardResult(ok=False, message=PII_MESSAGE, pii_types=tuple(pii_types))

    return GuardResult(ok=True)
