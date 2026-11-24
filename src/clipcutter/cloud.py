"""Website engine: text-first analysis (any length, even 24 h) + render one chosen moment.

    analyze_url(url)          -> moments (no video downloaded; captions + chat + replay heatmap)
    render_moment(...)        -> downloads only that ~60 s section, renders the 9:16 clip

See docs/SYSTEM_DESIGN.md.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import numpy as np

from . import analyze, ingest, render, score, writer

Progress = Callable[[str, float], None]

WEIGHTS = {"replay": 0.35, "chat": 0.30, "speech": 0.25, "audio": 0.10, "visual": 0.0}
NO_CAPTION_MAX = 3 * 3600   # without captions we must transcribe audio on CPU: cap it


def _noop(step: str, pct: float) -> None:
    pass


def analyze_url(url: str, cfg: dict, cache: Path, n_moments: int = 12, progress: Progress = _noop,
                with_chat: bool = False, force: bool = False) -> dict:
    """Find the best moments of a video WITHOUT downloading it. Result is cached (shared by all users).

    Phase 1 (with_chat=False): captions + "most replayed" -> moments in seconds.
    Phase 2 (with_chat=True, background): adds the live-chat replay, which is slow to fetch on long streams."""
    cache.mkdir(parents=True, exist_ok=True)
    done = cache / "analysis.json"
    if done.exists() and not force:
        return json.loads(done.read_text())

    progress("Reading video info and captions…", 5)
    info, subs, _ = ingest.fetch_meta(url, cache / "meta")
    chat = None
    if with_chat:
        progress("Downloading live chat replay…", 20)
        chat = ingest.fetch_chat(url, cache / "meta", hook=lambda d: progress("Downloading live chat replay…", 30))
    T = int(info.get("duration") or 0)
    if T <= 0:
        raise RuntimeError("Couldn't read the video's length.")
    title = info.get("title", "")

    words: list[dict] = []
    db = None
    if subs:
        progress("Reading captions…", 30)
        words = ingest.caption_words(subs)
    else:
        if T > NO_CAPTION_MAX:
            raise RuntimeError("This video has no captions and is longer than 3 hours. "
                               "Long videos need captions (most YouTube videos have them).")
        progress("No captions: downloading audio…", 15)
        audio = ingest.download_audio(url, cache / "audio")
        pcm = analyze.load_audio(audio, cache)
        db = analyze.loudness(pcm, T)

    chat_rate, chat_samples = analyze.chat_activity(chat, T, cfg["chat_delay"])
    progress("Finding the best moments…", 55)
    signals = {
        "replay": score.replay_signal(info.get("heatmap"), T),
        "chat": score.chat_signal(chat_rate) if chat_rate is not None else None,
        "speech": score.speech_signal(words, T) if words else None,
        "audio": score.audio_signal(db) if db is not None else None,
    }
    if all(v is None for v in signals.values()):
        raise RuntimeError("Nothing to analyse (no captions, chat or audio).")
    base = score.combine(signals, WEIGHTS)
    cands = score.candidates(base, n_moments * 2, gap=int(cfg["max_len"] * 0.6))

    for i, m in enumerate(cands, 1):
        a, b = max(0.0, m.peak - cfg["max_len"] - 5), min(T, m.peak + 20)
        if words:
            win = [x for x in words if a <= x["s"] <= b]
        else:
            progress(f"Listening to moment {i} of {len(cands)}…", 55 + 30 * i / len(cands))
            win = analyze.transcribe_window(pcm, a, b, cfg["whisper_model"], cfg["language"])
        score.shape(m, win, cfg["min_len"], cfg["max_len"], T)
        m.speech = score.speech_hype(m)
        m.score = round(0.8 * m.base + 0.2 * m.speech, 4)
        m.reasons = [k for k, sig in signals.items() if sig is not None and sig[min(m.peak, T - 1)] > 0.5]

    chosen = sorted(score.pick(cands, n_moments), key=lambda m: -m.score)
    # virality 60-98 relative to this video's other candidates (absolute scores saturate on long videos)
    lo_s, hi_s = min(c.score for c in cands), max(c.score for c in cands)
    rel = {id(m): (m.score - lo_s) / max(1e-9, hi_s - lo_s) for m in cands}
    progress("Writing hooks…", 90)
    moments, used = [], set()
    for i, m in enumerate(chosen):
        lo, hi = max(int(m.start), m.peak - 3), min(int(m.end) - 1, m.peak + 3)
        peak = lo + int(np.argmax(base[lo:hi + 1])) if hi >= lo else m.peak
        hook_start = max(m.start, peak - 1.0)
        transcript = " ".join(x["w"] for x in m.words)
        chat_near = [msg for s in range(m.peak - 3, m.peak + 8) for msg in chat_samples.get(s, [])]
        meta = writer.write(transcript, chat_near, cfg, seed=m.peak, title=title, avoid=used)
        used.add(meta["hook"].lower())
        moments.append({
            "id": i, "start": m.start, "end": m.end, "peak": float(peak),
            "hook_start": hook_start, "hook_dur": min(cfg["hook"]["seconds"], m.end - hook_start),
            "score": m.score, "virality": (vir := int(round(60 + 38 * rel[id(m)]))), "signals": m.reasons,
            "recommended": score.recommended(m.reasons, vir, sum(v is not None for v in signals.values())),
            "transcript": transcript, "words": m.words, **meta,
            "post_caption": f"{meta['description']} {' '.join(meta['hashtags'])}".strip(),
        })

    result = {
        "url": info.get("webpage_url") or url, "id": info.get("id"), "platform": info.get("extractor_key"),
        "title": title, "uploader": info.get("uploader") or info.get("channel") or "",
        "duration": T, "thumbnail": info.get("thumbnail"),
        "sources": {"captions": bool(subs), "chat": chat is not None, "heatmap": bool(info.get("heatmap")),
                    "chat_available": ingest.has_chat_replay(info)},
        "moments": moments, "created": time.time(),
        "subs_file": str(subs) if subs else None,
        "subs_en_file": str(e) if (e := ingest.english_subs(cache / "meta", info.get("language"))) else None,
        "language": info.get("language"),
    }
    try:
        result["frames"] = save_frames(info, moments, cache / "frames")
    except Exception:
        result["frames"] = 0
    result["facecam"] = None
    if result["frames"] >= 4:
        try:
            from .facecam import detect_files
            result["facecam"] = detect_files(sorted((cache / "frames").glob("*.jpg")))
        except Exception:
            pass
    done.write_text(json.dumps(result, ensure_ascii=False))
    progress(f"{len(moments)} moments found", 100)
    return result


def apply_edits(analysis: dict, moment: dict, opts: dict | None) -> dict:
    """Editor: custom hook, trimmed start/end, corrected caption text. Keeps word timings where possible."""
    opts = opts or {}
    m = dict(moment)
    T = analysis["duration"]
    if opts.get("hook"):
        m["hook"] = str(opts["hook"])[:90]
    s0, e0 = m["start"], m["end"]
    if opts.get("start") is not None and opts.get("end") is not None:
        s = max(0.0, min(float(opts["start"]), T - 3))
        e = max(s + 5, min(float(opts["end"]), s + 56, T))   # + hook stays under 59 s (Reels/Shorts)
        m["start"], m["end"] = s, e
    if (m["start"], m["end"]) != (s0, e0):   # new range: take words for it from the full captions
        words = [w for w in moment["words"] if m["start"] <= w["s"] < m["end"]]
        sf = analysis.get("subs_file")
        if sf and Path(sf).exists():
            words = [w for w in ingest.caption_words(Path(sf)) if m["start"] <= w["s"] < m["end"]]
        m["words"] = words
        m["hook_start"] = min(max(m["start"], m["hook_start"]), m["end"] - 1)
    m["hook_dur"] = max(0.5, min(m.get("hook_dur", 2.5), m["end"] - m["hook_start"]))
    lang = (opts.get("cap_lang") or "auto").lower()
    ef = analysis.get("subs_en_file")
    if lang == "english" and opts.get("text") is None:
        if ef and Path(ef).exists():
            m["words"] = [w for w in ingest.caption_words(Path(ef)) if m["start"] <= w["s"] < m["end"]]
        else:
            m["_translate"] = True   # no YouTube English track: translate this clip's audio when rendering
    elif lang in ("hinglish", "auto") and opts.get("text") is None:
        from .translit import hinglish
        m["words"] = [{**w, "w": hinglish(w["w"])} for w in m["words"]]
    if opts.get("text") is not None:
        toks = str(opts["text"]).split()[:400]
        old = m["words"]
        if old and len(toks) == len(old):          # same word count: keep each word's exact timing
            m["words"] = [{**w, "w": t} for w, t in zip(old, toks)]
        elif toks:                                  # otherwise spread the words over the spoken span
            a = old[0]["s"] if old else m["start"]
            b = old[-1]["e"] if old else m["end"]
            step = max(0.12, (b - a) / len(toks))
            m["words"] = [{"w": t, "s": round(a + i * step, 2), "e": round(a + (i + 1) * step, 2)}
                          for i, t in enumerate(toks)]
        else:
            m["words"] = []
    return m


def render_moment(analysis: dict, moment: dict, cfg: dict, cache: Path, out: Path,
                  watermark: str | None = None, progress: Progress = _noop, opts: dict | None = None) -> dict:
    """Download just this moment's section (stream copy, cached) and render the 9:16 clip."""
    moment = apply_edits(analysis, moment, opts)
    if opts and opts.get("layout") in ("auto", "blur", "crop", "split", "split_top"):
        cfg = {**cfg, "layout": opts["layout"]}
    if analysis.get("facecam") and cfg.get("layout", "auto") in ("auto", "split", "split_top"):
        cfg = {**cfg, "facecam": analysis["facecam"]}
    if opts and opts.get("captions") is False:
        cfg = {**cfg, "captions": {**cfg["captions"], "enabled": False}}
    if opts and opts.get("cap_lang") == "original":
        cfg = {**cfg, "captions": {**cfg["captions"], "lang": "original"}}
    a = max(0.0, min(moment["start"], moment["hook_start"]) - 2)
    b = min(analysis["duration"], max(moment["end"], moment["hook_start"] + moment["hook_dur"]) + 2)
    sec = cache / "sections" / f"{int(a * 10)}_{int(b * 10)}.mp4"
    if not sec.exists():
        progress("Downloading this moment…", 10)
        ingest.on_download = lambda f: progress(f"Downloading this moment… {int(f * 100)}%", 10 + 40 * f)
        got = ingest.download_section(analysis["url"], a, b, sec)
        if got != sec:
            got.rename(sec)
    if moment.get("_translate"):
        progress("Translating captions to English…", 50)
        try:
            tw = out.parent / (out.stem + "_work")
            tw.mkdir(parents=True, exist_ok=True)
            pcm = analyze.load_audio(sec, tw)
            words = analyze.translate_window(pcm, 0, analyze.probe(sec)["duration"])
            moment = {**moment, "words": [{**w, "s": w["s"] + a, "e": w["e"] + a} for w in words
                                          if moment["start"] <= w["s"] + a < moment["end"]]}
        except Exception:
            pass   # keep the original captions rather than fail the clip
    progress("Editing: hook, captions, 9:16…", 55)
    clip = {k: moment[k] for k in ("start", "end", "peak", "hook_start", "hook_dur", "words", "hook")}
    shifted = {**clip, **{k: clip[k] - a for k in ("start", "end", "peak", "hook_start")},
               "words": [{**w, "s": w["s"] - a, "e": w["e"] - a} for w in clip["words"]]}
    out.parent.mkdir(parents=True, exist_ok=True)
    rcfg = {**cfg, "watermark": watermark}
    render.render(shifted, analyze.probe(sec), sec, rcfg, out, out.parent / (out.stem + "_work"))
    progress("Done", 100)
    return {"layout": shifted.get("layout")}


