"""Digest renderer tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hermes_os.collect import collect
from hermes_os.config import Config
from hermes_os.redact import contains_secret
from hermes_os.render_markdown import GREETING, render_digest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _inv():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cfg = Config(
            hermes_home=FIXTURES / "hermes_home",
            wiki_root=FIXTURES / "sample_wiki",
            state_dir=tmp_path / "state",
            dist_dir=tmp_path / "dist",
            skip_commands=True,
        )
        return collect(cfg)


class TestDigest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inv = _inv()
        cls.text = render_digest(cls.inv)

    def test_starts_with_greeting(self):
        self.assertTrue(self.text.startswith(GREETING))
        self.assertTrue(
            self.text.startswith("Aye, Captain — Hermes Android Agentic OS status")
        )

    def test_sections_present(self):
        for header in (
            "*Health*",
            "*Daybook — done / needs action*",
            "*Today / next cron runs*",
            "*Open approvals*",
            "*LLM-Wiki queue*",
            "*Risks / blockers*",
            "*Suggested next actions*",
        ):
            self.assertIn(header, self.text)

    def test_no_markdown_tables(self):
        self.assertNotIn("|", self.text.replace("||", ""))

    def test_content_from_fixtures(self):
        self.assertIn("LLM-Wiki whole-vault research", self.text)
        self.assertIn("queue: 5 open / 7 total", self.text)
        self.assertIn("getUpdates", self.text)  # duplicate-gateway risk surfaced

    def test_no_secrets(self):
        self.assertFalse(contains_secret(self.text), self.text[:600])

    def test_custom_template_and_greeting_enforcement(self):
        with tempfile.TemporaryDirectory() as tmp:
            tpl = Path(tmp) / "digest.md"
            tpl.write_text("custom header\n{{HEALTH}}\n", encoding="utf-8")
            out = render_digest(self.inv, tpl)
        # even a template that drops the greeting still opens with it
        self.assertTrue(out.startswith(GREETING))
        self.assertIn("custom header", out)

    def test_empty_inventory_renders(self):
        from hermes_os.models import Inventory

        out = render_digest(Inventory(generated_at="2026-07-04T12:00:00-03:00"))
        self.assertTrue(out.startswith(GREETING))
        self.assertIn("- none detected", out)


if __name__ == "__main__":
    unittest.main()
