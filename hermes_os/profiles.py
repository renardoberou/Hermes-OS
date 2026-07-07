"""Profile discovery: CLI output + allowlisted config metadata.

Two independent, read-only sources are merged:

1. The text output of ``hermes profile list`` (format treated as
   unstable; parsed defensively line by line).
2. ``~/.hermes/profiles/*/config.yaml`` — read with a deliberately dumb
   line scanner instead of a YAML parser. Only keys on ``SAFE_KEYS``
   are ever extracted; everything else in the file, including any
   credential, is never even kept in memory. This is an allowlist, not
   a blocklist: unknown keys are dropped by construction.
"""
from __future__ import annotations

import re
from pathlib import Path

from .models import Profile
from .redact import redact_text

#: The only config.yaml keys whose values we will read.
SAFE_KEYS = ("name", "model", "alias", "description", "gateway", "enabled")

_LINE_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_\-]*)\s*:\s*(?P<val>.+?)\s*$")
_MODEL_RE = re.compile(r"model\s*[:=]\s*(?P<model>[\w.\-/]+)", re.IGNORECASE)
_GATEWAY_RE = re.compile(r"gateway\s*[:=]\s*(?P<gw>[\w\-]+)", re.IGNORECASE)
_ALIAS_RE = re.compile(r"alias\s*[:=]\s*(?P<alias>[\w\-]+)", re.IGNORECASE)


def parse_profile_list(text: str) -> list[Profile]:
    """Parse ``hermes profile list`` output into Profile records.

    Tolerated shapes per line: optional ``*`` or ``-`` marker, a name
    token, then free-form annotations like ``(model: x)`` or
    ``[gateway: running]``. Header/blank lines are skipped.
    """
    profiles: list[Profile] = []
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.endswith(":") or lowered.startswith(("profiles", "usage", "#")):
            continue
        is_active = stripped.startswith("*") or "(default)" in lowered or "active" in lowered
        body = stripped.lstrip("*-• ").strip()
        if not body:
            continue
        name = body.split()[0].strip(",")
        if not re.match(r"^[\w.\-]+$", name):
            continue
        model_m = _MODEL_RE.search(body)
        gw_m = _GATEWAY_RE.search(body)
        alias_m = _ALIAS_RE.search(body)
        profiles.append(
            Profile(
                name=name,
                model=model_m.group("model") if model_m else "",
                gateway=gw_m.group("gw") if gw_m else "",
                alias=alias_m.group("alias") if alias_m else "",
                is_active=is_active,
                source="cli",
            )
        )
    return profiles


def read_profile_config(config_path: Path) -> dict:
    """Extract only SAFE_KEYS scalar values from a profile config.yaml.

    Values still pass through redaction as a second belt in case someone
    stored a credential under a benign key name.
    """
    meta: dict[str, str] = {}
    try:
        text = config_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return meta
    for raw in text.splitlines():
        # Top-level scalars only: an indented line belongs to a nested
        # block we don't inspect.
        if raw[:1].isspace():
            continue
        m = _LINE_RE.match(raw)
        if not m:
            continue
        key = m.group("key").lower()
        if key not in SAFE_KEYS:
            continue
        value = m.group("val").strip().strip("'\"")
        meta[key] = redact_text(value)
    return meta


def discover_config_profiles(profiles_dir: Path) -> list[Profile]:
    """Build Profile records from ``profiles/*/config.yaml`` metadata."""
    found: list[Profile] = []
    if not profiles_dir.is_dir():
        return found
    for child in sorted(profiles_dir.iterdir()):
        if not child.is_dir():
            continue
        meta = {}
        cfg = child / "config.yaml"
        if cfg.exists():
            meta = read_profile_config(cfg)
        found.append(
            Profile(
                name=meta.get("name", child.name),
                model=meta.get("model", ""),
                alias=meta.get("alias", ""),
                description=meta.get("description", ""),
                gateway=meta.get("gateway", ""),
                source="config",
            )
        )
    return found


def merge_profiles(cli: list[Profile], cfg: list[Profile]) -> list[Profile]:
    """Merge CLI and config views; CLI wins for live state, config fills gaps."""
    by_name: dict[str, Profile] = {p.name: p for p in cli}
    for p in cfg:
        if p.name in by_name:
            base = by_name[p.name]
            base.model = base.model or p.model
            base.alias = base.alias or p.alias
            base.description = base.description or p.description
            base.gateway = base.gateway or p.gateway
            base.source = "cli+config"
        else:
            by_name[p.name] = p
    # Active profile first, then alphabetical.
    return sorted(by_name.values(), key=lambda p: (not p.is_active, p.name))
