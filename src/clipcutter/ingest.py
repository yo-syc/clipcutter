"""Get the stream from a URL (YouTube, Twitch, Kick and ~1000 other sites via yt-dlp) or a local file.

For URLs we only download the AUDIO (+ chat) first. That's ~50 MB per hour instead of
~3 GB per hour of 1080p video. Moments are found from audio/chat, then only the few
video sections that become clips are downloaded.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

CHAT_SUFFIXES = (".live_chat.json", ".rechat.json", ".chat.json", ".chat.jsonl")
MEDIA_EXT = (".m4a", ".mp4", ".webm", ".mkv", ".mp3", ".opus", ".aac", ".ts")


@dataclass
class Source:
    id: str
    video: Path | None          # full local video (local files only)
    audio: Path                 # what we analyze (the video itself for local files)
    chat: Path | None
    title: str = ""
    url: str | None = None      # set for remote sources; clips are cut from here
    uploader: str = ""
    subs: Path | None = None    # platform captions (json3) with word timings, e.g. YouTube auto-captions


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")[:60] or "stream"


def _find_chat(media: Path) -> Path | None:
    stem = media.with_suffix("")
    for suf in CHAT_SUFFIXES:
        p = Path(str(stem) + suf)
        if p.exists():
            return p
    return None


def fetch(target: str, work_dir: Path, chat: str | None = None) -> Source:
    local = Path(target).expanduser()
    if local.exists():
        chat_path = Path(chat).expanduser() if chat else _find_chat(local)
        return Source(id=_slug(local.stem), video=local, audio=local, chat=chat_path, title=local.stem)
    return _fetch_audio(target, work_dir, chat)


def on_download(frac: float) -> None:
    """Download progress callback (0.0-1.0); the pipeline points this at the loader."""


def _hook(d: dict) -> None:
    if d.get("status") == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if total:
            on_download(min(1.0, d.get("downloaded_bytes", 0) / total))
    elif d.get("status") == "finished":
        on_download(1.0)


def _ydl_opts(**extra) -> dict:
    # YouTube needs a JS runtime to solve its download challenge (else HTTP 403); Node works.
    from .system import js_runtimes
    return {"quiet": True, "no_warnings": True, "noprogress": True, "js_runtimes": js_runtimes(),
            "progress_hooks": [lambda d: on_download_safe(d)], **extra}


def on_download_safe(d: dict) -> None:
    try:
        _hook(d)
    except Exception:
        pass


FULL_VIDEO_MAX = 2 * 3600   # up to 2 h: download the whole video once (fast), like Opus Clip etc.
VIDEO_FORMAT = ("bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b")


def _fetch_audio(url: str, work_dir: Path, chat: str | None) -> Source:
    """Videos up to 2 h: download the full video (cutting is then instant and local).
    Longer streams: download only the audio, and later just the parts that become clips."""
    import yt_dlp

    dl_dir = work_dir / "downloads"
    dl_dir.mkdir(parents=True, exist_ok=True)
    with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:  # cheap metadata look (no format resolving)
        meta = ydl.extract_info(url, download=False, process=False)
    if meta.get("is_live") or meta.get("live_status") in ("is_live", "is_upcoming"):
        raise RuntimeError("this stream is still live; it will be clipped once the VOD is up")
    full = (meta.get("duration") or 0) <= FULL_VIDEO_MAX
    opts = _ydl_opts(
        format=VIDEO_FORMAT if full else "bestaudio[ext=m4a]/bestaudio/worstvideo*+bestaudio/best",
        merge_output_format="mp4" if full else None,
        outtmpl=str(dl_dir / ("%(extractor_key)s_%(id)s" + (".video" if full else "") + ".%(ext)s")),
        writesubtitles=True,
        # YouTube's own captions: ".*-orig" = auto captions in the video's original language,
        # plus creator-uploaded ones in that language. Word timings for free, no speech-to-text needed.
        writeautomaticsub=True,
        subtitleslangs=[".*-orig", *([meta["language"]] if meta.get("language") else []), "live_chat", "rechat"],
        subtitlesformat="json3/json/best",
        concurrent_fragment_downloads=8,
    )
    # one YoutubeDL instance resolves AND downloads: YouTube 403s URLs resolved by another instance
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        media = Path(ydl.prepare_filename(info))
        if full:
            media = media.with_suffix(".mp4")
        have_subs = any(media.parent.glob(media.with_suffix("").name + ".*.json3"))
        if not media.exists() or not have_subs:
            ydl.params["skip_download"] = media.exists()  # video cached: only fetch captions/chat
            ydl.process_ie_result(info, download=True)
    if not media.exists():  # extension changed after post-processing
        media = next(p for p in dl_dir.glob(media.stem + ".*") if p.suffix in MEDIA_EXT)
    sid = _slug(media.stem.removesuffix(".video")).lower()
    chat_path = Path(chat).expanduser() if chat else _find_chat(media)
    return Source(id=sid, video=media if full else None, audio=media, chat=chat_path,
                  title=info.get("title", ""), url=info.get("webpage_url") or url,
                  uploader=info.get("uploader") or info.get("channel") or "",
                  subs=_pick_subs(media, meta.get("language")))


def _pick_subs(media: Path, lang: str | None) -> Path | None:
    stem = media.with_suffix("").name
    files = sorted(media.parent.glob(stem + ".*.json3"))
    for want in ([f"{lang}.json3"] if lang else []) + ["-orig.json3"]:  # creator subs beat auto ones
        for f in files:
            if f.name.endswith(want):
                return f
    return files[0] if files else None


def caption_words(path: Path) -> list[dict]:
    """YouTube json3 captions -> [{w, s, e}] with per-word timings."""
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    words: list[dict] = []
    for ev in data.get("events", []):
        t0 = ev.get("tStartMs", 0)
        end = t0 + ev.get("dDurationMs", 0)
        segs = [sg for sg in ev.get("segs") or [] if sg.get("utf8", "").strip()]
        for i, sg in enumerate(segs):
            s = (t0 + sg.get("tOffsetMs", 0)) / 1000
            e = (t0 + segs[i + 1].get("tOffsetMs", 0)) / 1000 if i + 1 < len(segs) else min(end / 1000, s + 1.2)
            text = re.sub(r"\[[^\]]*\]|>>|&gt;&gt;", " ", sg["utf8"])   # [laughter], [music], speaker marks
            for k, tok in enumerate(text.split()):   # manual captions put a whole line in one seg
                words.append({"w": tok, "s": round(s, 2), "e": round(max(e, s + 0.15), 2)})
    words.sort(key=lambda w: w["s"])
    # spread tokens that share one timestamp (whole-line segments) evenly across their span
    i = 0
    while i < len(words):
        j = i
        while j + 1 < len(words) and words[j + 1]["s"] == words[i]["s"]:
            j += 1
        if j > i:
            a, b = words[i]["s"], max(words[j]["e"], words[i]["s"] + 0.3 * (j - i + 1))
            step = (b - a) / (j - i + 1)
            for k in range(i, j + 1):
                words[k]["s"], words[k]["e"] = round(a + step * (k - i), 2), round(a + step * (k - i + 1), 2)
        i = j + 1
    for a, b in zip(words, words[1:]):  # caption events overlap: a word ends when the next one starts
        if b["s"] > a["s"]:
            a["e"] = min(a["e"], b["s"])
    return words


def download_section(url: str, start: float, end: float, dest: Path, exact: bool = False) -> Path:
    """Download only [start, end] of the video.

    exact=False (default): stream copy, no re-encode: fast, a few MB. The MP4 edit list keeps
    t=0 at `start`, so clip timings stay right. exact=True re-encodes at the cuts, which is slow
    (minutes), and is only needed for players that ignore edit lists."""
    import yt_dlp
    from yt_dlp.utils import download_range_func

    dest.parent.mkdir(parents=True, exist_ok=True)
    for old in dest.parent.glob(dest.stem + ".*"):
        old.unlink()
    opts = _ydl_opts(
        format=VIDEO_FORMAT,
        merge_output_format="mp4",
        outtmpl=str(dest.with_suffix(".%(ext)s")),
        download_ranges=download_range_func(None, [(start, end)]),
        force_keyframes_at_cuts=exact,
        concurrent_fragment_downloads=8,
    )
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    got = [p for p in dest.parent.glob(dest.stem + ".*") if p.suffix in MEDIA_EXT]
    if not got:
        raise RuntimeError(f"section download failed for {url} [{start:.0f}-{end:.0f}]")
    return got[0]


# ---------- text-first ingest (website / long videos) ----------

def fetch_meta(url: str, dest: Path, want_chat: bool = False) -> tuple[dict, Path | None, Path | None]:
    """Video info + the platform's captions (+ chat replay) WITHOUT downloading the video.
    Returns (info, captions_json3, chat_json). Info includes YouTube's "Most replayed" heatmap."""
    import yt_dlp

    dest.mkdir(parents=True, exist_ok=True)
    langs = [".*-orig"] + (["live_chat", "rechat"] if want_chat else [])
    opts = _ydl_opts(
        skip_download=True,
        writesubtitles=True,
        writeautomaticsub=True,
        subtitleslangs=langs,
        subtitlesformat="json3/json/best",
        outtmpl=str(dest / "meta.%(ext)s"),
    )
    with yt_dlp.YoutubeDL(opts) as ydl:  # one instance resolves AND downloads (else YouTube 403)
        info = ydl.extract_info(url, download=False)
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            raise RuntimeError("This stream is still live. Try again when the VOD is up.")
        lang = info.get("language")
        if lang:  # creator-uploaded captions in the video's language beat auto ones
            ydl.params["subtitleslangs"] = [lang] + langs
        ydl.process_ie_result(info, download=True)
    if lang and not lang.startswith("en"):
        fetch_english(url, dest)   # best effort: YouTube rate-limits translated tracks (HTTP 429)
    subs = _pick_subs(dest / "meta.mp4", lang)
    chat = next((p for p in dest.glob("meta.*") if p.name.endswith((".live_chat.json", ".rechat.json"))), None)
    return info, subs, chat


