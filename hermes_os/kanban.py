"""Read-only Kanban board inventory for Hermes-OS.

The Hermes Kanban system stores durable task state in SQLite databases under
``~/.hermes``. This module reads those databases directly instead of invoking
mutating CLI commands. It never writes to the board.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import Config
from .redact import redact_text

_STATUS_ORDER = ("triage", "todo", "scheduled", "ready", "running", "blocked", "review", "done", "archived")
_OPEN_STATUSES = {"triage", "todo", "scheduled", "ready", "running", "blocked", "review"}
_WORKER_RE = re.compile(r"(?:^|\s)--profile\s+(?P<profile>\S+)")
_KANBAN_TASK_RE = re.compile(r"(?:kanban|task)[_/ -]?(?P<task>t_[0-9a-fA-F]+)")


def _epoch_to_iso(value: Any) -> str:
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return ""
    if ivalue <= 0:
        return ""
    try:
        return datetime.fromtimestamp(ivalue, tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    except (OSError, OverflowError, ValueError):
        return ""


def _safe_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _board_entries(cfg: Config) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    default_db = cfg.kanban_default_db
    if default_db.exists():
        entries.append({"slug": "default", "name": "Default", "db": default_db})
    boards_dir = cfg.kanban_boards_dir
    if boards_dir.is_dir():
        for child in sorted(boards_dir.iterdir()):
            if not child.is_dir():
                continue
            db = child / "kanban.db"
            if not db.exists():
                continue
            meta = _safe_json(child / "board.json")
            slug = str(meta.get("slug") or child.name)
            name = str(meta.get("name") or slug)
            archived = bool(meta.get("archived"))
            entries.append({"slug": slug, "name": name, "db": db, "archived": archived})
    # stable de-dupe in case the default board is represented twice
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        slug = entry["slug"]
        if slug in seen:
            continue
        seen.add(slug)
        deduped.append(entry)
    return deduped


def _current_board(cfg: Config) -> str:
    try:
        current = cfg.kanban_current_file.read_text(encoding="utf-8").strip()
        return current or "default"
    except OSError:
        return "default"


def _query_board(entry: dict[str, Any], limit_per_board: int) -> dict[str, Any]:
    board = {
        "slug": entry.get("slug", ""),
        "name": entry.get("name", ""),
        "archived": bool(entry.get("archived", False)),
        "db": str(entry.get("db", "")),
        "counts": {status: 0 for status in _STATUS_ORDER},
        "open_count": 0,
        "running": [],
        "blocked": [],
        "ready": [],
        "recent_done": [],
        "recent_events": [],
        "running_runs": [],
    }
    db = Path(str(entry.get("db", "")))
    if not db.exists():
        return board
    con: Optional[sqlite3.Connection] = None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1)
        con.row_factory = sqlite3.Row
        for row in con.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status"):
            status = str(row["status"] or "unknown")
            board["counts"][status] = int(row["n"] or 0)
        board["open_count"] = sum(int(board["counts"].get(s, 0)) for s in _OPEN_STATUSES)

        def task_rows(statuses: tuple[str, ...], *, order: str, limit: int) -> list[dict[str, Any]]:
            if not statuses or limit <= 0:
                return []
            qs = ",".join("?" for _ in statuses)
            rows = con.execute(
                f"""
                SELECT id,title,assignee,status,priority,started_at,completed_at,
                       worker_pid,last_heartbeat_at,current_run_id,block_kind,
                       consecutive_failures,last_failure_error
                FROM tasks
                WHERE status IN ({qs})
                ORDER BY {order}
                LIMIT ?
                """,
                (*statuses, limit),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for r in rows:
                out.append({
                    "id": r["id"],
                    "title": redact_text(str(r["title"] or ""))[:160],
                    "assignee": redact_text(str(r["assignee"] or ""))[:80],
                    "status": r["status"],
                    "priority": r["priority"],
                    "started_at": _epoch_to_iso(r["started_at"]),
                    "completed_at": _epoch_to_iso(r["completed_at"]),
                    "worker_pid": r["worker_pid"],
                    "last_heartbeat_at": _epoch_to_iso(r["last_heartbeat_at"]),
                    "current_run_id": r["current_run_id"],
                    "block_kind": redact_text(str(r["block_kind"] or ""))[:80],
                    "consecutive_failures": r["consecutive_failures"],
                    "last_failure_error": redact_text(str(r["last_failure_error"] or ""))[:160],
                })
            return out

        board["running"] = task_rows(("running",), order="started_at DESC, priority DESC", limit=limit_per_board)
        board["blocked"] = task_rows(("blocked",), order="priority DESC, created_at ASC", limit=limit_per_board)
        board["ready"] = task_rows(("ready", "todo", "triage", "scheduled", "review"), order="priority DESC, created_at ASC", limit=limit_per_board)
        board["recent_done"] = task_rows(("done",), order="completed_at DESC, priority DESC", limit=min(limit_per_board, 5))

        run_rows = con.execute(
            """
            SELECT r.id AS run_id,r.task_id,r.profile,r.status,r.worker_pid,
                   r.last_heartbeat_at,r.started_at,t.title,t.assignee
            FROM task_runs r
            LEFT JOIN tasks t ON t.id = r.task_id
            WHERE r.status='running'
            ORDER BY r.started_at DESC
            LIMIT ?
            """,
            (limit_per_board,),
        ).fetchall()
        board["running_runs"] = [
            {
                "run_id": r["run_id"],
                "task_id": r["task_id"],
                "title": redact_text(str(r["title"] or ""))[:160],
                "profile": redact_text(str(r["profile"] or r["assignee"] or ""))[:80],
                "status": r["status"],
                "worker_pid": r["worker_pid"],
                "started_at": _epoch_to_iso(r["started_at"]),
                "last_heartbeat_at": _epoch_to_iso(r["last_heartbeat_at"]),
            }
            for r in run_rows
        ]

        event_rows = con.execute(
            """
            SELECT task_id,kind,payload,created_at
            FROM task_events
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (min(limit_per_board, 8),),
        ).fetchall()
        board["recent_events"] = [
            {
                "task_id": r["task_id"],
                "kind": redact_text(str(r["kind"] or ""))[:80],
                "payload": redact_text(str(r["payload"] or ""))[:160],
                "created_at": _epoch_to_iso(r["created_at"]),
            }
            for r in event_rows
        ]
    except sqlite3.Error as exc:
        board["warning"] = f"kanban db read failed: {exc.__class__.__name__}"
    finally:
        if con is not None:
            con.close()
    return board


