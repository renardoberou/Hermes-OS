# PRD — Hermes-OS v0

## Problem

B. runs a real agentic operating system on a phone: Hermes Agent v0.18.x on Android/Termux, ten profiles, a cron scheduler carrying research and maintenance lanes, a single-owner Telegram gateway, and the LLM-Wiki vault as the durable knowledge layer. What's missing is a control plane: one place that answers "is everything alive, what runs next, what's waiting on my decision, and what's about to become a problem" — readable on a phone, without giving any tool the power to change the system it observes.

## Users

Exactly one: the operator. This shapes everything — no auth, no multi-tenancy, no server. The product runs where the operator's fingers already are (Termux, Telegram, a local browser tab) and speaks in the operator's own vocabulary (profiles, lanes, the vault, the gateway).

## Product

A local CLI, `hermes-os`, with three renderings of one read-only inventory, plus one writable-but-inert artifact:

1. **`status`** — the terminal answer to "is it alive": health checks, risk list, next actions.
2. **`digest`** — the same inventory compressed into a Telegram-friendly Markdown message opening with `Aye, Captain — Hermes Android Agentic OS status`.
3. **`render-html`** — a static, phone-first dashboard (`dist/index.html`) with ten sections: Now, Health, Cron jobs, Profiles, Approvals, LLM-Wiki, Skills/Automations, Projects, Risks, Next actions.
4. **`approvals`** — a local queue file recording proposed changes (title, kind, detail, risk level, status, optional suggested command and rollback). The product records and displays; it never executes.

Supporting commands: `collect --json` (the raw normalized inventory, for piping into other lanes) and `doctor` (environment self-check that reports rather than crashes).

## Data sources (all read-only)

`~/.hermes/cron/jobs.json`; tails of `~/.hermes/logs/gateway.log` and `errors.log`; allowlisted metadata from `~/.hermes/profiles/*/config.yaml`; the safe Hermes CLI probes (`--version`, `profile list`, `cron status`, `cron list --all`, `tools list`, `gateway status`); LLM-Wiki structural files (`SCHEMA.md`, `index.md`, `index-full.md`, `log.md`, `queries/queue-keep.md`, `_meta/personal-api/HEARTBEAT.md`); and `shutil.disk_usage` on home and wiki storage. Every unknown is discovered at runtime; nothing is hardcoded as a guess that would break when a fact goes stale.

## Hard constraints

Android/Termux runtime; Python stdlib + POSIX shell + static HTML only; no paid services; no laptop-only workflows; no Docker/systemd/desktop-browser assumptions. No credential is ever read, printed, or requested — `.env` files, token files, and session transcripts are out of bounds by construction, and everything that *is* read passes a tested redaction layer. Live Hermes cron/profiles/memory/gateway state is never modified, and no second Telegram gateway is ever started: there is one gateway owner, and this product is not it.

## Success criteria (v0 acceptance)

The repo is self-contained; `hermes-os` works via wrapper or `python -m hermes_os.cli`; the unittest suite passes with `python -m unittest discover -s tests -v`; the dashboard and digest generate; redaction tests prove secrets cannot reach JSON/Markdown/HTML output; a missing Hermes installation or vault degrades to warnings instead of crashes; install/uninstall touch exactly one file in `~/.local/bin` and nothing in Hermes.

## Non-goals for v0

No writing to Hermes state, no cron editing, no gateway management, no Telegram sending (the digest is composed for Telegram; delivery rides existing lanes), no background daemon, no historical database of inventories, no remote access. Several of these are deliberate v0.1/v1 candidates — see `ROADMAP.md` — and all of them stay behind the approval-first policy when they arrive.
