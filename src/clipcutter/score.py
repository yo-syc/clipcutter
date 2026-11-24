"""Turn raw signals into a per-second "virality" score, pick moments, snap to sentences."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

HYPE_SPEECH = re.compile(
    r"\b(oh my god|omg|no way|what+|bro+|yo+|let'?s go+|run|help|wtf|dude|holy|"
    r"insane|crazy|dead|died|nah+|yes+|no+|how|why|wait|look|stop|chill)\b",
    re.I,
)


HYPE_HINDI = re.compile(
    r"(भाई|भाईयों|अरे|क्या|पागल|बवाल|गज़ब|गजब|वाह|भागो|बाप रे|यार|सच में|हिल|मज़ा|मजा|ज़बरदस्त|जबरदस्त|"
    r"कमाल|ओ माय गॉड|ओह माय गॉड|नहीं|देखो|रुको|लेट्स गो|पगला|खतरनाक|डेंजर|रियलिस्टिक)"
)


@dataclass
class Moment:
    peak: int
    base: float
    start: float = 0.0
    end: float = 0.0
    speech: float = 0.0
    score: float = 0.0
    words: list = field(default_factory=list)
    reasons: list = field(default_factory=list)


def _rolling(x: np.ndarray, win: int, fn) -> np.ndarray:
    pad = win // 2
    xp = np.pad(x, (pad, pad), mode="edge")
    return fn(sliding_window_view(xp, 2 * pad + 1), axis=1)[: len(x)]


def _smooth(x: np.ndarray, win: int) -> np.ndarray:
    if win <= 1:
        return x
    return np.convolve(x, np.ones(win) / win, mode="same")


def _unit(x: np.ndarray, cap: float) -> np.ndarray:
    return np.clip(x, 0, cap) / cap


def audio_signal(db: np.ndarray) -> np.ndarray:
    base = _rolling(db, 61, np.median)
    spread = np.median(np.abs(db - base)) + 1.0
    return _unit((db - base) / spread, 4.0)


def chat_signal(rate: np.ndarray) -> np.ndarray:
    sm = _smooth(rate, 5)
    base = _rolling(sm, 121, np.median)
    level = _unit(np.log1p(sm) - np.log1p(base), 1.5)
    # burst bonus: chat jumping up fast (vs the previous 20 s) is the strongest live reaction
    prev = np.concatenate([np.zeros(20, dtype=sm.dtype), sm[:-20]]) if len(sm) > 20 else np.zeros_like(sm)
    burst = _unit(np.log1p(sm) - np.log1p(prev), 1.2)
    return np.clip(0.75 * level + 0.35 * burst, 0, 1)


def visual_signal(cuts: np.ndarray) -> np.ndarray:
    sm = _smooth(cuts, 5) * 5
    return _unit(sm, 3.0)


def speech_signal(words: list[dict], seconds: int) -> np.ndarray:
    """Per-second excitement from the full transcript: hype words (English + Hindi), '!' and fast talking."""
    hype = np.zeros(seconds, dtype=np.float32)
    rate = np.zeros(seconds, dtype=np.float32)
    for w in words:
        t = int(w["s"])
        if 0 <= t < seconds:
            rate[t] += 1
            if HYPE_SPEECH.search(w["w"]) or HYPE_HINDI.search(w["w"]) or "!" in w["w"]:
                hype[t] += 1
    # scale by this video's own top values (not a fixed cap): a fixed cap saturated at 1.0 on long,
    # chatty streams, every second tied, and all picks bunched at the start of the video
    h = _smooth(hype, 15)
    top = np.percentile(h[h > 0], 99.5) if (h > 0).any() else 1.0
    h = np.clip(h / max(top, 1e-6), 0, 1)
    r = _smooth(rate, 9)
    if (r > 0).any():
        r = r - np.median(r[r > 0])
        r = np.clip(r / max(np.percentile(r[r > 0], 99) if (r > 0).any() else 1.0, 1e-6), 0, 1)
    return np.clip(0.75 * h + 0.25 * r, 0, 1)


def replay_signal(heatmap: list[dict] | None, seconds: int) -> np.ndarray | None:
    """YouTube's "Most replayed" graph (what real viewers rewatch) -> 0..1 per second."""
    if not heatmap:
        return None
    out = np.zeros(seconds, dtype=np.float32)
    for h in heatmap:
        a, b = int(h.get("start_time", 0)), int(h.get("end_time", 0)) + 1
        out[max(0, a):min(seconds, b)] = float(h.get("value") or 0)
    base = float(np.median(out))
    return np.clip((out - base) / max(1e-6, 1 - base), 0, 1)


