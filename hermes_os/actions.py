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
QUEUE_VERBS = {"queue"}
APPLY_VERBS = {"dry-run", "execute"}
SYSTEM_VERBS = {"refresh"}
VALID_ACTION_VERBS = DECISION_VERBS | QUEUE_VERBS | APPLY_VERBS | SYSTEM_VERBS

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



def derived_action_id(kind: str, title: str, source: str = "") -> str:
    """Stable URL-safe id for a dashboard-derived action candidate."""
    raw = f"{kind}|{title}|{source}".lower().encode("utf-8", "replace")
    return "drv-" + hashlib.sha256(raw).hexdigest()[:12]


def derive_action_candidates(inv) -> list[dict]:
    """Promote Daybook/Next Actions observations into queueable decisions.

    This is intentionally non-mutating: render/collect can suggest candidates,
    but a button click must explicitly queue one as a real pending approval.
    """
    candidates: list[dict] = []
    seen: set[str] = set()

    def add(kind: str, title: str, detail: str = "", source: str = "", risk: str = "medium") -> None:
        title = redact_text(str(title or "")).strip()
        detail = redact_text(str(detail or "")).strip()
        source = redact_text(str(source or "")).strip()
        if not title:
            return
        cid = derived_action_id(kind, title, source)
        if cid in seen:
            return
        seen.add(cid)
        candidates.append({
            "id": cid,
            "kind": kind or "derived-action",
            "title": title[:140],
            "detail": detail or "Derived from Hermes-OS dashboard signal.",
            "source": source,
            "risk_level": risk if risk in {"low", "medium", "high"} else "medium",
            "suggested_command": "",
            "rollback": "Record-only approval candidate; reject or mark done to close it.",
        })

    today = getattr(inv, "today", None) or {}
    for item in today.get("requires_action", []) or []:
        kind = str(item.get("kind") or "requires-action")
        risk = "low" if "approval" in kind.lower() else "medium"
        detail = str(item.get("detail") or "")
        source = str(item.get("source") or "")
        add(kind, str(item.get("title") or kind), detail, source, risk)

    for idx, title in enumerate(getattr(inv, "next_actions", []) or []):
        text = str(title or "")
        if not text or text.lower().startswith("all clear"):
            continue
        add("next-action", text, "Derived from the dashboard Next actions section.", f"next-actions:{idx}", "medium")
        if len(candidates) >= 12:
            break
    return candidates[:12]

class ActionBridge:
    """Dispatch a structured button action and append a receipt."""

    def __init__(self, cfg: Config, queue: Optional[ApprovalQueue] = None):
        self.cfg = cfg
        self.queue = queue or ApprovalQueue(cfg.approvals_file)
        self.apply = GuardedApply(cfg, self.queue)

    def command_for(self, object_id: str, verb: str) -> list[str]:
        if verb in DECISION_VERBS:
            return ["hermes-os", "approvals", "set", object_id, _STATUS_FOR_VERB[verb]]
        if verb == "queue":
            return ["hermes-os", "action", object_id, "--verb", "queue"]
        if verb == "dry-run":
            return ["hermes-os", "apply", object_id]
        if verb == "execute":
            return ["hermes-os", "apply", object_id, "--execute"]
        if verb == "refresh" and object_id == "system":
            return ["hermes-os", "render-html"]
        return []

    def execution_command_for(self, command: list[str]) -> list[str]:
        """Map display argv to executable argv for plugin environments without ~/.local/bin on PATH."""
        if command and command[0] == "hermes-os":
            return [str(Path(self.cfg.hermes_os_bin).expanduser()), *command[1:]]
        return list(command)

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

        if verb == "queue":
            result = self._queue_derived_action(action_id, object_id, command, source)
            self._refresh_dashboard_best_effort(result)
            return self._append_receipt(result)

        if verb in APPLY_VERBS:
            apply_result = self.apply.apply(object_id, dry_run=(verb == "dry-run"))
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
                self.execution_command_for(command),
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


    def _queue_derived_action(self, action_id: str, object_id: str, command: list[str], source: str) -> ActionResult:
        try:
            from .collect import collect

            inv = collect(self.cfg)
            candidates = {c.get("id"): c for c in derive_action_candidates(inv)}
        except Exception as exc:  # pragma: no cover - defensive mobile fallback
            return ActionResult(
                action_id=action_id,
                object_id=object_id,
                verb="queue",
                status="failed",
                source=source,
                command=command,
                reason="could not collect derived actions: " + redact_text(str(exc)),
            )
        candidate = candidates.get(object_id)
        if not candidate:
            return ActionResult(
                action_id=action_id,
                object_id=object_id,
                verb="queue",
                status="refused",
                source=source,
                command=command,
                reason=f"no derived action candidate with id {object_id!r}",
            )
        marker = f"source: {candidate.get('source', '')} · candidate: {object_id}"
        for item in self.queue.load():
            if item.title == candidate.get("title") and marker in item.detail:
                return ActionResult(
                    action_id=action_id,
                    object_id=item.id,
                    verb="queue",
                    status="ok",
                    source=source,
                    command=command,
                    reason=f"approval already queued as {item.id}",
                )
        detail_parts = [candidate.get("detail", ""), marker]
        item = self.queue.add(
            title=str(candidate.get("title", "")),
            kind=str(candidate.get("kind", "derived-action")),
            detail="\n\n".join(x for x in detail_parts if x),
            risk_level=str(candidate.get("risk_level", "medium")),
            suggested_command=str(candidate.get("suggested_command", "")),
            rollback=str(candidate.get("rollback", "Record-only approval candidate; reject or mark done to close it.")),
        )
        return ActionResult(
            action_id=action_id,
            object_id=item.id,
            verb="queue",
            status="ok",
            source=source,
            command=command,
            reason=f"approval queued as {item.id}",
        )

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
