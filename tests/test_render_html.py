"""Dashboard renderer tests."""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from hermes_os.collect import collect
from hermes_os.config import Config
from hermes_os.models import Inventory, Risk
from hermes_os.redact import contains_secret
from hermes_os.render_html import render_dashboard, write_dashboard

FIXTURES = Path(__file__).resolve().parent / "fixtures"

SECTION_TITLES = (
    "1 · Now",
    "2 · Daybook",
    "3 · Kanban / live agents",
    "4 · Health",
    "5 · Cron jobs",
    "6 · Profiles",
    "7 · Approvals",
    "8 · Action Center",
    "9 · LLM-Wiki",
    "10 · Skills / Automations",
    "11 · Projects",
    "12 · Risks",
    "13 · Next actions",
)


def _inv() -> Inventory:
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


class TestDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inv = _inv()
        cls.html = render_dashboard(cls.inv)

    def test_write_dashboard_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_dashboard(self.inv, Path(tmp) / "dist" / "index.html")
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 4000)

    def test_all_sections_present(self):
        for title in SECTION_TITLES:
            self.assertIn(title, self.html, f"missing section {title}")

    def test_no_external_assets(self):
        lowered = self.html.lower()
        self.assertNotIn("<script", lowered)
        self.assertNotIn("http://", lowered)
        self.assertNotIn("https://", lowered)
        self.assertNotIn("cdn", lowered)

    def test_mobile_viewport(self):
        self.assertIn('name="viewport"', self.html)
        self.assertIn("width=device-width", self.html)

    def test_fixture_content_rendered(self):
        self.assertIn("cron/gateway watchdog", self.html)
        self.assertIn("LLM-Wiki research steward", self.html)
        self.assertIn("5 open / 7 total", self.html)
        self.assertIn("Live agents", self.html)
        self.assertIn("Boards", self.html)
        self.assertIn("Action scripts", self.html)
        self.assertIn("structured buttons dispatch", self.html)
        self.assertIn("hermesos://termux", self.html)
        self.assertIn("hermesos://copy", self.html)
        self.assertIn("Guarded Apply v0.1", self.html)
        self.assertIn("hermes-os apply &lt;id&gt;", self.html)

    def test_no_secrets(self):
        self.assertFalse(contains_secret(self.html), self.html[:600])

    def test_values_are_escaped(self):
        inv = Inventory(
            generated_at="2026-07-04T12:00:00-03:00",
            risks=[Risk(level="risk", code="x", message="<script>alert(1)</script>")],
            next_actions=["<img src=x onerror=alert(1)>"],
        )
        html = render_dashboard(inv)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<img src=x", html)

    def test_risk_lamp_reflects_state(self):
        # fixture inventory has real risks → risk lamp on
        m = re.search(r'<span class="lamp (\w*)"><i></i>risks</span>', self.html)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "risk")

    def test_template_file_matches_embedded_default(self):
        tpl = Path(__file__).resolve().parent.parent / "templates" / "dashboard.html"
        from hermes_os.render_html import _DEFAULT_TEMPLATE

        self.assertEqual(tpl.read_text(encoding="utf-8"), _DEFAULT_TEMPLATE)


if __name__ == "__main__":
    unittest.main()
