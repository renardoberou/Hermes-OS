"""Local JSONL audit trail and trend summaries for Hermes-OS.

History is intentionally small and append-only: each line stores a redacted
health/risk summary derived from one inventory collection. It is not a full
snapshot database and never stores prompts, logs, credentials, or task bodies.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import Config
from .models import Inventory
from .redact import redact_obj, redact_text

_TREND_FIELDS = (
    "cron_failing",
    "approvals_pending",
    "kanban_running",
    "kanban_blocked",
    "kanban_open",
    "active_agents",
    "risk_count",
    "warn_count",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _wiki_heartbeat(inv: Inventory) -> Optional[float]:
    if inv.wiki is None:
        return None
    return inv.wiki.heartbeat_age_hours


def history_entry(inv: Inventory) -> dict[str, Any]:
    """Return the compact, redacted audit-trail row for an inventory."""
    cron_counts = inv.cron.get("counts", {}) if inv.cron else {}
    approval_counts = inv.approvals.get("counts", {}) if inv.approvals else {}
    kanban_counts = inv.kanban.get("counts", {}) if inv.kanban else {}
    risks = list(inv.risks or [])
    entry = {
        "recorded_at": _now_iso(),
        "inventory_generated_at": inv.generated_at,
        "gateway_running": inv.gateway.get("running") if inv.gateway else None,
        "cron_scheduler_running": inv.cron.get("scheduler_running") if inv.cron else None,
        "cron_total": int(cron_counts.get("total", 0) or 0),
        "cron_enabled": int(cron_counts.get("enabled", 0) or 0),
        "cron_failing": int(cron_counts.get("failing", 0) or 0),
        "approvals_pending": int(approval_counts.get("pending", 0) or 0),
        "approvals_total": int(approval_counts.get("total", 0) or 0),
        "wiki_heartbeat_age_hours": _wiki_heartbeat(inv),
        "wiki_queue_open": inv.wiki.queue_open if inv.wiki else None,
        "wiki_queue_total": inv.wiki.queue_total if inv.wiki else None,
        "kanban_running": int(kanban_counts.get("running", 0) or 0),
        "kanban_blocked": int(kanban_counts.get("blocked", 0) or 0),
        "kanban_open": int(inv.kanban.get("open_count", 0) or 0) if inv.kanban else 0,
        "active_agents": len(inv.kanban.get("active_agents", []) or []) if inv.kanban else 0,
        "risk_count": sum(1 for r in risks if r.level == "risk"),
        "warn_count": sum(1 for r in risks if r.level == "warn"),
        "risk_codes": [redact_text(r.code) for r in risks[:12]],
    }
    return redact_obj(entry)


def append_history(cfg: Config, inv: Inventory) -> dict[str, Any]:
    """Append one compact inventory summary to ``cfg.history_file``."""
    entry = history_entry(inv)
    path = cfg.history_file
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
    # Atomic append for Android: write a temp copy, then replace. The history
    # file is small by design; callers can rotate later if it grows.
    existing = ""
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = ""
    fd, tmp = tempfile.mkstemp(prefix=".history-", suffix=".jsonl", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            if existing:
                fh.write(existing.rstrip("\n") + "\n")
            fh.write(line + "\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return entry


def read_history(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    """Read valid JSONL rows, tolerating missing/corrupt lines."""
    if not Path(path).exists():
        return []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(redact_obj(item))
    return rows[-limit:] if limit else rows


def summarize_trend(path: Path, limit: int = 200) -> dict[str, Any]:
    rows = read_history(path, limit=limit)
    if not rows:
        return {"samples": 0, "latest": {}, "max": {}, "first": {}, "history_file": str(path)}
    maxima: dict[str, Any] = {}
    for field in _TREND_FIELDS:
        values = [int(row.get(field, 0) or 0) for row in rows]
        maxima[field] = max(values) if values else 0
    return {
        "samples": len(rows),
        "first": rows[0],
        "latest": rows[-1],
        "max": maxima,
        "history_file": str(path),
    }


def render_trend_text(trend: dict[str, Any]) -> str:
    if not trend.get("samples"):
        return f"no history samples yet ({trend.get('history_file', 'history.jsonl')})\n"
    latest = trend.get("latest", {}) or {}
    maxima = trend.get("max", {}) or {}
    lines = [
        f"samples: {trend.get('samples', 0)}",
        f"latest recorded: {latest.get('recorded_at', '—')}",
        f"latest cron failing: {latest.get('cron_failing', 0)} (max {maxima.get('cron_failing', 0)})",
        f"latest approvals pending: {latest.get('approvals_pending', 0)} (max {maxima.get('approvals_pending', 0)})",
        f"latest Kanban running/blocked/open: {latest.get('kanban_running', 0)}/{latest.get('kanban_blocked', 0)}/{latest.get('kanban_open', 0)}",
        f"latest active agents: {latest.get('active_agents', 0)} (max {maxima.get('active_agents', 0)})",
        f"latest risk/warn count: {latest.get('risk_count', 0)}/{latest.get('warn_count', 0)}",
    ]
    return "\n".join(lines) + "\n"
