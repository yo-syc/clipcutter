"""Creator tracker: watch a list of creators, clip every new stream/video automatically.

creators.yaml is the list (easy to edit/share). State (what's been seen/clipped) lives in SQLite.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .ingest import _ydl_opts

CREATORS_FILE = Path("creators.yaml")


# ---------- creators list ----------

def load_creators() -> list[dict]:
    if not CREATORS_FILE.exists():
        return []
    return (yaml.safe_load(CREATORS_FILE.read_text()) or {}).get("creators") or []


def save_creators(creators: list[dict]) -> None:
    CREATORS_FILE.write_text(
        "# Creators to track. permission: true = you're allowed to post clips of them\n"
        "# (e.g. their official clipper program). keyword: only clip videos whose title matches.\n"
        + yaml.safe_dump({"creators": creators}, sort_keys=False, allow_unicode=True)
    )


def platform(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for name in ("youtube", "twitch", "kick", "tiktok", "facebook", "instagram", "x.com", "twitter", "rumble"):
        if name in host:
            return name.replace(".com", "")
    return host or "web"


def feeds(url: str) -> list[str]:
    """Which listing pages to check for a creator URL."""
    u = url.rstrip("/")
    p = platform(u)
    if p == "youtube" and re.search(r"youtube\.com/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)$", u):
        return [u + "/streams", u + "/videos"]
    if p == "twitch" and re.fullmatch(r"https?://(www\.)?twitch\.tv/[^/]+", u):
        return [u + "/videos?filter=archives&sort=time"]
    return [u]


def add(url: str, name: str | None, keyword: str | None, permission: bool) -> dict:
    creators = load_creators()
    if any(c["url"].rstrip("/") == url.rstrip("/") for c in creators):
        raise SystemExit(f"already tracking {url}")
    if not name:
        name = _channel_name(url)
    c = {"name": name, "url": url, "platform": platform(url), "permission": permission}
    if keyword:
        c["keyword"] = keyword
    creators.append(c)
    save_creators(creators)
    return c


def remove(name_or_url: str) -> bool:
    creators = load_creators()
    keep = [c for c in creators if name_or_url not in (c["name"], c["url"])]
    save_creators(keep)
    return len(keep) != len(creators)


def _channel_name(url: str) -> str:
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(_ydl_opts(extract_flat="in_playlist", playlistend=1)) as ydl:
            info = ydl.extract_info(feeds(url)[0], download=False)
        return info.get("channel") or info.get("uploader") or info.get("title") or url
    except Exception:
        return urlparse(url).path.strip("/").split("/")[0].lstrip("@") or url


# ---------- state ----------

def db(cfg: dict) -> sqlite3.Connection:
    path = Path(cfg["work_dir"]) / "tracker.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS videos (
        key TEXT PRIMARY KEY, creator TEXT, url TEXT, title TEXT, duration REAL,
        status TEXT, out_dir TEXT, clips INTEGER DEFAULT 0, error TEXT,
        first_seen REAL, updated REAL)""")
    con.execute("CREATE TABLE IF NOT EXISTS checks (creator TEXT PRIMARY KEY, at REAL, error TEXT)")
    return con


def _latest(feed: str, n: int) -> list[dict]:
    import yt_dlp
    with yt_dlp.YoutubeDL(_ydl_opts(extract_flat="in_playlist", playlistend=n)) as ydl:
        info = ydl.extract_info(feed, download=False)
    entries = info.get("entries") or ([info] if info.get("id") else [])
    return [e for e in entries if e and e.get("id")][:n]


def check(cfg: dict, con: sqlite3.Connection, creator: dict, backfill: int, log) -> int:
    """Look for new videos from one creator. Returns how many were queued."""
    name = creator["name"]
    first_time = con.execute("SELECT COUNT(*) FROM videos WHERE creator=?", (name,)).fetchone()[0] == 0
    kw = creator.get("keyword")
    entries: list[dict] = []
    err = None
    for feed in feeds(creator["url"]):
        try:
            entries += _latest(feed, 6)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:300]
    con.execute("INSERT OR REPLACE INTO checks VALUES (?,?,?)", (name, time.time(), err if not entries else None))
    queued = 0
    fresh = 0
    for e in entries:
        key = f"{e.get('ie_key') or platform(creator['url'])}:{e['id']}"
        if con.execute("SELECT 1 FROM videos WHERE key=?", (key,)).fetchone():
            continue
        live = e.get("live_status") in ("is_live", "is_upcoming") or e.get("is_live")
        if live:
            continue  # try again when the VOD is up
        url = e.get("url") or e.get("webpage_url")
        if url and not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={e['id']}"
        title = e.get("title") or ""
        dur = e.get("duration") or 0
        status = "new"
        if dur and dur < 120:
            status = "skipped"      # shorts / tiny clips
        elif kw and not re.search(kw, title, re.I):
            status = "skipped"
        elif first_time and fresh >= backfill:
            status = "skipped"      # don't clip a creator's whole back catalogue on day one
        if status == "new":
            fresh += 1
            queued += 1
        con.execute("INSERT INTO videos (key, creator, url, title, duration, status, first_seen, updated) "
                    "VALUES (?,?,?,?,?,?,?,?)", (key, name, url, title, dur, status, time.time(), time.time()))
    con.commit()
    if err and not entries:
        log(f"   ! {name}: couldn't list videos ({err[:120]})")
    return queued


