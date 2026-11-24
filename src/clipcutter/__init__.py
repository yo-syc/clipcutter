"""ClipCutter: livestream -> viral vertical clips, automatically."""
from __future__ import annotations

import argparse
import sys
import time


def _common(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--clips", type=int, help="clips per video")
    sp.add_argument("--layout", choices=["blur", "crop", "split", "auto"])
    sp.add_argument("--style", choices=["genz", "hype", "clean"])
    sp.add_argument("--llm", choices=["auto", "claude", "openai", "ollama", "templates"], help="who writes hooks/titles")
    sp.add_argument("--whisper", help="whisper model, e.g. mlx-community/whisper-base-mlx (faster)")
    sp.add_argument("--config", help="path to config.yaml")
    sp.add_argument("--campaign", help="clipping-campaign preset (CTA, logo, caption rules): bobby, kreekcraft, luckylatvian")
    sp.add_argument("--from", dest="win_from", help="only clip after this point, e.g. 100m, 1:40:00 or 6000 (seconds)")
    sp.add_argument("--to", dest="win_to", help="only clip before this point (same formats as --from)")


def _at(t: str | None) -> float | None:
    """'100m' / '1:40:00' / '6000' -> seconds."""
    if not t:
        return None
    t = t.strip().lower()
    if t.endswith("m"):
        return float(t[:-1]) * 60
    if t.endswith("h"):
        return float(t[:-1]) * 3600
    sec = 0.0
    for part in t.split(":"):
        sec = sec * 60 + float(part)
    return sec


def _enable_hindi_text() -> None:
    """Pillow shapes Hindi (matras, conjuncts) only if it can find libfribidi (brew install fribidi).
    Homebrew's lib folder isn't on the default search path, so restart once with it added."""
    import os
    if sys.platform != "darwin" or os.environ.get("CLIPCUTTER_LIBS"):
        return
    lib = next((d for d in ("/opt/homebrew/lib", "/usr/local/lib") if os.path.exists(f"{d}/libfribidi.0.dylib")), None)
    if not lib:
        return
    env = dict(os.environ, CLIPCUTTER_LIBS="1",
               DYLD_FALLBACK_LIBRARY_PATH=f"{lib}:/usr/local/lib:/usr/lib")
    os.execve(sys.executable, [sys.executable] + sys.argv, env)


def _windows_utf8() -> None:
    """Windows opens files as cp1252 by default, and clip JSON/captions hold emoji and Hindi.
    Run once more in Python's UTF-8 mode (the desktop app sets it at build time)."""
    import os
    import subprocess
    if not sys.platform.startswith("win") or sys.flags.utf8_mode or getattr(sys, "frozen", False):
        return
    env = dict(os.environ, PYTHONUTF8="1")
    code = "import sys, clipcutter; sys.argv[0] = 'clipcutter'; clipcutter.main()"
    try:
        sys.exit(subprocess.run([sys.executable, "-X", "utf8", "-c", code, *sys.argv[1:]], env=env).returncode)
    except KeyboardInterrupt:
        sys.exit(130)


def main() -> None:
    _windows_utf8()
    _enable_hindi_text()
    p = argparse.ArgumentParser(prog="clipcutter", description="Turn streams into ready-to-post clips.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="clip one link (YouTube, Twitch, Kick, …) or a local video file")
    r.add_argument("target", help="URL or path to a video file")
    r.add_argument("--chat", help="chat log file (optional)")
    _common(r)

    rr = sub.add_parser("rerender", help="re-edit finished clips from cached video parts (no download)")
    rr.add_argument("out_dir", help="output folder, e.g. output/youtube_abc123")
    _common(rr)

    lv = sub.add_parser("live", help="clip a stream WHILE it's live (clips arrive a few minutes behind)")
    lv.add_argument("url", help="live stream link: twitch.tv/<channel>, youtube.com/watch?v=<live id>, kick.com/<channel>")
    lv.add_argument("--segment", type=float, default=5, help="minutes per chunk (smaller = faster clips)")
    lv.add_argument("--per-segment", type=int, default=2, help="max clips per chunk")
    lv.add_argument("--out", default="output/live")
    lv.add_argument("--keep-weak", action="store_true", help="also render moments the quality gate rejects")
    _common(lv)

    a = sub.add_parser("add", help="track a creator (channel URL)")
    a.add_argument("url")
    a.add_argument("--name")
    a.add_argument("--keyword", help="only clip videos whose title matches, e.g. 'gta'")
    a.add_argument("--permission", action="store_true", help="you have permission to post their clips")

    rm = sub.add_parser("remove", help="stop tracking a creator (name or URL)")
    rm.add_argument("who")

    sub.add_parser("creators", help="list tracked creators and their stats")

    t = sub.add_parser("track", help="check all creators for new videos and clip them")
    t.add_argument("--every", type=float, help="keep running, checking every N minutes")
    t.add_argument("--backfill", type=int, default=1, help="for a newly added creator, clip this many latest videos")
    t.add_argument("--limit", type=int, help="max videos to clip per check")
    t.add_argument("--retry", action="store_true", help="retry failed videos")
    _common(t)

    d = sub.add_parser("discover", help="find top creators for a topic on YouTube")
    d.add_argument("query", nargs="?", default="gta 6 live stream")
    d.add_argument("--limit", type=int, default=50, help="search results to scan")
    d.add_argument("--add-top", type=int, default=0, help="also start tracking the top N channels")

    sub.add_parser("dashboard", help="rebuild the dashboard page")
    sub.add_parser("doctor", help="check that everything needed is installed")

    st = sub.add_parser("site", help="run the multi-user website (needs: clipcutter site-worker)")
    st.add_argument("--port", type=int, default=8000)
    st.add_argument("--host", default="127.0.0.1")
    sub.add_parser("site-worker", help="run a website background worker (analyse videos, render clips)")
    sp = sub.add_parser("site-plan", help="admin: set a user's plan, e.g. site-plan you@x.com creator --days 30")
    sp.add_argument("email")
    sp.add_argument("plan", choices=["free", "starter", "creator", "pro"])
    sp.add_argument("--days", type=int, default=30)

    sv = sub.add_parser("serve", help="open the web app (paste links, tracker, clips)")
    sv.add_argument("--port", type=int, default=8787)
    sv.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to allow phones on your Wi-Fi")
    args = p.parse_args()

    from . import config, tracker

    cfg = config.load(getattr(args, "config", None))
    for key in ("clips", "layout", "style"):
        if getattr(args, key, None):
            cfg[key] = getattr(args, key)
    if getattr(args, "llm", None):
        cfg["llm"]["provider"] = args.llm
    if getattr(args, "whisper", None):
        cfg["whisper_model"] = args.whisper
    if getattr(args, "campaign", None):
        from . import campaigns
        campaigns.apply(cfg, args.campaign)
    if getattr(args, "win_from", None) or getattr(args, "win_to", None):
        cfg["window"] = (_at(args.win_from), _at(args.win_to))

    try:
        if args.cmd == "rerender":
            from . import pipeline
            pipeline.rerender(args.out_dir, cfg)
        elif args.cmd == "run":
            from . import pipeline
            pipeline.run(args.target, cfg, args.chat)
        elif args.cmd == "live":
            from pathlib import Path
            from .live import LiveSession
            sess = LiveSession(args.url, Path(args.out), cfg, segment_sec=int(args.segment * 60),
                               clips_per_segment=args.per_segment, keep_weak=args.keep_weak,
                               log=lambda m: print(time.strftime("[%H:%M:%S] ") + m, flush=True))
            try:
                n = sess.run()
            except KeyboardInterrupt:
                sess.shutdown()
                n = sess.n_clips
            print(f"{n} clips in {getattr(sess, 'dir', args.out)}")
        elif args.cmd == "add":
            c = tracker.add(args.url, args.name, args.keyword, args.permission)
            print(f"tracking {c['name']} ({c['platform']}). run: clipcutter track")
        elif args.cmd == "remove":
            print("removed" if tracker.remove(args.who) else "not found")
        elif args.cmd == "creators":
            rows = tracker.summary(cfg)
            if not rows:
                print("no creators yet: clipcutter add <channel url>")
            for c in rows:
                perm = "✓" if c.get("permission") else "✗"
                print(f"{c['name'][:28]:28} {c['platform']:8} perm {perm}  clipped {c['done']:3}  "
                      f"clips {c['clips']:4}  queue {c['new']:2}  failed {c['failed']:2}")
        elif args.cmd == "track":
            if args.retry:
                print(f"retrying {tracker.retry_failed(cfg)} failed videos")
            tracker.run(cfg, backfill=args.backfill, every=args.every, limit=args.limit,
                        log=lambda m: print(m, flush=True))
        elif args.cmd == "discover":
            chans = tracker.discover(args.query, args.limit)
            print(f"top channels for {args.query!r}:\n")
            for i, c in enumerate(chans[:20], 1):
                print(f"{i:2}. {c['name'][:30]:30} {c['views']:>13,} views  {c['videos']} vids  {c['url']}")
            for c in chans[: args.add_top]:
                try:
                    tracker.add(c["url"], c["name"], None, False)
                    print(f"   + tracking {c['name']}")
                except SystemExit:
                    pass
        elif args.cmd == "serve":
            from . import server
            server.serve(args.port, args.host, getattr(args, "config", None))
        elif args.cmd == "site":
            import uvicorn
            uvicorn.run("clipcutter.site.app:app", host=args.host, port=args.port, proxy_headers=True,
                        forwarded_allow_ips="*")
        elif args.cmd == "site-worker":
            from .site import worker
            worker.main(getattr(args, "config", None))
        elif args.cmd == "site-plan":
            import time as _t
            from .site import db as sdb
            sdb.init()
            con = sdb.connect()
            until = None if args.plan == "free" else _t.time() + args.days * 86400
            n = con.execute("UPDATE users SET plan=?, plan_until=? WHERE email=?",
                            (args.plan, until, args.email.lower())).rowcount
            print(f"{args.email}: {args.plan}" + (f" for {args.days} days" if until else "") if n else "no such user")
        elif args.cmd == "doctor":
            sys.exit(doctor())
        elif args.cmd == "dashboard":
            from . import dashboard
            print(dashboard.build(cfg, tracker.db(cfg), tracker.load_creators()))
    except KeyboardInterrupt:
        sys.exit(130)


def doctor() -> int:
    """Print what's installed and what's missing. Exit code 1 if something required is missing."""
    import shutil
    import subprocess

    from . import system

    ok = True

    def line(good: bool, name: str, detail: str, required: bool = True) -> None:
        nonlocal ok
        mark = "✅" if good else ("❌" if required else "⚠️ ")
        print(f"{mark} {name:22} {detail}")
        if required and not good:
            ok = False

    print(f"ClipCutter doctor  ({sys.platform}, python {sys.version.split()[0]})\n")
    ff = shutil.which("ffmpeg")
    line(bool(ff), "ffmpeg", ff or "missing: install ffmpeg (see docs/SETUP.md)")
    if ff:
        enc = system.encoder_args("8M")[1]
        line(True, "video encoder", enc + ("  (hardware, fast)" if enc != "libx264" else "  (CPU)"))
    js = system.js_runtimes()
    line(bool(js), "JS runtime (YouTube)", ", ".join(js) or "missing: install Node.js or Deno, else YouTube gives HTTP 403")
    try:
        bf = system.bold_font()
        line(True, "caption font", bf)
    except SystemExit as e:
        line(False, "caption font", str(e))
    hf = system.hindi_font()
    line(bool(hf), "Hindi font", hf[0] if hf else "missing: Hindi captions will show boxes (install Noto Sans Devanagari)", False)
    line(system.text_shaping_ok(), "Hindi text shaping", "ok" if system.text_shaping_ok()
         else "missing libfribidi: Hindi matras may look wrong (mac: brew install fribidi, linux: apt install libfribidi0)", False)
    ef = system.emoji_font()
    line(bool(ef), "emoji font", ef or "missing: emoji left out of captions (linux: apt install fonts-noto-color-emoji)", False)
    backend = system.whisper_backend()
    try:
        __import__("mlx_whisper" if backend == "mlx" else "faster_whisper")
        line(True, "speech-to-text", backend + ("  (Apple GPU)" if backend == "mlx" else "  (CPU/CUDA)"))
    except ImportError:
        line(False, "speech-to-text", f"{backend} not installed: run `uv sync`")
    try:
        import cv2
        line(hasattr(cv2, "CascadeClassifier"), "facecam detection", f"opencv {cv2.__version__}", False)
    except ImportError:
        line(False, "facecam detection", "opencv missing: run `uv sync`", False)
    from . import updater
    line(updater.current_version() != "?", "downloader (yt-dlp)", updater.current_version())
    import os
    if system.FROZEN:
        line(True, "your files", str(system.user_data_dir()), False)
    key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    line(key, "AI hooks (optional)", "ANTHROPIC_API_KEY set" if key else "not set: built-in Gen Z hook lines are used", False)
    start = "Open the ClipCutter app." if system.FROZEN else "Run: uv run clipcutter serve"
    print("\n" + (f"All required parts are installed. {start}" if ok
                  else "Fix the ❌ items above, then run this again."))
    return 0 if ok else 1