def collect_live_agents(process_text: str, kanban: Optional[dict[str, Any]] = None, limit: int = 12) -> list[dict[str, Any]]:
    """Extract live agent-like processes and running Kanban runs.

    This is intentionally conservative: it keeps only metadata useful for the
    dashboard and never stores full prompts/queries from process command lines.
    """
    agents: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(key: str, item: dict[str, Any]) -> None:
        if key in seen or len(agents) >= limit:
            return
        seen.add(key)
        agents.append(item)

    if kanban:
        for board in kanban.get("boards", []):
            for run in board.get("running_runs", []):
                key = f"kanban:{board.get('slug')}:{run.get('run_id')}"
                add(key, {
                    "kind": "kanban-worker",
                    "profile": run.get("profile", ""),
                    "pid": run.get("worker_pid") or "",
                    "task_id": run.get("task_id", ""),
                    "title": run.get("title", ""),
                    "board": board.get("slug", ""),
                    "status": run.get("status", "running"),
                    "heartbeat": run.get("last_heartbeat_at", ""),
                })

    for raw in (process_text or "").splitlines():
        line = raw.strip()
        lowered = line.lower()
        if not line or "grep" in lowered:
            continue
        # Skip supervisors/loggers; they are service plumbing, not agents doing work.
        if "runsv " in lowered or "svlogd " in lowered:
            continue
        if not any(token in lowered for token in ("hermes", "codex", "opencode")):
            continue
        parts = line.split(None, 7)
        pid = parts[1] if len(parts) > 1 else ""
        cmd = parts[7] if len(parts) > 7 else line
        cmd_l = cmd.lower()
        if "hermes gateway run" in cmd_l:
            add(f"pid:{pid}", {"kind": "gateway", "profile": "default", "pid": pid, "title": "Telegram gateway / scheduler", "status": "running"})
            continue
        if "hermes_local_web_backend" in cmd_l:
            add(f"pid:{pid}", {"kind": "local-web", "profile": "default", "pid": pid, "title": "Hermes local web backend", "status": "running"})
            continue
        profile_match = _WORKER_RE.search(cmd)
        profile = profile_match.group("profile") if profile_match else ""
        task_match = _KANBAN_TASK_RE.search(cmd)
        task_id = task_match.group("task") if task_match else ""
        if "hermes" in cmd_l and " chat" in cmd_l:
            kind = "profile-agent" if profile else "hermes-agent"
            title = f"Hermes chat worker" + (f" ({profile})" if profile else "")
            add(f"pid:{pid}", {"kind": kind, "profile": profile, "pid": pid, "task_id": task_id, "title": title, "status": "running"})
        elif any(token in cmd_l for token in ("codex", "opencode")):
            add(f"pid:{pid}", {"kind": "coding-agent", "profile": profile, "pid": pid, "task_id": task_id, "title": cmd.split()[0], "status": "running"})
        elif "/.hermes/scripts/" in cmd_l:
            script = Path(cmd.split()[0]).name if cmd.split() else "script"
            add(f"pid:{pid}", {"kind": "cron-script", "profile": profile, "pid": pid, "title": script, "status": "running"})

    return agents


def collect_kanban(cfg: Config, process_text: str = "", limit_per_board: int = 10) -> dict[str, Any]:
    current = _current_board(cfg)
    boards = [_query_board(entry, limit_per_board) for entry in _board_entries(cfg)]
    counts = {status: 0 for status in _STATUS_ORDER}
    open_total = 0
    for board in boards:
        open_total += int(board.get("open_count", 0) or 0)
        for status, n in board.get("counts", {}).items():
            counts[status] = counts.get(status, 0) + int(n or 0)
    kanban = {
        "current_board": current,
        "boards": boards,
        "counts": counts,
        "open_count": open_total,
        "active_agents": [],
    }
    kanban["active_agents"] = collect_live_agents(process_text, kanban)
    return kanban
