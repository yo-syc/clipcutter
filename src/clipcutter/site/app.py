"""Website API (FastAPI). Run:  uv run clipcutter site      (workers:  uv run clipcutter site-worker)"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db

STATIC = Path(__file__).with_name("static")
SECURE_COOKIES = os.environ.get("CLIPCUTTER_SECURE_COOKIES", "0") == "1"
SESSION_DAYS = 30
COOKIE = "cc_session"
MAX_MAIN = 56.0   # + ~2.5 s hook = under 59 s: fits Reels, Shorts and TikTok

app = FastAPI(title="ClipCutter", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.on_event("startup")
def _startup() -> None:
    db.init()


# ---------- helpers ----------

def video_key(url: str) -> tuple[str, str]:
    """Allowed platforms only (also blocks SSRF). Returns (key, canonical_url)."""
    try:
        u = urlparse(url.strip())
    except ValueError:
        raise HTTPException(400, "That doesn't look like a link.")
    if u.scheme not in ("http", "https"):
        raise HTTPException(400, "Paste a full link that starts with https://")
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    path = u.path.rstrip("/")
    vid = None
    if host in ("youtube.com", "music.youtube.com"):
        vid = parse_qs(u.query).get("v", [None])[0]
        m = re.match(r"^/(shorts|live|embed)/([\w-]{6,})", path)
        vid = vid or (m.group(2) if m else None)
        if vid:
            return f"youtube_{vid}", f"https://www.youtube.com/watch?v={vid}"
    elif host == "youtu.be":
        vid = path.lstrip("/").split("/")[0]
        if vid:
            return f"youtube_{vid}", f"https://www.youtube.com/watch?v={vid}"
    elif host == "twitch.tv":
        m = re.match(r"^/videos/(\d+)$", path)
        if m:
            return f"twitch_{m.group(1)}", f"https://www.twitch.tv/videos/{m.group(1)}"
    elif host == "kick.com":
        m = re.search(r"/videos?/([0-9a-f-]{20,})$", path)
        if m:
            return f"kick_{m.group(1)}", f"https://kick.com/video/{m.group(1)}"
    raise HTTPException(400, "Paste a YouTube, Twitch (twitch.tv/videos/…) or Kick video link.")


def _hash_pw(pw: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def _check_pw(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        return hmac.compare_digest(_hash_pw(pw, bytes.fromhex(salt)).split("$")[2], h)
    except ValueError:
        return False


_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(key: str, limit: int, window: float) -> None:
    q, now = _hits[key], time.time()
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Too many tries. Please wait a few minutes.")
    q.append(now)


def _client_ip(req: Request) -> str:
    return (req.headers.get("x-forwarded-for") or (req.client.host if req.client else "?")).split(",")[0].strip()


def csrf(req: Request) -> None:
    """State-changing calls must come from our page (custom header can't be sent cross-site without CORS)."""
    if req.headers.get("x-cc") != "1":
        raise HTTPException(403, "Bad request origin.")


def current_user(req: Request):
    token = req.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Please log in.")
    con = db.connect()
    try:
        row = con.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
                          "WHERE s.token=? AND s.expires>?", (token, time.time())).fetchone()
    finally:
        con.close()
    if not row:
        raise HTTPException(401, "Please log in.")
    return row


def _new_session(resp: Response, user_id: int) -> None:
    token = secrets.token_urlsafe(32)
    con = db.connect()
    con.execute("INSERT INTO sessions VALUES (?,?,?,?)", (token, user_id, time.time(), time.time() + SESSION_DAYS * 86400))
    con.close()
    resp.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                    secure=SECURE_COOKIES, path="/")


def _video_dir(key: str) -> Path:
    return db.DATA / "videos" / key


def _analysis(key: str) -> dict | None:
    p = _video_dir(key) / "analysis.json"
    return json.loads(p.read_text()) if p.exists() else None


def _me(con, user) -> dict:
    plan = db.plan_of(user)
    return {"email": user["email"], "plan": plan, "used": db.clips_used(con, user["id"]),
            "plan_until": user["plan_until"]}


