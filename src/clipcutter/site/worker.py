"""Background worker: analyse videos, render clips, clean up old files.

Run one or many (on one or many machines sharing the DB + storage):
    uv run clipcutter site-worker
Jobs are claimed with an atomic UPDATE, so two workers never take the same job.
Jobs stuck in 'working' (crashed worker) are picked up again after a timeout.
"""
from __future__ import annotations

import json
import shutil
import time
import traceback
from pathlib import Path

from .. import cloud, config
from . import db

STALE_VIDEO = 5 * 60      # no progress heartbeat for this long = the worker died
STALE_ENRICH = 5 * 60     # heartbeat-based too
STALE_CLIP = 15 * 60
KEEP_CLIPS = 7 * 86400
KEEP_SECTIONS = 2 * 86400
KEEP_ANALYSIS = 30 * 86400
WATERMARK = "made with ClipCutter"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _friendly(e: Exception) -> str:
    s = str(e)
    if "Sign in to confirm" in s or "not a bot" in s:
        return "YouTube is blocking our server right now. Please try again in a few minutes."
    if "Private video" in s or "members-only" in s.lower():
        return "This video is private or members-only."
    if "Video unavailable" in s:
        return "This video is unavailable."
    return s.split("\n")[0][:300] or type(e).__name__


def _progress_writer(table: str, key_col: str, key):
    last = [0.0]

    def write(step: str, pct: float) -> None:
        now = time.time()
        if now - last[0] < 0.8 and pct < 100:
            return
        last[0] = now
        con = db.connect()
        con.execute(f"UPDATE {table} SET step=?, pct=?, updated=?, claimed=? WHERE {key_col}=?",
                    (step, round(pct, 1), now, now, key))
        con.close()
    return write


def claim_clip():
    now = time.time()
    with db.tx() as con:
        r = con.execute("SELECT id FROM clips WHERE status='queued' OR (status='working' AND claimed<?) "
                        "ORDER BY priority DESC, created LIMIT 1", (now - STALE_CLIP,)).fetchone()
        if not r:
            return None
        con.execute("UPDATE clips SET status='working', step='Starting…', claimed=?, updated=? WHERE id=?",
                    (now, now, r["id"]))
        return con.execute("SELECT * FROM clips WHERE id=?", (r["id"],)).fetchone()


def claim_video():
    now = time.time()
    with db.tx() as con:
        r = con.execute("SELECT key FROM videos WHERE status='queued' OR (status='working' AND claimed<?) "
                        "ORDER BY created LIMIT 1", (now - STALE_VIDEO,)).fetchone()
        if not r:
            return None
        con.execute("UPDATE videos SET status='working', step='Starting…', claimed=?, updated=? WHERE key=?",
                    (now, now, r["key"]))
        return con.execute("SELECT * FROM videos WHERE key=?", (r["key"],)).fetchone()


def do_video(cfg: dict, v) -> None:
    log(f"analyse {v['key']}")
    t = time.time()
    try:
        a = cloud.analyze_url(v["url"], cfg, db.DATA / "videos" / v["key"], 12,
                              _progress_writer("videos", "key", v["key"]))
        con = db.connect()
        con.execute("UPDATE videos SET status='ready', title=?, duration=?, step=?, pct=100, error=NULL, updated=?, "
                    "enrich=? WHERE key=?", (a["title"], a["duration"], f"{len(a['moments'])} moments found",
                                             time.time(), "pending" if a["sources"].get("chat_available") else None,
                                             v["key"]))
        con.close()
        log(f"  ready: {len(a['moments'])} moments in {time.time() - t:.0f}s")
    except Exception as e:
        log(f"  failed: {e}")
        traceback.print_exc()
        con = db.connect()
        con.execute("UPDATE videos SET status='failed', error=?, step='Failed', updated=? WHERE key=?",
                    (_friendly(e), time.time(), v["key"]))
        con.close()
        shutil.rmtree(db.DATA / "videos" / v["key"] / "analysis.json", ignore_errors=True)


def do_clip(cfg: dict, c) -> None:
    log(f"clip {c['id']} ({c['video_key']} #{c['moment_id']})")
    t = time.time()
    vdir = db.DATA / "videos" / c["video_key"]
    out = db.DATA / "clips" / str(c["user_id"]) / f"{c['id']}.mp4"
    try:
        a = json.loads((vdir / "analysis.json").read_text())
        m = next(x for x in a["moments"] if x["id"] == c["moment_id"])
        opts = json.loads(c["opts"]) if c["opts"] else None
        cloud.render_moment(a, m, cfg, vdir, out, WATERMARK if c["watermark"] else None,
                            _progress_writer("clips", "id", c["id"]), opts)
        con = db.connect()
        con.execute("UPDATE clips SET status='done', path=?, step='Ready', pct=100, error=NULL, updated=? WHERE id=?",
                    (str(out), time.time(), c["id"]))
        con.close()
        log(f"  done in {time.time() - t:.0f}s")
    except Exception as e:
        log(f"  failed: {e}")
        traceback.print_exc()
        con = db.connect()   # failed clips don't count against the quota (refund)
        con.execute("UPDATE clips SET status='failed', error=?, step='Failed', updated=? WHERE id=?",
                    (_friendly(e), time.time(), c["id"]))
        con.close()
    finally:
        shutil.rmtree(out.parent / (out.stem + "_work"), ignore_errors=True)


