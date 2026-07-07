"""Static mobile dashboard renderer.

Writes a single self-contained HTML file (no JS, no external assets,
no CDN) styled as a phosphor-amber bridge console — the visual language
of the Resonant Systems instruments carried over to the control plane.
Every dynamic value is HTML-escaped; the inventory it renders is
already redacted at collection time, and escaping here guarantees log
lines can't inject markup.

If ``templates/dashboard.html`` exists it is used as the frame
(``{{TOKEN}}`` substitution); otherwise an embedded copy is used.
"""
from __future__ import annotations

import html
from pathlib import Path
from typing import Optional

from . import __version__
from .models import Inventory

_DEFAULT_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Hermes // Android Agentic OS</title>
<style>
:root{
  --ink:#120d08;        /* warm black */
  --panel:#1c1510;      /* card */
  --line:#3a2a1a;       /* copper rule */
  --text:#e9dcc3;       /* bone */
  --dim:#9a8768;        /* faded brass */
  --amber:#ffb454;      /* phosphor amber (signature) */
  --ok:#8fd68f;
  --warn:#ffb454;
  --risk:#ff6b57;
}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%}
body{
  background:var(--ink);color:var(--text);
  font-family:ui-monospace,"Cascadia Mono","JetBrains Mono","Fira Code",Menlo,Consolas,monospace;
  font-size:14px;line-height:1.55;
  padding-bottom:48px;
}
.wrap{max-width:720px;margin:0 auto;padding:0 14px}
header{
  position:sticky;top:0;z-index:5;
  background:linear-gradient(180deg,rgba(18,13,8,.97) 75%,rgba(18,13,8,.85));
  border-bottom:1px solid var(--line);
  padding:14px 0 10px;
  backdrop-filter:blur(2px);
}
header .wrap{display:flex;flex-direction:column;gap:8px}
.masthead{display:flex;align-items:baseline;justify-content:space-between;gap:10px;flex-wrap:wrap}
h1{
  font-size:15px;letter-spacing:.14em;font-weight:700;color:var(--amber);
  text-transform:uppercase;white-space:nowrap;
}
h1 span{color:var(--dim);font-weight:400}
.stamp{color:var(--dim);font-size:11.5px}
.lamps{display:flex;gap:14px;flex-wrap:wrap}
.lamp{display:flex;align-items:center;gap:6px;font-size:11px;letter-spacing:.08em;color:var(--dim);text-transform:uppercase}
.lamp i{width:9px;height:9px;border-radius:50%;display:inline-block;background:var(--dim)}
.lamp.ok i{background:var(--ok);box-shadow:0 0 6px var(--ok)}
.lamp.warn i{background:var(--warn);box-shadow:0 0 6px var(--warn)}
.lamp.risk i{background:var(--risk);box-shadow:0 0 7px var(--risk)}
@media (prefers-reduced-motion: no-preference){
  .lamp.risk i{animation:pulse 1.6s ease-in-out infinite}
  @keyframes pulse{50%{opacity:.45}}
}
main{padding-top:16px}
section{
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:8px;
  margin:0 0 14px;
  padding:12px 14px 13px;
}
section h2{
  font-size:11px;font-weight:700;letter-spacing:.18em;text-transform:uppercase;
  color:var(--amber);margin-bottom:9px;
  padding-bottom:7px;border-bottom:1px solid var(--line);
}
.subhead{
  font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--dim);
  margin:10px 0 3px;
}
.kv{display:flex;justify-content:space-between;gap:12px;padding:3px 0;border-bottom:1px dotted rgba(154,135,104,.18)}
.kv:last-child{border-bottom:0}
.kv .k{color:var(--dim);flex:0 0 auto}
.kv .v{text-align:right;word-break:break-word}
ul{list-style:none}
li{padding:5px 0;border-bottom:1px dotted rgba(154,135,104,.18);word-break:break-word}
li:last-child{border-bottom:0}
.row-title{color:var(--text)}
.row-sub{color:var(--dim);font-size:12px;display:block;margin-top:1px}
.pill{
  display:inline-block;font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;
  border:1px solid;border-radius:999px;padding:0 7px;margin-left:6px;vertical-align:1px;
}
.pill.ok{color:var(--ok);border-color:var(--ok)}
.pill.warn{color:var(--warn);border-color:var(--warn)}
.pill.risk{color:var(--risk);border-color:var(--risk)}
.pill.unknown,.pill.dim{color:var(--dim);border-color:var(--dim)}
.empty{color:var(--dim);font-style:italic}
.bar{height:5px;background:rgba(154,135,104,.2);border-radius:3px;overflow:hidden;margin-top:4px}
.bar b{display:block;height:100%;background:var(--amber)}
.bar.hot b{background:var(--risk)}
footer{color:var(--dim);font-size:11px;text-align:center;margin-top:22px}
footer .rule{color:var(--line)}
a{color:var(--amber)}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <div class="masthead">
      <h1>Hermes <span>//</span> Android Agentic OS</h1>
      <div class="stamp">{{GENERATED_AT}}</div>
    </div>
    <div class="lamps">{{LAMPS}}</div>
  </div>
