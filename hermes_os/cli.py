"""Command dispatcher for hermes-os.

    hermes-os status
    hermes-os collect --json
    hermes-os digest
    hermes-os render-html [--out PATH]
    hermes-os approvals list [--status pending|approved|rejected|done]
    hermes-os approvals add --title "..." --kind "..." --detail "..."
                            [--risk low|medium|high]
                            [--command "..."] [--rollback "..."]
    hermes-os approvals set ID STATUS
    hermes-os action ID --verb approve|reject|queue|dry-run|execute|done|refresh
    hermes-os apply ID [--execute]
    hermes-os doctor
    hermes-os version

Exit codes: 0 on success; 2 on usage errors; doctor exits 1 only when a
hard failure (e.g. unwritable state dir) is found — missing optional
paths are warnings, not failures.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import PRODUCT_NAME, __version__
from .actions import ActionBridge
from .apply import DEFAULT_MAX_APPROVAL_AGE_HOURS, GuardedApply
from .approvals import VALID_RISK, VALID_STATUS, ApprovalQueue
from .collect import collect
from .config import Config, is_termux
from .history import append_history, render_trend_text, summarize_trend
from .render_html import write_dashboard
from .render_markdown import render_digest


def _cfg() -> Config:
    return Config.load()


# ---- commands --------------------------------------------------------------

def cmd_status(_args: argparse.Namespace) -> int:
    cfg = _cfg()
    inv = collect(cfg)
    icon = {"ok": "OK ", "warn": "WARN", "risk": "RISK", "unknown": "?  "}
    print(f"{PRODUCT_NAME} v{__version__} — {inv.generated_at}")
    print(f"host: {'Termux' if inv.host.get('is_termux') else inv.host.get('platform', '?')} · Python {inv.host.get('python')}")
    hermes_ver = inv.hermes.get("version") or ("(hermes binary not found)" if not inv.hermes.get("bin_found") else "")
    print(f"hermes: {hermes_ver}")
    print()
    for check in inv.health:
        print(f"  [{icon.get(check.status, '?  ')}] {check.name}: {check.detail}")
    counts = inv.cron.get("counts", {})
    print()
    print(f"cron: {counts.get('enabled', 0)} enabled / {counts.get('total', 0)} jobs, {counts.get('failing', 0)} failing")
    print(f"profiles: {len(inv.profiles)} · approvals pending: {inv.approvals.get('counts', {}).get('pending', 0)}")
    if inv.wiki and inv.wiki.exists:
        print(f"wiki: {inv.wiki.note_count} notes · queue {inv.wiki.queue_open}/{inv.wiki.queue_total} open")
    if inv.risks:
        print()
        print("risks:")
        for r in inv.risks:
            print(f"  ({r.level}) {r.message}")
    print()
    print("next:")
    for a in inv.next_actions:
        print(f"  - {a}")
    if inv.warnings:
        print()
        print(f"({len(inv.warnings)} collector warning(s) — see `collect --json` for detail)")
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    inv = collect(_cfg())
    payload = inv.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    else:
        # Human-oriented fallback: compact JSON is still the contract.
        print(json.dumps(payload, ensure_ascii=False, default=str))
    return 0


def cmd_digest(_args: argparse.Namespace) -> int:
    cfg = _cfg()
    inv = collect(cfg)
    print(render_digest(inv, cfg.templates_dir / "digest.md"), end="")
    return 0


def cmd_render_html(args: argparse.Namespace) -> int:
    cfg = _cfg()
    inv = collect(cfg)
    out = Path(args.out).expanduser() if args.out else cfg.dashboard_out
    written = write_dashboard(inv, out, cfg.templates_dir / "dashboard.html")
    print(f"wrote {written}")
    print("open it on Android with:  termux-open " + str(written))
    return 0


def cmd_approvals(args: argparse.Namespace) -> int:
    cfg = _cfg()
    queue = ApprovalQueue(cfg.approvals_file)
    if args.approvals_cmd == "list":
        items = queue.list(status=args.status)
        if not items:
            print("approval queue is empty" + (f" (status={args.status})" if args.status else ""))
            return 0
        for a in items:
            line = f"{a.id}  [{a.status}] ({a.risk_level}) {a.title}"
            print(line)
            if a.kind:
                print(f"      kind: {a.kind}")
            if a.detail:
                print(f"      {a.detail}")
            if a.suggested_command:
                print(f"      suggested: {a.suggested_command}")
            if a.rollback:
                print(f"      rollback: {a.rollback}")
        return 0
    if args.approvals_cmd == "add":
        item = queue.add(
            title=args.title,
            kind=args.kind or "general",
            detail=args.detail or "",
            risk_level=args.risk,
            suggested_command=args.command or "",
            rollback=args.rollback or "",
        )
        print(f"added {item.id} [{item.status}] ({item.risk_level}) {item.title}")
        print("note: this only records the request — nothing is executed.")
        return 0
    if args.approvals_cmd == "show":
        try:
            print(queue.render_detail(args.id), end="")
        except KeyError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0
    if args.approvals_cmd == "script":
        try:
            path = queue.write_script(args.id, cfg.action_scripts_dir)
        except (KeyError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print("note: script was written for manual execution only; Hermes-OS did not run it.")
        print(f"wrote {path}")
        return 0
    if args.approvals_cmd == "set":
        try:
            item = queue.set_status(args.id, args.status)
        except KeyError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"{item.id} → {item.status} (record-keeping only; nothing executed)")
        return 0
    print("usage: hermes-os approvals {list,add,show,script,set}", file=sys.stderr)
    return 2


def cmd_history(args: argparse.Namespace) -> int:
    cfg = _cfg()
    if args.history_cmd == "append":
        inv = collect(cfg)
        entry = append_history(cfg, inv)
        print(f"appended {cfg.history_file}")
        print(
            "latest: cron_failing={cron} approvals_pending={appr} kanban_blocked={blocked} active_agents={agents}".format(
                cron=entry.get("cron_failing", 0),
                appr=entry.get("approvals_pending", 0),
                blocked=entry.get("kanban_blocked", 0),
                agents=entry.get("active_agents", 0),
            )
        )
        return 0
    print("usage: hermes-os history append", file=sys.stderr)
    return 2


def cmd_trend(_args: argparse.Namespace) -> int:
    cfg = _cfg()
    print(render_trend_text(summarize_trend(cfg.history_file)), end="")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    cfg = _cfg()
    guard = GuardedApply(cfg)
    result = guard.apply(
        args.id,
        dry_run=not args.execute,
        max_age_hours=args.max_age_hours,
    )
    if result.status == "dry-run":
        print(f"DRY RUN {result.approval_id}")
        print(f"would run: {result.command}")
        print(f"log: {cfg.apply_log_file}")
        print("validated only; use --execute for guarded execution")
        return 0
    if result.status == "refused":
        print(f"REFUSED {result.approval_id}")
        print(result.reason)
        print(f"log: {cfg.apply_log_file}")
        return 2
    if result.status == "executed":
        print(f"EXECUTED {result.approval_id} rc={result.returncode}")
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
        print(f"log: {cfg.apply_log_file}")
        return 0
    print(f"FAILED {result.approval_id} rc={result.returncode}")
    print(result.reason)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
    print(f"log: {cfg.apply_log_file}")
    return 1


def cmd_action(args: argparse.Namespace) -> int:
    """Native Decision Bridge: structured verbs for Android buttons."""
    cfg = _cfg()
    result = ActionBridge(cfg).dispatch(args.id, args.verb, source=args.source)
    label = "DRY RUN" if result.status == "dry-run" else result.status.upper()
    print(f"{label} {result.object_id} verb={result.verb}")
    if result.command:
        print("command: " + " ".join(result.command))
    if result.reason:
        print(result.reason)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
    print(f"receipt: {cfg.action_receipts_file}")
    if result.status in {"ok", "dry-run", "executed"}:
        return 0
    if result.status == "failed":
        return 1
    return 2


def cmd_doctor(_args: argparse.Namespace) -> int:
    cfg = _cfg()
    failures = 0

    def report(level: str, name: str, detail: str) -> None:
        nonlocal failures
        if level == "FAIL":
            failures += 1
        print(f"[{level:4}] {name}: {detail}")

    print(f"{PRODUCT_NAME} doctor — v{__version__}")
    print(f"termux: {'yes' if is_termux() else 'no (fine for development)'}")
    print()

    ver = sys.version_info
    report("OK" if ver >= (3, 9) else "FAIL", "python", f"{sys.version.split()[0]}")

    for name, path, required_kind in (
        ("hermes home", cfg.hermes_home, "dir"),
        ("cron jobs.json", cfg.cron_jobs_file, "file"),
        ("gateway log", cfg.gateway_log, "file"),
        ("errors log", cfg.errors_log, "file"),
        ("profiles dir", cfg.profiles_dir, "dir"),
        ("wiki root", cfg.wiki_root, "dir"),
    ):
        exists = path.is_dir() if required_kind == "dir" else path.is_file()
        report("OK" if exists else "WARN", name, f"{path}" + ("" if exists else " (missing — sections degrade gracefully)"))

    # State dir must be creatable/writable: it's ours.
    try:
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        probe = cfg.state_dir / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        report("OK", "state dir", f"{cfg.state_dir} (writable)")
    except OSError as exc:
        report("FAIL", "state dir", f"{cfg.state_dir} not writable: {exc}")

    try:
        cfg.dist_dir.mkdir(parents=True, exist_ok=True)
        report("OK", "dist dir", str(cfg.dist_dir))
    except OSError as exc:
        report("FAIL", "dist dir", f"{cfg.dist_dir} not writable: {exc}")

    for tool in (cfg.hermes_bin, "git", "python3"):
        found = shutil.which(tool) is not None
        report("OK" if found else "WARN", f"tool:{tool}", "found" if found else "not on PATH")

    for tpl in ("dashboard.html", "digest.md"):
        p = cfg.templates_dir / tpl
        report("OK" if p.exists() else "WARN", f"template:{tpl}", str(p) + ("" if p.exists() else " (embedded fallback will be used)"))

    print()
    if failures:
        print(f"doctor: {failures} hard failure(s)")
        return 1
    print("doctor: no hard failures (warnings above are informational)")
    return 0


def cmd_version(_args: argparse.Namespace) -> int:
    print(f"{PRODUCT_NAME} {__version__}")
    return 0


# ---- parser ------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hermes-os",
        description="Phone-first active decision interface with Native Decision Bridge and Guarded Apply.",
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="concise human status").set_defaults(func=cmd_status)

    p_collect = sub.add_parser("collect", help="normalized redacted inventory")
    p_collect.add_argument("--json", action="store_true", help="pretty-printed JSON")
    p_collect.set_defaults(func=cmd_collect)

    sub.add_parser("digest", help="Telegram-friendly Markdown digest").set_defaults(func=cmd_digest)

    p_html = sub.add_parser("render-html", help="write the static mobile dashboard")
    p_html.add_argument("--out", help="output path (default: <repo>/dist/index.html)")
    p_html.set_defaults(func=cmd_render_html)

    p_appr = sub.add_parser("approvals", help="local approval queue (records only; never executes)")
    appr_sub = p_appr.add_subparsers(dest="approvals_cmd")
    p_list = appr_sub.add_parser("list", help="list approvals")
    p_list.add_argument("--status", choices=VALID_STATUS, default=None)
    p_add = appr_sub.add_parser("add", help="add a pending approval item")
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--kind", default="general")
    p_add.add_argument("--detail", default="")
    p_add.add_argument("--risk", choices=VALID_RISK, default="medium")
    p_add.add_argument("--command", default="", help="suggested command (recorded, never run)")
    p_add.add_argument("--rollback", default="", help="how to undo it, for the human")
    p_set = appr_sub.add_parser("set", help="update an item's status (record-keeping only)")
    p_set.add_argument("id")
    p_set.add_argument("status", choices=VALID_STATUS)
    p_show = appr_sub.add_parser("show", help="show one approval with command/rollback detail")
    p_show.add_argument("id")
    p_script = appr_sub.add_parser("script", help="write a manual one-shot action script; never executes it")
    p_script.add_argument("id")
    p_appr.set_defaults(func=cmd_approvals)

    p_hist = sub.add_parser("history", help="local audit-trail snapshots")
    hist_sub = p_hist.add_subparsers(dest="history_cmd")
    hist_sub.add_parser("append", help="append one compact inventory summary")
    p_hist.set_defaults(func=cmd_history)

    sub.add_parser("trend", help="summarize the local audit-trail history").set_defaults(func=cmd_trend)

    p_apply = sub.add_parser("apply", help="Guarded Apply v0.1: dry-run by default; allowlisted execution only")
    p_apply.add_argument("id", help="approval id")
    p_apply.add_argument("--execute", action="store_true", help="execute after all guards pass; default is dry-run")
    p_apply.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_APPROVAL_AGE_HOURS)
    p_apply.set_defaults(func=cmd_apply)

    p_action = sub.add_parser("action", help="Native Decision Bridge v0.4.2 structured button action")
    p_action.add_argument("id", help="approval id, or 'system' for refresh")
    p_action.add_argument("--verb", required=True, help="approve|reject|queue|dry-run|execute|done|refresh")
    p_action.add_argument("--source", default="cli", help="receipt source label, e.g. android-shell")
    p_action.set_defaults(func=cmd_action)

    sub.add_parser("doctor", help="self-checks; reports missing paths/tools").set_defaults(func=cmd_doctor)
    sub.add_parser("version", help="print version").set_defaults(func=cmd_version)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 2
    if args.cmd == "approvals" and not getattr(args, "approvals_cmd", None):
        parser.parse_args(["approvals", "--help"])
        return 2
    if args.cmd == "history" and not getattr(args, "history_cmd", None):
        parser.parse_args(["history", "--help"])
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
