"""Settings: defaults merged with an optional config.yaml."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

DEFAULTS: dict = {
    "clips": 5,                 # how many clips to make per stream
    "min_len": 15,              # seconds (main part, hook not counted)
    "max_len": 55,
    "style": "genz",            # genz | hype | clean
    "layout": "auto",           # auto (facecam -> split, else blur) | blur | crop | split
    "facecam": None,            # for split layout: [x, y, w, h] as fractions of the frame
    "chat_delay": 5,            # chat reacts a few seconds after the moment
    "weights": {"chat": 0.40, "audio": 0.25, "speech": 0.20, "visual": 0.15},
    "whisper_model": "mlx-community/whisper-large-v3-turbo",
    "language": None,           # None = auto-detect
    "llm": {
        "provider": "auto",     # auto | claude | openai | ollama | templates
        "model": "claude-opus-5-5",
        "ollama_model": "llama3.2",
    },
    "hook": {"enabled": True, "seconds": 2.5, "zoom": 1.2, "boom": True},
    "captions": {
        "enabled": True,
        "words_per_chunk": 3,
        "lang": "auto",         # auto/hinglish: Hindi becomes Roman Hinglish · original: keep the script
        "font": None,           # None = auto (Arial Black on mac/Windows, DejaVu Sans Bold on Linux)
        "size": 88,
        "color": "#FFFFFF",
        "highlight": "#FFE600",
        "y": 1220,              # Reels/Shorts safe zone: bottom ~35% is covered by the app's caption + buttons
    },
    "header": True,             # keep hook text as a small header for the whole clip
    "video": {"width": 1080, "height": 1920, "fps": 30, "bitrate": "8M"},
    "output_dir": "output",
    "work_dir": ".work",
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


AI_FILE = Path("ai-settings.json")   # the web app's "AI key" box (kept out of config.yaml; never commit it)


def load_ai() -> dict:
    try:
        return json.loads(AI_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_ai(service: str | None, key: str | None, model: str | None = None) -> dict:
    """Save (or with service=None, remove) the AI key. Returns what's stored."""
    if not service:
        AI_FILE.unlink(missing_ok=True)
        return {}
    from .writer import AI_SERVICES, pick_model
    svc = AI_SERVICES[service]
    data = {"service": service, "api_base": svc["base"], "api_key": key.strip(),
            "api_model": (model or "").strip() or pick_model(service, svc["base"], key.strip())}
    AI_FILE.write_text(json.dumps(data, indent=1))
    try:
        AI_FILE.chmod(0o600)
    except OSError:
        pass
    return data


def apply_ai(cfg: dict) -> dict:
    """Put the saved AI key into cfg['llm'] (config.yaml's llm.api_* settings win if set)."""
    ai = load_ai()
    llm = cfg["llm"]
    if ai.get("api_key") and not llm.get("api_key"):
        llm.update(api_base=ai["api_base"], api_key=ai["api_key"], api_model=ai["api_model"],
                   api_service=ai.get("service", "openai"))
    return cfg


def load(path: str | None = None) -> dict:
    candidates = [Path(path)] if path else [Path("config.yaml")]
    for p in candidates:
        if p.exists():
            return apply_ai(_merge(DEFAULTS, yaml.safe_load(p.read_text()) or {}))
    return apply_ai(copy.deepcopy(DEFAULTS))
