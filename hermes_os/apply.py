"""Guarded Apply v0.1: narrow allowlisted execution with audit logging.

The module is intentionally conservative. It accepts only approved, non-stale,
non-high-risk approval records that include rollback metadata and whose command
matches a small exact allowlist. Dry-run is the default caller posture; actual
execution uses ``subprocess.run(..., shell=False)`` and records an append-only
hash-chained JSONL entry.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .approvals import Approval, ApprovalQueue
from .config import Config
from .redact import redact_text

DEFAULT_MAX_APPROVAL_AGE_HOURS = 24.0

# Exact command families allowed in v0.1. Keep this boring on purpose.
_ALLOWED_EXACT: tuple[tuple[str, ...], ...] = (
    ("hermes-os", "status"),
    ("hermes-os", "trend"),
    ("hermes-os", "history", "append"),
    ("hermes-os", "render-html"),
)


@dataclass
class ApplyResult:
    action_id: str
    approval_id: str
    command: str
    status: str              # dry-run | executed | failed | refused
    mode: str                # dry-run | execute
    executed: bool = False
    reason: str = ""
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    entry_hash: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _canonical_hash(payload: dict) -> str:
    body = {k: v for k, v in payload.items() if k != "entry_hash"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _last_entry_hash(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        h = raw.get("entry_hash")
        if h:
            return str(h)
    return ""


class GuardedApply:
    """Validate and optionally execute one approval record under v0.1 guards."""

    def __init__(self, cfg: Config, queue: Optional[ApprovalQueue] = None):
        self.cfg = cfg
        self.queue = queue or ApprovalQueue(cfg.approvals_file)

    def command_argv(self, command: str) -> list[str]:
        try:
            return shlex.split(command)
        except ValueError:
            return []

    def is_allowlisted(self, command: str) -> bool:
        argv = self.command_argv(command)
        if tuple(argv) in _ALLOWED_EXACT:
            return True
        # Allow render-html with a single explicit output path only when it stays
        # inside dist/ or the public HermesOS mirror directory.
        if len(argv) == 4 and tuple(argv[:2]) == ("hermes-os", "render-html") and argv[2] == "--out":
            out = Path(argv[3]).expanduser()
            if not out.is_absolute():
                out = (self.cfg.repo_root / out).resolve()
            else:
                out = out.resolve()
            allowed_roots = [
                self.cfg.dist_dir.resolve(),
                Path("/storage/emulated/0/Documents/HermesOS").resolve(),
            ]
            return any(out == root or root in out.parents for root in allowed_roots)
        return False

    def validate(self, item: Approval, *, max_age_hours: float = DEFAULT_MAX_APPROVAL_AGE_HOURS) -> Optional[str]:
        if item.status != "approved":
            return f"approval must be approved before guarded apply; current status is {item.status!r}"
        if item.risk_level == "high":
            return "high-risk approvals are refused by Guarded Apply v0.1"
        if not item.rollback.strip():
            return "rollback metadata is required before guarded apply"
        if not item.suggested_command.strip():
            return "suggested command is required before guarded apply"
        timestamp = _parse_iso(item.updated_at or item.created_at)
        if timestamp is None:
            return "approval timestamp is missing or invalid"
        age_hours = (datetime.now(timezone.utc) - timestamp).total_seconds() / 3600
        if age_hours > max_age_hours:
            return f"stale approval refused: {age_hours:.1f}h old exceeds {max_age_hours:.1f}h limit"
        if not self.is_allowlisted(item.suggested_command):
            return "command is outside the Guarded Apply v0.1 allowlist"
        return None

    def apply(self, item_id: str, *, dry_run: bool = True, max_age_hours: float = DEFAULT_MAX_APPROVAL_AGE_HOURS) -> ApplyResult:
        action_id = "act-" + uuid.uuid4().hex[:10]
        try:
            item = self.queue.get(item_id)
        except KeyError as exc:
            result = ApplyResult(
                action_id=action_id,
                approval_id=item_id,
                command="",
                status="refused",
                mode="dry-run" if dry_run else "execute",
                reason=str(exc),
            )
            return self._append_log(result)

        reason = self.validate(item, max_age_hours=max_age_hours)
        if reason:
            result = ApplyResult(
                action_id=action_id,
                approval_id=item.id,
                command=item.suggested_command,
                status="refused",
                mode="dry-run" if dry_run else "execute",
                reason=reason,
            )
            return self._append_log(result)

        if dry_run:
            result = ApplyResult(
                action_id=action_id,
                approval_id=item.id,
                command=item.suggested_command,
                status="dry-run",
                mode="dry-run",
                executed=False,
                reason="validated only; use --execute for guarded execution",
            )
            return self._append_log(result)

        if self.cfg.skip_commands:
            result = ApplyResult(
                action_id=action_id,
                approval_id=item.id,
                command=item.suggested_command,
                status="refused",
                mode="execute",
                executed=False,
                reason="execution disabled by HERMES_OS_SKIP_COMMANDS",
            )
            return self._append_log(result)

        argv = self.command_argv(item.suggested_command)
        try:
            proc = subprocess.run(
                argv,
                cwd=str(self.cfg.repo_root),
                text=True,
                capture_output=True,
                timeout=self.cfg.cmd_timeout,
                shell=False,
                env=os.environ.copy(),
            )
            status = "executed" if proc.returncode == 0 else "failed"
            result = ApplyResult(
                action_id=action_id,
                approval_id=item.id,
                command=item.suggested_command,
                status=status,
                mode="execute",
                executed=True,
                reason="command completed" if proc.returncode == 0 else "command exited non-zero",
                returncode=proc.returncode,
                stdout=redact_text(proc.stdout[-4000:]),
                stderr=redact_text(proc.stderr[-4000:]),
            )
            if proc.returncode == 0:
                self.queue.set_status(item.id, "done")
            return self._append_log(result)
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = ApplyResult(
                action_id=action_id,
                approval_id=item.id,
                command=item.suggested_command,
                status="failed",
                mode="execute",
                executed=True,
                reason=redact_text(str(exc)),
            )
            return self._append_log(result)

    def _append_log(self, result: ApplyResult) -> ApplyResult:
        path = self.cfg.apply_log_file
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = result.to_dict()
        for key in ("command", "reason", "stdout", "stderr"):
            payload[key] = redact_text(str(payload.get(key, "")))
        payload.update(
            {
                "version": 1,
                "timestamp": _now_iso(),
                "prev_hash": _last_entry_hash(path),
            }
        )
        payload["entry_hash"] = _canonical_hash(payload)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")
        result.entry_hash = payload["entry_hash"]
        return result
