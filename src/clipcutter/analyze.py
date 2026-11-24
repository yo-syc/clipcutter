"""Signals: loudness, scene cuts, chat activity, and speech (transcript with word timings)."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np

SR = 16000

HYPE_CHAT = re.compile(
    r"(lul|lmao|lmfao|kekw|omegalul|pog|poggers|w+\b|clip|clip it|no way|wtf|bro|"
    r"💀|😭|😂|🤣|🔥|😳|!!|\?\?|monka|pepelaugh|icant|cinema|aura|cooked|ratio)",
    re.I,
)


# ---------- basics ----------

def probe(video: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    s = (data.get("streams") or [{}])[0]
    return {"width": int(s.get("width") or 0), "height": int(s.get("height") or 0),
            "duration": float(data["format"]["duration"])}


def load_audio(video: Path, work: Path) -> np.ndarray:
    """Mono 16 kHz float32 audio, cached on disk as raw PCM."""
    raw = work / "audio16k.pcm"
    if not raw.exists():
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1",
             "-ar", str(SR), "-f", "s16le", str(raw)],
            check=True,
        )
    pcm = np.memmap(raw, dtype=np.int16, mode="r")
    return pcm


def loudness(pcm: np.ndarray, seconds: int) -> np.ndarray:
    """RMS loudness in dB for every second."""
    out = np.full(seconds, -90.0, dtype=np.float32)
    for t in range(seconds):
        chunk = np.asarray(pcm[t * SR:(t + 1) * SR], dtype=np.float32)
        if chunk.size:
            rms = np.sqrt(np.mean(chunk ** 2)) / 32768.0
            out[t] = 20 * np.log10(rms + 1e-9)
    return out


def scene_cuts(video: Path, seconds: int, work: Path) -> np.ndarray:
    """Scene-change count per second, from keyframes only (fast even on long VODs)."""
    cache = work / "scenes.json"
    if cache.exists():
        times = json.loads(cache.read_text())
    else:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-skip_frame", "nokey", "-i", str(video),
             "-vf", "scale=320:-2,scdet=threshold=12", "-an", "-f", "null", "-"],
            capture_output=True, text=True,
        )
        times = [float(m) for m in re.findall(r"lavfi\.scd\.time:\s*([\d.]+)", proc.stderr)]
        cache.write_text(json.dumps(times))
    out = np.zeros(seconds, dtype=np.float32)
    for t in times:
        if 0 <= int(t) < seconds:
            out[int(t)] += 1
    return out


# ---------- chat ----------

def _yt_item(item: dict, offset: float | None):
    """One YouTube live-chat renderer -> chat dict (offset = video time, or None for a live stream)."""
    kinds = {"liveChatTextMessageRenderer": "text", "liveChatPaidMessageRenderer": "paid",
             "liveChatPaidStickerRenderer": "paid", "liveChatMembershipItemRenderer": "member",
             "liveChatSponsorshipsGiftPurchaseAnnouncementRenderer": "gift"}
    for key, vm in item.items():   # newer "view model" items, e.g. giftMessageViewModel ("sent Speed bolt")
        if key.endswith("ViewModel") and isinstance(vm, dict):
            msg = (vm.get("text") or {}).get("content", "") if isinstance(vm.get("text"), dict) else ""
            user = (vm.get("authorName") or {}).get("content", "?") if isinstance(vm.get("authorName"), dict) else "?"
            kind = "gift" if "gift" in key.lower() else "paid" if "paid" in key.lower() else "text"
            return {"t": offset, "wall": None, "msg": msg, "user": user.strip(), "kind": kind}
    for key, kind in kinds.items():
        rend = item.get(key)
        if not rend:
            continue
        runs = (rend.get("message") or rend.get("headerSubtext") or {}).get("runs", [])
        msg = "".join(x.get("text") or (x.get("emoji", {}).get("shortcuts") or [""])[0] for x in runs)
        user = (rend.get("authorExternalChannelId") or (rend.get("authorName") or {}).get("simpleText") or "?")
        wall = int(rend["timestampUsec"]) / 1e6 if rend.get("timestampUsec") else None
        return {"t": offset, "wall": wall, "msg": msg, "user": user, "kind": kind}
    return None


def chat_items(path: Path):
    """Yield chat dicts {t (video seconds) or wall (epoch), msg, user, kind} from every format we know:
    yt-dlp YouTube live_chat (replay or live), TwitchDownloader, chat-downloader, our own live JSONL."""
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return
    records: list = []
    if text[0] == "[":
        records = json.loads(text)
    elif text[0] == "{" and "\n" not in text:
        obj = json.loads(text)
        records = obj.get("comments") or obj.get("messages") or [obj]
    else:
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass   # a live file can end with a half-written line

    last_wall = None
    for r in records:
        if not isinstance(r, dict):   # partial / joined live files can contain stray non-object lines
            continue
        replay = r.get("replayChatItemAction")
        if replay or "addChatItemAction" in json.dumps(r)[:200]:
            acts = replay.get("actions", []) if replay else [r]
            off = int(replay["videoOffsetTimeMsec"]) / 1000 if replay and replay.get("videoOffsetTimeMsec") else None
            for act in acts:
                d = _yt_item(act.get("addChatItemAction", {}).get("item", {}), off)
                if d:
                    if d["wall"] is None and d["t"] is None:   # gift items carry no time: chat arrives in order
                        d["wall"] = last_wall
                    last_wall = d["wall"] or last_wall
                    yield d
            continue
        if "content_offset_seconds" in r:   # TwitchDownloader
            body = r.get("message", {})
            yield {"t": float(r["content_offset_seconds"]), "wall": None,
                   "msg": body.get("body", "") if isinstance(body, dict) else str(body),
                   "user": (r.get("commenter") or {}).get("_id", "?"),
                   "kind": "paid" if isinstance(body, dict) and body.get("bits_spent") else "text"}
            continue
        if "wall" in r:                      # our live capture (Twitch IRC / Kick)
            yield {"t": None, "wall": float(r["wall"]), "msg": str(r.get("message", "")),
                   "user": str(r.get("user", "?")), "kind": r.get("kind", "text")}
            continue
        for tk in ("time_in_seconds", "offset", "time", "t"):   # chat-downloader and simple formats
            if tk in r:
                a = r.get("author")
                yield {"t": float(r[tk]), "wall": None, "msg": str(r.get("message") or r.get("text") or ""),
                       "user": str(a.get("id") if isinstance(a, dict) else a or r.get("user") or "?"),
                       "kind": "paid" if r.get("money") else "text"}
                break


KIND_WEIGHT = {"text": 1.0, "paid": 5.0, "gift": 4.0, "member": 3.0}   # money/actions are stronger votes


def chat_activity(path: Path | None, seconds: int, delay: int, wall0: float | None = None,
                  items: list | None = None) -> tuple[np.ndarray | None, dict]:
    """Chat 'votes' per second, shifted back by `delay` to line up with the moment.

    Smart scoring (ideas from open-source live clippers):
    - one viewer counts at most twice per 10 s (spam can't fake a highlight)
    - hype words/emotes x2, super chats/bits x5, gifts x4, new members x3
    wall0: epoch time of video second 0, for live chat that only has wall-clock timestamps."""
    if items is None:
        if not path or not path.exists():
            return None, {}
        items = list(chat_items(path))
    out = np.zeros(seconds, dtype=np.float32)
    samples: dict[int, list[str]] = {}
    per_user: dict[tuple, int] = {}
    n = 0
    for it in items:
        # live: wall-clock wins (offsets may count from the stream's start, not from when we joined)
        t = it["wall"] - wall0 if (wall0 and it.get("wall")) else it.get("t")
        if t is None:
            continue
        sec = int(t) - delay
        if not 0 <= sec < seconds:
            continue
        user = it.get("user") or "?"
        if user != "?":   # unknown authors (some chat exports) can't be capped per user
            key = (user, sec // 10)
            per_user[key] = per_user.get(key, 0) + 1
            if per_user[key] > 2 and it.get("kind", "text") == "text":
                continue
        w = KIND_WEIGHT.get(it.get("kind", "text"), 1.0) * (2.0 if HYPE_CHAT.search(it["msg"]) else 1.0)
        out[sec] += w
        samples.setdefault(sec, []).append(it["msg"])
        n += 1
    if n == 0:
        return None, {}
    return out, samples


# ---------- speech ----------

def transcribe_window(pcm: np.ndarray, start: float, end: float, model: str, language: str | None) -> list[dict]:
    """Words with absolute timestamps for [start, end].
    Apple Silicon: mlx-whisper (GPU). Windows/Linux/Intel mac: faster-whisper (CPU, or CUDA if available)."""
    from .system import whisper_backend

    a = max(0, int(start * SR))
    b = int(end * SR)
    audio = np.asarray(pcm[a:b], dtype=np.float32) / 32768.0
    if audio.size < SR:
        return []
    # anti-loop: few temperature retries + drop hallucinated text in silent/music parts
    # (without this, music in Hindi videos made one window take 5+ minutes)
    common = dict(word_timestamps=True, language=language, condition_on_previous_text=False,
                  temperature=(0.0, 0.4), hallucination_silence_threshold=2.0)
    words = []
    if whisper_backend() == "mlx":
        import mlx_whisper

        ensure_model(model)
        res = mlx_whisper.transcribe(audio, path_or_hf_repo=model, verbose=None, **common)
        for seg in res.get("segments", []):
            for w in seg.get("words", []):
                if w["word"].strip():
                    words.append({"w": w["word"].strip(), "s": round(start + w["start"], 2),
                                  "e": round(start + w["end"], 2)})
    else:
        segments, _ = _faster_model(model).transcribe(audio, **common)
        for seg in segments:
            for w in seg.words or []:
                if w.word.strip():
                    words.append({"w": w.word.strip(), "s": round(start + w.start, 2), "e": round(start + w.end, 2)})
    return words


TRANSLATE_MODEL = "mlx-community/whisper-small-mlx"   # "turbo" models can't translate; small is fast and can


def translate_window(pcm: np.ndarray, start: float, end: float) -> list[dict]:
    """English words (with timings) for speech in any language, via Whisper's translate task."""
    from .system import whisper_backend

    a, b = max(0, int(start * SR)), int(end * SR)
    audio = np.asarray(pcm[a:b], dtype=np.float32) / 32768.0
    if audio.size < SR:
        return []
    common = dict(task="translate", word_timestamps=True, condition_on_previous_text=False,
                  temperature=(0.0, 0.4))
    words = []
    if whisper_backend() == "mlx":
        import mlx_whisper
        ensure_model(TRANSLATE_MODEL)
        res = mlx_whisper.transcribe(audio, path_or_hf_repo=TRANSLATE_MODEL, verbose=None, **common)
        for seg in res.get("segments", []):
            for w in seg.get("words", []):
                if w["word"].strip():
                    words.append({"w": w["word"].strip(), "s": round(start + w["start"], 2), "e": round(start + w["end"], 2)})
    else:
        segments, _ = _faster_model("small").transcribe(audio, **common)
        for seg in segments:
            for w in seg.words or []:
                if w.word.strip():
                    words.append({"w": w.word.strip(), "s": round(start + w.start, 2), "e": round(start + w.end, 2)})
    return words


_FW = {}
on_model_progress = None   # callable(text): the web app shows first-run model download progress
_READY: set[str] = set()


def ensure_model(repo: str) -> None:
    """Download a speech model from Hugging Face once, reporting progress (it's ~0.5-1.6 GB)."""
    if repo in _READY or "/" not in repo or Path(repo).exists():
        return
    import threading

    from huggingface_hub import HfApi, snapshot_download
    try:
        snapshot_download(repo, local_files_only=True)
        _READY.add(repo)
        return
    except Exception:
        pass
    say = on_model_progress or (lambda t: print(t, flush=True))
    try:
        total = sum(s.size or 0 for s in HfApi().model_info(repo, files_metadata=True).siblings or [])
    except Exception:
        total = 0
    from huggingface_hub.constants import HF_HUB_CACHE
    cache = Path(HF_HUB_CACHE) / ("models--" + repo.replace("/", "--"))
    err: list = []
    t = threading.Thread(target=lambda: _try(lambda: snapshot_download(repo), err), daemon=True)
    t.start()
    while t.is_alive():
        got = sum(f.stat().st_size for f in cache.rglob("*") if f.is_file() and not f.is_symlink()) if cache.exists() else 0
        pct = f"{min(99, 100 * got / total):.0f}% of {total / 1e9:.1f} GB" if total else f"{got / 1e6:.0f} MB"
        say(f"Downloading the speech model (first time only): {pct}")
        t.join(2)
    if err:
        raise err[0]
    _READY.add(repo)


def _try(fn, err: list) -> None:
    try:
        fn()
    except BaseException as e:  # noqa: BLE001
        err.append(e)


def _faster_model(model: str):
    """faster-whisper model name from our config name, e.g. mlx-community/whisper-large-v3-turbo -> large-v3-turbo."""
    from faster_whisper import WhisperModel

    name = model.split("/")[-1].removeprefix("whisper-").removesuffix("-mlx")
    if name not in _FW:
        from faster_whisper.utils import _MODELS
        ensure_model(_MODELS.get(name, name))
        try:
            import ctranslate2
            cuda = ctranslate2.get_cuda_device_count() > 0
        except Exception:
            cuda = False
        _FW[name] = WhisperModel(name, device="cuda" if cuda else "cpu",
                                 compute_type="float16" if cuda else "int8")
    return _FW[name]