</header>
<main class="wrap">
{{SECTIONS}}
<footer>read-only inventory · dashboard snapshots are regenerated locally<br>
<a href="llm-wiki-graph.html">open LLM-Wiki graph view</a><br>
<span class="rule">─────</span> hermes-os v{{VERSION}} <span class="rule">─────</span></footer>
</main>
</body>
</html>
"""


def _e(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _pill(status: str) -> str:
    status = status if status in ("ok", "warn", "risk", "unknown") else "dim"
    return f'<span class="pill {status}">{_e(status)}</span>'


def _section(title: str, inner: str) -> str:
    return f"<section>\n<h2>{_e(title)}</h2>\n{inner}\n</section>"


def _kv(pairs: list[tuple[str, str]]) -> str:
    rows = "".join(
        f'<div class="kv"><span class="k">{_e(k)}</span><span class="v">{v}</span></div>'
        for k, v in pairs
    )
    return rows or '<p class="empty">nothing to show</p>'


def _ul(items: list[str], empty: str) -> str:
    if not items:
        return f'<p class="empty">{_e(empty)}</p>'
    return "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"


# ---- individual sections -------------------------------------------------

def _sec_now(inv: Inventory) -> str:
    active = next((p for p in inv.profiles if p.is_active), None)
    gw = inv.gateway.get("running")
    gw_label = {True: "running" + _pill("ok"), False: "down" + _pill("risk")}.get(
        gw, "unknown" + _pill("unknown")
    )
    pairs = [
        ("generated", _e(inv.generated_at)),
        ("active profile", _e(active.name if active else "unknown")),
        ("gateway", gw_label),
        ("hermes", _e(inv.hermes.get("version") or ("found" if inv.hermes.get("bin_found") else "not found"))),
        ("host", _e(("Termux · " if inv.host.get("is_termux") else "") + "Python " + str(inv.host.get("python", "")))),
    ]
    return _section("1 · Now", _kv(pairs))


def _today_rows(rows: list[dict], empty: str, *, max_items: int = 12) -> str:
    items = []
    for row in rows[:max_items]:
        status = row.get("status", "")
        pill = ""
        if status:
            pill = _pill("ok" if status == "ok" else "risk" if status == "error" else "unknown")
        elif row.get("kind"):
            pill = f'<span class="pill warn">{_e(row.get("kind"))}</span>'
        detail_bits = [row.get("detail", ""), row.get("source", "")]
        detail = " · ".join(str(b) for b in detail_bits if b)
        items.append(
            f'<span class="row-title">{_e(row.get("title", ""))}</span>{pill}'
            f'<span class="row-sub">{_e(detail)}</span>'
        )
    more = len(rows) - len(items)
    if more > 0:
        items.append(f'<span class="row-sub">…and {_e(more)} more</span>')
    return _ul(items, empty)


def _sec_today(inv: Inventory) -> str:
    today = inv.today or {}
    done = today.get("done", [])
    required = today.get("requires_action", [])
    head = _kv([
        ("date", _e(today.get("date", "—"))),
        ("completed today", _e(f"{len(done)} item(s) · {today.get('cron_runs', 0)} cron lane(s) ran")),
        ("requires action", _e(f"{len(required)} item(s)")),
    ])
    inner = head
    inner += '<h3 class="subhead">Done today</h3>' + _today_rows(done, "no completed work detected for today")
    inner += '<h3 class="subhead">Needs Bernado / approval</h3>' + _today_rows(required, "nothing waiting on you")
    return _section("2 · Daybook", inner)


def _sec_health(inv: Inventory) -> str:
    items = []
    for c in inv.health:
        items.append(
            f'<span class="row-title">{_e(c.name)}</span>{_pill(c.status)}'
            f'<span class="row-sub">{_e(c.detail)}</span>'
        )
    inner = _ul(items, "no health checks ran")
    bars = ""
    for d in inv.disks:
        if d.used_pct is None:
            continue
        hot = " hot" if d.warn else ""
        bars += (
            f'<div class="kv"><span class="k">{_e(d.path)}</span>'
            f'<span class="v">{d.used_pct}% of {d.total_gb} GB</span></div>'
            f'<div class="bar{hot}"><b style="width:{min(d.used_pct,100)}%"></b></div>'
        )
    return _section("3 · Health", inner + bars)


def _sec_cron(inv: Inventory) -> str:
    items = []
    for j in inv.cron.get("jobs", []):
        status = j.last_status or "unknown"
        pill = _pill("ok" if status == "ok" else "risk" if status == "error" else "unknown")
        enabled = "" if j.enabled is not False else ' <span class="pill dim">disabled</span>'
        sub_bits = []
        if j.schedule:
            sub_bits.append(f"sched {j.schedule}")
        if j.next_run:
            sub_bits.append(f"next {j.next_run}")
        if j.last_run:
            sub_bits.append(f"last {j.last_run}")
        if j.delivery:
            sub_bits.append(f"→ {j.delivery}")
        items.append(
            f'<span class="row-title">{_e(j.name)}</span>{pill}{enabled}'
            f'<span class="row-sub">{_e(" · ".join(sub_bits))}</span>'
        )
    counts = inv.cron.get("counts", {})
    head = _kv([
        ("scheduler", {True: "running" + _pill("ok"), False: "stopped" + _pill("risk")}.get(
            inv.cron.get("scheduler_running"), "unknown" + _pill("unknown"))),
        ("jobs", _e(f"{counts.get('enabled', 0)} enabled / {counts.get('total', 0)} total, {counts.get('failing', 0)} failing")),
    ])
    return _section("4 · Cron jobs", head + _ul(items, "no jobs found"))


def _sec_profiles(inv: Inventory) -> str:
    items = []
    for p in inv.profiles:
        active = ' <span class="pill ok">active</span>' if p.is_active else ""
        gw = f' <span class="pill warn">gateway</span>' if p.gateway else ""
        sub_bits = [b for b in (p.model, p.alias and f"alias {p.alias}", p.description) if b]
        items.append(
            f'<span class="row-title">{_e(p.name)}</span>{active}{gw}'
            f'<span class="row-sub">{_e(" · ".join(sub_bits))}</span>'
        )
    return _section("5 · Profiles", _ul(items, "no profiles detected"))


def _sec_approvals(inv: Inventory) -> str:
    counts = inv.approvals.get("counts", {})
    head = _kv([
        ("pending", _e(counts.get("pending", 0))),
        ("approved / done", _e(f"{counts.get('approved', 0)} / {counts.get('done', 0)}")),
    ])
    items = []
    for a in inv.approvals.get("pending", []):
        risk = a.get("risk_level", "medium")
        pill = _pill("risk" if risk == "high" else "warn" if risk == "medium" else "ok")
        items.append(
            f'<span class="row-title">{_e(a.get("title", ""))}</span>{pill}'
            f'<span class="row-sub">{_e(a.get("kind", ""))} · {_e(a.get("id", ""))} · {_e(a.get("detail", "")[:120])}</span>'
        )
    return _section("6 · Approvals", head + _ul(items, "queue is empty"))


def _sec_wiki(inv: Inventory) -> str:
    w = inv.wiki
    if w is None or not w.exists:
        return _section("7 · LLM-Wiki", f'<p class="empty">vault not reachable at {_e(w.root if w else "?")}</p>')
    hb = "—"
    if w.heartbeat_age_hours is not None:
        hb = f"{w.heartbeat_age_hours}h ago" + (_pill("warn") if w.heartbeat_stale else _pill("ok"))
    pairs = [
        ("notes", _e(w.note_count if w.note_count is not None else "—")),
        ("queue", _e(f"{w.queue_open} open / {w.queue_total} total" if w.queue_total is not None else "—")),
        ("heartbeat", hb),
    ]
    if w.lint_status:
        pairs.append(("lint/audit", _e(w.lint_status)))
    log_items = [f'<span class="row-sub">{_e(entry)}</span>' for entry in w.recent_log]
    return _section("7 · LLM-Wiki", _kv(pairs) + _ul(log_items, "no recent log entries"))


def _sec_skills(inv: Inventory) -> str:
    lanes = inv.skills.get("cron_lanes", {})
    items = []
    for lane, jobs in sorted(lanes.items()):
        items.append(
            f'<span class="row-title">{_e(lane)}</span>'
            f'<span class="row-sub">{_e(", ".join(jobs[:6]))}</span>'
        )
    promo = inv.skills.get("promotion_candidates", [])
    promo_html = ""
    if promo:
        promo_html = _kv([("promotion candidates", _e("; ".join(promo[:5])))])
    tools = inv.skills.get("tools", [])
    tools_html = _kv([("tools", _e(", ".join(tools[:20]) if tools else "—"))])
    return _section("8 · Skills / Automations", _ul(items, "no automation lanes detected") + promo_html + tools_html)


def _sec_projects(inv: Inventory) -> str:
    items = []
    for lane, data in sorted(inv.projects.items()):
        profs = ", ".join(data.get("profiles", [])) or "—"
        jobs = len(data.get("jobs", []))
        items.append(
            f'<span class="row-title">{_e(lane)}</span>'
            f'<span class="row-sub">profiles: {_e(profs)} · cron jobs: {jobs}</span>'
        )
    return _section("9 · Projects", _ul(items, "no project lanes detected"))


def _sec_risks(inv: Inventory) -> str:
    items = []
    for r in inv.risks:
        items.append(f"{_pill(r.level)} {_e(r.message)}")
    return _section("10 · Risks", _ul(items, "none detected"))


def _sec_actions(inv: Inventory) -> str:
    items = [_e(a) for a in inv.next_actions]
    return _section("11 · Next actions", _ul(items, "nothing suggested"))


def _lamps(inv: Inventory) -> str:
    gw = inv.gateway.get("running")
    gw_cls = "ok" if gw else ("risk" if gw is False else "")
    cron = inv.cron.get("scheduler_running")
    cron_cls = "ok" if cron else ("risk" if cron is False else "")
    has_risk = any(r.level == "risk" for r in inv.risks)
    has_warn = any(r.level == "warn" for r in inv.risks)
    risk_cls = "risk" if has_risk else ("warn" if has_warn else "ok")
    return (
        f'<span class="lamp {gw_cls}"><i></i>gateway</span>'
        f'<span class="lamp {cron_cls}"><i></i>cron</span>'
        f'<span class="lamp {risk_cls}"><i></i>risks</span>'
    )


def render_dashboard(inv: Inventory, template_path: Optional[Path] = None) -> str:
    template = _DEFAULT_TEMPLATE
    if template_path and template_path.exists():
        try:
            template = template_path.read_text(encoding="utf-8")
        except OSError:
            template = _DEFAULT_TEMPLATE
    sections = "\n".join(
        fn(inv)
        for fn in (
            _sec_now,
            _sec_today,
            _sec_health,
            _sec_cron,
            _sec_profiles,
            _sec_approvals,
            _sec_wiki,
            _sec_skills,
            _sec_projects,
            _sec_risks,
            _sec_actions,
        )
    )
    return (
        template.replace("{{GENERATED_AT}}", _e(inv.generated_at))
        .replace("{{LAMPS}}", _lamps(inv))
        .replace("{{SECTIONS}}", sections)
        .replace("{{VERSION}}", _e(__version__))
    )


def write_dashboard(inv: Inventory, out_path: Path, template_path: Optional[Path] = None) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_dashboard(inv, template_path), encoding="utf-8")
    return out_path
