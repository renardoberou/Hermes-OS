# Hermes-OS

A phone-first, **active decision interface** for a Hermes Agent installation on Android/Termux. One command gives you status; one writes a static mobile dashboard; the Android shell can now dispatch structured approve/reject/dry-run/execute decisions through the Native Decision Bridge. A local approval queue records proposed changes, can emit manual scripts, keeps audit trails, and supports Guarded Apply v0.1 for a tiny allowlisted command set.

This is not a generic agent wrapper. It is built around one specific operating system: Hermes profiles, the cron scheduler, the single-owner Telegram gateway, and the LLM-Wiki vault at `/storage/emulated/0/Documents/LLM-Wiki`.

## What it will and won't do

It reads. It renders. It records. It writes only its own state (`approvals.json`, `history.jsonl`, `apply-log.jsonl`, `action-receipts.jsonl`, generated dashboard/action-script files). Native Decision Bridge v0.4.2 accepts structured verbs only (`approve`, `reject`, `queue`, `dry-run`, `execute`, `done`, `refresh`) and maps them to fixed Hermes-OS argv lists. Guarded Apply v0.1 may execute only approved, fresh, low/medium-risk commands from a narrow allowlist (`hermes-os status`, `trend`, `history append`, `render-html`); it never starts a second gateway, never edits profiles/memory/credentials, and never runs arbitrary shell. Everything ingested passes through a redaction layer that is itself under test.

## Requirements

Python ≥ 3.9 (stdlib only — no pip installs needed) and a POSIX shell. Developed for Termux on Android; runs identically on any Linux for development.

## Quickstart (Termux)

```sh
cd ~   # or wherever you keep repos
git clone https://github.com/renardoberou/Hermes-OS.git   # or unpack the tarball
cd Hermes-OS

python -m hermes_os.cli doctor        # what's present, what's missing
python -m hermes_os.cli status       # concise human status
```

Install the `hermes-os` command:

```sh
sh scripts/install_termux.sh
hermes-os status
```

The installer writes exactly one file, `~/.local/bin/hermes-os`, with this repo's path baked in. It refuses to overwrite a `hermes-os` it didn't create (override with `FORCE=1`), and it does not touch Hermes configuration. `scripts/uninstall_termux.sh` removes that one file; add `--purge-state` if you also want the approval queue gone.

If your Termux is old enough to lack `termux-exec`, the installer still writes the installed wrapper with the absolute path returned by `command -v sh`, so the installed `hermes-os` command does not depend on `/usr/bin/env` existing.

## Commands

```sh
hermes-os status          # human-readable component status + risks + next actions
hermes-os collect --json  # full normalized, redacted inventory as JSON
hermes-os digest          # Telegram-friendly Markdown ("Aye, Captain — ...")
hermes-os render-html     # writes dist/index.html (static, no JS, no CDN)
hermes-os approvals list  # pending items in the local approval queue
hermes-os approvals add --title "..." --kind "..." --detail "..." \
                         [--risk low|medium|high] [--command "..."] [--rollback "..."]
hermes-os approvals show <id>      # full proposal detail, command, rollback, policy
hermes-os approvals script <id>    # writes dist/actions/<id>-*.sh for manual execution
hermes-os approvals set <id> <pending|approved|rejected|done>   # record-keeping only
hermes-os history append  # append one compact JSONL audit snapshot
hermes-os trend           # summarize audit snapshots
hermes-os apply <id>      # Guarded Apply v0.1 dry-run; add --execute to run allowlisted actions
hermes-os action <id> --verb approve|reject|queue|dry-run|execute|done
hermes-os action system --verb refresh
hermes-os doctor          # self-checks; missing paths are warnings, not crashes
```

`approvals show`, `approvals script`, and `approvals set` update or render only the product's own files. `action <id> --verb ...` is the Native Decision Bridge endpoint used by Android buttons; it writes `action-receipts.jsonl`, refreshes the dashboard best-effort, and never accepts arbitrary shell. `apply <id>` is dry-run by default. `apply <id> --execute` is guarded by status, age, risk, rollback metadata, and an exact command allowlist, then records a hash-chained action log. Arbitrary shell and high-risk approvals are refused.

