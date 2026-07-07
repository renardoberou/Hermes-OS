"""Read-only parsing of the Hermes cron state.

The on-disk schema of ``~/.hermes/cron/jobs.json`` is treated as
untrusted and possibly version-drifting: the parser accepts either a
bare list of jobs or a ``{"jobs": [...]}`` wrapper, and looks each
field up under several plausible key names. Unknown fields are ignored;
nothing here writes anything.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import CronJob

# Candidate key names per normalized field, checked in order.
_KEYMAP: dict[str, tuple[str, ...]] = {
    "id": ("id", "job_id", "uuid", "key"),
    "name": ("name", "title", "label", "description"),
    "profile": ("profile", "agent", "profile_name"),
    "schedule": ("schedule", "cron", "cron_expr", "interval", "every", "spec"),
    "enabled": ("enabled", "active", "is_enabled"),
    "last_run": ("last_run", "lastRun", "last_run_at", "last_started_at"),
    "last_status": ("last_status", "lastStatus", "last_result", "status"),
    "next_run": ("next_run", "nextRun", "next_run_at", "next_fire_time"),
    "delivery": ("delivery", "target", "channel", "notify", "output"),
}


def _pick(record: dict, field: str) -> Any:
    for key in _KEYMAP[field]:
        if key in record and record[key] is not None:
            return record[key]
    return None


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        # e.g. delivery: {"type": "telegram", "chat": ...} -> "telegram"
        if isinstance(value, dict):
            for k in ("type", "kind", "name", "channel"):
                if isinstance(value.get(k), str):
                    return value[k]
        return json.dumps(value, ensure_ascii=False)[:80]
    return str(value)


def _as_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "on", "1", "enabled", "active"):
            return True
        if lowered in ("false", "no", "off", "0", "disabled", "paused"):
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def normalize_job(record: dict) -> CronJob:
    """Normalize one raw job record into a :class:`CronJob`."""
    status = _as_str(_pick(record, "last_status")).lower()
    if status in ("success", "succeeded", "passed", "done", "completed"):
        status = "ok"
    elif status in ("failure", "failed", "err", "crash", "crashed"):
        status = "error"
    return CronJob(
        id=_as_str(_pick(record, "id")),
        name=_as_str(_pick(record, "name")) or _as_str(_pick(record, "id")),
        profile=_as_str(_pick(record, "profile")),
        schedule=_as_str(_pick(record, "schedule")),
        enabled=_as_bool(_pick(record, "enabled")),
        last_run=_as_str(_pick(record, "last_run")),
        last_status=status,
        next_run=_as_str(_pick(record, "next_run")),
        delivery=_as_str(_pick(record, "delivery")),
        raw_keys=sorted(record.keys()),
    )


def parse_jobs_payload(payload: Any) -> list[CronJob]:
    """Accept a decoded jobs.json payload in any of the tolerated shapes."""
    records: Iterable
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        for key in ("jobs", "items", "entries", "crons"):
            if isinstance(payload.get(key), list):
                records = payload[key]
                break
        else:
            # A dict of id -> job is also plausible.
            values = list(payload.values())
            if values and all(isinstance(v, dict) for v in values):
                records = values
            else:
                return []
    else:
        return []
    return [normalize_job(r) for r in records if isinstance(r, dict)]


def read_jobs(path: Path) -> tuple[list[CronJob], list[str]]:
    """Read and parse jobs.json. Returns (jobs, warnings); never raises."""
    warnings: list[str] = []
    if not path.exists():
        warnings.append(f"cron jobs file not found: {path}")
        return [], warnings
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"could not parse {path.name}: {exc}")
        return [], warnings
    jobs = parse_jobs_payload(payload)
    if not jobs:
        warnings.append(f"{path.name} parsed but contained no recognizable jobs")
    return jobs, warnings


def parse_scheduler_status(text: str) -> Optional[bool]:
    """Interpret `hermes cron status` output. True/False/None(unknown)."""
    lowered = (text or "").lower()
    if not lowered.strip():
        return None
    if "not running" in lowered or "stopped" in lowered or "inactive" in lowered:
        return False
    if "running" in lowered or "active" in lowered or "started" in lowered:
        return True
    return None


def job_counts(jobs: list[CronJob]) -> dict:
    enabled = [j for j in jobs if j.enabled is not False]
    return {
        "total": len(jobs),
        "enabled": len(enabled),
        "disabled": len(jobs) - len(enabled),
        "failing": len([j for j in jobs if j.last_status == "error"]),
    }


def upcoming(jobs: list[CronJob], limit: int = 6) -> list[CronJob]:
    """Jobs sorted by next_run when present; schedule-only jobs follow."""
    dated = sorted(
        (j for j in jobs if j.next_run and j.enabled is not False),
        key=lambda j: j.next_run,
    )
    undated = [j for j in jobs if not j.next_run and j.enabled is not False]
    return (dated + undated)[:limit]
