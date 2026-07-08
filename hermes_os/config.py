"""Central configuration: path defaults + environment overrides.

Every path and tunable the product uses is defined here so that tests,
fixtures, and unusual setups can redirect the whole product with
``HERMES_OS_*`` environment variables. This module performs no I/O
beyond ``expanduser`` — existence checks belong to ``doctor``/collect.

Environment overrides (all optional):

    HERMES_OS_HERMES_HOME           default: ~/.hermes
    HERMES_OS_WIKI_ROOT             default: /storage/emulated/0/Documents/LLM-Wiki
    HERMES_OS_STATE_DIR             default: <hermes_home>/state/hermes-android-agentic-os
    HERMES_OS_DIST_DIR              default: <repo>/dist
    HERMES_OS_HERMES_BIN            default: hermes
    HERMES_OS_SELF_BIN              default: ~/.local/bin/hermes-os
    HERMES_OS_LOG_TAIL_LINES        default: 40
    HERMES_OS_HEARTBEAT_STALE_HOURS default: 26
    HERMES_OS_DISK_WARN_PCT         default: 90
    HERMES_OS_CMD_TIMEOUT           default: 12 (seconds)
    HERMES_OS_SKIP_COMMANDS         default: unset; "1" disables all subprocess calls
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ENV_PREFIX = "HERMES_OS_"

#: Android default location of the LLM-Wiki vault (shared storage).
DEFAULT_WIKI_ROOT = "/storage/emulated/0/Documents/LLM-Wiki"

#: Repo root (this file lives at <repo>/hermes_os/config.py).
REPO_ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(ENV_PREFIX + name, default)


def _env_path(name: str, default: str) -> Path:
    return Path(os.path.expanduser(_env(name, default)))


def _env_int(name: str, default: int) -> int:
    raw = _env(name, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env(name, str(default))
    try:
        return float(raw)
    except ValueError:
        return default


def is_termux() -> bool:
    """Best-effort Termux detection (env var or the canonical prefix path)."""
    if os.environ.get("TERMUX_VERSION"):
        return True
    return Path("/data/data/com.termux/files/usr").exists()


@dataclass
class Config:
    """Resolved configuration for one invocation."""

    hermes_home: Path
    wiki_root: Path
    state_dir: Path
    dist_dir: Path
    hermes_bin: str = "hermes"
    hermes_os_bin: str = str(Path.home() / ".local" / "bin" / "hermes-os")
    log_tail_lines: int = 40
    heartbeat_stale_hours: float = 26.0
    disk_warn_pct: int = 90
    cmd_timeout: int = 12
    skip_commands: bool = False
    repo_root: Path = field(default_factory=lambda: REPO_ROOT)

    # ---- derived paths -------------------------------------------------
    @property
    def cron_jobs_file(self) -> Path:
        return self.hermes_home / "cron" / "jobs.json"

    @property
    def gateway_log(self) -> Path:
        return self.hermes_home / "logs" / "gateway.log"

    @property
    def errors_log(self) -> Path:
        return self.hermes_home / "logs" / "errors.log"

    @property
    def profiles_dir(self) -> Path:
        return self.hermes_home / "profiles"

    @property
    def approvals_file(self) -> Path:
        return self.state_dir / "approvals.json"

    @property
    def action_scripts_dir(self) -> Path:
        return self.dist_dir / "actions"

    @property
    def history_file(self) -> Path:
        return self.state_dir / "history.jsonl"

    @property
    def apply_log_file(self) -> Path:
        return self.state_dir / "apply-log.jsonl"

    @property
    def action_receipts_file(self) -> Path:
        return self.state_dir / "action-receipts.jsonl"

    @property
    def public_dashboard_file(self) -> Path:
        return Path("/storage/emulated/0/Documents/HermesOS/index.html")

    @property
    def kanban_default_db(self) -> Path:
        return self.hermes_home / "kanban.db"

    @property
    def kanban_root(self) -> Path:
        return self.hermes_home / "kanban"

    @property
    def kanban_boards_dir(self) -> Path:
        return self.kanban_root / "boards"

    @property
    def kanban_current_file(self) -> Path:
        return self.kanban_root / "current"

    @property
    def templates_dir(self) -> Path:
        return self.repo_root / "templates"

    @property
    def dashboard_out(self) -> Path:
        return self.dist_dir / "index.html"

    # ---- construction --------------------------------------------------
    @classmethod
    def load(cls) -> "Config":
        """Build a Config from defaults + HERMES_OS_* environment overrides."""
        hermes_home = _env_path("HERMES_HOME", "~/.hermes")
        state_default = str(hermes_home / "state" / "hermes-android-agentic-os")
        return cls(
            hermes_home=hermes_home,
            wiki_root=_env_path("WIKI_ROOT", DEFAULT_WIKI_ROOT),
            state_dir=_env_path("STATE_DIR", state_default),
            dist_dir=_env_path("DIST_DIR", str(REPO_ROOT / "dist")),
            hermes_bin=_env("HERMES_BIN", "hermes"),
            hermes_os_bin=_env("SELF_BIN", str(Path.home() / ".local" / "bin" / "hermes-os")),
            log_tail_lines=_env_int("LOG_TAIL_LINES", 40),
            heartbeat_stale_hours=_env_float("HEARTBEAT_STALE_HOURS", 26.0),
            disk_warn_pct=_env_int("DISK_WARN_PCT", 90),
            cmd_timeout=_env_int("CMD_TIMEOUT", 12),
            skip_commands=_env("SKIP_COMMANDS", "") == "1",
        )

    def describe_paths(self) -> dict:
        """Plain-dict view of the resolved paths (for status/doctor output)."""
        return {
            "hermes_home": str(self.hermes_home),
            "wiki_root": str(self.wiki_root),
            "state_dir": str(self.state_dir),
            "dist_dir": str(self.dist_dir),
            "cron_jobs_file": str(self.cron_jobs_file),
            "gateway_log": str(self.gateway_log),
            "errors_log": str(self.errors_log),
            "profiles_dir": str(self.profiles_dir),
            "hermes_os_bin": str(self.hermes_os_bin),
            "approvals_file": str(self.approvals_file),
            "action_scripts_dir": str(self.action_scripts_dir),
            "history_file": str(self.history_file),
            "apply_log_file": str(self.apply_log_file),
            "action_receipts_file": str(self.action_receipts_file),
            "public_dashboard_file": str(self.public_dashboard_file),
            "kanban_default_db": str(self.kanban_default_db),
            "kanban_boards_dir": str(self.kanban_boards_dir),
            "kanban_current_file": str(self.kanban_current_file),
        }
