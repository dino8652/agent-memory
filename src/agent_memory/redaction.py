from __future__ import annotations

import re


PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]+"),
    re.compile(r"ghp_[A-Za-z0-9_\-]+"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"password=[^\s]+", re.IGNORECASE),
    re.compile(r"secret=[^\s]+", re.IGNORECASE),
]


def redact(text: str | None) -> str | None:
    if text is None:
        return None
    result = text
    for pattern in PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result