def claim_enrich():
    now = time.time()
    with db.tx() as con:
        r = con.execute("SELECT key FROM videos WHERE status='ready' AND (enrich='pending' OR "
                        "(enrich='working' AND enrich_claimed<?)) ORDER BY updated LIMIT 1",
                        (now - STALE_ENRICH,)).fetchone()
        if not r:
            return None
        con.execute("UPDATE videos SET enrich='working', enrich_claimed=? WHERE key=?", (now, r["key"]))
        return con.execute("SELECT * FROM videos WHERE key=?", (r["key"],)).fetchone()


def do_enrich(cfg: dict, v) -> None:
    """Phase 2: re-score with the live-chat replay. Skipped if someone already made a clip
    (moment ids must not change under existing clips)."""
    log(f"chat {v['key']}")
    vdir = db.DATA / "videos" / v["key"]
    state = "skipped"
    try:
        if not _has_clips(v["key"]):
            # build the improved analysis on the side, then swap it in only if still no clips exist
            side = vdir / "with_chat"

            def beat(step: str, pct: float, key=v["key"]) -> None:   # heartbeat so a dead worker is noticed
                con = db.connect()
                con.execute("UPDATE videos SET enrich_claimed=? WHERE key=?", (time.time(), key))
                con.close()

            cloud.analyze_url(v["url"], cfg, side, 12, beat, with_chat=True, force=True)
            with db.tx() as con:
                if not con.execute("SELECT 1 FROM clips WHERE video_key=?", (v["key"],)).fetchone():
                    (side / "analysis.json").replace(vdir / "analysis.json")
                    state = "done"
        log(f"  chat {state}")
    except Exception as e:
        log(f"  chat failed: {e}")
        state = "skipped"
    con = db.connect()
    con.execute("UPDATE videos SET enrich=?, updated=? WHERE key=?", (state, time.time(), v["key"]))
    con.close()


def _has_clips(key: str) -> bool:
    con = db.connect()
    n = con.execute("SELECT COUNT(*) FROM clips WHERE video_key=?", (key,)).fetchone()[0]
    con.close()
    return n > 0


def cleanup() -> None:
    now = time.time()
    con = db.connect()
    for r in con.execute("SELECT id, path FROM clips WHERE status='done' AND updated<?", (now - KEEP_CLIPS,)).fetchall():
        if r["path"]:
            Path(r["path"]).unlink(missing_ok=True)
        con.execute("UPDATE clips SET status='expired', path=NULL WHERE id=?", (r["id"],))
    for sec in (db.DATA / "videos").glob("*/sections/*.mp4"):
        if sec.stat().st_mtime < now - KEEP_SECTIONS:
            sec.unlink(missing_ok=True)
    for r in con.execute("SELECT key FROM videos WHERE status='ready' AND updated<?", (now - KEEP_ANALYSIS,)).fetchall():
        shutil.rmtree(db.DATA / "videos" / r["key"], ignore_errors=True)
        con.execute("UPDATE videos SET status='expired' WHERE key=?", (r["key"],))
    con.execute("DELETE FROM sessions WHERE expires<?", (now,))
    con.close()


def enrich_loop(cfg: dict) -> None:
    """Live-chat improvement runs in its own thread: it can take minutes and must never hold up clips."""
    while True:
        try:
            e = claim_enrich()
            if e:
                do_enrich(cfg, e)
                continue
        except Exception as ex:
            log(f"enrich loop: {ex}")
        time.sleep(3.0)


MAX_LIVE = 2   # live sessions per worker (each records a stream; ~1 CPU core while clipping)
LIVE_RUNNING: dict[int, tuple] = {}


def stop_all_live(*_) -> None:
    """Worker is exiting: stop its ffmpeg / yt-dlp recorders too, so none are left orphaned."""
    for sess, _, _ in list(LIVE_RUNNING.values()):
        try:
            sess.shutdown()
        except Exception:
            pass


