"""Guarded Apply v0.1 tests: validated, logged, allowlisted execution only."""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hermes_os import cli
from hermes_os.approvals import ApprovalQueue
from hermes_os.apply import GuardedApply
from hermes_os.config import Config

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@contextlib.contextmanager
def env(**overrides):
    saved = {}
    try:
        for key, value in overrides.items():
            full = "HERMES_OS_" + key
            saved[full] = os.environ.get(full)
            os.environ[full] = str(value)
        yield
    finally:
        for full, old in saved.items():
            if old is None:
                os.environ.pop(full, None)
            else:
                os.environ[full] = old


def run_cli(*argv) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(list(argv))
    return code, buf.getvalue()


class TestGuardedApply(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.cfg = Config(
            hermes_home=FIXTURES / "hermes_home",
            wiki_root=FIXTURES / "sample_wiki",
            state_dir=tmp / "state",
            dist_dir=tmp / "dist",
            skip_commands=True,
            repo_root=Path(__file__).resolve().parent.parent,
        )
        self.queue = ApprovalQueue(self.cfg.approvals_file)
        self.guard = GuardedApply(self.cfg, self.queue)

    def tearDown(self):
        self._tmp.cleanup()

    def _approved(self, *, command="hermes-os trend", risk="low", rollback="no state change"):
        item = self.queue.add(
            title="Apply safe local action",
            kind="guarded-apply-test",
            detail="exercise guarded apply",
            risk_level=risk,
            suggested_command=command,
            rollback=rollback,
        )
        return self.queue.set_status(item.id, "approved")

    def _log_lines(self):
        return [json.loads(line) for line in self.cfg.apply_log_file.read_text(encoding="utf-8").splitlines()]

    def test_dry_run_validates_allowlisted_approved_item_without_executing(self):
        item = self._approved(command="hermes-os trend")
        result = self.guard.apply(item.id, dry_run=True)
        self.assertEqual(result.status, "dry-run")
        self.assertFalse(result.executed)
        self.assertEqual(result.command, "hermes-os trend")
        self.assertEqual(self.queue.get(item.id).status, "approved")
        log = self._log_lines()[-1]
        self.assertEqual(log["approval_id"], item.id)
        self.assertEqual(log["mode"], "dry-run")
        self.assertEqual(log["status"], "dry-run")

    def test_rejects_commands_outside_allowlist(self):
        item = self._approved(command="rm -rf /tmp/not-allowed")
        result = self.guard.apply(item.id, dry_run=True)
        self.assertEqual(result.status, "refused")
        self.assertIn("allowlist", result.reason.lower())
        self.assertEqual(self.queue.get(item.id).status, "approved")

    def test_rejects_stale_approval(self):
        item = self._approved(command="hermes-os trend")
        old = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat(timespec="seconds")
        payload = json.loads(self.cfg.approvals_file.read_text(encoding="utf-8"))
        payload["items"][0]["updated_at"] = old
        self.cfg.approvals_file.write_text(json.dumps(payload), encoding="utf-8")
        result = self.guard.apply(item.id, dry_run=True)
        self.assertEqual(result.status, "refused")
        self.assertIn("stale", result.reason.lower())

    def test_refuses_high_risk_even_if_approved(self):
        item = self._approved(command="hermes-os trend", risk="high", rollback="manual rollback")
        result = self.guard.apply(item.id, dry_run=True)
        self.assertEqual(result.status, "refused")
        self.assertIn("high-risk", result.reason.lower())

    def test_requires_rollback_metadata(self):
        item = self._approved(command="hermes-os render-html", rollback="")
        result = self.guard.apply(item.id, dry_run=True)
        self.assertEqual(result.status, "refused")
        self.assertIn("rollback", result.reason.lower())

    def test_action_log_is_append_only_hash_chained_jsonl(self):
        item = self._approved(command="hermes-os status")
        first = self.guard.apply(item.id, dry_run=True)
        second = self.guard.apply(item.id, dry_run=True)
        lines = self._log_lines()
        self.assertEqual(len(lines), 2)
        self.assertNotEqual(lines[0]["action_id"], lines[1]["action_id"])
        self.assertEqual(lines[1]["prev_hash"], lines[0]["entry_hash"])
        self.assertTrue(first.entry_hash)
        self.assertTrue(second.entry_hash)

    def test_cli_apply_defaults_to_dry_run_and_has_execute_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with env(
                HERMES_HOME=FIXTURES / "hermes_home",
                WIKI_ROOT=FIXTURES / "sample_wiki",
                STATE_DIR=tmp_path / "state",
                DIST_DIR=tmp_path / "dist",
                SKIP_COMMANDS="1",
            ):
                queue = ApprovalQueue(tmp_path / "state" / "approvals.json")
                item = queue.add(
                    title="Trend check",
                    kind="guarded-apply-test",
                    risk_level="low",
                    suggested_command="hermes-os trend",
                    rollback="no state change",
                )
                queue.set_status(item.id, "approved")
                code, out = run_cli("apply", item.id)
                self.assertEqual(code, 0, out)
                self.assertIn("DRY RUN", out)
                self.assertIn("use --execute", out)
                self.assertEqual(queue.get(item.id).status, "approved")
                code, out = run_cli("apply", item.id, "--execute")
                self.assertEqual(code, 2, out)
                self.assertIn("execution disabled by HERMES_OS_SKIP_COMMANDS", out)


if __name__ == "__main__":
    unittest.main()
