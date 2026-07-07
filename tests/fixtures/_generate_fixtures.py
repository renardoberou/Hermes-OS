"""Regenerate the test fixtures. Run from repo root:

    python tests/fixtures/_generate_fixtures.py

Fixtures contain ONLY fake, pattern-shaped credentials so redaction can
be proven. Nothing here is or ever was a live secret.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --- fake credentials, asserted against the product's own regexes -----------
FAKE_SK = "sk-or-v1-" + "f4ke" * 8                      # OpenRouter-style
FAKE_TG = "8123456789:" + ("AAf4keF4kef4keF4kef4keF4kef4keF4kef"[:35])
FAKE_BEARER = "Bearer f4kef4kef4kef4kef4kef4ke"
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJmYWtlIjoidHJ1ZSJ9.f4kef4kef4ke"
FAKE_APIFY = "apify_api_" + "f4ke" * 6
FAKE_SUPABASE = "sbp_" + "f4ke" * 6

assert re.fullmatch(r"sk-[A-Za-z0-9_\-]{16,}", FAKE_SK)
assert re.fullmatch(r"\d{8,10}:[A-Za-z0-9_\-]{35}", FAKE_TG)
assert re.fullmatch(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}", FAKE_JWT)
assert re.fullmatch(r"apify_api_[A-Za-z0-9]{16,}", FAKE_APIFY)
assert re.fullmatch(r"sbp_[A-Za-z0-9]{16,}", FAKE_SUPABASE)

# --- cron jobs ---------------------------------------------------------------
JOBS = {
    "version": 1,
    "jobs": [
        {
            "id": "job-wiki-research",
            "name": "LLM-Wiki whole-vault research",
            "profile": "wiki",
            "schedule": "0 6 * * *",
            "enabled": True,
            "last_run": "2026-07-03T06:00:11-03:00",
            "last_status": "ok",
            "next_run": "2026-07-04T06:00:00-03:00",
            "delivery": "telegram",
        },
        {
            "id": "job-placement-audit",
            "name": "Weekly placement audit",
            "profile": "wiki",
            "schedule": "0 7 * * 1",
            "enabled": True,
            "last_run": "2026-06-29T07:00:04-03:00",
            "last_status": "ok",
            "next_run": "2026-07-06T07:00:00-03:00",
            "delivery": "telegram",
        },
        {
            "id": "job-watchdog",
            "name": "cron/gateway watchdog",
            "profile": "ops",
            "schedule": "*/15 * * * *",
            "enabled": True,
            "last_run": "2026-07-04T11:45:02-03:00",
            "last_status": "ok",
            "next_run": "2026-07-04T12:00:00-03:00",
            "delivery": "file",
        },
        {
            "id": "job-steward",
            "name": "A+ LLM-Wiki structural steward",
            "profile": "wiki",
            "schedule": "30 5 * * *",
            "enabled": True,
            "last_run": "2026-07-04T05:30:09-03:00",
            "last_status": "ok",
            "next_run": "2026-07-05T05:30:00-03:00",
            "delivery": "telegram",
        },
        {
            "id": "job-memory-distill",
            "name": "memory distillation",
            "profile": "default",
            "schedule": "15 4 * * *",
            "enabled": True,
            "last_run": "2026-07-04T04:15:20-03:00",
            "last_status": "error",
            "next_run": "2026-07-05T04:15:00-03:00",
            "delivery": "file",
        },
        {
            "id": "job-source-digest",
            "name": "research-source approval digest",
            "profile": "wiki",
            "schedule": "0 20 * * *",
            "enabled": True,
            "last_run": "2026-07-03T20:00:07-03:00",
            "last_status": "ok",
            "next_run": "2026-07-04T20:00:00-03:00",
            "delivery": "telegram",
        },
        {
            "id": "job-selfimprove",
            "name": "self-improvement loop",
            "profile": "selfimprove",
            "schedule": "0 3 * * 0",
            "enabled": True,
            "last_run": "2026-06-28T03:00:31-03:00",
            "last_status": "ok",
            "next_run": "2026-07-05T03:00:00-03:00",
            "delivery": "telegram",
        },
        {
            "id": "job-eir-draft",
            "name": "camera-lens draft: EIR preset research digest",
            "profile": "camera-lens",
            "schedule": "0 9 * * 6",
            "enabled": False,
            "last_run": "2026-06-27T09:00:12-03:00",
            "last_status": "ok",
            "next_run": "",
            "delivery": "telegram",
        },
    ],
}

# --- files -------------------------------------------------------------------

def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print("wrote", path.relative_to(HERE.parent.parent))


def main() -> None:
    jobs_json = json.dumps(JOBS, indent=2, ensure_ascii=False) + "\n"
    write(HERE / "sample_jobs.json", jobs_json)
    write(HERE / "hermes_home" / "cron" / "jobs.json", jobs_json)

    write(
        HERE / "sample_profile_list.txt",
        """Profiles:
