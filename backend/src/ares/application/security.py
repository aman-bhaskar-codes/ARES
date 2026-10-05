from __future__ import annotations

import base64
import re
from dataclasses import dataclass

_INSTRUCTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("instruction_override", re.compile(r"\b(?:ignore|disregard|forget)\b.{0,48}\b(?:instruction|prompt|rule|policy)s?\b", re.I | re.S)),
    ("role_override", re.compile(r"\b(?:you are now|act as|developer mode|system override)\b", re.I)),
    ("prompt_exfiltration", re.compile(r"\b(?:reveal|print|show|repeat|leak|expose)\b.{0,48}\b(?:system prompt|developer message|hidden instruction|api key|secret)s?\b", re.I | re.S)),
    ("tool_manipulation", re.compile(r"\b(?:call|invoke|run|execute|send|upload|delete|write)\b.{0,48}\b(?:tool|shell|command|request|file|database|webhook|endpoint)s?\b", re.I | re.S)),
    ("instruction_delimiter", re.compile(r"(?:^|\n)\s*(?:system|developer|assistant|tool)\s*:\s*", re.I)),
)
_BASE64ISH = re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b")
_INVISIBLE = {"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff", "\u202a", "\u202b", "\u202d", "\u202e"}


@dataclass(frozen=True, slots=True)
class ContentRisk:
    score: int
    categories: tuple[str, ...]
    suspicious: bool


class RemoteContentRiskScanner:
    """Cheap detector for observability around indirect prompt-injection attempts.

    It is intentionally *not* an authorization boundary and never decides whether retrieved
    content may be trusted. ARES treats every remote document as untrusted regardless of this
    score. The scanner exists so adversarial content is visible in telemetry/evaluations without
    pretending regexes can solve prompt injection.
    """

    def inspect(self, text: str) -> ContentRisk:
        categories: list[str] = []
        score = 0
        sample = text[:200_000]
        for name, pattern in _INSTRUCTION_PATTERNS:
            if pattern.search(sample):
                categories.append(name)
                score += 2 if name in {"prompt_exfiltration", "tool_manipulation"} else 1

        if any(char in sample for char in _INVISIBLE):
            categories.append("invisible_unicode")
            score += 1

        # Encoded blobs are only a weak signal. Decode a bounded prefix and look for instruction
        # language so ordinary hashes/assets do not become high-confidence alerts.
        encoded_match = _BASE64ISH.search(sample)
        if encoded_match:
            token = encoded_match.group(0)[:4096]
            try:
                decoded = base64.b64decode(token + "=" * (-len(token) % 4), validate=False).decode(
                    "utf-8", errors="ignore"
                )
            except (ValueError, UnicodeError):
                decoded = ""
            if decoded and any(pattern.search(decoded) for _, pattern in _INSTRUCTION_PATTERNS):
                categories.append("encoded_instruction")
                score += 2

        categories = list(dict.fromkeys(categories))
        return ContentRisk(score=score, categories=tuple(categories), suspicious=score >= 2)
