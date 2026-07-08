"""Native Decision Bridge v0.4 tests.

The bridge exposes structured approval/apply/system verbs for Android buttons.
It must never accept arbitrary shell commands from WebView URLs.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from hermes_os import cli
from hermes_os.actions import ActionBridge
from hermes_os.approvals import ApprovalQueue
from hermes_os.collect import collect
from hermes_os.config import Config
from hermes_os.render_html import render_dashboard

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO = Path(__file__).resolve().parent.parent


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


def run_cli(*argv) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TestDecisionBridge(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.cfg = Config(
            hermes_home=FIXTURES / "hermes_home",
            wiki_root=FIXTURES / "sample_wiki",
            state_dir=root / "state",
            dist_dir=root / "dist",
            skip_commands=True,
            repo_root=REPO,
        )
        self.queue = ApprovalQueue(self.cfg.approvals_file)
        self.bridge = ActionBridge(self.cfg, self.queue)

    def tearDown(self):
        self._tmp.cleanup()

    def _approval(self, *, status="pending", risk="low", command="hermes-os trend", rollback="no state change"):
        item = self.queue.add(
            title="Bridge candidate",
            kind="decision-bridge-test",
            detail="button-triggered decision",
            risk_level=risk,
            suggested_command=command,
            rollback=rollback,
        )
        if status != "pending":
            item = self.queue.set_status(item.id, status)
        return item

    def _receipts(self):
        return [
            json.loads(line)
            for line in self.cfg.action_receipts_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_approve_reject_done_verbs_update_status_and_write_receipts(self):
        item = self._approval()
        approved = self.bridge.dispatch(item.id, "approve", source="test")
        self.assertEqual(approved.status, "ok")
        self.assertEqual(self.queue.get(item.id).status, "approved")

        rejected = self.bridge.dispatch(item.id, "reject", source="test")
        self.assertEqual(rejected.status, "ok")
        self.assertEqual(self.queue.get(item.id).status, "rejected")

        done = self.bridge.dispatch(item.id, "done", source="test")
        self.assertEqual(done.status, "ok")
        self.assertEqual(self.queue.get(item.id).status, "done")

        receipts = self._receipts()
        self.assertEqual([r["verb"] for r in receipts], ["approve", "reject", "done"])
        self.assertEqual(receipts[1]["prev_hash"], receipts[0]["entry_hash"])
        self.assertEqual(receipts[2]["prev_hash"], receipts[1]["entry_hash"])

    def test_unknown_verb_is_refused_and_logged(self):
        item = self._approval()
        result = self.bridge.dispatch(item.id, "rm -rf /", source="test")
        self.assertEqual(result.status, "refused")
        self.assertIn("unknown verb", result.reason.lower())
        receipt = self._receipts()[-1]
        self.assertEqual(receipt["status"], "refused")
        self.assertEqual(receipt["command"], [])

    def test_unknown_id_is_refused_and_logged(self):
        result = self.bridge.dispatch("apv-missing", "approve", source="test")
        self.assertEqual(result.status, "refused")
        self.assertIn("no approval", result.reason.lower())
        self.assertEqual(self._receipts()[-1]["object_id"], "apv-missing")

    def test_dry_run_and_execute_verbs_route_through_guarded_apply(self):
        item = self._approval(status="approved", command="hermes-os trend")
        dry_run = self.bridge.dispatch(item.id, "dry-run", source="test")
        self.assertEqual(dry_run.status, "dry-run")
        self.assertFalse(dry_run.executed)
        self.assertIn("apply", dry_run.command)

        execute = self.bridge.dispatch(item.id, "execute", source="test")
        self.assertEqual(execute.status, "refused")
        self.assertIn("execution disabled", execute.reason)
        self.assertEqual(self.queue.get(item.id).status, "approved")

    def test_high_risk_execute_refused(self):
        item = self._approval(status="approved", risk="high", command="hermes-os trend", rollback="manual rollback")
        result = self.bridge.dispatch(item.id, "execute", source="test")
        self.assertEqual(result.status, "refused")
        self.assertIn("high-risk", result.reason.lower())

    def test_system_refresh_is_structured_and_logged(self):
        result = self.bridge.dispatch("system", "refresh", source="test")
        self.assertEqual(result.status, "refused")
        self.assertIn("execution disabled", result.reason)
        receipt = self._receipts()[-1]
        self.assertEqual(receipt["command"], ["hermes-os", "render-html"])

    def test_cli_action_verbs(self):
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
                    title="CLI bridge candidate",
                    kind="decision-bridge-test",
                    risk_level="low",
                    suggested_command="hermes-os trend",
                    rollback="no state change",
                )
                code, out, err = run_cli("action", item.id, "--verb", "approve")
                self.assertEqual(code, 0, out + err)
                self.assertIn("OK", out)
                self.assertEqual(queue.get(item.id).status, "approved")

                code, out, err = run_cli("action", item.id, "--verb", "dry-run")
                self.assertEqual(code, 0, out + err)
                self.assertIn("DRY RUN", out)

                code, out, err = run_cli("action", item.id, "--verb", "explode")
                self.assertEqual(code, 2)
                self.assertIn("unknown verb", out.lower())

    def test_dashboard_renders_real_decision_bridge_buttons(self):
        pending = self._approval(status="pending")
        approved = self._approval(status="approved")
        inv = collect(self.cfg)
        html = render_dashboard(inv)
        self.assertIn("Native Decision Bridge v0.4.2", html)
        self.assertIn(f"hermesos://decision?id={pending.id}&amp;verb=approve", html)
        self.assertIn(f"hermesos://decision?id={pending.id}&amp;verb=reject", html)
        self.assertIn(f"hermesos://apply?id={approved.id}&amp;mode=dry-run", html)
        self.assertIn(f"hermesos://apply?id={approved.id}&amp;mode=execute", html)
        self.assertIn("hermesos://system?verb=refresh", html)
        self.assertIn("Last action", html)

    def test_android_service_pathless_environment_uses_absolute_hermes_os_binary(self):
        item = self._approval(status="approved", command="hermes-os render-html")
        argv = self.bridge.execution_command_for(["hermes-os", "render-html"])
        self.assertNotEqual(argv[0], "hermes-os")
        self.assertTrue(argv[0].endswith("/hermes-os"))

        apply_argv = self.bridge.apply.execution_argv(item.suggested_command)
        self.assertNotEqual(apply_argv[0], "hermes-os")
        self.assertTrue(apply_argv[0].endswith("/hermes-os"))

    def test_derived_daybook_action_can_be_queued_as_pending_approval(self):
        inv = collect(self.cfg)
        derived = inv.action_center.get("derived_actions", [])
        self.assertTrue(derived, "fixture should expose daybook/next-action candidates")
        candidate = derived[0]

        result = self.bridge.dispatch(candidate["id"], "queue", source="test")
        self.assertEqual(result.status, "ok", result.reason)
        self.assertIn("approval queued", result.reason)
        pending_titles = [a.title for a in self.queue.list(status="pending")]
        self.assertIn(candidate["title"], pending_titles)


    def test_completed_derived_action_is_not_rendered_as_queueable_again(self):
        inv = collect(self.cfg)
        candidate = inv.action_center.get("derived_actions", [])[0]

        queued = self.bridge.dispatch(candidate["id"], "queue", source="test")
        self.assertEqual(queued.status, "ok", queued.reason)
        self.bridge.dispatch(queued.object_id, "done", source="test")

        refreshed = collect(self.cfg)
        ids = [c.get("id") for c in refreshed.action_center.get("derived_actions", [])]
        self.assertNotIn(candidate["id"], ids)
        html = render_dashboard(refreshed)
        self.assertNotIn(f"id={candidate['id']}&amp;verb=queue", html)

    def test_dashboard_renders_daybook_and_next_action_queue_buttons(self):
        inv = collect(self.cfg)
        html = render_dashboard(inv)
        self.assertIn("Action candidates", html)
        self.assertIn("Queue approval", html)
        self.assertIn("hermesos://decision?id=drv-", html)
        self.assertIn("verb=queue", html)

    def test_android_bridge_declares_run_command_and_structured_handlers(self):
        manifest = (REPO / "android-native/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        java = (REPO / "android-native/app/src/main/java/com/resonantsystems/hermesos/MainActivity.java").read_text(encoding="utf-8")
        self.assertIn("com.termux.permission.RUN_COMMAND", manifest)
        self.assertIn('<package android:name="com.termux" />', manifest)
        self.assertIn("handleDecisionUrl", java)
        self.assertIn("handleApplyUrl", java)
        self.assertIn("handleSystemUrl", java)
        self.assertIn('"approve"', java)
        self.assertIn('"reject"', java)
        self.assertIn('"queue"', java)
        self.assertIn('"dry-run"', java)
        self.assertIn('"execute"', java)
        self.assertIn("RUN_COMMAND_PERMISSION", java)
        self.assertNotIn("RUN_COMMAND_ARGUMENTS", java[java.find("handleDashboardUrl"):java.find("private void copyTextToClipboard")])


if __name__ == "__main__":
    unittest.main()
