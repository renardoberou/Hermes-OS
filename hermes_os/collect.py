"""Read-only system inventory.

``collect()`` assembles the full :class:`~hermes_os.models.Inventory`:
host facts, Hermes CLI probes, cron state, profiles, tools, log tails,
LLM-Wiki status, disk pressure, approval counts, project lanes, health
checks, risks, and suggested next actions.

Guarantees:

* Read-only. No file outside the product's own state dir is written.
* Never raises: every probe degrades to a warning in the inventory.
* Everything ingested passes through redaction before being stored.
* Log files are tailed with a block-seek reader; whole logs are never
  loaded into memory.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import __version__
from .actions import latest_receipt
from .approvals import ApprovalQueue
from .config import Config, is_termux
from .cron import job_counts, parse_scheduler_status, read_jobs, upcoming
from .history import summarize_trend
from .kanban import collect_kanban
from .models import DiskUsage, HealthCheck, Inventory, Risk
from .profiles import discover_config_profiles, merge_profiles, parse_profile_list
from .redact import redact_text
from .wiki import collect_wiki

# Signals in log tails that indicate two processes polling one Telegram bot.
_DUP_GATEWAY_MARKERS = (
    "terminated by other getupdates",
    "409 conflict",
    "conflict: terminated",
    "another instance is already running",
    "gateway already running",
)

# Keywords mapping cron jobs / profiles into B.'s project lanes.
_PROJECT_KEYWORDS = {
    "wiki": ("wiki", "llm-wiki", "vault", "steward", "placement"),
    "selfimprove": ("selfimprove", "self-improve", "self_improve"),
    "bighart": ("bighart",),
    "camera-lens": ("camera", "lens", "spectral", "eir", "aerochrome"),
    "perdurabo": ("perdurabo",),
    "resonant-systems": ("resonant",),
    "ops": ("ops", "watchdog", "doctor", "health"),
    "experimental-models": ("experimental", "model-review", "model_eval"),
    "client": ("client",),
    "memory": ("memory", "distill"),
    "research": ("research", "digest", "approval-digest", "source"),
}

_PROMOTION_HINTS = ("draft", "test", "experiment", "trial", "candidate", "wip")

_ACTION_HEADINGS = (
    "decision list",
    "decisions",
    "action required",
    "actions required",
    "required action",
    "requires action",
    "pending approval",
    "pending approvals",
    "approval",
    "approvals",
    "next actions",
    "suggested next actions",
)

_ACTION_KEYWORDS = (
    "approval",
    "approve",
    "decision",
    "keep ",
    "deep-pass",
    "deep pass",
    "user selection",
    "requires bernado",
    "pending",
)

_MD_BOLD_PREFIX = re.compile(r"^\*\*(?P<title>[^*]{1,120})\*\*\s*(?:[—:-]\s*)?(?P<detail>.*)$")
_HEADING_RE = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(?P<body>\S.*)$")


def run_safe_command(
    args: list[str], timeout: int = 12
) -> tuple[str, Optional[str]]:
    """Run an allowlisted read-only command; return (redacted stdout, error)."""
    binary = args[0]
    if shutil.which(binary) is None:
        return "", f"binary not found: {binary}"
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "", f"{' '.join(args)}: {exc.__class__.__name__}"
    out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    if proc.returncode != 0:
        return redact_text(out.strip()), f"{' '.join(args)} exited {proc.returncode}"
    return redact_text(out.strip()), None


def tail_file(path: Path, lines: int = 40, block: int = 4096) -> list[str]:
    """Return the last *lines* lines of *path* without reading the file.

    Reads fixed-size blocks from the end. Each returned line is redacted
    and truncated; the full log never enters memory.
    """
    if lines <= 0 or not path.exists():
        return []
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            data = b""
            while size > 0 and data.count(b"\n") <= lines:
                step = min(block, size)
                size -= step
                fh.seek(size)
                data = fh.read(step) + data
                if size == 0:
                    break
        text = data.decode("utf-8", errors="replace")
    except OSError:
        return []
    tail = [ln for ln in text.splitlines() if ln.strip()][-lines:]
    return [redact_text(ln)[:300] for ln in tail]


def _disk(path: Path, warn_pct: int, label: str) -> Optional[DiskUsage]:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError:
        return None
    used_pct = int(round(100 * (usage.total - usage.free) / usage.total)) if usage.total else None
    return DiskUsage(
        path=f"{label} ({probe})",
        total_gb=round(usage.total / 1024**3, 1),
        used_pct=used_pct,
        warn=bool(used_pct is not None and used_pct >= warn_pct),
    )


def _parse_gateway_status(text: str) -> Optional[bool]:
    lowered = (text or "").lower()
    if not lowered.strip():
        return None
    if "not running" in lowered or "stopped" in lowered or "offline" in lowered:
        return False
    if "running" in lowered or "online" in lowered or "connected" in lowered:
        return True
    return None


def _detect_duplicate_gateway(log_lines: list[str]) -> bool:
    joined = "\n".join(log_lines).lower()
    return any(marker in joined for marker in _DUP_GATEWAY_MARKERS)


def _lane_for(name: str) -> Optional[str]:
    lowered = name.lower()
    for lane, keywords in _PROJECT_KEYWORDS.items():
        if any(k in lowered for k in keywords):
            return lane
    return None


def _today_date_label(now_iso: str) -> str:
    return (now_iso or datetime.now().astimezone().isoformat())[:10]


def _date_of(raw: str) -> str:
    return (raw or "")[:10]


def _time_of(raw: str) -> str:
    if not raw:
        return ""
    if "T" in raw:
        return raw.split("T", 1)[1][:5]
    if " " in raw:
        return raw.split(" ", 1)[1][:5]
    return raw[:5]


def _read_small(path: Path, limit_bytes: int = 220_000) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit_bytes)
    except OSError:
        return ""


def _strip_md(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[\[([^]|]+)\|([^]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^]]+)\]\]", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    return redact_text(" ".join(text.split()))[:240]


def _last_response(text: str) -> str:
    marker = "\n## Response"
    idx = text.rfind(marker)
    if idx >= 0:
        return text[idx + 1 :]
    return text


def _response_title(response: str, fallback: str) -> str:
    for line in response.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("Job ID:") or line == "[SILENT]":
            continue
        return _strip_md(line)[:140]
    return fallback


def _action_item_from_bullet(body: str, source: str, default_kind: str = "decision") -> Optional[dict]:
    body = body.strip()
    if not body or body.lower() in ("(none)", "none"):
        return None
    match = _MD_BOLD_PREFIX.match(body)
    if match:
        title = _strip_md(match.group("title"))
        detail = _strip_md(match.group("detail") or body)
    else:
        parts = re.split(r"\s+[—–-]\s+|:\s+", body, maxsplit=1)
        title = _strip_md(parts[0])[:120]
        detail = _strip_md(parts[1] if len(parts) > 1 else body)
    title_l = title.lower()
    if title_l.startswith("keep"):
        kind = "wiki-ingest approval"
    elif "deep" in title_l:
        kind = "deep-pass"
    elif "approve" in title_l or "approval" in title_l:
        kind = "approval"
    else:
        kind = default_kind
    return {"kind": kind, "title": title, "detail": detail, "source": source}


def _extract_actions_from_response(response: str, source: str, limit: int = 8) -> list[dict]:
    actions: list[dict] = []
    in_action_section = False
    for raw in response.splitlines():
        line = raw.rstrip()
        heading = _HEADING_RE.match(line.strip())
        if heading:
            title = heading.group("title").strip().lower()
            in_action_section = any(title.startswith(h) for h in _ACTION_HEADINGS)
            continue
        bullet = _BULLET_RE.match(line)
        if not bullet:
            continue
        body = bullet.group("body").strip()
        body_l = body.lower()
        if not in_action_section:
            strict_prefix = body_l.lstrip("* ").startswith(
                ("keep ", "deep-pass", "deep pass", "approve", "approval", "decision", "pending")
            )
            if not strict_prefix and "user selection" not in body_l and "requires bernado" not in body_l:
                continue
        item = _action_item_from_bullet(body, source)
        if item:
            actions.append(item)
        if len(actions) >= limit:
            break
    return actions


def _latest_output_for_job(cfg: Config, job_id: str, date_label: str) -> Optional[Path]:
    out_dir = cfg.hermes_home / "cron" / "output" / job_id
    if not out_dir.is_dir():
        return None
    files = sorted(out_dir.glob(f"{date_label}_*.md"), key=lambda p: p.name)
    return files[-1] if files else None


def _collect_keep_queue_actions(wiki_root: Path, limit: int = 8) -> list[dict]:
    path = wiki_root / "queries" / "queue-keep.md"
    text = _read_small(path, 80_000)
    if not text:
        return []
    actions: list[dict] = []
    in_keep = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            in_keep = "KEEP" in line.upper() and "DONE" not in line.upper()
            if line.lower().startswith("## processing") or line.lower().startswith("## done"):
                in_keep = False
            continue
        if not in_keep:
            continue
        bullet = _BULLET_RE.match(line)
        if not bullet:
            continue
        body = bullet.group("body")
        if "**DONE" in body.upper() or body.lower().strip() in ("(none)", "none"):
            continue
        item = _action_item_from_bullet(body, "queries/queue-keep.md", "deep-pass")
        if item:
            item["kind"] = "deep-pass backlog"
            actions.append(item)
        if len(actions) >= limit:
            break
    return actions


def _collect_memory_inbox_actions(wiki_root: Path, limit: int = 6) -> list[dict]:
    path = wiki_root / "_meta" / "personal-api" / "memory-inbox.md"
    text = _read_small(path, 80_000)
    if not text:
        return []
    actions: list[dict] = []
    in_pending = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            in_pending = line.lower().startswith("## pending")
            if line.lower().startswith("## archive"):
                break
            continue
        if not in_pending:
            continue
        bullet = _BULLET_RE.match(line)
        if not bullet:
            continue
        body = bullet.group("body")
        if "append new candidates here" in body.lower():
            continue
        actions.append({
            "kind": "memory review",
            "title": _strip_md(body)[:120],
            "detail": "Pending memory candidate needs routing or archival.",
            "source": "_meta/personal-api/memory-inbox.md",
        })
        if len(actions) >= limit:
            break
    return actions


def _dedupe_actions(items: list[dict], limit: int = 20) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for item in items:
        key = (item.get("kind", "") + "|" + item.get("title", "") + "|" + item.get("source", "")).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _collect_today(inv: Inventory, cfg: Config) -> dict:
    date_label = _today_date_label(inv.generated_at)
    done: list[dict] = []
    actions: list[dict] = []
    cron_runs = 0
    for job in inv.cron.get("jobs", []):
        if _date_of(job.last_run) != date_label:
            continue
        cron_runs += 1
        status = job.last_status or "unknown"
        source = f"cron:{job.id}"
        output_path = _latest_output_for_job(cfg, job.id, date_label)
        detail = f"{status} at {_time_of(job.last_run)}"
        if output_path:
            detail += f" · {output_path.name}"
        title = job.name
        if output_path:
            output_text = _read_small(output_path)
            if "## Response" in output_text:
                response = _last_response(output_text)
                title = _response_title(response, job.name)
                actions.extend(_extract_actions_from_response(response, source))
        done.append({
            "kind": "cron run",
            "title": _strip_md(title)[:140],
            "detail": _strip_md(detail),
            "source": source,
            "status": status,
        })

    # Explicit local queues that require human or specialist action.
    for item in inv.approvals.get("pending", []):
        actions.append({
            "kind": "approval",
            "title": _strip_md(item.get("title", "approval")),
            "detail": _strip_md(item.get("detail", "")),
            "source": f"approvals:{item.get('id', '')}",
        })
    actions.extend(_collect_keep_queue_actions(cfg.wiki_root))
    actions.extend(_collect_memory_inbox_actions(cfg.wiki_root))

    return {
        "date": date_label,
        "cron_runs": cron_runs,
        "done": done[:30],
        "requires_action": _dedupe_actions(actions, limit=30),
    }


def collect(cfg: Optional[Config] = None) -> Inventory:
    cfg = cfg or Config.load()
    inv = Inventory(
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        product_version=__version__,
    )
    inv.host = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "is_termux": is_termux(),
        "home": str(Path.home()),
    }

    # ---- Hermes CLI probes (all optional) -------------------------------
    probes: dict[str, str] = {}
    if cfg.skip_commands:
        inv.warnings.append("subprocess probes skipped (HERMES_OS_SKIP_COMMANDS=1)")
    else:
        for key, args in {
            "version": [cfg.hermes_bin, "--version"],
            "profile_list": [cfg.hermes_bin, "profile", "list"],
            "cron_status": [cfg.hermes_bin, "cron", "status"],
            "cron_list": [cfg.hermes_bin, "cron", "list", "--all"],
            "tools_list": [cfg.hermes_bin, "tools", "list"],
            "gateway_status": [cfg.hermes_bin, "gateway", "status"],
            "processes": ["ps", "-ef"],
        }.items():
            out, err = run_safe_command(args, timeout=cfg.cmd_timeout)
            probes[key] = out
            if err:
                inv.warnings.append(err)

    inv.hermes = {
        "bin": cfg.hermes_bin,
        "bin_found": shutil.which(cfg.hermes_bin) is not None,
        "version": probes.get("version", ""),
    }

    # ---- Gateway ---------------------------------------------------------
    gw_text = probes.get("gateway_status", "")
    inv.gateway = {
        "running": _parse_gateway_status(gw_text),
        "status_text": gw_text[:400],
    }

    # ---- Cron ------------------------------------------------------------
    jobs, cron_warnings = read_jobs(cfg.cron_jobs_file)
    inv.warnings.extend(cron_warnings)
    inv.cron = {
        "scheduler_running": parse_scheduler_status(probes.get("cron_status", "")),
        "status_text": probes.get("cron_status", "")[:400],
        "jobs": jobs,
        "counts": job_counts(jobs),
        "upcoming": upcoming(jobs),
    }

    # ---- Profiles ----------------------------------------------------------
    cli_profiles = parse_profile_list(probes.get("profile_list", ""))
    cfg_profiles = discover_config_profiles(cfg.profiles_dir)
    inv.profiles = merge_profiles(cli_profiles, cfg_profiles)

    # ---- Tools -------------------------------------------------------------
    tools_text = probes.get("tools_list", "")
    inv.tools = [
        t.strip().lstrip("-•* ").strip()
        for t in tools_text.splitlines()
        if t.strip() and not t.strip().lower().startswith(("available", "tools", "usage"))
    ][:60]

    # ---- Logs (tails only) ---------------------------------------------------
    inv.logs = {
        "gateway_tail": tail_file(cfg.gateway_log, cfg.log_tail_lines),
        "errors_tail": tail_file(cfg.errors_log, cfg.log_tail_lines),
    }

    # ---- Wiki -----------------------------------------------------------------
    inv.wiki = collect_wiki(cfg.wiki_root, stale_hours=cfg.heartbeat_stale_hours)

    # ---- Disk pressure ---------------------------------------------------------
    seen = set()
    for label, path in (("home", cfg.hermes_home), ("wiki-storage", cfg.wiki_root)):
        d = _disk(path, cfg.disk_warn_pct, label)
        if d and d.path not in seen:
            seen.add(d.path)
            inv.disks.append(d)

    # ---- Approvals ---------------------------------------------------------------
    queue = ApprovalQueue(cfg.approvals_file)
    inv.approvals = {
        "file": str(cfg.approvals_file),
        "counts": queue.counts(),
        "pending": queue.pending_preview(),
        "approved": [a.to_dict() for a in queue.list(status="approved")[:8]],
    }

    # ---- Action Center -----------------------------------------------------------
    inv.action_center = {
        "approval_file": str(cfg.approvals_file),
        "action_scripts_dir": str(cfg.action_scripts_dir),
        "history_file": str(cfg.history_file),
        "apply_log_file": str(cfg.apply_log_file),
        "action_receipts_file": str(cfg.action_receipts_file),
        "public_dashboard_file": str(cfg.public_dashboard_file),
        "last_action": latest_receipt(cfg.action_receipts_file),
        "decision_bridge": {
            "enabled": True,
            "status": "available",
            "version": "Native Decision Bridge v0.4.0",
            "reason": "Dashboard buttons dispatch structured Hermes-OS verbs through Android/Termux RUN_COMMAND; URLs never carry arbitrary shell.",
            "verbs": ["approve", "reject", "dry-run", "execute", "done", "refresh"],
        },
        "audit_trend": summarize_trend(cfg.history_file),
        "guarded_apply": {
            "enabled": True,
            "status": "available",
            "version": "Guarded Apply v0.1",
            "reason": "Guarded Apply v0.1 is dry-run by default, executes only approved non-stale low/medium-risk allowlisted commands with rollback metadata, and records a hash-chained local action log.",
            "allowed_commands": [
                "hermes-os status",
                "hermes-os trend",
                "hermes-os history append",
                "hermes-os render-html",
            ],
        },
    }

    # ---- Today / daybook ------------------------------------------------------------
    inv.today = _collect_today(inv, cfg)

    # ---- Kanban / live agents -------------------------------------------------------
    inv.kanban = collect_kanban(cfg, probes.get("processes", ""))

    # ---- Skills / automations ------------------------------------------------------
    lanes: dict[str, list[str]] = {}
    promotion: list[str] = []
    for job in jobs:
        lane = _lane_for(job.name + " " + job.profile) or "other"
        lanes.setdefault(lane, []).append(job.name)
        name_l = job.name.lower()
        if any(h in name_l for h in _PROMOTION_HINTS) and job.last_status == "ok":
            promotion.append(job.name)
        elif job.enabled is False and job.last_status == "ok":
            promotion.append(f"{job.name} (disabled but last run ok)")
    inv.skills = {
        "cron_lanes": lanes,
        "tools": inv.tools,
        "promotion_candidates": promotion,
    }

    # ---- Projects --------------------------------------------------------------------
    projects: dict[str, dict] = {}
    for p in inv.profiles:
        lane = _lane_for(p.name) or p.name
        projects.setdefault(lane, {"profiles": [], "jobs": []})
        projects[lane]["profiles"].append(p.name)
    for job in jobs:
        lane = _lane_for(job.name + " " + job.profile)
        if lane:
            projects.setdefault(lane, {"profiles": [], "jobs": []})
            projects[lane]["jobs"].append(job.name)
    inv.projects = projects

    # ---- Health + risks -----------------------------------------------------------------
    _derive_health_and_risks(inv, cfg)
    _suggest_next_actions(inv)
    return inv


def _derive_health_and_risks(inv: Inventory, cfg: Config) -> None:
    checks: list[HealthCheck] = []
    risks: list[Risk] = []

    def check(name: str, ok: Optional[bool], ok_msg: str, bad_msg: str, *, risk_code: str = "", level: str = "risk"):
        if ok is True:
            checks.append(HealthCheck(name=name, status="ok", detail=ok_msg))
        elif ok is False:
            checks.append(HealthCheck(name=name, status=level, detail=bad_msg))
            if risk_code:
                risks.append(Risk(level=level, code=risk_code, message=bad_msg))
        else:
            checks.append(HealthCheck(name=name, status="unknown", detail="no signal"))

    check(
        "gateway",
        inv.gateway.get("running"),
        "gateway reports running",
        "gateway is not running",
        risk_code="gateway-down",
    )
    check(
        "cron-scheduler",
        inv.cron.get("scheduler_running"),
        "cron scheduler running",
        "cron scheduler is not running",
        risk_code="cron-down",
    )

    failing = inv.cron.get("counts", {}).get("failing", 0)
    check(
        "cron-jobs",
        failing == 0 if inv.cron.get("jobs") else None,
        "no failing jobs",
        f"{failing} cron job(s) last exited with an error",
        risk_code="cron-failing",
        level="warn" if failing == 1 else "risk",
    )

    if inv.wiki and inv.wiki.exists:
        if inv.wiki.heartbeat_stale is None:
            checks.append(HealthCheck(name="wiki-heartbeat", status="unknown", detail="no heartbeat file"))
        else:
            age = inv.wiki.heartbeat_age_hours
            check(
                "wiki-heartbeat",
                not inv.wiki.heartbeat_stale,
                f"heartbeat {age}h old",
                f"heartbeat stale: {age}h old (threshold {cfg.heartbeat_stale_hours}h)",
                risk_code="heartbeat-stale",
                level="warn",
            )
    else:
        checks.append(HealthCheck(name="wiki", status="warn", detail="LLM-Wiki root not found"))
        risks.append(Risk(level="warn", code="wiki-missing", message=f"LLM-Wiki not found at {inv.wiki.root if inv.wiki else cfg.wiki_root}"))

    for d in inv.disks:
        check(
            f"disk:{d.path}",
            not d.warn if d.used_pct is not None else None,
            f"{d.used_pct}% used",
            f"disk pressure: {d.used_pct}% used on {d.path}",
            risk_code="disk-pressure",
        )

    dup = _detect_duplicate_gateway(
        inv.logs.get("gateway_tail", []) + inv.logs.get("errors_tail", [])
    )
    if dup:
        msg = "log tail shows duplicate-gateway signals (409/getUpdates conflict) — check for a second gateway owner"
        checks.append(HealthCheck(name="gateway-ownership", status="risk", detail=msg))
        risks.append(Risk(level="risk", code="duplicate-gateway", message=msg))
    else:
        checks.append(HealthCheck(name="gateway-ownership", status="ok", detail="no duplicate-owner signals in log tail"))

    inv.health = checks
    inv.risks = risks


def _suggest_next_actions(inv: Inventory) -> None:
    actions: list[str] = []
    codes = {r.code for r in inv.risks}
    if "gateway-down" in codes:
        actions.append("Start the gateway from its single owner profile (check `hermes gateway status` first).")
    if "duplicate-gateway" in codes:
        actions.append("Identify which process owns the Telegram gateway and stop the extra one — one owner only.")
    if "cron-down" in codes:
        actions.append("Restart the Hermes cron scheduler, then re-run `hermes-os status`.")
    if "cron-failing" in codes:
        failing = [j.name for j in inv.cron.get("jobs", []) if j.last_status == "error"]
        if failing:
            actions.append("Inspect failing job(s): " + ", ".join(failing[:4]) + ".")
    if "heartbeat-stale" in codes:
        actions.append("Check the LLM-Wiki heartbeat lane — the vault may not be receiving automated updates.")
    if "disk-pressure" in codes:
        actions.append("Free disk space (yt-dlp caches and old logs are the usual suspects).")
    pending = inv.approvals.get("counts", {}).get("pending", 0)
    if pending:
        actions.append(f"Review {pending} pending approval(s): `hermes-os approvals list`.")
    required = inv.today.get("requires_action", []) if inv.today else []
    if required:
        actions.append(f"Review today's {len(required)} action item(s) in the Daybook section.")
        for item in required[:4]:
            title = item.get("title") or item.get("kind", "action")
            kind = item.get("kind", "action")
            actions.append(f"{kind}: {title}")
    kanban = inv.kanban or {}
    active_agents = kanban.get("active_agents", [])
    blocked = int((kanban.get("counts") or {}).get("blocked", 0) or 0)
    running = int((kanban.get("counts") or {}).get("running", 0) or 0)
    if active_agents:
        actions.append(f"Monitor {len(active_agents)} live agent(s) in the Kanban / live agents section.")
    if blocked:
        actions.append(f"Review {blocked} blocked Kanban task(s).")
    elif running:
        actions.append(f"Kanban has {running} running task(s); check heartbeat if they stay running too long.")
    if not actions:
        actions.append("All clear. Regenerate the dashboard (`hermes-os render-html`) if you want a fresh view.")
    inv.next_actions = actions
