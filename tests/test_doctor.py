"""Doctor + CLI wiring tests: missing paths must be reported, not fatal."""
from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from hermes_os import cli

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


class TestDoctor(unittest.TestCase):
    def test_doctor_with_missing_paths_reports_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with env(
                HERMES_HOME=tmp_path / "no-hermes",
                WIKI_ROOT=tmp_path / "no-wiki",
                STATE_DIR=tmp_path / "state",
                DIST_DIR=tmp_path / "dist",
                SKIP_COMMANDS="1",
            ):
                code, out = run_cli("doctor")
        self.assertEqual(code, 0, out)
        self.assertIn("WARN", out)
        self.assertIn("no hard failures", out)
        self.assertIn("missing", out)

    def test_doctor_hard_failure_on_unwritable_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "blocked"
            blocker.write_text("i am a file, not a dir", encoding="utf-8")
            with env(
                HERMES_HOME=Path(tmp) / "no-hermes",
                WIKI_ROOT=Path(tmp) / "no-wiki",
                STATE_DIR=blocker / "state",  # parent is a file → mkdir fails
                DIST_DIR=Path(tmp) / "dist",
                SKIP_COMMANDS="1",
            ):
                code, out = run_cli("doctor")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL", out)


class TestCliCommands(unittest.TestCase):
    def _fixture_env(self, tmp_path: Path):
        return env(
            HERMES_HOME=FIXTURES / "hermes_home",
            WIKI_ROOT=FIXTURES / "sample_wiki",
            STATE_DIR=tmp_path / "state",
            DIST_DIR=tmp_path / "dist",
            SKIP_COMMANDS="1",
        )

    def test_status_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self._fixture_env(Path(tmp)):
                code, out = run_cli("status")
        self.assertEqual(code, 0)
        self.assertIn("Hermes-OS", out)
        self.assertIn("risks:", out)

    def test_collect_json_is_valid(self):
        import json

        with tempfile.TemporaryDirectory() as tmp:
            with self._fixture_env(Path(tmp)):
                code, out = run_cli("collect", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["product"], "Hermes-OS")
        self.assertEqual(payload["cron"]["counts"]["total"], 8)

    def test_digest_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self._fixture_env(Path(tmp)):
                code, out = run_cli("digest")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("Aye, Captain"))

    def test_render_html_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "dist" / "index.html"
            with self._fixture_env(Path(tmp)):
                code, out = run_cli("render-html")
            self.assertEqual(code, 0)
            self.assertIn("wrote", out)
            self.assertTrue(out_file.exists())
            self.assertIn("Hermes", out_file.read_text(encoding="utf-8"))

    def test_approvals_roundtrip_via_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self._fixture_env(Path(tmp)):
                code, out = run_cli(
                    "approvals",
                    "add",
                    "--title",
                    "Promote EIR draft to weekly",
                    "--kind",
                    "cron-change",
                    "--detail",
                    "enable job-eir-draft",
                    "--risk",
                    "low",
                )
                self.assertEqual(code, 0)
                item_id = out.split()[1]
                code, out = run_cli("approvals", "list")
                self.assertEqual(code, 0)
                self.assertIn("Promote EIR draft", out)
                code, out = run_cli("approvals", "set", item_id, "approved")
                self.assertEqual(code, 0)
                code, out = run_cli("approvals", "list", "--status", "approved")
                self.assertIn(item_id, out)

    def test_no_command_prints_help(self):
        code, out = run_cli()
        self.assertEqual(code, 2)
        self.assertIn("usage", out.lower())


if __name__ == "__main__":
    unittest.main()
