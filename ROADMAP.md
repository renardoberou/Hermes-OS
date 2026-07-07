# Roadmap

## v0 — shipped

Read-only inventory with health/risk derivation; `status`, `collect --json`, `digest`, `render-html`, `approvals list/add/set`, `doctor`; static ten-section mobile dashboard; Telegram-ready digest; record-only approval queue with atomic writes; redaction layer under test; Termux installer/uninstaller that touch one file; fixtures + 63 unittest cases; this documentation set.

## v0.1 — quality of life, still read-only

**Digest delivery via existing lanes.** A documented recipe (not a daemon) for wiring `hermes-os digest` into the already-running Hermes cron + Telegram gateway — e.g. a cron job whose command is `hermes-os digest` and whose delivery target is the existing chat. The product composes; Hermes delivers; the single-owner rule is untouched.

**Dashboard auto-refresh into the vault.** An opt-in `render-html --out` recipe writing into `LLM-Wiki/_meta/` so the dashboard rides the vault's existing sync/export flow, plus a `<meta http-equiv="refresh">` toggle for a leave-open tab.

**History.** Append each collection's health/risk summary as one JSON line under the state dir, and a `hermes-os trend` view (last N days of heartbeat age, failing-job counts, disk pressure). Still stdlib, still local.

**Richer wiki signals.** Parse lint/audit reports when the steward lane standardizes their location; surface queue *age* (oldest open item) alongside counts.

## v1 — guarded write paths, approval-first

**Approval → command handoff.** `hermes-os approvals show <id> --copy` prints the suggested command for manual paste; possibly `--script` emitting a one-shot shell file to `dist/`. Execution remains a human keystroke in a separate terminal — the product still never runs anything.

**Cron change proposals.** Generate *proposed* `jobs.json` diffs (e.g. "enable job-eir-draft") as approval items with rollback text, rendered as human-readable diffs. Applying stays manual.

**Watchdog integration.** Optional exit-code contract so the existing ops watchdog lane can call `hermes-os doctor --quiet` and alert on hard failures.

## Explicitly not planned

Starting/managing gateways; direct mutation of Hermes state from this codebase; network services or remote dashboards; paid dependencies; anything requiring a laptop. If a future need appears to demand one of these, the requirement is re-examined before the rule is.