def save_frames(info: dict, moments: list[dict], out: Path) -> int:
    """Real preview frame per moment from YouTube's storyboard (frame grids, one frame every ~10 s).
    A few small JPEGs, no video download. Returns how many frames were saved."""
    import io
    import urllib.request

    from PIL import Image

    boards = [f for f in info.get("formats") or [] if f.get("format_note") == "storyboard" and f.get("fragments")]
    if not boards:
        return 0
    sb = max(boards, key=lambda f: f.get("width") or 0)      # sharpest: 320x180 tiles
    fps, rows, cols = sb.get("fps") or 0, sb.get("rows") or 1, sb.get("columns") or 1
    w, h, frags = sb.get("width"), sb.get("height"), sb["fragments"]
    if not (fps and w and h):
        return 0
    out.mkdir(parents=True, exist_ok=True)
    sheets: dict[int, Image.Image] = {}
    saved = 0
    for m in moments:
        k = int(m["peak"] * fps)
        n, cell = divmod(k, rows * cols)
        if n >= len(frags):
            n, cell = len(frags) - 1, 0
        try:
            if n not in sheets:
                req = urllib.request.Request(frags[n]["url"], headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    sheets[n] = Image.open(io.BytesIO(r.read())).convert("RGB")
            r_, c_ = divmod(cell, cols)
            sheets[n].crop((c_ * w, r_ * h, (c_ + 1) * w, (r_ + 1) * h)).save(out / f"{m['id']}.jpg", quality=88)
            saved += 1
        except Exception:
            continue
    return saved


def backfill_frames(url: str, vdir: Path) -> int:
    """Add frames to an analysis made before frames existed."""
    import yt_dlp

    a = json.loads((vdir / "analysis.json").read_text())
    with yt_dlp.YoutubeDL(ingest._ydl_opts()) as ydl:
        info = ydl.extract_info(url, download=False)
    return save_frames(info, a["moments"], vdir / "frames")


def _virality(s: float) -> int:
    return int(max(1, min(99, round(99 * max(0.0, s) ** 0.6))))
