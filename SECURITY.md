# Security

## Threat model, honestly sized

Single operator, single device, local files. The realistic risks are not attackers but leaks and self-inflicted wounds: a credential surfacing in a digest that gets pasted into Telegram, a status tool quietly mutating the system it observes, or two processes fighting over one Telegram bot. The design answers each structurally.

## Secrets never enter, and couldn't leave

The product refuses to read `.env` files, token files, API keys, OAuth tokens, or session transcripts — they are simply not data sources. Profile configs are read through an **allowlist** of six metadata keys; a credential line in `config.yaml` is skipped unread, not read-then-filtered.

For the sources that are read (logs, command output, wiki files), every string passes `redact.redact_text()` at ingest, before it is stored in the inventory. Renderers therefore cannot leak what the collector never kept. Patterns covered: `sk-*` API keys (OpenAI/Anthropic/OpenRouter shapes), Apify and Supabase tokens, Telegram bot tokens, JWTs, `Bearer` headers, GitHub and AWS key shapes, generic 40+-char opaque tokens (UUIDs exempted so job ids stay readable), and `KEY=value` / `key: value` assignments whose key name looks secret. `redact_obj()` additionally masks any dict value under a secret-looking key regardless of the value's shape.

Tests plant pattern-exact fake credentials in fixture logs, configs, and wiki files, then assert `contains_secret()` is false across the full JSON inventory, the digest, the dashboard HTML, and the approvals file on disk. Approval items are redacted on write too, since titles and suggested commands are human-typed.

## Read-only by construction

No module writes outside the product's own state dir and `dist/`. There is no code path that edits `jobs.json`, profile configs, memory, or gateway state — not a guarded one, none. The six `hermes` CLI probes are informational subcommands run with timeouts; the runner takes a fixed argv list, never a shell string.

## One gateway owner

This product never starts, stops, or restarts a gateway. It does the opposite: it watches the log tails for the signature of a duplicate owner (Telegram's `409 Conflict: terminated by other getUpdates request` and kin) and raises it as a named risk, because two pollers on one bot token is the classic self-inflicted outage of this setup.

## Approval-first, execution-never

The approval queue converts "I should change X" into a reviewed record with a risk level and a rollback note. `approvals.py` exposes add, list, and status changes — there is no execute function to misuse. When a v0.1+ feature ever proposes acting on the system, the policy is already in place: it must arrive as a pending approval, and a human runs the command.

## Dashboard hardening

`dist/index.html` is static: no JavaScript, no external requests, no CDN, so opening it grants nothing network access and it can be copied anywhere. All dynamic values are HTML-escaped at render time — a hostile log line renders as text, not markup — and a test injects `<script>` through the risk pipeline to prove it.

## Residual risks worth knowing

Redaction is regex-based; a genuinely novel token format could pass (the generic 40-char rule is the backstop). The installed wrapper bakes in a repo path — if you move the repo, re-run the installer. And `collect --json` output, though redacted, still describes your system's shape; treat it like any operational document.
