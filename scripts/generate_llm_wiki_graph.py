#!/usr/bin/env python3
"""Generate a standalone local HTML graph for the LLM-Wiki vault.

Reads markdown wikilinks from the vault and writes a self-contained Canvas graph
with inline JavaScript. No network requests, no external assets, and no wiki edits.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

WIKILINK_RE = re.compile(r"!?\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
DEFAULT_SKIP_PARTS = {".obsidian", ".trash", ".git", "node_modules", "__pycache__"}


def iter_notes(root: Path):
    for p in root.rglob("*.md"):
        rel = p.relative_to(root)
        if any(part in DEFAULT_SKIP_PARTS for part in rel.parts):
            continue
        yield p


def norm_no_ext(rel: Path) -> str:
    return rel.as_posix()[:-3] if rel.as_posix().endswith(".md") else rel.as_posix()


def folder_group(note_id: str) -> str:
    first = note_id.split("/", 1)[0]
    if first in {"concepts", "entities", "comparisons", "projects", "books", "queries", "inbox", "raw", "_meta", "templates", "scripts"}:
        return first
    if "/" not in note_id:
        return "root"
    return first


def title_from_text(text: str, fallback: str) -> str:
    for line in text.splitlines()[:80]:
        if line.startswith("title:"):
            val = line.split(":", 1)[1].strip().strip('"\'')
            if val:
                return val[:120]
        if line.startswith("# "):
            return line[2:].strip()[:120]
    return fallback.rsplit("/", 1)[-1]


def build_graph(root: Path):
    paths = list(iter_notes(root))
    rel_ids = {norm_no_ext(p.relative_to(root)): p for p in paths}
    by_stem: dict[str, list[str]] = defaultdict(list)
    by_lower: dict[str, list[str]] = defaultdict(list)
    for nid in rel_ids:
        stem = nid.rsplit("/", 1)[-1]
        by_stem[stem.lower()].append(nid)
        by_lower[nid.lower()].append(nid)

    def resolve(raw: str) -> str | None:
        target = raw.strip().replace("\\", "/")
        if not target or target.startswith(("http://", "https://", "mailto:")):
            return None
        if target.endswith(".md"):
            target = target[:-3]
        # exact path, case-sensitive then lower-case fallback
        if target in rel_ids:
            return target
        low = target.lower()
        if low in by_lower and len(by_lower[low]) == 1:
            return by_lower[low][0]
        # bare note name
        stem = target.rsplit("/", 1)[-1].lower()
        if stem in by_stem and len(by_stem[stem]) == 1:
            return by_stem[stem][0]
        # suffix path match, e.g. [[folder/name]] from another folder
        matches = [nid for nid in rel_ids if nid.lower().endswith("/" + low)]
        if len(matches) == 1:
            return matches[0]
        return None

    nodes = []
    edges_set = set()
    unresolved = Counter()
    inbound = Counter()
    outbound = Counter()
    titles = {}

    for nid, p in rel_ids.items():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        titles[nid] = title_from_text(text, nid)
        for raw in WIKILINK_RE.findall(text):
            target = resolve(raw)
            if target and target != nid:
                edges_set.add((nid, target))
                outbound[nid] += 1
                inbound[target] += 1
            elif raw.strip():
                unresolved[raw.strip()] += 1

    edge_list = sorted(edges_set)
    degree = Counter()
    for a, b in edge_list:
        degree[a] += 1
        degree[b] += 1

    for nid in sorted(rel_ids):
        group = folder_group(nid)
        obsidian_uri = "obsidian://open?vault=LLM-Wiki&file=" + quote(nid + ".md", safe="")
        nodes.append(
            {
                "id": nid,
                "title": titles.get(nid, nid),
                "group": group,
                "degree": degree[nid],
                "in": inbound[nid],
                "out": outbound[nid],
                "uri": obsidian_uri,
            }
        )

    id_index = {n["id"]: i for i, n in enumerate(nodes)}
    links = [
        {"source": id_index[a], "target": id_index[b]}
        for a, b in edge_list
        if a in id_index and b in id_index
    ]
    groups = Counter(n["group"] for n in nodes)
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "vault": str(root),
        "nodes": nodes,
        "links": links,
        "groups": dict(sorted(groups.items())),
        "unresolved_count": sum(unresolved.values()),
        "top_unresolved": unresolved.most_common(20),
    }


def render_html(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    stats = f"{len(data['nodes'])} notes · {len(data['links'])} links · {data['unresolved_count']} unresolved wikilinks"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>LLM-Wiki Graph // Hermes Android Agentic OS</title>
<style>
:root{{--bg:#120d08;--panel:#1c1510;--line:#3a2a1a;--text:#e9dcc3;--dim:#9a8768;--amber:#ffb454;--ok:#8fd68f;--risk:#ff6b57;}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:13px/1.45 ui-monospace,Menlo,Consolas,monospace;overflow:hidden}}
header{{position:fixed;top:0;left:0;right:0;z-index:2;background:rgba(18,13,8,.96);border-bottom:1px solid var(--line);padding:10px 12px}}
h1{{font-size:14px;color:var(--amber);letter-spacing:.12em;text-transform:uppercase;margin:0 0 8px}}
.controls{{display:grid;grid-template-columns:1fr auto auto;gap:8px;align-items:center}}
input,select,button{{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:7px;font:inherit;min-width:0}}
button{{color:var(--amber)}}
#stats{{color:var(--dim);font-size:11px;margin-top:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
#graph{{display:block;width:100vw;height:100vh}}
#side{{position:fixed;right:10px;top:108px;width:min(380px,calc(100vw - 20px));max-height:calc(100vh - 120px);overflow:auto;background:rgba(28,21,16,.94);border:1px solid var(--line);border-radius:8px;padding:12px;z-index:3;display:none}}
#side h2{{font-size:13px;color:var(--amber);margin:0 0 8px}} #side p{{margin:6px 0;color:var(--dim)}} #side a{{color:var(--amber)}}
.legend{{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}} .chip{{border:1px solid var(--line);border-radius:999px;padding:2px 7px;color:var(--dim);font-size:11px}}
</style>
</head>
<body>
<header>
  <h1>LLM-Wiki graph <span style="color:var(--dim)">// Hermes Android Agentic OS</span></h1>
  <div class="controls">
    <input id="q" placeholder="Search notes…" autocomplete="off">
    <select id="group"><option value="all">all folders</option></select>
    <button id="reset">reset</button>
  </div>
  <div id="stats">{html.escape(stats)} · generated {html.escape(data['generated_at'])}</div>
</header>
<canvas id="graph"></canvas>
<aside id="side"></aside>
<script>
const DATA = {payload};
const canvas = document.getElementById('graph'), ctx = canvas.getContext('2d');
const q = document.getElementById('q'), groupSel = document.getElementById('group'), side = document.getElementById('side');
const colors = {{root:'#ffb454', concepts:'#7F77DD', entities:'#1D9E75', comparisons:'#D85A30', projects:'#378ADD', books:'#D4537E', queries:'#BA7517', inbox:'#888780', raw:'#5F5E5A', _meta:'#8fd68f', scripts:'#ff6b57', templates:'#9a8768'}};
let W=0,H=0, zoom=1, panX=0, panY=0, dragging=false, lastX=0, lastY=0, selected=null, tick=0;
const nodes = DATA.nodes.map((n,i)=>Object.assign({{}}, n, {{i, x:Math.random()*1200-600, y:Math.random()*900-450, vx:0, vy:0}}));
const links = DATA.links.map(l=>({{s:nodes[l.source], t:nodes[l.target]}}));
for (const g of Object.keys(DATA.groups).sort()) {{ const o=document.createElement('option'); o.value=g; o.textContent=`${{g}} (${{DATA.groups[g]}})`; groupSel.appendChild(o); }}
function resize(){{ W=canvas.width=innerWidth*devicePixelRatio; H=canvas.height=innerHeight*devicePixelRatio; canvas.style.width=innerWidth+'px'; canvas.style.height=innerHeight+'px'; ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0); }}
addEventListener('resize', resize); resize();
function visible(n){{ const s=q.value.toLowerCase().trim(); return (groupSel.value==='all'||n.group===groupSel.value) && (!s||n.id.toLowerCase().includes(s)||n.title.toLowerCase().includes(s)); }}
function step(){{
  tick++;
  const vis = nodes.filter(visible); const visSet = new Set(vis);
  for (const n of vis) {{ n.vx += -n.x*0.0007; n.vy += -n.y*0.0007; }}
  for (const l of links) if (visSet.has(l.s)&&visSet.has(l.t)) {{
    const dx=l.t.x-l.s.x, dy=l.t.y-l.s.y, d=Math.hypot(dx,dy)||1, want=42+Math.min(70,(l.s.degree+l.t.degree));
    const f=(d-want)*0.0009; const fx=dx/d*f, fy=dy/d*f; l.s.vx+=fx; l.s.vy+=fy; l.t.vx-=fx; l.t.vy-=fy;
  }}
  for (let a=0; a<vis.length; a++) for (let b=a+1; b<Math.min(vis.length,a+70); b++) {{
    const n=vis[a], m=vis[(a+b)%vis.length]; const dx=n.x-m.x, dy=n.y-m.y, d2=dx*dx+dy*dy+0.01; if (d2<3600) {{ const f=18/d2; n.vx+=dx*f; n.vy+=dy*f; m.vx-=dx*f; m.vy-=dy*f; }}
  }}
  for (const n of vis) {{ n.vx*=0.88; n.vy*=0.88; n.x+=n.vx; n.y+=n.vy; }}
}}
function draw(){{
  for(let i=0;i<3 && tick<900;i++) step();
  ctx.save(); ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0); ctx.clearRect(0,0,innerWidth,innerHeight); ctx.translate(innerWidth/2+panX, innerHeight/2+panY); ctx.scale(zoom, zoom);
  const visSet = new Set(nodes.filter(visible));
  ctx.lineWidth=0.35/zoom; ctx.strokeStyle='rgba(154,135,104,.28)';
  for (const l of links) if (visSet.has(l.s)&&visSet.has(l.t)) {{ ctx.beginPath(); ctx.moveTo(l.s.x,l.s.y); ctx.lineTo(l.t.x,l.t.y); ctx.stroke(); }}
  for (const n of visSet) {{ const r=Math.max(2.2, Math.min(8, 2.2+Math.sqrt(n.degree)*0.75)); ctx.beginPath(); ctx.fillStyle=colors[n.group]||'#ffb454'; ctx.globalAlpha=(selected===n?1:.86); ctx.arc(n.x,n.y,r,0,Math.PI*2); ctx.fill(); if(selected===n){{ctx.lineWidth=2/zoom;ctx.strokeStyle='#e9dcc3';ctx.stroke();}} }}
  ctx.globalAlpha=1; ctx.restore(); requestAnimationFrame(draw);
}}
requestAnimationFrame(draw);
function screenToWorld(x,y){{ return {{x:(x-innerWidth/2-panX)/zoom, y:(y-innerHeight/2-panY)/zoom}}; }}
canvas.addEventListener('mousedown', e=>{{dragging=true; lastX=e.clientX; lastY=e.clientY;}});
addEventListener('mouseup', e=>{{dragging=false;}});
canvas.addEventListener('mousemove', e=>{{ if(dragging){{panX+=e.clientX-lastX; panY+=e.clientY-lastY; lastX=e.clientX; lastY=e.clientY;}} }});
canvas.addEventListener('wheel', e=>{{ e.preventDefault(); const z=Math.exp(-e.deltaY*0.001); zoom=Math.max(.12,Math.min(5,zoom*z)); }}, {{passive:false}});
canvas.addEventListener('click', e=>{{
  const p=screenToWorld(e.clientX,e.clientY); let best=null, bd=14/zoom;
  for(const n of nodes) if(visible(n)){{ const d=Math.hypot(n.x-p.x,n.y-p.y); if(d<bd){{bd=d; best=n;}} }}
  selected=best; if(best){{ side.style.display='block'; side.innerHTML=`<h2>${{escapeHtml(best.title)}}</h2><p>${{escapeHtml(best.id)}}</p><p>folder: ${{escapeHtml(best.group)}} · degree: ${{best.degree}} · in: ${{best.in}} · out: ${{best.out}}</p><p><a href="${{best.uri}}">open in Obsidian</a></p>`; }} else {{ side.style.display='none'; }}
}});
function escapeHtml(s){{return String(s).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}}[c]));}}
q.addEventListener('input',()=>{{tick=0;}}); groupSel.addEventListener('change',()=>{{tick=0;}}); document.getElementById('reset').onclick=()=>{{q.value='';groupSel.value='all';zoom=1;panX=panY=0;selected=null;side.style.display='none';tick=0;}};
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="/storage/emulated/0/Documents/LLM-Wiki")
    ap.add_argument("--out", default="/data/data/com.termux/files/home/hermes-android-agentic-os/dist/llm-wiki-graph.html")
    args = ap.parse_args()
    root = Path(args.wiki).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"wiki root not found: {root}")
    data = build_graph(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(data), encoding="utf-8")
    print(json.dumps({"out": str(out), "nodes": len(data["nodes"]), "links": len(data["links"]), "unresolved": data["unresolved_count"], "generated_at": data["generated_at"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
