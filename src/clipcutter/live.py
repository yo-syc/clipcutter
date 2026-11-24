"""Live mode: clip a stream WHILE it is live (clips land ~segment length behind the stream).

    uv run clipcutter live https://www.twitch.tv/<channel>
    uv run clipcutter live https://www.youtube.com/watch?v=<live-id>

How it works (ideas from open-source live clippers like bilive / hotclip):
1. yt-dlp pulls the live HLS stream (720p) and ffmpeg cuts it into N-minute segments, no re-encode.
2. Chat is captured in real time: Twitch over anonymous IRC, YouTube via yt-dlp's live chat.
3. Each finished segment is scored (loudness + smart chat votes, resonance) against the whole stream so far,
   the best new moments are transcribed (only those windows), get a hook, and are rendered right away.
"""
from __future__ import annotations

import csv
import json
import random
import re
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

from . import analyze, render, score, writer
from .ingest import _ydl_opts, _slug
from .system import js_runtimes

# YouTube serves live video and audio as separate HLS streams; Twitch serves one muxed stream.
LIVE_FORMAT = "bv*[height<=720]+ba/b[height<=720]/b"


# ---------------- chat capture ----------------

class TwitchChat(threading.Thread):
    """Anonymous read-only Twitch IRC (no login needed). Writes JSONL: {wall, user, message, kind}."""

    def __init__(self, channel: str, out: Path):
        super().__init__(daemon=True)
        self.channel, self.out, self.stop = channel.lower(), out, threading.Event()

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                self._loop()
            except Exception:
                time.sleep(5)   # reconnect

    def _loop(self) -> None:
        s = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=30)
        for line in ("CAP REQ :twitch.tv/tags twitch.tv/commands", "PASS SCHMOOPIIE",
                     f"NICK justinfan{random.randint(10000, 99999)}", f"JOIN #{self.channel}"):
            s.sendall((line + "\r\n").encode())
        buf = ""
        with self.out.open("a", encoding="utf-8") as f:
            while not self.stop.is_set():
                try:
                    data = s.recv(65536).decode("utf-8", "ignore")
                except socket.timeout:
                    s.sendall(b"PING :tmi.twitch.tv\r\n")
                    continue
                if not data:
                    raise ConnectionError("closed")
                buf += data
                *lines, buf = buf.split("\r\n")
                for ln in lines:
                    if ln.startswith("PING"):
                        s.sendall(ln.replace("PING", "PONG", 1).encode() + b"\r\n")
                        continue
                    m = re.match(r"(?:@(\S+) )?:(\w+)!\S+ PRIVMSG #\w+ :(.*)", ln)
                    n = re.match(r"@(\S+) :tmi\.twitch\.tv USERNOTICE #\w+(?: :(.*))?", ln)
                    if m:
                        tags = dict(kv.split("=", 1) for kv in (m.group(1) or "").split(";") if "=" in kv)
                        kind = "paid" if tags.get("bits") else "text"
                        rec = {"wall": time.time(), "user": m.group(2), "message": m.group(3), "kind": kind}
                    elif n:
                        tags = dict(kv.split("=", 1) for kv in n.group(1).split(";") if "=" in kv)
                        mid = tags.get("msg-id", "")
                        kind = "gift" if "gift" in mid else "member" if "sub" in mid else "text"
                        rec = {"wall": time.time(), "user": tags.get("login", "?"), "message": n.group(2) or mid,
                               "kind": kind}
                    else:
                        continue
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    f.flush()


class YouTubeChat(threading.Thread):
    """YouTube live chat through yt-dlp (writes .live_chat.json(.part) as messages arrive)."""

    def __init__(self, url: str, out_dir: Path):
        super().__init__(daemon=True)
        self.url, self.out_dir, self.proc = url, out_dir, None

    def run(self) -> None:
        cmd = ["yt-dlp", "--skip-download", "--write-subs", "--sub-langs", "live_chat", "--no-warnings",
               "-o", str(self.out_dir / "chat.%(ext)s"), self.url]
        for rt in js_runtimes():
            cmd[1:1] = ["--js-runtimes", rt]
            break
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.proc.wait()

    def path(self) -> Path | None:
        parts = sorted(self.out_dir.glob("chat.live_chat.json*"), key=lambda p: (len(p.name), p.name))
        parts = [p for p in parts if p.stat().st_size > 0]
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0]
        joined = self.out_dir / "chat_joined.jsonl"
        joined.write_bytes(b"\n".join(p.read_bytes().rstrip(b"\n") for p in parts) + b"\n")
        return joined