* default          (model: hermes-4-405b)  [gateway: running]
  wiki             (model: hermes-4-405b)
  selfimprove      (model: hermes-4-70b)
  resonant-systems (model: hermes-4-70b)
  perdurabo        (model: hermes-4-405b)
  bighart          (model: hermes-4-70b)
  camera-lens      (model: hermes-4-70b)
  experimental-review (model: experimental-model)
  ops              (model: hermes-4-70b)
  client-template  (model: hermes-4-70b)
""",
    )

    write(
        HERE / "sample_tools_list.txt",
        """Available tools:
- shell
- python
- browser
- telegram_send
- wiki_search
- git
- yt_dlp
""",
    )

    write(
        HERE / "hermes_home" / "logs" / "gateway.log",
        f"""2026-07-04 11:02:11 INFO gateway: polling ok (profile=default)
2026-07-04 11:04:41 INFO telegram: session refreshed token={FAKE_TG}
2026-07-04 11:07:03 INFO http: Authorization: {FAKE_BEARER}
2026-07-04 11:15:00 INFO gateway: heartbeat ok
2026-07-04 11:17:22 ERROR telegram: 409 Conflict: terminated by other getUpdates request
2026-07-04 11:18:01 INFO gateway: retry scheduled
""",
    )

    write(
        HERE / "hermes_home" / "logs" / "errors.log",
        f"""2026-07-04 04:15:20 ERROR memory-distill: upstream 502 (key={FAKE_SK})
2026-07-04 04:15:21 ERROR memory-distill: giving up after 3 retries
""",
    )

    profiles = {
        "default": {
            "name": "default",
            "model": "hermes-4-405b",
            "alias": "H",
            "description": "primary gateway owner",
            "gateway": "running",
            "api_key": FAKE_SK,
            "telegram_bot_token": FAKE_TG,
        },
        "wiki": {
            "name": "wiki",
            "model": "hermes-4-405b",
            "alias": "W",
            "description": "LLM-Wiki research steward",
            "openrouter_api_key": FAKE_SK,
        },
        "bighart": {
            "name": "bighart",
            "model": "hermes-4-70b",
            "alias": "B",
            "description": "Resonant Systems instrument lane",
            "supabase_service_key": FAKE_JWT,
            "apify_token": FAKE_APIFY,
        },
    }
    for name, cfg in profiles.items():
        lines = [f"{k}: {v}" for k, v in cfg.items()]
        write(HERE / "hermes_home" / "profiles" / name / "config.yaml", "\n".join(lines) + "\n")

    # --- sample wiki ---------------------------------------------------------
    wiki = HERE / "sample_wiki"
    write(wiki / "SCHEMA.md", "# LLM-Wiki schema\n\nNotes carry YAML frontmatter with `type`, `status`, `links`.\n")
    write(wiki / "index.md", "# Index\n\n- [[concepts/predictive-processing]]\n- [[concepts/modular-flow]]\n")
    write(wiki / "index-full.md", "# Full index\n\n(generated)\n")
    write(
        wiki / "log.md",
        """# Vault log

- 2026-07-01 steward: relinked 12 orphan notes
- 2026-07-02 research: queued 3 sources on interoceptive inference
- 2026-07-03 distill: memory summary appended (supabase key rotated: {jwt})
- 2026-07-03 audit: 0 schema violations
- 2026-07-04 steward: normalized frontmatter in 5 notes
""".replace("{jwt}", FAKE_JWT),
    )
    write(
        wiki / "queries" / "queue-keep.md",
        """# Research queue (keep)

- [x] Tomita–Takesaki survey pass
- [x] Rovelli relational QM re-read
- [ ] Seth interoceptive inference 2024 follow-ups
- [ ] Friston active inference agency phenotyping
- [ ] modular flow ↔ thermal time note merge
- [ ] Proclus → Liber de Causis transmission map
- [ ] EIR emulsion spectral response sources
""",
    )
    write(
        wiki / "_meta" / "personal-api" / "HEARTBEAT.md",
        "# Heartbeat\n\nlast: 2026-07-01T09:00:00-03:00\n",
    )
    # concept notes so note_count > structural files
    write(wiki / "concepts" / "predictive-processing.md", "# Predictive processing\n\nstub\n")
    write(wiki / "concepts" / "modular-flow.md", "# Modular flow\n\nstub\n")
    write(wiki / "concepts" / "neuroscience-open-problems.md", "# Open problems\n\nstub\n")

    print("fixtures ok")


if __name__ == "__main__":
    main()
