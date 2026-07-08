"""Native Decision Bridge v0.4.

Structured action dispatcher for Android/WebView buttons. The bridge accepts a
small verb vocabulary and maps it to Hermes-OS operations; it never accepts an
arbitrary shell command from the UI.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .apply import GuardedApply
from .approvals import ApprovalQueue
from .config import Config
from .redact import redact_text

DECISION_VERBS = {"approve", "reject", "done"}
APPLY_VERBS = {"dry-run", "execute"}
SYSTEM_VERBS = {"refresh"}
VALID_ACTION_VERBS = DECISION_VERBS | APPLY_VERBS | SYSTEM_VERBS

_STATUS_FOR_VERB = {
    "approve": "approved",
    "reject": "rejected",
    "done": "done",
}


@dataclass
class ActionResult:
    action_id: str
    object_id: str
    verb: str
    status: str                  # ok | dry-run | executed | failed | refused
    command: list[str]
    source: str = "cli"
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
        if raw.get("entry_hash"):
            return str(raw["entry_hash"])
    return ""


def latest_receipt(path: Path) -> dict:
    """Return the most recent valid action receipt, or an empty dict."""
    if not path.exists():
        return {}
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return {}
    for line in reversed(lines):
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            return raw
    return {}


class ActionBridge:
    """Dispatch a structured button action and append a receipt."""

    def __init__(self, cfg: Config, queue: Optional[ApprovalQueue] = None):
        self.cfg = cfg
        self.queue = queue or ApprovalQueue(cfg.approvals_file)

    def command_for(self, object_id: str, verb: str) -> list[str]:
        if verb in DECISION_VERBS:
            return ["hermes-os", "approvals", "set", object_id, _STATUS_FOR_VERB[verb]]
        if verb == "dry-run":
            return ["hermes-os", "apply", object_id]
        if verb == "execute":
            return ["hermes-os", "apply", object_id, "--execute"]
        if verb == "refresh" and object_id == "system":
            return ["hermes-os", "render-html"]
        return []

    def dispatch(self, object_id: str, verb: str, *, source: str = "cli") -> ActionResult:
        object_id = str(object_id or "").strip()
        verb = str(verb or "").strip()
        action_id = "act-" + uuid.uuid4().hex[:10]

        if verb not in VALID_ACTION_VERBS:
            return self._append_receipt(ActionResult(
                action_id=action_id,
                object_id=object_id,
                verb=verb,
                status="refused",
                source=source,
                command=[],
                reason=f"unknown verb {verb!r}; expected one of {sorted(VALID_ACTION_VERBS)}",
            ))

        if verb == "refresh" and object_id != "system":
            return self._append_receipt(ActionResult(
                action_id=action_id,
                object_id=object_id,
                verb=verb,
                status="refused",
                source=source,
                command=[],
                reason="refresh is only allowed for object id 'system'",
            ))

        command = self.command_for(object_id, verb)

        if verb in DECISION_VERBS:
            try:
                item = self.queue.set_status(object_id, _STATUS_FOR_VERB[verb])
            except KeyError as exc:
                return self._append_receipt(ActionResult(
                    action_id=action_id,
                    object_id=object_id,
                    verb=verb,
                    status="refused",
                    source=source,
                    command=command,
                    reason=str(exc),
                ))
            result = ActionResult(
                action_id=action_id,
                object_id=item.id,
                verb=verb,
                status="ok",
                source=source,
                command=command,
                reason=f"approval marked {item.status}",
            )
            self._refresh_dashboard_best_effort(result)
            return self._append_receipt(result)

        if verb in APPLY_VERBS:
            apply_result = GuardedApply(self.cfg, self.queue).apply(object_id, dry_run=(verb == "dry-run"))
            result = ActionResult(
                action_id=action_id,
                object_id=apply_result.approval_id,
                verb=verb,
                status=apply_result.status,
                source=source,
                command=command,
                executed=apply_result.executed,
                reason=apply_result.reason,
                returncode=apply_result.returncode,
                stdout=apply_result.stdout,
                stderr=apply_result.stderr,
            )
            self._refresh_dashboard_best_effort(result)
            return self._append_receipt(result)

        # verb == refresh, object_id == system
        if self.cfg.skip_commands:
            result = ActionResult(
                action_id=action_id,
                object_id=object_id,
                verb=verb,
                status="refused",
                source=source,
                command=command,
                reason="execution disabled by HERMES_OS_SKIP_COMMANDS",
            )
            return self._append_receipt(result)
        try:
            proc = subprocess.run(
                command,
                cwd=str(self.cfg.repo_root),
                text=True,
                capture_output=True,
                timeout=self.cfg.cmd_timeout,
                shell=False,
                env=os.environ.copy(),
            )
            result = ActionResult(
                action_id=action_id,
                object_id=object_id,
                verb=verb,
                status="ok" if proc.returncode == 0 else "failed",
                source=source,
                command=command,
                executed=True,
                reason="dashboard refresh completed" if proc.returncode == 0 else "dashboard refresh failed",
                returncode=proc.returncode,
                stdout=redact_text(proc.stdout[-4000:]),
                stderr=redact_text(proc.stderr[-4000:]),
            )
            self._mirror_dashboard_best_effort(result)
            return self._append_receipt(result)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return self._append_receipt(ActionResult(
                action_id=action_id,
                object_id=object_id,
                verb=verb,
                status="failed",
                source=source,
                command=command,
                executed=True,
                reason=redact_text(str(exc)),
            ))

    def _refresh_dashboard_best_effort(self, result: ActionResult) -> None:
        """Regenerate static dashboard after a state-changing button action.

        This is deliberately best-effort: decision success/refusal should still be
        recorded even if rendering fails due to a transient collector issue.
        """
        try:
            from .collect import collect
            from .render_html import write_dashboard

            written = write_dashboard(collect(self.cfg), self.cfg.dashboard_out, self.cfg.templates_dir / "dashboard.html")
            self._copy_public(written)
        except Exception as exc:  # pragma: no cover - defensive mobile fallback
            note = redact_text(str(exc))
            result.reason = (result.reason + f"; dashboard refresh warning: {note}").strip("; ")

    def _mirror_dashboard_best_effort(self, result: ActionResult) -> None:
        try:
            self._copy_public(self.cfg.dashboard_out)
        except Exception as exc:  # pragma: no cover - defensive mobile fallback
            note = redact_text(str(exc))
            result.reason = (result.reason + f"; mirror warning: {note}").strip("; ")

    def _copy_public(self, source: Path) -> None:
        public = self.cfg.public_dashboard_file
        if not source.exists():
            return
        public.parent.mkdir(parents=True, exist_ok=True)
        public.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    def _append_receipt(self, result: ActionResult) -> ActionResult:
        path = self.cfg.action_receipts_file
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = result.to_dict()
        for key in ("object_id", "verb", "reason", "stdout", "stderr"):
            payload[key] = redact_text(str(payload.get(key, "")))
        payload["command"] = [redact_text(str(part)) for part in payload.get("command", [])]
        payload.update({
            "version": 1,
            "timestamp": _now_iso(),
            "prev_hash": _last_entry_hash(path),
        })
        payload["entry_hash"] = _canonical_hash(payload)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")
        result.entry_hash = payload["entry_hash"]
        return result
