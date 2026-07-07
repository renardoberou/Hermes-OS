"""Read-only LLM-Wiki status: queue, log, heartbeat, structure.

Reads only the vault's structural files (SCHEMA.md, index.md,
index-full.md, log.md, queries/queue-keep.md, the heartbeat file) plus
directory-level counts. Note bodies are never ingested wholesale — the
wiki is B.'s canonical knowledge layer, and this product only reports
on its operational health.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import WikiStatus
from .redact import redact_text

STRUCTURAL_FILES = (
    "SCHEMA.md",
    "index.md",
    "index-full.md",
    "log.md",
    "queries/queue-keep.md",
    "_meta/personal-api/HEARTBEAT.md",
)

_CHECKBOX_RE = re.compile(r"^\s*[-*]\s*\[(?P<state>[ xX])\]", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*]\s+\S", re.MULTILINE)
_ISO_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:?\d{2}|Z)?)"
)
_LINT_CANDIDATES = (
    "_meta/lint-status.md",
    "_meta/audit-status.md",
    "audits/latest.md",
    "lint-report.md",
)


def _read(path: Path, limit_bytes: int = 200_000) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit_bytes)
    except OSError:
        return ""


def count_queue(text: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """(total, open, done) from a queue markdown file.

    Checkbox items are authoritative when present; otherwise plain
    bullets count as open items.
    """
    if not text.strip():
        return None, None, None
    boxes = _CHECKBOX_RE.findall(text)
    if boxes:
        done = sum(1 for s in boxes if s.lower() == "x")
        total = len(boxes)
        return total, total - done, done
    bullets = _BULLET_RE.findall(text)
    if bullets:
        return len(bullets), len(bullets), 0
    return 0, 0, 0


def tail_log_entries(text: str, limit: int = 5) -> list[str]:
    """Last *limit* non-empty content lines of log.md, redacted, trimmed."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    content = [ln for ln in lines if not ln.startswith("#")]
    out = []
    for ln in content[-limit:]:
        out.append(redact_text(ln)[:160])
    return out


def parse_heartbeat(
    path: Path, now: Optional[datetime] = None
) -> tuple[str, Optional[float]]:
    """(timestamp_str, age_hours) from the heartbeat file.

    Prefers an ISO timestamp inside the file; falls back to file mtime.
    """
    now = now or datetime.now(timezone.utc)
    if not path.exists():
        return "", None
    text = _read(path, 20_000)
    ts: Optional[datetime] = None
    label = ""
    matches = _ISO_RE.findall(text)
    if matches:
        label = matches[-1]
        ts = _parse_iso(label)
    if ts is None:
        try:
            mtime = path.stat().st_mtime
            ts = datetime.fromtimestamp(mtime, tz=timezone.utc)
            label = ts.isoformat(timespec="seconds")
        except OSError:
            return "", None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = (now - ts).total_seconds() / 3600.0
    return label, round(age, 2)


def _parse_iso(raw: str) -> Optional[datetime]:
    candidate = raw.strip().replace(" ", "T")
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    # Normalize +HHMM to +HH:MM for fromisoformat on older Pythons.
    m = re.search(r"([+-]\d{2})(\d{2})$", candidate)
    if m:
        candidate = candidate[: -4] + m.group(1) + ":" + m.group(2)
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def collect_wiki(
    root: Path,
    stale_hours: float = 26.0,
    now: Optional[datetime] = None,
) -> WikiStatus:
    """Build the full WikiStatus for the vault at *root*. Never raises."""
    status = WikiStatus(root=str(root), exists=root.is_dir())
    if not status.exists:
        return status

    # Structural file presence map.
    for rel in STRUCTURAL_FILES:
        status.structural_files[rel] = (root / rel).exists()

    # Note count: markdown files, excluding meta/hidden dirs.
    try:
        count = 0
        for p in root.rglob("*.md"):
            parts = p.relative_to(root).parts
            if any(part.startswith((".", "_")) for part in parts[:-1]):
                continue
            count += 1
        status.note_count = count
    except OSError:
        status.note_count = None

    # Queue.
    q_total, q_open, q_done = count_queue(_read(root / "queries" / "queue-keep.md"))
    status.queue_total, status.queue_open, status.queue_done = q_total, q_open, q_done

    # Recent log entries.
    status.recent_log = tail_log_entries(_read(root / "log.md"))

    # Heartbeat.
    hb_path = root / "_meta" / "personal-api" / "HEARTBEAT.md"
    status.heartbeat_at, status.heartbeat_age_hours = parse_heartbeat(hb_path, now)
    if status.heartbeat_age_hours is not None:
        status.heartbeat_stale = status.heartbeat_age_hours > stale_hours

    # Lint/audit status if any known report file exists.
    for rel in _LINT_CANDIDATES:
        p = root / rel
        if p.exists():
            first = _read(p, 4_000).strip().splitlines()
            if first:
                status.lint_status = redact_text(first[0])[:160]
            break

    return status