# ---------- pages ----------

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def sw():
    return FileResponse(STATIC / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/share")
def share(url: str = "", text: str = ""):
    """PWA share target: YouTube app → Share → ClipCutter."""
    link = url or next(iter(re.findall(r"https?://\S+", text)), "")
    return RedirectResponse(f"/#new={link}", status_code=303)


@app.get("/legal/{page}")
def legal_page(page: str):
    from fastapi.responses import HTMLResponse
    from . import legal
    body = legal.render(page)
    if body is None:
        raise HTTPException(404, "Not found.")
    return HTMLResponse(body)


@app.get("/healthz")
def health():
    return {"ok": True}


# ---------- auth ----------

class Creds(BaseModel):
    email: str
    password: str


@app.post("/api/signup", dependencies=[Depends(csrf)])
def signup(c: Creds, req: Request):
    rate_limit("signup:" + _client_ip(req), 5, 3600)
    email = c.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "Enter a valid email.")
    if len(c.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    con = db.connect()
    try:
        cur = con.execute("INSERT INTO users (email, pw_hash, created) VALUES (?,?,?)",
                          (email, _hash_pw(c.password), time.time()))
    except Exception:
        raise HTTPException(400, "An account with this email already exists. Log in instead.")
    finally:
        con.close()
    resp = JSONResponse({"ok": True})
    _new_session(resp, cur.lastrowid)
    return resp


@app.post("/api/login", dependencies=[Depends(csrf)])
def login(c: Creds, req: Request):
    rate_limit("login:" + _client_ip(req), 10, 600)
    con = db.connect()
    user = con.execute("SELECT * FROM users WHERE email=?", (c.email.strip().lower(),)).fetchone()
    con.close()
    if not user or not _check_pw(c.password, user["pw_hash"]):
        raise HTTPException(400, "Wrong email or password.")
    resp = JSONResponse({"ok": True})
    _new_session(resp, user["id"])
    return resp


@app.post("/api/logout", dependencies=[Depends(csrf)])
def logout(req: Request):
    token = req.cookies.get(COOKIE)
    if token:
        con = db.connect()
        con.execute("DELETE FROM sessions WHERE token=?", (token,))
        con.close()
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@app.get("/api/me")
def me(user=Depends(current_user)):
    con = db.connect()
    try:
        return _me(con, user)
    finally:
        con.close()


@app.get("/api/plans")
def plans():
    return db.PLANS


# ---------- videos & moments ----------

class NewVideo(BaseModel):
    url: str


@app.post("/api/videos", dependencies=[Depends(csrf)])
def add_video(v: NewVideo, user=Depends(current_user)):
    rate_limit(f"videos:{user['id']}", 30, 3600)
    key, url = video_key(v.url)
    now = time.time()
    with db.tx() as con:
        row = con.execute("SELECT status FROM videos WHERE key=?", (key,)).fetchone()
        if not row:
            con.execute("INSERT INTO videos (key, url, status, step, created, updated) VALUES (?,?,?,?,?,?)",
                        (key, url, "queued", "Waiting in line…", now, now))
        elif row["status"] in ("failed", "expired"):
            con.execute("UPDATE videos SET status='queued', step='Waiting in line…', pct=0, error=NULL, updated=? "
                        "WHERE key=?", (now, key))
        con.execute("INSERT OR IGNORE INTO user_videos VALUES (?,?,?)", (user["id"], key, now))
    return {"key": key}


def _video_public(row, analysis: dict | None) -> dict:
    d = {k: row[k] for k in ("key", "url", "title", "duration", "status", "step", "pct", "error", "enrich")}
    if analysis:
        d.update(title=analysis["title"], uploader=analysis["uploader"], thumbnail=analysis.get("thumbnail"),
                 platform=analysis["platform"], vid=analysis["id"], sources=analysis["sources"])
    return d


@app.get("/api/videos")
def my_videos(user=Depends(current_user)):
    con = db.connect()
    rows = con.execute("SELECT v.* FROM user_videos uv JOIN videos v ON v.key=uv.video_key "
                       "WHERE uv.user_id=? ORDER BY uv.created DESC LIMIT 100", (user["id"],)).fetchall()
    con.close()
    out = []
    for r in rows:
        a = _analysis(r["key"]) if r["status"] == "ready" else None
        d = _video_public(r, a)
        d["moments"] = len(a["moments"]) if a else 0
        out.append(d)
    return out


@app.get("/api/videos/{key}")
def video(key: str, user=Depends(current_user)):
    con = db.connect()
    row = con.execute("SELECT v.* FROM user_videos uv JOIN videos v ON v.key=uv.video_key "
                      "WHERE uv.user_id=? AND v.key=?", (user["id"], key)).fetchone()
    clips = con.execute("SELECT id, moment_id, status, step, pct, error, opts FROM clips WHERE user_id=? AND video_key=?",
                        (user["id"], key)).fetchall()
    con.close()
    if not row:
        raise HTTPException(404, "Not found.")
    a = _analysis(key) if row["status"] == "ready" else None
    d = _video_public(row, a)
    en_words = []
    if a and a.get("subs_en_file") and Path(a["subs_en_file"]).exists():
        from .. import ingest
        en_words = ingest.caption_words(Path(a["subs_en_file"]))
    from ..translit import hinglish

    def texts(m):
        orig = " ".join(w["w"] for w in m["words"])
        return {"text": orig, "text_hinglish": hinglish(orig),
                "text_en": " ".join(w["w"] for w in en_words if m["start"] <= w["s"] < m["end"]) or None}
    d["moments"] = [{**{k: m[k] for k in ("id", "start", "end", "virality", "hook", "title", "transcript",
                                          "post_caption", "signals")}, **texts(m)}
                    for m in (a["moments"] if a else [])]
    d["clips"] = [{**dict(c), "opts": json.loads(c["opts"]) if c["opts"] else None} for c in clips]
    d["has_captions"] = bool(a and a.get("subs_file"))
    d["frames"] = (_video_dir(key) / "frames").is_dir()
    d["facecam"] = (a or {}).get("facecam")
    lang = (a or {}).get("language") or ""
    hindi = lang.startswith("hi") or any("\u0900" <= ch <= "\u097f" for m in (a or {}).get("moments", [])[:3]
                                         for ch in m["transcript"][:200])
    has_en = bool(a and a.get("subs_en_file") and Path(a["subs_en_file"]).exists())
    d["cap_langs"] = (["hinglish", "english", "original"] if hindi else ["original"]) if a else []
    d["english_track"] = has_en   # False: English captions are translated from the clip's audio (AI, ~20 s)
    d["hindi"] = hindi
    return d


class NewClip(BaseModel):
    moment_id: int
    hook: str | None = None          # editor
    text: str | None = None          # corrected captions
    start: float | None = None
    end: float | None = None
    layout: str | None = None        # auto | blur | crop | split
    captions: bool | None = None
    cap_lang: str | None = None      # auto | hinglish | english | original


def _opts(c: NewClip) -> str | None:
    o = {}
    if c.hook is not None:
        o["hook"] = c.hook.strip()[:90]
    if c.text is not None:
        o["text"] = c.text[:4000]
    if c.start is not None and c.end is not None:
        if not (0 <= c.start < c.end) or c.end - c.start > MAX_MAIN or c.end - c.start < 5:
            raise HTTPException(400, f"Clips must be between 5 and {int(MAX_MAIN)} seconds (plus the hook), "
                                     "so they fit Reels, Shorts and TikTok.")
        o["start"], o["end"] = round(c.start, 2), round(c.end, 2)
    if c.layout in ("auto", "blur", "crop", "split", "split_top"):
        o["layout"] = c.layout
    if c.captions is False:
        o["captions"] = False
    if c.cap_lang in ("hinglish", "english", "original"):
        o["cap_lang"] = c.cap_lang
    return json.dumps(o, ensure_ascii=False) if o else None


@app.post("/api/videos/{key}/clips", dependencies=[Depends(csrf)])
def make_clip(key: str, c: NewClip, user=Depends(current_user)):
    a = _analysis(key)
    if not a or not any(m["id"] == c.moment_id for m in a["moments"]):
        raise HTTPException(404, "Moment not found.")
    plan = db.plan_of(user)
    if a["duration"] > plan["max_len"]:
        raise HTTPException(402, f"Videos longer than {plan['max_len'] // 3600} h need a paid plan.")
    now = time.time()
    with db.tx() as con:
        if not con.execute("SELECT 1 FROM user_videos WHERE user_id=? AND video_key=?", (user["id"], key)).fetchone():
            raise HTTPException(404, "Not found.")
        old = con.execute("SELECT id, status FROM clips WHERE user_id=? AND video_key=? AND moment_id=?",
                          (user["id"], key, c.moment_id)).fetchone()
        opts = _opts(c)
        if old and old["status"] in ("queued", "working"):
            raise HTTPException(409, "This clip is already being made. Wait a moment.")
        if old and old["status"] == "done" and opts is None:
            return {"id": old["id"]}
        if old and old["status"] == "done":   # re-make with edits: same credit, no extra charge
            con.execute("UPDATE clips SET status='queued', step='Waiting in line…', pct=0, error=NULL, opts=?, "
                        "updated=? WHERE id=?", (opts, now, old["id"]))
            return {"id": old["id"]}
        if db.clips_used(con, user["id"]) >= plan["clips"]:
            raise HTTPException(402, f"You've used all {plan['clips']} clips this month. Upgrade for more.")
        prio = {"free": 0, "starter": 1, "creator": 2, "pro": 3}[plan["name"]]
        if old:
            con.execute("UPDATE clips SET status='queued', step='Waiting in line…', pct=0, error=NULL, path=NULL, "
                        "watermark=?, priority=?, opts=?, created=?, updated=? WHERE id=?",
                        (int(plan["watermark"]), prio, opts, now, now, old["id"]))
            return {"id": old["id"]}
        cur = con.execute("INSERT INTO clips (user_id, video_key, moment_id, step, watermark, priority, opts, created, "
                          "updated) VALUES (?,?,?,?,?,?,?,?,?)", (user["id"], key, c.moment_id, "Waiting in line…",
                                                                  int(plan["watermark"]), prio, opts, now, now))
        return {"id": cur.lastrowid}


# ---------- live ----------

def live_url(url: str) -> str:
    """Live stream links: twitch.tv/<channel>, kick.com/<channel>, youtube watch / live / youtu.be."""
    try:
        u = urlparse(url.strip())
    except ValueError:
        raise HTTPException(400, "That doesn't look like a link.")
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    path = u.path.rstrip("/")
    if u.scheme in ("http", "https"):
        if host == "twitch.tv" and re.fullmatch(r"/\w{3,25}", path):
            return f"https://www.twitch.tv{path}"
        if host == "kick.com" and re.fullmatch(r"/[\w-]{3,40}", path):
            return f"https://kick.com{path}"
        if host in ("youtube.com", "youtu.be"):
            return video_key(url)[1] if not re.fullmatch(r"/@[\w.-]+(/live)?", path) else f"https://www.youtube.com{path.removesuffix('/live')}/live"
    raise HTTPException(400, "Paste a live link: twitch.tv/<channel>, a YouTube live link, or kick.com/<channel>.")


class NewLive(BaseModel):
    url: str


@app.post("/api/live", dependencies=[Depends(csrf)])
def start_live(v: NewLive, user=Depends(current_user)):
    url = live_url(v.url)
    now = time.time()
    with db.tx() as con:
        if con.execute("SELECT 1 FROM live_sessions WHERE user_id=? AND status IN ('queued','recording')",
                       (user["id"],)).fetchone():
            raise HTTPException(409, "You already have a live session running. Stop it first.")
        if db.clips_used(con, user["id"]) >= db.plan_of(user)["clips"]:
            raise HTTPException(402, "You've used all your clips this month. Upgrade for more.")
        cur = con.execute("INSERT INTO live_sessions (user_id, url, status, step, created, updated) VALUES (?,?,?,?,?,?)",
                          (user["id"], url, "queued", "Connecting to the stream…", now, now))
    return {"id": cur.lastrowid}


@app.get("/api/live")
def my_live(user=Depends(current_user)):
    con = db.connect()
    rows = con.execute("SELECT * FROM live_sessions WHERE user_id=? ORDER BY created DESC LIMIT 20", (user["id"],)).fetchall()
    con.close()
    return [{k: r[k] for k in ("id", "url", "title", "status", "step", "clips", "error", "created", "updated")} for r in rows]


@app.post("/api/live/{sid}/stop", dependencies=[Depends(csrf)])
def stop_live(sid: int, user=Depends(current_user)):
    con = db.connect()
    n = con.execute("UPDATE live_sessions SET stop=1, step='Stopping…', updated=? WHERE id=? AND user_id=? "
                    "AND status IN ('queued','recording')", (time.time(), sid, user["id"])).rowcount
    con.close()
    return {"stopping": bool(n)}


@app.get("/api/clips")
def my_clips(user=Depends(current_user)):
    con = db.connect()
    rows = con.execute("SELECT * FROM clips WHERE user_id=? ORDER BY created DESC LIMIT 200", (user["id"],)).fetchall()
    con.close()
    out, cache = [], {}
    for r in rows:
        meta = json.loads(r["meta"]) if r["meta"] else None   # live clips
        a = None if meta else cache.setdefault(r["video_key"], _analysis(r["video_key"]))
        m = meta or next((x for x in (a or {}).get("moments", []) if x["id"] == r["moment_id"]), {})
        out.append({"id": r["id"], "status": r["status"], "step": r["step"], "pct": r["pct"], "error": r["error"],
                    "live": bool(meta),
                    "video_key": r["video_key"], "video_title": (meta or {}).get("source_title") or (a or {}).get("title"),
                    "hook": m.get("hook"), "recommended": m.get("recommended", True),
                    "post_caption": m.get("post_caption"), "virality": m.get("virality"), "created": r["created"],
                    "file": f"/api/clips/{r['id']}/file" if r["status"] == "done" else None})
    return out


@app.get("/api/clips/{clip_id}/file")
def clip_file(clip_id: int, download: int = 0, user=Depends(current_user)):
    con = db.connect()
    r = con.execute("SELECT * FROM clips WHERE id=? AND user_id=?", (clip_id, user["id"])).fetchone()
    con.close()
    if not r or r["status"] != "done" or not r["path"] or not Path(r["path"]).exists():
        raise HTTPException(404, "Clip not found (clips are kept for 7 days).")
    name = f"clipcutter_{clip_id}.mp4"
    return FileResponse(r["path"], media_type="video/mp4",
                        filename=name if download else None,
                        content_disposition_type="attachment" if download else "inline")


@app.get("/api/videos/{key}/text")
def range_text(key: str, start: float, end: float, lang: str = "auto", user=Depends(current_user)):
    """Caption text for a custom range (editor trims). Only for videos the user added."""
    con = db.connect()
    ok = con.execute("SELECT 1 FROM user_videos WHERE user_id=? AND video_key=?", (user["id"], key)).fetchone()
    con.close()
    a = _analysis(key) if ok else None
    if not a:
        raise HTTPException(404, "Not found.")
    if end - start > 120:
        raise HTTPException(400, "Range too long.")
    from .. import ingest
    sf, ef = a.get("subs_file"), a.get("subs_en_file")
    if lang == "english" and ef and Path(ef).exists():
        sf = ef
    words = ingest.caption_words(Path(sf)) if sf and Path(sf).exists() else \
        [w for m in a["moments"] for w in m["words"]]
    text = " ".join(w["w"] for w in words if start <= w["s"] < end)
    if lang in ("auto", "hinglish") or (lang == "english" and sf != ef):
        from ..translit import hinglish
        text = hinglish(text)
    return {"text": text}


@app.get("/api/videos/{key}/frame/{moment_id}.jpg")
def frame(key: str, moment_id: int, user=Depends(current_user)):
    """The moment's real preview frame (from YouTube's storyboard)."""
    con = db.connect()
    ok = con.execute("SELECT 1 FROM user_videos WHERE user_id=? AND video_key=?", (user["id"], key)).fetchone()
    con.close()
    f = _video_dir(key) / "frames" / f"{moment_id}.jpg"
    if not ok or not f.exists():
        raise HTTPException(404, "No frame.")
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
