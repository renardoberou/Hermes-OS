"""Collector tests: parsing fixtures, graceful degradation, no leaks."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from hermes_os.collect import collect, run_safe_command, tail_file
from hermes_os.config import Config
from hermes_os.cron import job_counts, parse_scheduler_status, read_jobs, upcoming
from hermes_os.profiles import (
    discover_config_profiles,
    merge_profiles,
    parse_profile_list,
)
from hermes_os.redact import contains_secret
from hermes_os.wiki import collect_wiki

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture_config(tmp_state: Path, tmp_dist: Path) -> Config:
    return Config(
        hermes_home=FIXTURES / "hermes_home",
        wiki_root=FIXTURES / "sample_wiki",
        state_dir=tmp_state,
        dist_dir=tmp_dist,
        skip_commands=True,  # no subprocess in tests
    )


class TestCronParsing(unittest.TestCase):
    def test_read_sample_jobs(self):
        jobs, warnings = read_jobs(FIXTURES / "sample_jobs.json")
        self.assertEqual(warnings, [])
        self.assertEqual(len(jobs), 8)
        by_id = {j.id: j for j in jobs}
        self.assertEqual(by_id["job-wiki-research"].profile, "wiki")
        self.assertEqual(by_id["job-wiki-research"].last_status, "ok")
        self.assertEqual(by_id["job-memory-distill"].last_status, "error")
        self.assertIs(by_id["job-eir-draft"].enabled, False)

    def test_counts_and_upcoming(self):
        jobs, _ = read_jobs(FIXTURES / "sample_jobs.json")
        counts = job_counts(jobs)
        self.assertEqual(counts["total"], 8)
        self.assertEqual(counts["disabled"], 1)
        self.assertEqual(counts["failing"], 1)
        up = upcoming(jobs, limit=3)
        self.assertEqual(len(up), 3)
        # sorted by next_run string: wiki research (06:00) precedes watchdog (12:00)
        self.assertEqual(up[0].id, "job-wiki-research")
        self.assertIn("job-watchdog", [j.id for j in up])
        # disabled job never appears
        self.assertNotIn("job-eir-draft", [j.id for j in up])

    def test_missing_file_degrades(self):
        jobs, warnings = read_jobs(FIXTURES / "does-not-exist.json")
        self.assertEqual(jobs, [])
        self.assertTrue(any("not found" in w for w in warnings))

    def test_bare_list_and_wrapper_shapes(self):
        from hermes_os.cron import parse_jobs_payload

        bare = parse_jobs_payload([{"id": "a", "name": "A"}])
        wrapped = parse_jobs_payload({"jobs": [{"id": "a", "name": "A"}]})
        keyed = parse_jobs_payload({"a": {"id": "a", "name": "A"}})
        for result in (bare, wrapped, keyed):
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].id, "a")

    def test_scheduler_status_text(self):
        self.assertTrue(parse_scheduler_status("Scheduler: running (8 jobs)"))
        self.assertFalse(parse_scheduler_status("scheduler stopped"))
        self.assertIsNone(parse_scheduler_status(""))
        # "not running" must win over the "running" substring
        self.assertFalse(parse_scheduler_status("Scheduler: not running"))


class TestProfileParsing(unittest.TestCase):
    def test_parse_cli_output(self):
        text = (FIXTURES / "sample_profile_list.txt").read_text()
        profiles = parse_profile_list(text)
        names = [p.name for p in profiles]
        self.assertEqual(len(profiles), 10)
        self.assertIn("perdurabo", names)
        active = [p for p in profiles if p.is_active]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].name, "default")
        self.assertEqual(active[0].model, "hermes-4-405b")
        self.assertEqual(active[0].gateway, "running")

    def test_config_discovery_allowlist(self):
        profiles = discover_config_profiles(FIXTURES / "hermes_home" / "profiles")
        self.assertEqual(len(profiles), 3)
        blob = json.dumps([p.__dict__ for p in profiles])
        self.assertFalse(contains_secret(blob), f"secret leaked: {blob[:400]}")
        wiki = next(p for p in profiles if p.name == "wiki")
        self.assertEqual(wiki.model, "hermes-4-405b")
        self.assertEqual(wiki.description, "LLM-Wiki research steward")

    def test_merge_prefers_cli_state(self):
        cli = parse_profile_list((FIXTURES / "sample_profile_list.txt").read_text())
        cfg = discover_config_profiles(FIXTURES / "hermes_home" / "profiles")
        merged = merge_profiles(cli, cfg)
        self.assertEqual(len(merged), 10)  # config names all overlap CLI names
        self.assertTrue(merged[0].is_active)  # active first
        default = merged[0]
        self.assertEqual(default.source, "cli+config")
        self.assertEqual(default.description, "primary gateway owner")


class TestWiki(unittest.TestCase):
    def test_collect_wiki_fixture(self):
        status = collect_wiki(FIXTURES / "sample_wiki")
        self.assertTrue(status.exists)
        self.assertEqual(status.queue_total, 7)
        self.assertEqual(status.queue_done, 2)
        self.assertEqual(status.queue_open, 5)
        # heartbeat fixture is dated 2026-07-01 → always stale by now
        self.assertIsNotNone(status.heartbeat_age_hours)
        self.assertTrue(status.heartbeat_stale)
        # structural files map
        self.assertTrue(status.structural_files["SCHEMA.md"])
        self.assertTrue(status.structural_files["queries/queue-keep.md"])
        # note count excludes _meta but includes concepts + structural md
        self.assertGreaterEqual(status.note_count, 7)
        # log tail is redacted (fixture log contains a fake JWT)
        joined = "\n".join(status.recent_log)
        self.assertFalse(contains_secret(joined), joined)
        self.assertIn("[REDACTED:jwt]", joined)

    def test_missing_vault(self):
        status = collect_wiki(FIXTURES / "no-such-vault")
        self.assertFalse(status.exists)
        self.assertIsNone(status.note_count)


class TestRunSafeCommand(unittest.TestCase):
    def test_nonzero_command_keeps_stdout_out_of_traceback_body(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cmd = tmp_path / "probe"
            cmd.write_text(
                "#!/bin/sh\n"
                "printf 'Hermes Agent v9\\n'\n"
                "printf 'Traceback secret-side-channel\\n' >&2\n"
                "exit 1\n",
                encoding="utf-8",
            )
            cmd.chmod(0o755)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{tmp_path}{os.pathsep}{old_path}"
            try:
                out, err = run_safe_command(["probe"])
            finally:
                os.environ["PATH"] = old_path

        self.assertEqual(out, "Hermes Agent v9")
        self.assertIn("exited 1", err or "")
        self.assertIn("Traceback", err or "")
        self.assertNotIn("Traceback", out)


class TestTailFile(unittest.TestCase):
    def test_tail_redacts_and_limits(self):
        log = FIXTURES / "hermes_home" / "logs" / "gateway.log"
        lines = tail_file(log, lines=3)
        self.assertEqual(len(lines), 3)
        # full tail must cover and mask the planted telegram + bearer lines
        all_lines = tail_file(log, lines=50)
        joined = "\n".join(all_lines)
        self.assertIn("[REDACTED:telegram-token]", joined)
        self.assertIn("[REDACTED:bearer]", joined)
        self.assertFalse(contains_secret(joined), joined)

    def test_tail_missing_file(self):
        self.assertEqual(tail_file(FIXTURES / "nope.log"), [])


class TestFullCollect(unittest.TestCase):
    def test_collect_against_fixtures(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cfg = fixture_config(tmp_path / "state", tmp_path / "dist")
            inv = collect(cfg)

        self.assertEqual(inv.cron["counts"]["total"], 8)
        self.assertEqual(len(inv.profiles), 3)  # config-only (commands skipped)
        self.assertTrue(inv.wiki.exists)
        self.assertEqual(inv.approvals["counts"]["total"], 0)

        # duplicate-gateway signal from the fixture 409 line
        codes = {r.code for r in inv.risks}
        self.assertIn("duplicate-gateway", codes)
        self.assertIn("cron-failing", codes)
        self.assertIn("heartbeat-stale", codes)

        # next actions mention the failing job
        joined_actions = " ".join(inv.next_actions)
        self.assertIn("memory distillation", joined_actions)

        # the whole JSON payload must be secret-free
        payload = json.dumps(inv.to_dict(), default=str)
        self.assertFalse(contains_secret(payload), payload[:600])

    def test_collect_with_everything_missing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cfg = Config(
                hermes_home=tmp_path / "no-hermes",
                wiki_root=tmp_path / "no-wiki",
                state_dir=tmp_path / "state",
                dist_dir=tmp_path / "dist",
                skip_commands=True,
            )
            inv = collect(cfg)  # must not raise
        self.assertEqual(inv.cron["counts"]["total"], 0)
        self.assertFalse(inv.wiki.exists)
        self.assertTrue(inv.warnings)
        self.assertTrue(inv.next_actions)


if __name__ == "__main__":
    unittest.main()