def combine(signals: dict[str, np.ndarray | None], weights: dict) -> np.ndarray:
    """Weighted mix + resonance: a moment where several signals rise together (loud AND chat AND
    hype words) is real; one signal alone is often music, spam or a random loud noise."""
    present = {k: v for k, v in signals.items() if v is not None and weights.get(k, 0) > 0}
    total = sum(weights[k] for k in present)
    out = sum(weights[k] / total * v for k, v in present.items())
    if len(present) >= 2:
        strong = sum((_smooth(v, 7) > 0.45).astype(np.float32) for v in present.values())
        out = out * (0.75 + 0.18 * np.minimum(strong, 3))   # 1 signal x0.93 · 2 x1.11 · 3+ x1.29
    return _smooth(out, 3)


def recommended(signal_names: list[str], virality: int, n_signals: int) -> bool:
    """Quality gate: weak clips are flagged 'not recommended' instead of being posted blindly."""
    if virality >= 85:
        return True
    if "chat" in signal_names and virality >= 72:   # many different viewers reacting at once (spam is capped)
        return True
    return virality >= 70 and (len(signal_names) >= 2 or n_signals <= 1)


def candidates(score: np.ndarray, n: int, gap: int, skip_edges: int = 3) -> list[Moment]:
    s = score.copy()
    s[:skip_edges] = 0
    s[-skip_edges:] = 0
    out = []
    while len(out) < n:
        p = int(np.argmax(s))
        if s[p] <= 0.02:
            break
        out.append(Moment(peak=p, base=float(score[p])))
        s[max(0, p - gap): p + gap] = 0
    return out


def _boundaries(words: list[dict]) -> tuple[list[float], list[float]]:
    """Sentence starts and ends (a pause > 0.6 s also counts)."""
    starts, ends = [], []
    for i, w in enumerate(words):
        prev = words[i - 1] if i else None
        if prev is None or re.search(r"[.!?]$", prev["w"]) or w["s"] - prev["e"] > 0.6:
            starts.append(w["s"])
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None or re.search(r"[.!?]$", w["w"]) or nxt["s"] - w["e"] > 0.6:
            ends.append(w["e"])
    return starts, ends


def _nearest(options: list[float], target: float, lo: float, hi: float) -> float | None:
    ok = [o for o in options if lo <= o <= hi]
    return min(ok, key=lambda o: abs(o - target)) if ok else None


def shape(m: Moment, words: list[dict], min_len: float, max_len: float, duration: float) -> None:
    """Pick start/end around the peak, snapped to sentence boundaries."""
    p = m.peak
    starts, ends = _boundaries(words)
    start = _nearest(starts, p - 12, p - (max_len - 4), p - 3)
    start = start if start is not None else p - 12
    end = _nearest(ends, p + 6, p + 2, start + max_len)
    end = end + 0.3 if end is not None else p + 6
    if end - start < min_len:
        earlier = _nearest(starts, end - min_len - 2, end - max_len, end - min_len)
        start = earlier if earlier is not None else end - min_len
    m.start = max(0.0, round(start - 0.15, 2))
    m.end = min(duration, round(end, 2))
    m.words = [w for w in words if m.start <= w["s"] < m.end]


def speech_hype(m: Moment) -> float:
    if not m.words:
        return 0.0
    text = " ".join(w["w"] for w in m.words)
    hits = len(HYPE_SPEECH.findall(text)) + len(HYPE_HINDI.findall(text)) + text.count("!")
    near = sum(1 for w in m.words if abs(w["s"] - m.peak) < 4
               and (HYPE_SPEECH.search(w["w"]) or HYPE_HINDI.search(w["w"])))
    density = len(m.words) / max(1.0, m.end - m.start)  # fast talking = excited
    return float(min(1.0, 0.12 * hits + 0.2 * near + 0.1 * max(0, density - 2.5)))


def pick(moments: list[Moment], n: int) -> list[Moment]:
    chosen: list[Moment] = []
    for m in sorted(moments, key=lambda x: -x.score):
        if all(m.end <= c.start or m.start >= c.end for c in chosen):
            chosen.append(m)
        if len(chosen) == n:
            break
    return sorted(chosen, key=lambda x: x.start)
