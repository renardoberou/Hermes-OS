# Roadmap

## v0 — shipped

Read-only inventory with health/risk derivation; `status`, `collect --json`, `digest`, `render-html`, `approvals list/add/set`, `doctor`; static mobile dashboard with Kanban board and live-agent visibility; Telegram-ready digest; record-only approval queue with atomic writes; redaction layer under test; Termux installer/uninstaller that touch one file; fixtures + unittest coverage; this documentation set.

## v0.1 — quality of life, still read-only

**Digest delivery via existing lanes.** A documented recipe (not a daemon) for wiring `hermes-os digest` into the already-running Hermes cron + Telegram gateway — e.g. a cron job whose command is `hermes-os digest` and whose delivery target is the existing chat. The product composes; Hermes delivers; the single-owner rule is untouched.

**Dashboard auto-refresh into the vault.** An opt-in `render-html --out` recipe writing into `LLM-Wiki/_meta/` so the dashboard rides the vault's existing sync/export flow, plus a `<meta http-equiv="refresh">` toggle for a leave-open tab.

**Richer wiki signals.** Parse lint/audit reports when the steward lane standardizes their location; surface queue *age* (oldest open item) alongside counts.

## v0.2 — Action Center, shipped

**Approval detail and script handoff.** `hermes-os approvals show <id>` renders full proposal detail; `hermes-os approvals script <id>` writes a provenance-rich one-shot script under `dist/actions/`. The script is never executed by Hermes-OS.

**Audit trail and trend.** `hermes-os history append` writes one compact, redacted JSONL inventory summary under the state dir; `hermes-os trend` summarizes recent samples for cron failures, approvals, Kanban, live agents, and risk/warn counts.

**Dashboard Action Center.** The HTML dashboard surfaces action-script location, audit-trail location, latest trend counters, and explicit guarded-apply status.

**Tappable mobile affordances.** Dashboard action chips use `hermesos://` links intercepted by the Android WebView shell to copy commands/open Termux. No JavaScript and no auto-execution.

## v0.3 — Guarded Apply v0.1, shipped

**Guarded Apply v0.1.** `hermes-os apply <id>` is dry-run by default; `--execute` is allowed only for approved, non-stale, low/medium-risk approvals with rollback metadata and a command matching the exact allowlist. Every attempt writes `apply-log.jsonl` with a hash chain. No arbitrary shell, no gateway ownership changes, no credentials, no profile/memory mutation.

## v1 — broader guarded write paths, approval-first

**Expanded guarded apply.** Future candidates may add structured cron-change proposals and other reversible local writes after v0.1 logs have been reviewed. Scope must remain allowlisted and rollback-backed.

**Cron change proposals.** Generate *proposed* `jobs.json` diffs (e.g. "enable job-eir-draft") as approval items with rollback text, rendered as human-readable diffs. Applying can move through Guarded Apply only after the proposed command lands in the allowlist and has rollback metadata; otherwise it stays manual.

**Watchdog integration.** Optional exit-code contract so the existing ops watchdog lane can call `hermes-os doctor --quiet` and alert on hard failures.

## Explicitly not planned

Starting/managing gateways; arbitrary shell execution; direct mutation of Hermes state outside reviewed Guarded Apply allowlists; network services or remote dashboards; paid dependencies; anything requiring a laptop. If a future need appears to demand one of these, the requirement is re-examined before the rule is.
