# Architecture

## Shape

One pipeline, three renderings, and guarded side-files:

```
                    read-mostly sources                    product state
  ┌───────────────────────────────────────────────┐   ┌──────────────────┐
  │ ~/.hermes/cron/jobs.json                      │   │ approvals.json   │
  │ ~/.hermes/logs/{gateway,errors}.log  (tails)  │   │ (~/.hermes/state/│
  │ ~/.hermes/profiles/*/config.yaml (allowlist)  │   │  hermes-android- │
  │ `hermes` CLI probes (safe commands)           │   │ history.jsonl    │
  │ LLM-Wiki structural files                     │   │ apply-log.jsonl  │
  │ Native Decision Bridge verbs                  │   │ receipts.jsonl   │
  │ Guarded Apply exact allowlist                 │   └────────┬─────────┘
  │ shutil.disk_usage                             │            │
  └───────────────┬───────────────────────────────┘            │
                  ▼                                             │
   cron.py  profiles.py  wiki.py ── parsers, tolerant, pure     │
                  │                                             │
                  ▼                                             ▼
             collect.py ──────────── redact.py ──────── approvals.py / actions.py / apply.py
                  │        (every string, on ingest)     (counts+preview
                  ▼                                       join inventory)
             models.Inventory  (normalized, already redacted)
                  │
    ┌─────────────┼──────────────────┐
    ▼             ▼                  ▼
 cli.status  render_markdown    render_html
 (terminal)  (Telegram digest)  (dist/index.html)
```

## Modules and boundaries

`config.py` owns every path and tunable; nothing else reads `os.environ`. `redact.py` is the security choke point — pure functions, no I/O, imported by anything that ingests text. The three parsers (`cron.py`, `profiles.py`, `wiki.py`) are pure given their inputs, which is what makes them unit-testable against fixture files with no environment at all.

`collect.py` is the only module that touches the outside world: it runs the six allowlisted `hermes` probes through one guarded `run_safe_command` (missing binary, timeout, and nonzero exit all degrade to inventory warnings), tails logs with a block-seek reader so file size is irrelevant, and derives health checks, risks, and next actions from the assembled facts. Its output — `models.Inventory` — is the single contract every renderer consumes; renderers never re-read the system.

`approvals.py` owns the proposal queue. Writes are atomic (`tempfile` + `os.replace`) because a phone process can die at any moment. Its API has no execution path: adding/showing/marking/script-generation never runs a `suggested_command`.

`apply.py` is the only guarded command execution gate. Guarded Apply v0.1 is deliberately narrow: approved status, fresh timestamp, low/medium risk, rollback metadata, exact command allowlist, `shell=False`, dry-run by default, and an append-only hash-chained `apply-log.jsonl`. Refusals are logged too.

`actions.py` is the Native Decision Bridge. It accepts only structured verbs (`approve`, `reject`, `dry-run`, `execute`, `done`, `refresh`), maps them to exact Hermes-OS argv lists, writes hash-chained `action-receipts.jsonl`, and refreshes the dashboard best-effort. Android URLs carry ids/verbs only; arbitrary command strings are never executed.

`cli.py` is thin dispatch: parse args, call collect/the queue/the guarded apply gate, hand the result to a renderer, choose an exit code.

## Key decisions

**Tolerant parsing over schema pinning.** Hermes's on-disk formats are treated as version-drifting: `jobs.json` may be a list, a `{"jobs": [...]}` wrapper, or an id-keyed map, and each field is looked up under several plausible names. A schema change downgrades the product's detail, never its availability.

**Allowlist, not blocklist, for profile configs.** `config.yaml` is scanned line-by-line for six safe keys (`name`, `model`, `alias`, `description`, `gateway`, `enabled`); every other line — including any credential — is never even held in memory. Redaction still runs on the extracted values as a second belt.

**Templates with embedded fallbacks.** `templates/dashboard.html` and `templates/digest.md` are `{{TOKEN}}` frames you can edit; byte-identical defaults are embedded in the renderers, so a partial checkout still renders. A test pins template file ≡ embedded default to prevent drift.

**Derived intelligence stays heuristic and says so.** Project lanes come from keyword maps over profile and job names; promotion candidates are jobs named like experiments (`draft`, `test`, ...) with a passing last run, or disabled jobs that last ran clean; duplicate-gateway detection greps log tails for Telegram's 409 `getUpdates` conflict signature. Each of these is cheap, explainable, and wrong in ways that are visible rather than silent.

## Testing strategy

Fixtures model a realistic installation — eight cron jobs across B.'s actual lanes, ten profiles, a mini-vault with queue and stale heartbeat, logs salted with pattern-exact fake credentials — and the suite asserts both the happy path and the two failure modes that matter: everything missing (fresh phone) and secrets planted everywhere (hostile logs). The verification bar is that `contains_secret()` returns false over the entire rendered JSON, Markdown, and HTML.