# ---------------- live session ----------------

class LiveSession:
    def __init__(self, url: str, out_root: Path, cfg: dict, segment_sec: int = 300, clips_per_segment: int = 2,
                 on_clip: Callable[[dict], None] | None = None, log: Callable[[str], None] = print,
                 keep_weak: bool = False, can_clip: Callable[[], bool] | None = None):
        self.url, self.cfg, self.seg_sec, self.per_seg = url, cfg, segment_sec, clips_per_segment
        self.on_clip, self.log = on_clip or (lambda r: None), log
        self.out_root = out_root
        self.stop = threading.Event()
        self.clipped: list[tuple[float, float]] = []
        self.used_hooks: set[str] = set()
        self.n_clips = 0
        self.keep_weak = keep_weak                  # weak moments are skipped: saves CPU and the user's credits
        self.can_clip = can_clip or (lambda: True)  # e.g. the user still has credits this month

    # -- setup --
    def _probe(self) -> dict:
        import yt_dlp
        with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
            info = ydl.extract_info(self.url, download=False)
        if not (info.get("is_live") or info.get("live_status") == "is_live"):
            raise RuntimeError("This stream isn't live right now. Use the normal mode for videos and VODs.")
        return info

    def _resolve(self) -> tuple[list[str], dict]:
        """Current HLS URLs (1 muxed, or video + audio) and the headers to fetch them with."""
        import yt_dlp
        with yt_dlp.YoutubeDL(_ydl_opts(format=LIVE_FORMAT)) as ydl:
            info = ydl.extract_info(self.url, download=False)
        fmts = info.get("requested_formats") or [info]
        return [f["url"] for f in fmts], (fmts[0].get("http_headers") or {})

    def _start_recorder(self, start_number: int = 0) -> None:
        urls, headers = self._resolve()
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
        hdr = "".join(f"{k}: {v}\r\n" for k, v in headers.items() if k.lower() != "user-agent")
        for u in urls:
            if headers.get("User-Agent"):
                cmd += ["-user_agent", headers["User-Agent"]]
            if hdr:
                cmd += ["-headers", hdr]
            cmd += ["-i", u]
        cmd += (["-map", "0:v:0", "-map", "1:a:0"] if len(urls) == 2 else ["-map", "0"])
        cmd += ["-c", "copy", "-f", "segment", "-segment_time", str(self.seg_sec), "-reset_timestamps", "1",
                "-segment_start_number", str(start_number),
                "-segment_list", str(self.seg_dir / "segments.csv"), "-segment_list_type", "csv",
                "-segment_list_flags", "+live", "-segment_format", "mpegts", str(self.seg_dir / "seg_%05d.ts")]
        self.dl = None
        self.ff = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=open(self.dir / "recorder.log", "a"))

    def _start_chat(self, info: dict) -> None:
        ex = (info.get("extractor_key") or "").lower()
        self.chat_file: Path | None = None
        self.yt_chat = None
        if "twitch" in ex:
            ch = info.get("uploader_id") or info.get("channel") or self.url.rstrip("/").split("/")[-1]
            self.chat_file = self.dir / "chat.jsonl"
            TwitchChat(ch, self.chat_file).start()
            self.log(f"chat: Twitch IRC #{ch}")
        elif "youtube" in ex:
            self.yt_chat = YouTubeChat(self.url, self.dir)
            self.yt_chat.start()
            self.log("chat: YouTube live chat")
        else:
            self.log("chat: not available for this platform (audio-only scoring)")

    def _chat_path(self) -> Path | None:
        if self.chat_file and self.chat_file.exists():
            return self.chat_file
        return self.yt_chat.path() if self.yt_chat else None

    # -- main loop --
    def run(self) -> int:
        info = self._probe()
        self.info = info
        sid = _slug(f"{info.get('extractor_key', 'live')}_{info.get('id')}").lower()
        self.dir = self.out_root / sid / time.strftime("%Y%m%d-%H%M%S")   # fresh folder per run (no mixing)
        self.seg_dir = self.dir / "segments"
        self.seg_dir.mkdir(parents=True, exist_ok=True)
        self.title = info.get("title") or ""
        self.log(f"Recording live: {self.title[:70]} · {info.get('uploader') or info.get('channel') or ''}")
        self.restarts = 0
        self.wall0 = time.time()
        self._start_recorder()
        self._start_chat(info)
        done: set[str] = set()
        self.timeline: list[tuple[Path, float, float]] = []   # (segment file, start, end) in stream seconds
        while not self.stop.is_set():
            finished = self._finished_segments()
            for name, a, b in finished:
                if name in done:
                    continue
                done.add(name)
                self.timeline.append((self.seg_dir / name, a, b))
                self.log(f"segment {name}: {a / 60:.1f}-{b / 60:.1f} min")
                try:
                    self._process(a, b)
                except Exception as e:
                    self.log(f"  ! segment failed: {type(e).__name__}: {e}")
            if self.ff.poll() is not None:   # recorder stopped: last segment is in the CSV now
                for name, a, b in self._finished_segments():
                    if name not in done:
                        done.add(name)
                        self.timeline.append((self.seg_dir / name, a, b))
                        self._process(a, b)
                still_live = False
                try:
                    still_live = bool(self._probe())
                except Exception:
                    pass
                if still_live and self.restarts < 50:
                    self.restarts += 1
                    self.log("recorder stopped but the stream is live: reconnecting")
                    self._start_recorder(start_number=len(done))
                    continue
                self.log("stream ended")
                break
            time.sleep(3)
        self.shutdown()
        return self.n_clips

    def shutdown(self) -> None:
        self.stop.set()
        for p in (getattr(self, "dl", None), getattr(self, "ff", None),
                  getattr(getattr(self, "yt_chat", None), "proc", None)):
            if p and p.poll() is None:
                p.terminate()

    def _finished_segments(self) -> list[tuple[str, float, float]]:
        f = self.seg_dir / "segments.csv"
        if not f.exists():
            return []
        rows = []
        for r in csv.reader(f.read_text(errors="ignore").replace("\x00", "").splitlines()):
            if len(r) >= 3 and re.fullmatch(r"seg_\d+\.ts", r[0]) and (self.seg_dir / r[0]).exists():
                try:
                    rows.append((r[0], float(r[1]), float(r[2])))
                except ValueError:
                    continue   # a half-written line
        # with -reset_timestamps the CSV times restart per segment: rebuild a running timeline
        out, t = [], 0.0
        for name, a, b in rows:
            out.append((name, t, t + (b - a)))
            t += b - a
        return out

    # -- per segment --
    def _audio_db(self) -> np.ndarray:
        """Loudness per second for the whole stream so far (each segment is measured once, then cached)."""
        parts = []
        for path, a, b in self.timeline:
            cache = path.with_suffix(".db.npy")
            if not cache.exists():
                tmp = path.with_suffix(".pcmdir")
                tmp.mkdir(exist_ok=True)
                pcm = analyze.load_audio(path, tmp)
                np.save(cache, analyze.loudness(pcm, int(round(b - a))))
            parts.append(np.load(cache))
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)

    def _media_for(self, a: float, b: float) -> tuple[Path, float]:
        """A playable file covering [a, b] (joins neighbouring segments when a moment crosses a cut)."""
        segs = [(p, s, e) for p, s, e in self.timeline if e > a and s < b]
        if len(segs) == 1:
            return segs[0][0], segs[0][1]
        lst = self.dir / f"join_{int(a)}.txt"
        lst.write_text("".join(f"file '{p.resolve()}'\n" for p, _, _ in segs))   # absolute: list lives elsewhere
        out = self.dir / f"join_{int(a)}.ts"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(out)], check=True, cwd=self.seg_dir)
        return out, segs[0][1]

    def _process(self, seg_a: float, seg_b: float) -> None:
        cfg = self.cfg
        db = self._audio_db()
        T = len(db)
        if T < 20:
            return
        chat_path = self._chat_path()
        rate, samples = analyze.chat_activity(chat_path, T, cfg["chat_delay"], wall0=self.wall0) \
            if chat_path else (None, {})
        signals = {"audio": score.audio_signal(db), "chat": score.chat_signal(rate) if rate is not None else None}
        base = score.combine(signals, {"audio": 0.4, "chat": 0.6})
        bar = max(0.3, float(np.percentile(base[: int(seg_a)], 85)) if seg_a > 120 else 0.3)
        window = base.copy()
        window[: max(0, int(seg_a) - 15)] = 0          # only moments peaking in the new segment
        for s0, e0 in self.clipped:                     # never clip the same moment twice
            window[max(0, int(s0)): int(e0) + 1] = 0
        cands = [m for m in score.candidates(window, self.per_seg * 3, gap=int(cfg["max_len"] * 0.6))
                 if m.base >= bar][: self.per_seg]
        if not cands:
            self.log("  no strong moments in this segment")
            return
        for m in cands:
            self._clip(m, db, signals, samples, T)

    def _clip(self, m, db, signals, samples, T) -> None:
        cfg = self.cfg
        a, b = max(0.0, m.peak - cfg["max_len"] - 5), min(T, m.peak + 20)
        media, off = self._media_for(a, b)
        work = self.dir / f"work_{m.peak}"
        work.mkdir(exist_ok=True)
        pcm = analyze.load_audio(media, work)
        words = [{**w, "s": w["s"] + off, "e": w["e"] + off}
                 for w in analyze.transcribe_window(pcm, a - off, b - off, cfg["whisper_model"], cfg["language"])]
        score.shape(m, words, cfg["min_len"], cfg["max_len"], T)
        m.speech = score.speech_hype(m)
        m.score = round(0.8 * m.base + 0.2 * m.speech, 4)
        m.reasons = [k for k, v in signals.items() if v is not None and v[min(m.peak, T - 1)] > 0.5]
        vir = int(max(1, min(99, round(99 * max(0.0, m.score) ** 0.6))))
        good = score.recommended(m.reasons, vir, sum(v is not None for v in signals.values()))
        if not good and not self.keep_weak:
            self.log(f"  skipped a weak moment at {m.start / 60:.1f} min (virality {vir})")
            self.clipped.append((m.start, m.end))
            return
        if not self.can_clip():
            self.log("  out of clip credits: not rendering")
            self.stop.set()
            return
        lo, hi = max(int(m.start), m.peak - 3), min(int(m.end) - 1, m.peak + 3)
        peak = lo + int(np.argmax(db[lo:hi + 1])) if hi >= lo else m.peak
        hook_start = max(m.start, peak - 1.0)
        transcript = " ".join(w["w"] for w in m.words)
        chat_near = [x for s in range(m.peak - 3, m.peak + 8) for x in samples.get(s, [])]
        meta = writer.write(transcript, chat_near, cfg, seed=m.peak, title=self.title, avoid=self.used_hooks)
        self.used_hooks.add(meta["hook"].lower())
        clip = {"start": m.start - off, "end": m.end - off, "peak": float(peak) - off, "hook_start": hook_start - off,
                "hook_dur": min(cfg["hook"]["seconds"], m.end - hook_start), "hook": meta["hook"],
                "words": [{**w, "s": w["s"] - off, "e": w["e"] - off} for w in m.words]}
        self.n_clips += 1
        out = self.dir / f"live_clip_{self.n_clips:03d}.mp4"
        render.render(clip, analyze.probe(media), media, cfg, out, work)
        self.clipped.append((m.start, m.end))
        rec = {"file": out.name, "path": str(out), "source": self.url, "source_title": self.title,
               "creator": self.info.get("uploader") or self.info.get("channel") or "",
               "stream_time": round(m.start), "start": m.start, "end": m.end, "virality": vir,
               "recommended": good,
               "signals": m.reasons, "transcript": transcript, "layout": clip.get("layout"), **meta,
               "post_caption": f"{meta['description']} {' '.join(meta['hashtags'])}".strip(),
               "made_at": time.time()}
        (self.dir / f"live_clip_{self.n_clips:03d}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False))
        self.log(f"  🎬 clip {self.n_clips}: {m.start / 60:.1f} min · v{vir} · \"{meta['hook']}\" -> {out.name}")
        self.on_clip(rec)
