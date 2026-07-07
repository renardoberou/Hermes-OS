"""Secret-safe redaction helpers.

Every string the product ingests from the outside world (logs, command
output, config metadata, wiki files) passes through :func:`redact_text`
before it is stored in the inventory, so downstream renderers (JSON,
Markdown, HTML) can never leak what the collector never kept.

Design rules:

* Specific, well-known token shapes are matched first so the redaction
  label says what was caught (``[REDACTED:telegram-token]`` etc.).
* A conservative generic rule catches long opaque tokens last.
* ``.env``-style and YAML-style assignments whose *key name* looks
  secret get their value redacted regardless of the value's shape.
* False positives are accepted as the cost of safety; readability of a
  log line matters less than never printing a live credential.
"""
from __future__ import annotations

import re
from typing import Any

MASK = "[REDACTED:{label}]"

# Keys whose values must never be shown, regardless of shape.
SECRET_KEY_RE = re.compile(
    r"(?:api[_-]?key|apikey|secret|token|password|passwd|credential|auth|"
    r"private[_-]?key|bearer)",
    re.IGNORECASE,
)

# UUIDs are identifiers, not credentials — exempt them from the generic
# long-opaque-token rule so job ids stay readable.
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Ordered: most specific first. Each entry is (label, compiled regex).
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # OpenAI/Anthropic/OpenRouter-style keys: sk-..., sk-ant-..., sk-or-v1-...
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b")),
    # Apify tokens
    ("apify-token", re.compile(r"\bapify_api_[A-Za-z0-9]{16,}\b")),
    # Supabase personal access tokens
    ("supabase-token", re.compile(r"\bsbp_[A-Za-z0-9]{16,}\b")),
    # Telegram bot tokens: 8-10 digit bot id, colon, 35-char secret
    ("telegram-token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b")),
    # JWTs (Supabase anon/service keys are JWTs): three base64url segments
    (
        "jwt",
        re.compile(
            r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}\b"
        ),
    ),
    # Authorization: Bearer <token>
    (
        "bearer",
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"),
    ),
    # GitHub tokens
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    # AWS access key ids
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
]

# Generic long opaque token: 40+ chars of token alphabet containing at
# least one letter and one digit. Applied after the specific rules.
_GENERIC_RE = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")

# KEY=value / KEY: value where the key name is secret-ish.
_ASSIGNMENT_RE = re.compile(
    r"(?im)^(?P<lead>\s*(?:export\s+)?)"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_\-]*)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<val>.+?)\s*$"
)


def _generic_candidate(token: str) -> bool:
    """True if a long token should be treated as opaque secret material."""
    if _UUID_RE.match(token):
        return False
    has_alpha = any(c.isalpha() for c in token)
    has_digit = any(c.isdigit() for c in token)
    return has_alpha and has_digit


def redact_text(text: str) -> str:
    """Return *text* with anything credential-shaped masked out."""
    if not text:
        return text

    # 1. Secret-named assignments (.env / YAML style) — value goes away.
    def _assign_sub(m: re.Match[str]) -> str:
        if SECRET_KEY_RE.search(m.group("key")):
            return (
                m.group("lead")
                + m.group("key")
                + m.group("sep")
                + MASK.format(label="env")
            )
        return m.group(0)

    text = _ASSIGNMENT_RE.sub(_assign_sub, text)

    # 2. Known token shapes.
    for label, pattern in _PATTERNS:
        text = pattern.sub(MASK.format(label=label), text)

    # 3. Generic long opaque tokens.
    def _generic_sub(m: re.Match[str]) -> str:
        tok = m.group(0)
        return MASK.format(label="opaque") if _generic_candidate(tok) else tok

    text = _GENERIC_RE.sub(_generic_sub, text)
    return text


def redact_obj(obj: Any) -> Any:
    """Recursively redact a JSON-ish structure (dicts, lists, strings).

    String values are passed through :func:`redact_text`; additionally,
    any dict value whose *key* looks secret is masked wholesale even if
    the value itself matches no pattern.
    """
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if isinstance(key, str) and SECRET_KEY_RE.search(key):
                out[key] = MASK.format(label="key-name")
            else:
                out[key] = redact_obj(value)
        return out
    if isinstance(obj, list):
        return [redact_obj(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(redact_obj(item) for item in obj)
    return obj


def contains_secret(text: str) -> bool:
    """Heuristic check used by tests: does *text* still look leaky?"""
    if _ASSIGNMENT_RE.search(text):
        for m in _ASSIGNMENT_RE.finditer(text):
            if SECRET_KEY_RE.search(m.group("key")) and "[REDACTED" not in m.group(
                "val"
            ):
                return True
    for _label, pattern in _PATTERNS:
        if pattern.search(text):
            return True
    for m in _GENERIC_RE.finditer(text):
        if _generic_candidate(m.group(0)):
            return True
    return False