def download_audio(url: str, dest: Path) -> Path:
    """Audio only (~50 MB per hour) for videos without captions."""
    import yt_dlp

    dest.mkdir(parents=True, exist_ok=True)
    opts = _ydl_opts(format="bestaudio[ext=m4a]/bestaudio/best", outtmpl=str(dest / "audio.%(ext)s"),
                     concurrent_fragment_downloads=8)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        path = Path(ydl.prepare_filename(info))
        if not path.exists():
            ydl.process_ie_result(info, download=True)
    return path if path.exists() else next(p for p in dest.glob("audio.*") if p.suffix in MEDIA_EXT)


def has_chat_replay(info: dict) -> bool:
    return any(k in (info.get("subtitles") or {}) for k in ("live_chat", "rechat"))


def fetch_chat(url: str, dest: Path, hook=None) -> Path | None:
    """Live-chat replay only. Can take minutes on long streams (YouTube serves it in small pages),
    so the website does this in the background after the first moments are shown."""
    import yt_dlp

    dest.mkdir(parents=True, exist_ok=True)
    opts = _ydl_opts(skip_download=True, writesubtitles=True, subtitleslangs=["live_chat", "rechat"],
                     subtitlesformat="json/best", outtmpl=str(dest / "meta.%(ext)s"),
                     progress_hooks=[hook] if hook else [])   # own hook: runs in a background thread
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        ydl.process_ie_result(info, download=True)
    return next((p for p in dest.glob("meta.*") if p.name.endswith((".live_chat.json", ".rechat.json"))), None)


def fetch_english(url: str, dest: Path) -> Path | None:
    """YouTube's auto-translated English captions for a non-English video. Never raises:
    the translated track is often rate-limited, and English captions are optional."""
    import yt_dlp

    try:
        opts = _ydl_opts(skip_download=True, writeautomaticsub=True, subtitleslangs=["en"],
                         subtitlesformat="json3", outtmpl=str(dest / "meta.%(ext)s"), ignoreerrors=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                ydl.process_ie_result(info, download=True)
    except Exception:
        pass
    f = dest / "meta.en.json3"
    return f if f.exists() else None


def english_subs(meta_dir: Path, lang: str | None) -> Path | None:
    """The auto-translated English track saved next to the original captions (non-English videos only)."""
    if not lang or lang.startswith("en"):
        return None
    f = next(iter(sorted(meta_dir.glob("meta.en.json3"))), None)
    return f
