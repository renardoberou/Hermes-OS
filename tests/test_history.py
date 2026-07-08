"""History/trend tests for the Action Center audit trail."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hermes_os.config import Config
from hermes_os.history import append_history, read_history, render_trend_text, summarize_trend
from hermes_os.models import HealthCheck, Inventory, Risk, WikiStatus
from hermes_os.redact import contains_secret


def _cfg(tmp: Path) -> Config:
    return Config(
        hermes_home=tmp / "home",
        wiki_root=tmp / "wiki",
        state_dir=tmp / "state",
        dist_dir=tmp / "dist",
        skip_commands=True,
    )


def _inv(*, failing: int = 0, pending: int = 0, blocked: int = 0, agents: int = 1) -> Inventory:
    inv = Inventory(generated_at="2026-07-07T20:00:00-03:00")
    inv.gateway = {"running": True}
    inv.cron = {"scheduler_running": True, "counts": {"total": 2, "enabled": 2, "failing": failing}}
    inv.approvals = {"counts": {"pending": pending, "approved": 0, "done": 0, "rejected": 0, "total": pending}}
    inv.kanban = {
        "counts": {"running": 2, "blocked": blocked},
        "open_count": 3 + blocked,
        "active_agents": [{"kind": "gateway"} for _ in range(agents)],
    }
    inv.wiki = WikiStatus(root="/vault", exists=True, heartbeat_age_hours=1.5, note_count=10, queue_total=4, queue_open=2)
    inv.health = [HealthCheck(name="gateway", status="ok", detail="up")]
    if failing:
        inv.risks = [Risk(level="warn", code="cron-failing", message="fake sk-or-v1-" + "abcd" * 8)]
    return inv


class TestHistory(unittest.TestCase):
    def test_append_history_writes_redacted_jsonl_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _cfg(Path(tmp))
            entry = append_history(cfg, _inv(failing=1, pending=2, blocked=3))
            lines = cfg.history_file.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 1)
        self.assertEqual(entry["cron_failing"], 1)
        self.assertEqual(entry["approvals_pending"], 2)
        self.assertEqual(entry["kanban_blocked"], 3)
        self.assertFalse(contains_secret(lines[0]), lines[0])

    def test_read_history_and_trend_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _cfg(Path(tmp))
            append_history(cfg, _inv(failing=0, pending=1, blocked=0, agents=1))
            append_history(cfg, _inv(failing=2, pending=3, blocked=4, agents=5))
            items = read_history(cfg.history_file)
            trend = summarize_trend(cfg.history_file)
            text = render_trend_text(trend)

        self.assertEqual(len(items), 2)
        self.assertEqual(trend["samples"], 2)
        self.assertEqual(trend["latest"]["cron_failing"], 2)
        self.assertEqual(trend["max"]["kanban_blocked"], 4)
        self.assertIn("samples: 2", text)
        self.assertIn("latest cron failing: 2", text)

    def test_missing_history_degrades(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _cfg(Path(tmp))
            trend = summarize_trend(cfg.history_file)
        self.assertEqual(trend["samples"], 0)
        self.assertIn("no history", render_trend_text(trend).lower())


if __name__ == "__main__":
    unittest.main()