## Daily use

Morning: `hermes-os digest` and paste (or pipe via your existing Hermes Telegram lane) into the chat where you live. The digest opens with health lamps, today's cron runs, open approvals, the LLM-Wiki queue, and anything that smells like a risk — stopped gateway, stale heartbeat, failing job, disk pressure, duplicate-gateway signals in the log tail.

When you're deciding whether to change something: `hermes-os approvals add --title "Enable EIR draft cron" --kind cron-change --risk low --command "hermes cron enable job-eir-draft" --rollback "hermes cron disable job-eir-draft"`. The queue is your buffer between "I noticed" and "I acted" — review it with `approvals list`, mark items `approved` when you've decided, `done` after you've executed them yourself.

For a fuller view: `hermes-os render-html`, then `termux-open dist/index.html`. The dashboard is a single static file styled for a phone screen — including **Now**, **Daybook**, **Kanban / live agents**, health, cron, approvals, **Action Center**, wiki queue, risks, and **Next actions** — so it also survives being copied anywhere (Downloads, the wiki's `_meta`, a browser bookmark).

Action Center v0.2 adds the safe proposal layer: `approvals show <id>`, `approvals script <id>`, `history append`, and `trend`. Guarded Apply v0.1 adds `apply <id>` as a dry-run-first execution gate for a tiny local allowlist. Native Decision Bridge v0.4.2 makes the Android shell an active surface: dashboard buttons dispatch structured **Approve**, **Reject**, **Dry run**, **Execute**, **Done**, and **Refresh** verbs through Termux RUN_COMMAND, then receipts and refreshed dashboard output are written locally. If permission/setup is missing, the app falls back to copying the structured command and opening Termux.

## Configuration

Everything is overridable with environment variables, which is also how the test suite redirects the product at fixtures:

| Variable | Default |
|---|---|
| `HERMES_OS_HERMES_HOME` | `~/.hermes` |
| `HERMES_OS_WIKI_ROOT` | `/storage/emulated/0/Documents/LLM-Wiki` |
| `HERMES_OS_STATE_DIR` | `<hermes_home>/state/hermes-android-agentic-os` |
| `HERMES_OS_DIST_DIR` | `<repo>/dist` |
| `HERMES_OS_HERMES_BIN` | `hermes` |
| `HERMES_OS_LOG_TAIL_LINES` | `40` |
| `HERMES_OS_HEARTBEAT_STALE_HOURS` | `26` |
| `HERMES_OS_DISK_WARN_PCT` | `90` |
| `HERMES_OS_CMD_TIMEOUT` | `12` |
| `HERMES_OS_SKIP_COMMANDS` | unset (`1` disables all subprocess probes) |

## Android notes

Reading `/storage/emulated/0` requires `termux-setup-storage` to have been run once. Active Android buttons also require Termux RUN_COMMAND setup: add `allow-external-apps = true` to `~/.termux/termux.properties`, run `termux-reload-settings`, and grant Hermes OS the Android permission “Run commands in Termux environment”. If the wiki root isn't reachable, the LLM-Wiki section degrades to "vault not reachable" and everything else keeps working — the same graceful-degradation rule applies to every data source, which is what `doctor` is for. Log files are tailed with a block-seek reader, so a large `gateway.log` costs nothing.

## Tests

```sh
python -m unittest discover -s tests -v
```

Fixtures live in `tests/fixtures/` (regenerate with `python tests/fixtures/_generate_fixtures.py`). Planted credentials in fixtures are fake and pattern-shaped on purpose: the suite proves they cannot survive into JSON, Markdown, or HTML output.

## Layout

```
hermes_os/        the package (config, collect, kanban, history, actions, apply, redact, renderers, approvals, cli)
scripts/          hermes-os wrapper + install/uninstall for Termux
templates/        dashboard.html and digest.md frames ({{TOKEN}} substitution)
tests/            unittest suite + fixtures (sample jobs, profiles, wiki, logs)
dist/             generated dashboard output (gitignored)
```

See `ARCHITECTURE.md` for data flow, `SECURITY.md` for the redaction and no-mutation policy, `PRD.md` for scope, and `ROADMAP.md` for what v0 deliberately leaves out.
