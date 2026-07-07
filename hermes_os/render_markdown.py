"""Telegram-friendly Markdown digest renderer.

Produces the compact status message that opens with the canonical
greeting line. Bullets only — no tables — so it stays readable inside
Telegram's message width on a phone.

If ``templates/digest.md`` exists it is used as the frame (simple
``{{TOKEN}}`` substitution); otherwise an embedded copy of the same
frame is used, so the renderer works even from a partial checkout.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .models import Inventory

GREETING = "Aye, Captain — Hermes Android Agentic OS status"

_DEFAULT_TEMPLATE = """{{GREETING}}
{{GENERATED_AT}}

*Health*
{{HEALTH}}

*Daybook — done / needs action*
{{TODAY}}

*Today / next cron runs*
{{CRON}}

*Open approvals*
{{APPROVALS}}

*LLM-Wiki queue*
{{WIKI}}

*Risks / blockers*
{{RISKS}}

*Suggested next actions*
{{ACTIONS}}
"""


def _bullets(lines: list[str], empty: str) -> str:
    lines = [ln for ln in lines if ln]
    if not lines:
        return f"- {empty}"
    return "\n".join(f"- {ln}" for ln in lines)


def _health_lines(inv: Inventory) -> list[str]:
    icon = {"ok": "✅", "warn": "⚠️", "risk": "🔴", "unknown": "◻️"}
    out = []
    for check in inv.health:
        out.append(f"{icon.get(check.status, '◻️')} {check.name}: {check.detail}")
    return out


def _cron_lines(inv: Inventory) -> list[str]:
    out = []
    for job in inv.cron.get("upcoming", [])[:6]:
        when = job.next_run or job.schedule or "unscheduled"
        status = f" · last: {job.last_status}" if job.last_status else ""
        target = f" → {job.delivery}" if job.delivery else ""
        out.append(f"{when} — {job.name}{target}{status}")
    counts = inv.cron.get("counts", {})
    if counts.get("total"):
        out.append(
            f"({counts.get('enabled', 0)} enabled / {counts.get('total', 0)} total"
            + (f", {counts['failing']} failing" if counts.get("failing") else "")
            + ")"
        )
    return out


def _today_lines(inv: Inventory) -> list[str]:
    today = inv.today or {}
    done = today.get("done", [])
    required = today.get("requires_action", [])
    out = [
        f"{today.get('date', 'today')}: {len(done)} done, {len(required)} waiting on you",
    ]
    for item in done[:4]:
        out.append(f"done: {item.get('title', '')} — {item.get('detail', '')}")
    for item in required[:6]:
        out.append(f"action: {item.get('kind', 'action')} — {item.get('title', '')}")
    extra = len(required) - 6
    if extra > 0:
        out.append(f"…and {extra} more action item(s)")
    return out


def _approval_lines(inv: Inventory) -> list[str]:
    out = []
    for item in inv.approvals.get("pending", [])[:8]:
        out.append(f"[{item.get('risk_level', '?')}] {item.get('title', '')} ({item.get('id', '')})")
    counts = inv.approvals.get("counts", {})
    extra = counts.get("pending", 0) - len(out)
    if extra > 0:
        out.append(f"…and {extra} more pending")
    return out


def _wiki_lines(inv: Inventory) -> list[str]:
    w = inv.wiki
    if w is None or not w.exists:
        return ["vault not reachable from here"]
    out = []
    if w.queue_total is not None:
        out.append(f"queue: {w.queue_open} open / {w.queue_total} total")
    if w.note_count is not None:
        out.append(f"{w.note_count} notes in vault")
    if w.heartbeat_age_hours is not None:
        stale = " (STALE)" if w.heartbeat_stale else ""
        out.append(f"heartbeat: {w.heartbeat_age_hours}h old{stale}")
    if w.lint_status:
        out.append(f"lint/audit: {w.lint_status}")
    for entry in w.recent_log[-2:]:
        out.append(f"log: {entry}")
    return out


def _risk_lines(inv: Inventory) -> list[str]:
    return [f"{'🔴' if r.level == 'risk' else '⚠️'} {r.message}" for r in inv.risks]


def render_digest(inv: Inventory, template_path: Optional[Path] = None) -> str:
    template = _DEFAULT_TEMPLATE
    if template_path and template_path.exists():
        try:
            template = template_path.read_text(encoding="utf-8")
        except OSError:
            template = _DEFAULT_TEMPLATE

    filled = (
        template.replace("{{GREETING}}", GREETING)
        .replace("{{GENERATED_AT}}", inv.generated_at)
        .replace("{{HEALTH}}", _bullets(_health_lines(inv), "no health data"))
        .replace("{{TODAY}}", _bullets(_today_lines(inv), "no daybook data"))
        .replace("{{CRON}}", _bullets(_cron_lines(inv), "no cron data"))
        .replace("{{APPROVALS}}", _bullets(_approval_lines(inv), "none pending"))
        .replace("{{WIKI}}", _bullets(_wiki_lines(inv), "no wiki data"))
        .replace("{{RISKS}}", _bullets(_risk_lines(inv), "none detected"))
        .replace("{{ACTIONS}}", _bullets(inv.next_actions, "nothing to do"))
    )
    # The greeting must be the first line even if a custom template
    # rearranged things badly.
    if not filled.startswith(GREETING):
        filled = GREETING + "\n" + filled
    return filled.rstrip() + "\n"
