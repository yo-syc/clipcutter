"""Render a 9:16 clip: HOOK (peak moment, zoomed) -> MAIN (setup -> payoff),
with Gen Z word-pop captions, hook text, header, and a bass "boom" on the hook."""
from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import system
from .writer import caption_emoji

EMOJI_FONT = system.emoji_font()
EMOJI_RE = re.compile("([\U0001F000-\U0001FAFF☀-➿⬀-⯿←-⇿][️‍\U0001F000-\U0001FAFF☀-➿]*)")


# ---------- text drawing (with emoji) ----------

@lru_cache(maxsize=None)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


@lru_cache(maxsize=1)
def _emoji_face() -> tuple[ImageFont.FreeTypeFont, int] | None:
    """Colour emoji fonts are bitmap fonts with fixed sizes: Apple 160, Noto 109; Segoe (Windows) any."""
    if not EMOJI_FONT:
        return None
    for px in (160, 109, 128):
        try:
            return ImageFont.truetype(EMOJI_FONT, px), px
        except OSError:
            continue
    return None


@lru_cache(maxsize=256)
def _emoji(seq: str, size: int) -> Image.Image:
    face = _emoji_face()
    if face is None:  # no emoji font on this machine: emoji are simply left out
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    f, px = face
    l, t, r, b = f.getbbox(seq)
    im = Image.new("RGBA", (max(1, r - l), max(1, b - t)), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((-l, -t), seq, font=f, embedded_color=True)
    scale = size / px * 1.05
    return im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)


HINDI_FONT = system.hindi_font()  # e.g. Kohinoor Devanagari Bold (mac), Nirmala UI (Windows), Noto (Linux)
DEVA_RE = re.compile("([\u0900-\u097F\u200c\u200d]+(?:[ ]+[\u0900-\u097F\u200c\u200d]+)*)")


@lru_cache(maxsize=None)
def _hindi(size: int) -> ImageFont.FreeTypeFont | None:
    return ImageFont.truetype(HINDI_FONT[0], size, index=HINDI_FONT[1]) if HINDI_FONT else None


def _runs(text: str):
    """Split into (kind, text): emoji / hindi (Devanagari) / plain."""
    for part in EMOJI_RE.split(text):
        if not part:
            continue
        if EMOJI_RE.fullmatch(part):
            yield "emoji", part
            continue
        for sub in DEVA_RE.split(part):
            if sub:
                yield ("hindi" if DEVA_RE.fullmatch(sub) else "text"), sub


def _font_for(kind: str, font):
    return (_hindi(font.size) or font) if kind == "hindi" else font


def measure(text: str, font: ImageFont.FreeTypeFont) -> int:
    w = 0
    for kind, part in _runs(text):
        w += _emoji(part, font.size).width + 6 if kind == "emoji" else int(_font_for(kind, font).getlength(part))
    return w


def draw_text(img: Image.Image, x: int, baseline: int, text: str, font, fill, stroke: int = 0) -> int:
    d = ImageDraw.Draw(img)
    cx = x
    for kind, part in _runs(text):
        if kind == "emoji":
            e = _emoji(part, font.size)
            img.alpha_composite(e, (cx + 3, baseline - int(font.size * 0.85)))
            cx += e.width + 6
        else:
            f = _font_for(kind, font)
            d.text((cx, baseline), part, font=f, fill=fill, anchor="ls",
                   stroke_width=stroke, stroke_fill="black")
            cx += int(f.getlength(part))
    return cx - x


