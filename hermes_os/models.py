"""Typed, normalized records for the inventory.

Everything the collector produces is normalized into these dataclasses
so renderers (JSON / Markdown / HTML) work against one stable shape,
regardless of what the underlying Hermes files or command output looked
like. ``to_dict()`` on :class:`Inventory` yields plain JSON-safe data.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class CronJob:
    id: str = ""
    name: str = ""
    profile: str = ""
    schedule: str = ""
    enabled: Optional[bool] = None
    last_run: str = ""
    last_status: str = ""      # "ok" | "error" | "" (unknown)
    next_run: str = ""
    delivery: str = ""         # e.g. "telegram", "file"
    raw_keys: list = field(default_factory=list)  # for debugging odd schemas


@dataclass
class Profile:
    name: str = ""
    model: str = ""
    alias: str = ""
    description: str = ""
    gateway: str = ""          # e.g. "running" when profile owns the gateway
    is_active: bool = False
    source: str = ""           # "cli" | "config" | "cli+config"


@dataclass
class Risk:
    level: str = "warn"        # "warn" | "risk"
    code: str = ""
    message: str = ""


@dataclass
class HealthCheck:
    name: str = ""
    status: str = "unknown"    # "ok" | "warn" | "risk" | "unknown"
    detail: str = ""


@dataclass
class WikiStatus:
    root: str = ""
    exists: bool = False
    note_count: Optional[int] = None
    queue_total: Optional[int] = None
    queue_open: Optional[int] = None
    queue_done: Optional[int] = None
    recent_log: list = field(default_factory=list)      # last few log.md lines
    heartbeat_at: str = ""
    heartbeat_age_hours: Optional[float] = None
    heartbeat_stale: Optional[bool] = None
    lint_status: str = ""       # free text if a lint/audit report is detectable
    structural_files: dict = field(default_factory=dict)  # name -> bool


@dataclass
class DiskUsage:
    path: str = ""
    total_gb: Optional[float] = None
    used_pct: Optional[int] = None
    warn: bool = False


@dataclass
class Inventory:
    """The full, already-redacted system inventory."""

    generated_at: str = ""
    product: str = "Hermes-OS"
    product_version: str = ""
    host: dict = field(default_factory=dict)
    hermes: dict = field(default_factory=dict)      # version, bin_found
    gateway: dict = field(default_factory=dict)     # running(bool|None), status_text
    cron: dict = field(default_factory=dict)        # scheduler_running, jobs, counts
    profiles: list = field(default_factory=list)    # [Profile]
    tools: list = field(default_factory=list)       # [str]
    logs: dict = field(default_factory=dict)        # gateway_tail, errors_tail
    wiki: Optional[WikiStatus] = None
    today: dict = field(default_factory=dict)       # daybook: done + user-action queue
    disks: list = field(default_factory=list)       # [DiskUsage]
    approvals: dict = field(default_factory=dict)   # counts + pending preview
    skills: dict = field(default_factory=dict)      # lanes, promotion candidates
    projects: dict = field(default_factory=dict)    # lane -> {profiles, jobs}
    health: list = field(default_factory=list)      # [HealthCheck]
    risks: list = field(default_factory=list)       # [Risk]
    next_actions: list = field(default_factory=list)
    warnings: list = field(default_factory=list)    # collector-level notes

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON-safe dict with stable top-level key order."""

        def _convert(value: Any) -> Any:
            if isinstance(
                value,
                (CronJob, Profile, Risk, HealthCheck, WikiStatus, DiskUsage),
            ):
                return asdict(value)
            if isinstance(value, list):
                return [_convert(v) for v in value]
            if isinstance(value, dict):
                return {k: _convert(v) for k, v in value.items()}
            return value

        ordered = {
            "generated_at": self.generated_at,
            "product": self.product,
            "product_version": self.product_version,
            "host": self.host,
            "hermes": self.hermes,
            "gateway": self.gateway,
            "cron": self.cron,
            "profiles": self.profiles,
            "tools": self.tools,
            "logs": self.logs,
            "wiki": self.wiki,
            "today": self.today,
            "disks": self.disks,
            "approvals": self.approvals,
            "skills": self.skills,
            "projects": self.projects,
            "health": self.health,
            "risks": self.risks,
            "next_actions": self.next_actions,
            "warnings": self.warnings,
        }
        return _convert(ordered)