def live_manager(cfg: dict) -> None:
    """Runs live sessions in their own threads; handles stop requests, time limits, credits, heartbeats."""
    import threading

    from ..live import LiveSession

    running = LIVE_RUNNING

    def run_one(row, plan):
        sid, uid = row["id"], row["user_id"]

        def setstep(msg: str) -> None:
            con = db.connect()
            con.execute("UPDATE live_sessions SET step=?, updated=? WHERE id=?", (msg[:200], time.time(), sid))
            con.close()

        def credits_left() -> bool:
            con = db.connect()
            ok = db.clips_used(con, uid) < plan["clips"]
            con.close()
            return ok

        def on_clip(rec: dict) -> None:
            now = time.time()
            with db.tx() as con:
                key = f"live_{sid}"
                con.execute("INSERT OR IGNORE INTO videos (key, url, title, status, step, created, updated) "
                            "VALUES (?,?,?,?,?,?,?)", (key, row["url"], rec["source_title"], "live", "live", now, now))
                n = con.execute("UPDATE live_sessions SET clips=clips+1, updated=? WHERE id=? RETURNING clips",
                                (now, sid)).fetchone()[0]
                con.execute("INSERT INTO clips (user_id, video_key, moment_id, status, step, pct, path, meta, "
                            "watermark, created, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (uid, key, n, "done", "Ready", 100, rec["path"], json.dumps(rec, ensure_ascii=False),
                             int(plan["watermark"]), now, now))

        lcfg = {**cfg, "watermark": WATERMARK if plan["watermark"] else None}
        import os
        seg = int(os.environ.get("CLIPCUTTER_LIVE_SEGMENT", "300"))   # seconds per chunk (smaller = faster clips)
        sess = LiveSession(row["url"], db.DATA / "live" / str(uid), lcfg, segment_sec=seg, clips_per_segment=2,
                           on_clip=on_clip, log=setstep, can_clip=credits_left)
        running[sid] = (sess, time.time(), plan["live_min"] * 60)
        status, err = "ended", None
        try:
            sess.run()
            if sess.stop.is_set():
                status = "stopped"
        except Exception as e:
            status, err = "failed", _friendly(e)
            log(f"live {sid} failed: {e}")
        finally:
            sess.shutdown()
            running.pop(sid, None)
            con = db.connect()
            con.execute("UPDATE live_sessions SET status=?, error=?, step=?, updated=? WHERE id=?",
                        (status, err, {"ended": "Stream ended", "stopped": "Stopped", "failed": "Failed"}[status],
                         time.time(), sid))
            con.close()

    while True:
        try:
            now = time.time()
            con = db.connect()
            for sid, (sess, t0, limit) in list(running.items()):      # heartbeat + stop + time limit
                r = con.execute("SELECT stop FROM live_sessions WHERE id=?", (sid,)).fetchone()
                if (r and r["stop"]) or now - t0 > limit:
                    sess.stop.set()
                    sess.shutdown()
                con.execute("UPDATE live_sessions SET updated=? WHERE id=?", (now, sid))
            # sessions whose worker died (no heartbeat for 2 min) go back in the queue
            con.execute("UPDATE live_sessions SET status='queued' WHERE status='recording' AND updated<? AND stop=0",
                        (now - 120,))
            con.execute("UPDATE live_sessions SET status='stopped', step='Stopped' WHERE status='queued' AND stop=1")
            con.close()
            if len(running) < MAX_LIVE:
                with db.tx() as con:
                    row = con.execute("SELECT * FROM live_sessions WHERE status='queued' AND stop=0 "
                                      "ORDER BY created LIMIT 1").fetchone()
                    if row:
                        con.execute("UPDATE live_sessions SET status='recording', step='Connecting to the stream…', "
                                    "updated=? WHERE id=?", (now, row["id"]))
                        user = con.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
                if row:
                    threading.Thread(target=run_one, args=(row, db.plan_of(user)), daemon=True).start()
        except Exception as e:
            log(f"live manager: {e}")
        time.sleep(5)


def main(config_path: str | None = None) -> None:
    import atexit
    import signal
    import sys
    import threading

    atexit.register(stop_all_live)
    for sig in (signal.SIGTERM, signal.SIGINT):   # main thread: handlers can be installed here
        signal.signal(sig, lambda s, f: (stop_all_live(), sys.exit(0)))

    db.init()
    cfg = config.load(config_path)
    threading.Thread(target=enrich_loop, args=(cfg,), daemon=True).start()
    threading.Thread(target=live_manager, args=(cfg,), daemon=True).start()
    log("worker started")
    last_clean = 0.0
    while True:
        if time.time() - last_clean > 600:
            cleanup()
            last_clean = time.time()
        c = claim_clip()        # people waiting on a clip first (it's quick)
        if c:
            do_clip(cfg, c)
            continue
        v = claim_video()
        if v:
            do_video(cfg, v)
            continue
        time.sleep(1.0)
