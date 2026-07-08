"""Approval queue tests: add/list/set behavior in a temp directory."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hermes_os.approvals import ApprovalQueue
from hermes_os.redact import contains_secret


class TestApprovals(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "state" / "approvals.json"
        self.queue = ApprovalQueue(self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_and_list(self):
        item = self.queue.add(
            title="Rotate EIR preset cron to daily",
            kind="cron-change",
            detail="Promote the camera-lens draft digest.",
            risk_level="low",
            suggested_command="hermes cron enable job-eir-draft",
            rollback="hermes cron disable job-eir-draft",
        )
        self.assertTrue(item.id.startswith("apv-"))
        self.assertEqual(item.status, "pending")
        items = self.queue.list()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Rotate EIR preset cron to daily")
        self.assertTrue(self.path.exists())

    def test_list_filters_by_status(self):
        a = self.queue.add(title="one", kind="k")
        self.queue.add(title="two", kind="k")
        self.queue.set_status(a.id, "approved")
        self.assertEqual(len(self.queue.list(status="pending")), 1)
        self.assertEqual(len(self.queue.list(status="approved")), 1)
        self.assertEqual(self.queue.list(status="approved")[0].id, a.id)

    def test_set_status_validates(self):
        a = self.queue.add(title="x", kind="k")
        with self.assertRaises(ValueError):
            self.queue.set_status(a.id, "launched")
        with self.assertRaises(KeyError):
            self.queue.set_status("apv-missing1", "done")
        updated = self.queue.set_status(a.id, "done")
        self.assertEqual(updated.status, "done")
        self.assertTrue(updated.updated_at)

    def test_add_validates(self):
        with self.assertRaises(ValueError):
            self.queue.add(title="   ", kind="k")
        with self.assertRaises(ValueError):
            self.queue.add(title="x", kind="k", risk_level="extreme")

    def test_counts(self):
        self.queue.add(title="a", kind="k")
        b = self.queue.add(title="b", kind="k")
        self.queue.set_status(b.id, "rejected")
        counts = self.queue.counts()
        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["pending"], 1)
        self.assertEqual(counts["rejected"], 1)

    def test_corrupt_file_tolerated(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.queue.load(), [])
        # and we can still add on top of the corrupt file
        self.queue.add(title="recovered", kind="k")
        self.assertEqual(len(self.queue.list()), 1)

    def test_secrets_redacted_on_write(self):
        fake = "sk-or-v1-" + "f4ke" * 8
        self.queue.add(
            title=f"deploy with {fake}",
            kind="k",
            suggested_command=f"curl -H 'Authorization: Bearer {fake}'",
        )
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn(fake, raw)
        self.assertFalse(contains_secret(raw), raw[:400])

    def test_file_shape(self):
        self.queue.add(title="shape", kind="k")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 1)
        self.assertIn("items", payload)
        item = payload["items"][0]
        for field in (
            "id",
            "created_at",
            "title",
            "kind",
            "detail",
            "risk_level",
            "status",
            "suggested_command",
            "rollback",
        ):
            self.assertIn(field, item)

    def test_no_stray_temp_files_after_save(self):
        self.queue.add(title="tmp check", kind="k")
        leftovers = [p for p in self.path.parent.iterdir() if p.name.startswith(".approvals-")]
        self.assertEqual(leftovers, [])

    def test_get_and_render_detail(self):
        item = self.queue.add(
            title="Refresh dashboard mirror",
            kind="dashboard-refresh",
            detail="Render dashboard and copy it to shared storage.",
            risk_level="low",
            suggested_command="hermes-os render-html",
            rollback="remove the generated mirror file",
        )
        found = self.queue.get(item.id)
        self.assertEqual(found.title, "Refresh dashboard mirror")
        detail = self.queue.render_detail(item.id)
        self.assertIn(item.id, detail)
        self.assertIn("Refresh dashboard mirror", detail)
        self.assertIn("Suggested command", detail)
        self.assertIn("Rollback", detail)
        with self.assertRaises(KeyError):
            self.queue.get("apv-missing")

    def test_write_script_creates_manual_one_shot_without_executing(self):
        item = self.queue.add(
            title="Refresh dashboard mirror",
            kind="dashboard-refresh",
            detail="Render dashboard and copy it to shared storage.",
            risk_level="low",
            suggested_command="hermes-os render-html",
            rollback="remove the generated mirror file",
        )
        out = self.queue.write_script(item.id, Path(self._tmp.name) / "dist" / "actions")
        self.assertTrue(out.exists())
        self.assertTrue(out.name.startswith(item.id))
        text = out.read_text(encoding="utf-8")
        self.assertIn("ACTION SCRIPT", text)
        self.assertIn("hermes-os render-html", text)
        self.assertIn("manual execution only", text.lower())
        self.assertFalse(contains_secret(text), text)

    def test_write_script_requires_suggested_command(self):
        item = self.queue.add(title="No command", kind="note")
        with self.assertRaises(ValueError):
            self.queue.write_script(item.id, Path(self._tmp.name) / "dist" / "actions")


if __name__ == "__main__":
    unittest.main()