def _wrap(text: str, font, max_w: int) -> list[str]:
    tokens: list[str] = []
    for tok in text.split():  # keep emoji glued to the word before it
        if tokens and EMOJI_RE.fullmatch(tok):
            tokens[-1] += " " + tok
        else:
            tokens.append(tok)
    lines, cur = [], ""
    for word in tokens:
        trial = f"{cur} {word}".strip()
        if measure(trial, font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


SAFE_W = 820   # Reels/Shorts/TikTok: text stays within x≈130-950, y≈270-1250 (outside the apps' own UI)


def draw_box_text(img, text: str, font, center_y: int, W: int, max_w: int = SAFE_W):
    """TikTok-style white rounded boxes with black text."""
    lines = _wrap(text, font, max_w)
    lh = int(font.size * 1.25)
    top = center_y - lh * len(lines) // 2
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        w = measure(line, font)
        x = (W - w) // 2
        y = top + i * lh
        d.rounded_rectangle((x - 26, y - 4, x + w + 26, y + lh + 2), radius=22, fill=(255, 255, 255, 245))
        draw_text(img, x, y + int(lh * 0.78), line, font, fill=(0, 0, 0, 255))


def draw_caption(img, words: list[str], active: int, cfg: dict, W: int):
    size = cfg["size"]
    base_font = _font(system.bold_font(cfg.get("font")), size)
    big_font = _font(system.bold_font(cfg.get("font")), int(size * 1.15))
    fonts = [big_font if i == active else base_font for i in range(len(words))]
    space = int(size * 0.3)
    widths = [measure(w, f) for w, f in zip(words, fonts)]
    # wrap into lines no wider than 820: keeps clear of the like/comment/share buttons on the right in Reels
    lines, cur, cur_w = [], [], 0
    for i, w in enumerate(widths):
        if cur and cur_w + space + w > SAFE_W:
            lines.append(cur)
            cur, cur_w = [], 0
        cur.append(i)
        cur_w += (space if cur_w else 0) + w
    if cur:
        lines.append(cur)
    lh = int(size * 1.2)
    y0 = cfg["y"] - lh * (len(lines) - 1) // 2
    for li, idxs in enumerate(lines):
        total = sum(widths[i] for i in idxs) + space * (len(idxs) - 1)
        x = (W - total) // 2
        for i in idxs:
            color = cfg["highlight"] if i == active else cfg["color"]
            draw_text(img, x, y0 + li * lh, words[i], fonts[i], fill=color, stroke=10)
            x += widths[i] + space


# ---------- overlay timeline ----------

def caption_chunks(words: list[dict], per_chunk: int, style: str, censor_words: bool = False) -> list[list[dict]]:
    chunks, cur = [], []
    for i, w in enumerate(words):
        txt = w["w"].strip()
        if censor_words:
            from .writer import censor
            txt = censor(txt)
        # keep Hindi letters AND vowel signs (matras are not \w)
        txt = re.sub(r"[^\w'?!*ऀ-ॿ-]", "", txt) if style != "clean" else txt
        if style == "genz":
            txt = txt.lower().rstrip(".,")
        if not txt:
            continue
        emo = caption_emoji(txt) if style == "genz" else ""
        cur.append({**w, "t": f"{txt} {emo}".strip()})
        nxt = words[i + 1] if i + 1 < len(words) else None
        brk = re.search(r"[.!?,]$", w["w"]) or (nxt and nxt["s"] - w["e"] > 0.5)
        if len(cur) >= per_chunk or brk:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def build_overlay(clip: dict, cfg: dict, out_dir: Path) -> Path:
    """Render overlay states to PNGs and write an ffconcat list with durations."""
    W, H = cfg["video"]["width"], cfg["video"]["height"]
    hook_d = clip["hook_dur"]
    total = hook_d + (clip["end"] - clip["start"])
    hook_font = _font(system.bold_font(cfg["captions"].get("font")), 84)
    head_font = _font(system.bold_font(cfg["captions"].get("font")), 52)
    hook_y = {"blur": 470, "split": 470, "split_top": 672}.get(cfg["layout"], 620)
    head_y = {"blur": 330, "split": 330, "split_top": 740}.get(cfg["layout"], 330)   # below the top ~270 px the apps cover

    # caption events in output time
    events = []  # (t0, t1, words_text, active_idx)
    if cfg["captions"]["enabled"]:
        words = clip["words"]
        if cfg["captions"].get("lang", "auto") != "original":   # Hindi -> Hinglish (Roman) captions by default
            from .translit import hinglish
            words = [{**w, "w": hinglish(w["w"])} for w in words]
        chunks = caption_chunks(words, cfg["captions"]["words_per_chunk"], cfg["style"], cfg["captions"].get("censor", False))
        for ci, ch in enumerate(chunks):
            chunk_end = chunks[ci + 1][0]["s"] if ci + 1 < len(chunks) else ch[-1]["e"] + 0.4
            chunk_end = min(chunk_end, ch[-1]["e"] + 0.8)
            for wi, w in enumerate(ch):
                t0 = w["s"] if wi else ch[0]["s"]
                t1 = ch[wi + 1]["s"] if wi + 1 < len(ch) else chunk_end
                events.append((hook_d + t0 - clip["start"], hook_d + t1 - clip["start"],
                               tuple(x["t"] for x in ch), wi))

    hook_until = hook_d if hook_d > 0 else 2.2
    cta_from = max(hook_until, total - 3.0) if cfg.get("cta") else total + 1   # campaign end card: last 3 s
    logo = None
    if cfg.get("logo"):   # campaign logo overlay, required on every frame by some briefs
        logo = Image.open(cfg["logo"]).convert("RGBA")
        lw = int(W * 0.45)
        logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
    cuts = {0.0, total, hook_until, min(cta_from, total)}
    for e in events:
        cuts.update((max(0.0, e[0]), min(total, e[1])))
    cuts = sorted(c for c in cuts if 0 <= c <= total)

    frames_dir = out_dir / "overlay"
    frames_dir.mkdir(parents=True, exist_ok=True)
    cache: dict = {}
    lines = ["ffconcat version 1.0"]
    last_file = None
    for a, b in zip(cuts, cuts[1:]):
        if b - a < 0.01:
            continue
        mid = (a + b) / 2
        show_hook = mid < hook_until
        show_cta = mid >= cta_from
        show_head = cfg["header"] and not show_hook and not show_cta
        cap = next((e for e in events if e[0] <= mid < e[1]), None)
        key = (show_hook, show_head, show_cta, cap[2] if cap else None, cap[3] if cap else None)
        if key not in cache:
            img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            if show_hook:
                draw_box_text(img, clip["hook"], hook_font, hook_y, W)
            if show_head:
                draw_box_text(img, clip["hook"], head_font, head_y, W, SAFE_W)
            if show_cta:
                draw_box_text(img, cfg["cta"], head_font, head_y, W, SAFE_W)
            if cap and not show_hook:
                draw_caption(img, list(cap[2]), cap[3], cfg["captions"], W)
            if logo is not None:   # centred below the (2-line) hook box, above the captions
                img.alpha_composite(logo, ((W - logo.width) // 2, hook_y + 250))
            if cfg.get("watermark"):  # free plan
                wm_font = _font(system.bold_font(cfg["captions"].get("font")), 34)
                wm = cfg["watermark"]
                ImageDraw.Draw(img).text(((W - measure(wm, wm_font)) // 2, 1340), wm, font=wm_font,  # visible above Reels UI
                                         fill=(255, 255, 255, 150), stroke_width=3, stroke_fill=(0, 0, 0, 120))
            path = frames_dir / f"s{len(cache):04d}.png"
            img.save(path, compress_level=1)
            cache[key] = path
        last_file = cache[key]
        lines += [f"file '{last_file.name}'", f"duration {b - a:.3f}"]
    lines.append(f"file '{last_file.name}'")
    lst = frames_dir / "list.ffconcat"
    lst.write_text("\n".join(lines) + "\n")
    return lst


# ---------- ffmpeg ----------

def _layout_filter(cfg: dict, src: dict) -> str:
    W, H = cfg["video"]["width"], cfg["video"]["height"]
    layout = cfg["layout"]
    vertical = src["width"] < src["height"]
    if layout == "crop" or vertical:
        return f"[cv]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}[lv]"
    if layout in ("split", "split_top") and cfg.get("facecam"):
        x, y, w, h = cfg["facecam"]
        cam_h = int(H * cfg.get("cam_frac", 0.35)) // 2 * 2   # campaigns where the streamer must be the focus use 0.5
        order = "[cam][game]" if layout == "split_top" else "[game][cam]"   # default: gameplay on top, face below
        return (
            f"[cv]split=2[c1][c2];"
            f"[c1]crop=iw*{w}:ih*{h}:iw*{x}:ih*{y},deblock=filter=strong:block=8,"   # webcams are tiny: hide blocks before the ~4x upscale
            f"scale={W}:{cam_h}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{cam_h},"
            f"hqdn3d=3:3:4:4,gblur=sigma=1.4,unsharp=5:5:0.6[cam];"
            f"[c2]scale=-2:{H - cam_h},crop={W}:{H - cam_h}[game];{order}vstack[lv]"
        )
    fg_w = int(W * 1.3) // 2 * 2
    return (
        f"[cv]split=2[b1][b2];"
        f"[b1]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},"
        f"boxblur=8:2,eq=brightness=-0.12,scale={W}:{H}[bg];"
        f"[b2]scale={fg_w}:-2,crop={W}:ih[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[lv]"
    )


def render(clip: dict, src_info: dict, video: Path, cfg: dict, out_path: Path, work: Path) -> None:
    vc = cfg["video"]
    fps = vc["fps"]
    hook = clip["hook_dur"] > 0
    first = min(clip["start"], clip["hook_start"]) if hook else clip["start"]
    last = max(clip["end"], clip["hook_start"] + clip["hook_dur"]) if hook else clip["end"]
    seek = max(0.0, first - 2.0)
    span = last - seek + 1.0
    rel = lambda t: f"{t - seek:.3f}"  # noqa: E731
    SW, SH = src_info["width"] // 2 * 2, src_info["height"] // 2 * 2
    z = cfg["hook"]["zoom"]

    if cfg["layout"] in ("auto", "split", "split_top"):
        cam = cfg.get("facecam")
        if not cam:
            from .facecam import detect
            cam = detect(video, clip["start"], clip["end"])
        if cfg["layout"] == "auto":
            cfg = {**cfg, "layout": "split" if cam else "blur", "facecam": cam}
        else:   # facecam asked for but none found: fall back to the blur layout
            cfg = {**cfg, "layout": cfg["layout"] if cam else "blur", "facecam": cam}
    clip["layout"] = cfg["layout"]
    overlay = build_overlay(clip, cfg, work)

    parts, concat_in = [], ""
    if hook:
        hs, he = clip["hook_start"], clip["hook_start"] + clip["hook_dur"]
        parts.append(
            f"[0:v]trim=start={rel(hs)}:end={rel(he)},setpts=PTS-STARTPTS,fps={fps},"
            f"crop=w='trunc(iw/{z}/2)*2':h='trunc(ih/{z}/2)*2',scale={SW}:{SH},setsar=1[v0];"
            f"[0:a]atrim=start={rel(hs)}:end={rel(he)},asetpts=PTS-STARTPTS,aresample=48000[a0]"
        )
        concat_in += "[v0][a0]"
    parts.append(
        f"[0:v]trim=start={rel(clip['start'])}:end={rel(clip['end'])},setpts=PTS-STARTPTS,fps={fps},"
        f"scale={SW}:{SH},setsar=1[v1];"
        f"[0:a]atrim=start={rel(clip['start'])}:end={rel(clip['end'])},asetpts=PTS-STARTPTS,aresample=48000[a1]"
    )
    concat_in += "[v1][a1]"
    n = 2 if hook else 1
    parts.append(f"{concat_in}concat=n={n}:v=1:a=1[cv][ca]")
    parts.append(_layout_filter(cfg, src_info))
    parts.append("[1:v]format=rgba[ov];[lv][ov]overlay=0:0:format=auto:eof_action=pass,format=yuv420p[outv]")

    # decode on the Mac's hardware video engine (frees the CPU for filters)
    inputs = [*system.hwaccel_args(), "-ss", f"{seek:.3f}", "-t", f"{span:.3f}", "-i", str(video),
              "-f", "concat", "-safe", "0", "-i", str(overlay)]
    boom = hook and cfg["hook"].get("boom")
    if boom:
        inputs += ["-f", "lavfi", "-i",
                   "aevalsrc='0.9*sin(2*PI*(45+180*exp(-9*t))*t)*exp(-3.5*t)':s=48000:d=1.2"]
        delay = int(max(0.0, clip["peak"] - clip["hook_start"]) * 1000)
        parts.append(f"[2:a]adelay={delay}|{delay},aformat=channel_layouts=stereo[bm];"
                     f"[ca]aformat=channel_layouts=stereo[cs];"
                     f"[cs][bm]amix=inputs=2:duration=first:normalize=0[mix]")
        audio_src = "[mix]"
    else:
        audio_src = "[ca]"
    parts.append(f"{audio_src}loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[outa]")

    cmd = ["ffmpeg", "-v", "error", "-y", *inputs,
           "-filter_complex", ";".join(parts),
           "-map", "[outv]", "-map", "[outa]",
           *system.encoder_args(vc["bitrate"]),
           "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
           str(out_path)]
    subprocess.run(cmd, check=True)
