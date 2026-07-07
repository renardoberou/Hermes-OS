"""Local approval queue: a file of intentions, never an executor.

The queue is a single JSON file (default:
``~/.hermes/state/hermes-android-agentic-os/approvals.json``). Items
record *proposed* actions with risk levels and optional rollback notes.
This module can add items, list them, and change their status — and
that is all. Nothing in this product ever executes an approval item's
``suggested_command``; execution stays a deliberate human act in a
separate terminal.

Writes are atomic (temp file + ``os.replace``) so a killed process
can't corrupt the queue on Android.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .redact import redact_text

VALID_STATUS = ("pending", "approved", "rejected", "done")
VALID_RISK = ("low", "medium", "high")


@dataclass
class Approval:
    id: str
    created_at: str
    title: str
    kind: str
    detail: str = ""
    risk_level: str = "medium"
    status: str = "pending"
    suggested_command: str = ""
    rollback: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _new_id() -> str:
    return "apv-" + uuid.uuid4().hex[:8]


class ApprovalQueue:
    """File-backed queue. All reads tolerate a missing/corrupt file."""

    def __init__(self, path: Path):
        self.path = Path(path)

    # ---- persistence ---------------------------------------------------
    def load(self) -> list[Approval]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        items = payload.get("items", []) if isinstance(payload, dict) else payload
        out: list[Approval] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            out.append(
                Approval(
                    id=str(raw.get("id", _new_id())),
                    created_at=str(raw.get("created_at", "")),
                    title=str(raw.get("title", "")),
                    kind=str(raw.get("kind", "")),
                    detail=str(raw.get("detail", "")),
                    risk_level=str(raw.get("risk_level", "medium")),
                    status=str(raw.get("status", "pending")),
                    suggested_command=str(raw.get("suggested_command", "")),
                    rollback=str(raw.get("rollback", "")),
                    updated_at=str(raw.get("updated_at", "")),
                )
            )
        return out

    def _save(self, items: list[Approval]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": _now_iso(),
            "items": [a.to_dict() for a in items],
        }
        data = json.dumps(payload, indent=2, ensure_ascii=False)
        fd, tmp = tempfile.mkstemp(
            prefix=".approvals-", suffix=".json", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data + "\n")
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    # ---- operations ----------------------------------------------------
    def add(
        self,
        title: str,
        kind: str,
        detail: str = "",
        risk_level: str = "medium",
        suggested_command: str = "",
        rollback: str = "",
    ) -> Approval:
        if not title.strip():
            raise ValueError("approval title must not be empty")
        if risk_level not in VALID_RISK:
            raise ValueError(f"risk_level must be one of {VALID_RISK}")
        item = Approval(
            id=_new_id(),
            created_at=_now_iso(),
            title=redact_text(title.strip()),
            kind=redact_text(kind.strip()) or "general",
            detail=redact_text(detail.strip()),
            risk_level=risk_level,
            status="pending",
            suggested_command=redact_text(suggested_command.strip()),
            rollback=redact_text(rollback.strip()),
        )
        items = self.load()
        items.append(item)
        self._save(items)
        return item

    def list(self, status: Optional[str] = None) -> list[Approval]:
        items = self.load()
        if status:
            items = [a for a in items if a.status == status]
        return sorted(items, key=lambda a: a.created_at)

    def set_status(self, item_id: str, status: str) -> Approval:
        """Record-keeping only: mark an item approved/rejected/done.

        Changing status never triggers execution of anything.
        """
        if status not in VALID_STATUS:
            raise ValueError(f"status must be one of {VALID_STATUS}")
        items = self.load()
        for item in items:
            if item.id == item_id:
                item.status = status
                item.updated_at = _now_iso()
                self._save(items)
                return item
        raise KeyError(f"no approval with id {item_id!r}")

    def counts(self) -> dict:
        items = self.load()
        by = {s: 0 for s in VALID_STATUS}
        for a in items:
            by[a.status] = by.get(a.status, 0) + 1
        by["total"] = len(items)
        return by

    def pending_preview(self, limit: int = 8) -> list[dict]:
        return [a.to_dict() for a in self.list(status="pending")[:limit]]
