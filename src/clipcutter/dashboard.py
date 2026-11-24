"""A local HTML dashboard: creators, their videos, and every clip ready to post."""
from __future__ import annotations

import html
import json
import os
import sqlite3
import time
from pathlib import Path

CSS = """
:root{--bg:#0b0b10;--card:#15151d;--line:#262633;--txt:#ececf1;--mut:#8b8b9a;--acc:#c8ff2e;--bad:#ff5470;--warn:#ffb020}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{padding:28px 24px 8px;max-width:1280px;margin:auto}h1{margin:0;font-size:28px;letter-spacing:-.5px}h1 span{color:var(--acc)}
.sub{color:var(--mut)}main{max-width:1280px;margin:auto;padding:8px 24px 60px}
h2{font-size:16px;margin:28px 0 12px;color:var(--mut);text-transform:uppercase;letter-spacing:1px}
.stats{display:flex;gap:12px;flex-wrap:wrap;margin-top:16px}.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;min-width:120px}
.stat b{display:block;font-size:24px}.stat small{color:var(--mut)}
.creators{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.cr{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}.cr a{color:var(--txt);text-decoration:none;font-weight:600}
.pill{display:inline-block;font-size:11px;padding:2px 8px;border-radius:99px;border:1px solid var(--line);color:var(--mut);margin-right:4px}
.ok{color:var(--acc);border-color:var(--acc)}.no{color:var(--warn);border-color:var(--warn)}.err{color:var(--bad);border-color:var(--bad)}
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:12px;overflow:hidden}td,th{padding:9px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:500;font-size:12px}td a{color:var(--txt)}
.clips{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:16px}
.clip{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden;display:flex;flex-direction:column}
.clip video{width:100%;aspect-ratio:9/16;background:#000;display:block}.clip .b{padding:10px 12px;display:flex;flex-direction:column;gap:6px}
.score{font-weight:800;color:var(--acc)}.cap{color:var(--mut);font-size:12px;word-break:break-word}
button{background:var(--acc);color:#000;border:0;border-radius:8px;padding:6px 10px;font-weight:700;cursor:pointer}
.empty{color:var(--mut);padding:20px;border:1px dashed var(--line);border-radius:12px}
@media(max-width:600px){header,main{padding-left:16px;padding-right:16px}td:nth-child(4),th:nth-child(4){display:none}}
"""

JS = """
document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>{navigator.clipboard.writeText(b.dataset.copy);b.textContent='copied ✓';setTimeout(()=>b.textContent='copy caption',1200)});
"""


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _ago(ts: float | None) -> str:
    if not ts:
        return "never"
    s = int(time.time() - ts)
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= n:
            return f"{s // n}{unit} ago"
    return "just now"


def build(cfg: dict, con: sqlite3.Connection, creators: list[dict]) -> Path:
    out_root = Path(cfg["output_dir"])
    out_root.mkdir(parents=True, exist_ok=True)
    page = out_root / "dashboard.html"
    videos = con.execute("SELECT * FROM videos ORDER BY first_seen DESC").fetchall()
    checks = {r["creator"]: r for r in con.execute("SELECT * FROM checks")}

    clips = []
    for v in videos:
        if v["status"] != "done" or not v["out_dir"]:
            continue
        idx = Path(v["out_dir"]) / "index.json"
        if idx.exists():
            for c in json.loads(idx.read_text()):
                c["_path"] = os.path.relpath(Path(v["out_dir"]) / c["file"], out_root)
                c["_creator"] = v["creator"]
                c["_video"] = v["title"]
                clips.append(c)
    clips.sort(key=lambda c: -(c.get("virality") or 0))

    n_clips = len(clips)
    n_done = sum(1 for v in videos if v["status"] == "done")
    n_queue = sum(1 for v in videos if v["status"] in ("new", "processing"))
    n_fail = sum(1 for v in videos if v["status"] == "failed")

    cr_html = []
    for c in creators:
        ck = checks.get(c["name"])
        mine = [v for v in videos if v["creator"] == c["name"]]
        perm = '<span class="pill ok">permission ✓</span>' if c.get("permission") else '<span class="pill no">no permission yet</span>'
        err = f'<span class="pill err">check failed</span>' if ck and ck["error"] else ""
        cr_html.append(
            f'<div class="cr"><a href="{_e(c["url"])}" target="_blank">{_e(c["name"])}</a><br>'
            f'<span class="pill">{_e(c.get("platform", ""))}</span>{perm}{err}'
            f'<div class="sub" style="margin-top:6px">{sum(1 for v in mine if v["status"] == "done")} clipped · '
            f'{sum(v["clips"] or 0 for v in mine)} clips · checked {_ago(ck["at"] if ck else None)}</div></div>'
        )

    rows = []
    for v in videos[:60]:
        if v["status"] == "skipped":
            continue
        cls = {"done": "ok", "failed": "err", "new": "", "processing": "no"}.get(v["status"], "")
        dur = f'{int(v["duration"] or 0) // 3600}h{int(v["duration"] or 0) % 3600 // 60:02d}m' if v["duration"] else ""
        rows.append(
            f'<tr><td><span class="pill {cls}">{_e(v["status"])}</span></td><td>{_e(v["creator"])}</td>'
            f'<td><a href="{_e(v["url"])}" target="_blank">{_e(v["title"])}</a>'
            f'{"<div class=cap>" + _e(v["error"]) + "</div>" if v["error"] else ""}</td>'
            f'<td>{dur}</td><td>{v["clips"] or ""}</td><td class="sub">{_ago(v["updated"])}</td></tr>'
        )

    clip_html = []
    for c in clips:
        cap = c.get("post_caption", "")
        clip_html.append(
            f'<div class="clip"><video src="{_e(c["_path"])}" controls preload="metadata" playsinline></video>'
            f'<div class="b"><div><span class="score">{c.get("virality", "–")}</span> <span class="sub">virality · {_e(c["_creator"])}</span></div>'
            f'<b>{_e(c.get("hook", ""))}</b><div class="cap">{_e(cap)}</div>'
            f'<div><button data-copy="{_e(cap)}">copy caption</button> '
            f'<a class="sub" href="{_e(c["_path"])}" download>download</a></div></div></div>'
        )

    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ClipCutter Tracker</title>
<style>{CSS}</style></head><body>
<header><h1>clip<span>cutter</span> tracker</h1><div class="sub">updated {time.strftime('%d %b %Y, %H:%M')}</div>
<div class="stats"><div class="stat"><b>{len(creators)}</b><small>creators</small></div>
<div class="stat"><b>{n_done}</b><small>videos clipped</small></div><div class="stat"><b>{n_clips}</b><small>clips ready</small></div>
<div class="stat"><b>{n_queue}</b><small>in queue</small></div><div class="stat"><b>{n_fail}</b><small>failed</small></div></div></header>
<main>
<h2>Best clips (highest virality first)</h2>
{'<div class="clips">' + ''.join(clip_html) + '</div>' if clip_html else '<div class="empty">no clips yet: run <code>clipcutter track</code></div>'}
<h2>Creators</h2><div class="creators">{''.join(cr_html) or '<div class="empty">add one: clipcutter add &lt;channel url&gt;</div>'}</div>
<h2>Videos</h2><table><tr><th>status</th><th>creator</th><th>video</th><th>length</th><th>clips</th><th>updated</th></tr>{''.join(rows)}</table>
</main><script>{JS}</script></body></html>"""
    page.write_text(body)
    return page.resolve()