def process(cfg: dict, con: sqlite3.Connection, log, limit: int | None = None) -> int:
    from . import pipeline

    rows = con.execute("SELECT * FROM videos WHERE status='new' ORDER BY first_seen").fetchall()
    done = 0
    for r in rows[:limit] if limit else rows:
        log(f"clipping [{r['creator']}] {r['title'][:70]}")
        con.execute("UPDATE videos SET status='processing', updated=? WHERE key=?", (time.time(), r["key"]))
        con.commit()
        try:
            out_dir, index = pipeline.run(r["url"], cfg, out_sub=_slug(r["creator"]))
            con.execute("UPDATE videos SET status='done', out_dir=?, clips=?, error=NULL, updated=? WHERE key=?",
                        (str(out_dir), len(index), time.time(), r["key"]))
            done += 1
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            status = "new" if "still live" in msg else "failed"
            log(f"   ! failed: {msg[:200]}")
            (Path(cfg["work_dir"]) / "errors.log").open("a").write(f"{r['url']}\n{traceback.format_exc()}\n")
            con.execute("UPDATE videos SET status=?, error=?, updated=? WHERE key=?",
                        (status, msg[:500], time.time(), r["key"]))
        con.commit()
    return done


def run(cfg: dict, backfill: int = 1, every: float | None = None, limit: int | None = None, log=print) -> None:
    from . import dashboard

    creators = load_creators()
    if not creators:
        raise SystemExit("no creators yet. add one:  clipcutter add <channel url>")
    con = db(cfg)
    while True:
        log(f"checking {len(creators)} creators")
        for c in creators:
            n = check(cfg, con, c, backfill, log)
            if n:
                log(f"   {c['name']}: {n} new")
        process(cfg, con, log, limit)
        page = dashboard.build(cfg, con, creators)
        log(f"dashboard: {page}")
        if not every:
            break
        log(f"next check in {every:g} min (ctrl+c to stop)")
        time.sleep(every * 60)
        creators = load_creators()  # pick up edits while running


def retry_failed(cfg: dict) -> int:
    con = db(cfg)
    n = con.execute("UPDATE videos SET status='new', error=NULL WHERE status='failed'").rowcount
    con.commit()
    return n


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")[:40] or "creator"


# ---------- discovery ----------

def discover(query: str, limit: int = 50) -> list[dict]:
    """Search YouTube and rank the channels that show up by total views."""
    import yt_dlp
    with yt_dlp.YoutubeDL(_ydl_opts(extract_flat="in_playlist")) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    chans: dict[str, dict] = {}
    for e in info.get("entries") or []:
        url = e.get("channel_url") or e.get("uploader_url")
        if not url:
            continue
        c = chans.setdefault(url, {"name": e.get("channel") or e.get("uploader") or url, "url": url,
                                   "videos": 0, "views": 0, "top_title": e.get("title", "")})
        c["videos"] += 1
        c["views"] += e.get("view_count") or 0
    return sorted(chans.values(), key=lambda c: -c["views"])


def summary(cfg: dict) -> list[dict]:
    con = db(cfg)
    out = []
    for c in load_creators():
        stats = {s: 0 for s in ("new", "processing", "done", "failed", "skipped")}
        for r in con.execute("SELECT status, COUNT(*) n FROM videos WHERE creator=? GROUP BY status", (c["name"],)):
            stats[r["status"]] = r["n"]
        clips = con.execute("SELECT COALESCE(SUM(clips),0) FROM videos WHERE creator=?", (c["name"],)).fetchone()[0]
        out.append({**c, **stats, "clips": clips})
    return out


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
