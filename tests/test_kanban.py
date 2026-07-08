"""Kanban collector tests."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from hermes_os.config import Config
from hermes_os.kanban import collect_kanban, collect_live_agents
from hermes_os.redact import contains_secret


def _cfg(tmp: Path) -> Config:
    return Config(
        hermes_home=tmp / "home",
        wiki_root=tmp / "wiki",
        state_dir=tmp / "state",
        dist_dir=tmp / "dist",
        skip_commands=True,
    )


def _make_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT,
            assignee TEXT,
            status TEXT NOT NULL,
            priority INTEGER DEFAULT 0,
            created_by TEXT,
            created_at INTEGER NOT NULL,
            started_at INTEGER,
            completed_at INTEGER,
            workspace_kind TEXT NOT NULL DEFAULT 'scratch',
            workspace_path TEXT,
            claim_lock TEXT,
            claim_expires INTEGER,
            tenant TEXT,
            result TEXT,
            idempotency_key TEXT,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            worker_pid INTEGER,
            last_failure_error TEXT,
            max_runtime_seconds INTEGER,
            last_heartbeat_at INTEGER,
            current_run_id INTEGER,
            workflow_template_id TEXT,
            current_step_key TEXT,
            skills TEXT,
            max_retries INTEGER,
            branch_name TEXT,
            model_override TEXT,
            session_id TEXT,
            goal_mode INTEGER NOT NULL DEFAULT 0,
            goal_max_turns INTEGER,
            project_id TEXT,
            block_kind TEXT,
            block_recurrences INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE task_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            profile TEXT,
            step_key TEXT,
            status TEXT NOT NULL,
            claim_lock TEXT,
            claim_expires INTEGER,
            worker_pid INTEGER,
            max_runtime_seconds INTEGER,
            last_heartbeat_at INTEGER,
            started_at INTEGER NOT NULL,
            ended_at INTEGER,
            outcome TEXT,
            summary TEXT,
            metadata TEXT,
            error TEXT
        );
        CREATE TABLE task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            run_id INTEGER,
            kind TEXT NOT NULL,
            payload TEXT,
            created_at INTEGER NOT NULL
        );
        """
    )
    con.execute(
        "INSERT INTO tasks (id,title,assignee,status,priority,created_at,started_at,worker_pid,last_heartbeat_at,current_run_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("t_abc123", "Build Kanban dashboard", "ops", "running", 5, 1778181000, 1778181100, 4242, 1778181200, 1),
    )
    con.execute(
        "INSERT INTO tasks (id,title,assignee,status,priority,created_at,block_kind,last_failure_error) VALUES (?,?,?,?,?,?,?,?)",
        ("t_def456", "Blocked task", "wiki", "blocked", 3, 1778181001, "needs-user", "contains token eyJabcdefgh.ijklmnopqr.stuvwx"),
    )
    con.execute(
        "INSERT INTO task_runs (task_id,profile,status,worker_pid,last_heartbeat_at,started_at) VALUES (?,?,?,?,?,?)",
        ("t_abc123", "ops", "running", 4242, 1778181200, 1778181100),
    )
    con.execute(
        "INSERT INTO task_events (task_id,run_id,kind,payload,created_at) VALUES (?,?,?,?,?)",
        ("t_abc123", 1, "heartbeat", "Bearer secret-value-1234567890", 1778181200),
    )
    con.commit()
    con.close()


class TestKanban(unittest.TestCase):
    def test_collect_kanban_reads_boards_and_live_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _cfg(root)
            _make_db(cfg.kanban_default_db)
            cfg.kanban_root.mkdir(parents=True, exist_ok=True)
            cfg.kanban_current_file.write_text("default\n", encoding="utf-8")
            data = collect_kanban(cfg)

        self.assertEqual(data["current_board"], "default")
        self.assertEqual(data["counts"]["running"], 1)
        self.assertEqual(data["counts"]["blocked"], 1)
        self.assertEqual(data["open_count"], 2)
        self.assertEqual(len(data["active_agents"]), 1)
        payload = repr(data)
        self.assertFalse(contains_secret(payload), payload)
        self.assertIn("[REDACTED:jwt]", payload)
        self.assertIn("[REDACTED:bearer]", payload)

    def test_collect_live_agents_parses_safe_process_metadata(self):
        process_text = """
root 111 1 0 00:00 ? 00:00:00 python -m hermes gateway run
u0_a 222 1 0 00:00 ? 00:00:00 hermes --profile wiki chat --task t_abc123 please do secret work
u0_a 333 1 0 00:00 ? 00:00:00 grep hermes
"""
        agents = collect_live_agents(process_text)
        kinds = {a["kind"] for a in agents}
        self.assertIn("gateway", kinds)
        self.assertIn("profile-agent", kinds)
        self.assertTrue(any(a.get("profile") == "wiki" and a.get("task_id") == "t_abc123" for a in agents))
        self.assertFalse(any("secret work" in repr(a) for a in agents))


if __name__ == "__main__":
    unittest.main()
