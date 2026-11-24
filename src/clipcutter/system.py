"""Everything that differs between macOS, Windows and Linux: fonts, video encoder, speech model."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")
APPLE_SILICON = IS_MAC and platform.machine() == "arm64"
WINFONTS = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"

# ---------- desktop app (PyInstaller bundle) ----------
# In the installed app, ffmpeg, ffprobe, deno, fonts and libfribidi ship inside the bundle.
# sys._MEIPASS is that folder (ClipCutter.app/Contents/Frameworks on mac, the _internal folder on Windows).
FROZEN = bool(getattr(sys, "frozen", False))
BUNDLE = Path(getattr(sys, "_MEIPASS", "")) if FROZEN else None
REPO = Path(__file__).resolve().parents[2]


def resource_dir() -> Path:
    """Where read-only files live: the bundle in the app, the repo when run from source."""
    return BUNDLE if FROZEN else REPO


def assets_dir() -> Path:
    return resource_dir() / "assets"


def user_data_dir() -> Path:
    """Per-user folder for output/, .work/, config.yaml, creators.yaml (never inside the app)."""
    if os.environ.get("CLIPCUTTER_HOME"):
        return Path(os.environ["CLIPCUTTER_HOME"]).expanduser()
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "ClipCutter"
    if IS_WIN:
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "ClipCutter"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "clipcutter"


def ytdlp_dir() -> Path:
    """Newer yt-dlp downloaded by the app lives here, outside the frozen bundle (see updater.py)."""
    return user_data_dir() / "yt-dlp"


def prepare_bundle() -> None:
    """Call first thing in the desktop app: put bundled tools on PATH and make Pillow find libfribidi."""
    if not FROZEN:
        return
    bin_dir, lib_dir = BUNDLE / "bin", BUNDLE / "lib"
    for stream in (sys.stdout, sys.stderr):   # Windows pipes default to cp1252: ✅ and Hindi would crash
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    os.environ["PATH"] = os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])
    try:   # python-build-standalone has no system CA list: use certifi's (yt-dlp, model download)
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except ImportError:
        pass
    if IS_WIN:
        _no_console_windows()
    if IS_WIN and lib_dir.is_dir():
        os.environ["PATH"] = os.pathsep.join([str(lib_dir), os.environ["PATH"]])
        os.add_dll_directory(str(lib_dir))
    if IS_MAC and lib_dir.is_dir() and not os.environ.get("CLIPCUTTER_LIBS"):
        # Pillow dlopen()s libfribidi by bare name; dyld reads the search path only at process start.
        env = dict(os.environ, CLIPCUTTER_LIBS="1",
                   DYLD_FALLBACK_LIBRARY_PATH=f"{lib_dir}:/usr/local/lib:/usr/lib")
        os.execve(sys.executable, [sys.executable, *sys.argv[1:]], env)


def _no_console_windows() -> None:
    """The Windows app has no console, so each ffmpeg call would flash a black window. Hide them."""
    orig = subprocess.Popen.__init__
    if getattr(orig, "_cc", False):
        return

    def init(self, *a, **k):
        k.setdefault("creationflags", 0x08000000)   # CREATE_NO_WINDOW
        if k.get("stdin") is None and "input" not in k:
            k["stdin"] = subprocess.DEVNULL
        orig(self, *a, **k)
    init._cc = True
    subprocess.Popen.__init__ = init


def bundled(name: str) -> Path | None:
    """A file shipped inside the app (bin/ffmpeg, fonts/…), or None when running from source."""
    if not FROZEN:
        return None
    p = BUNDLE / name
    return p if p.exists() else None


def _first(cands):
    for c in cands:
        path = c[0] if isinstance(c, tuple) else c
        if path and Path(path).exists():
            return c
    return None


# Bold caption/hook font (Latin text)
BOLD_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    str(WINFONTS / "ariblk.ttf"), str(WINFONTS / "arialbd.ttf"),
    "/usr/share/fonts/truetype/msttcorefonts/Arial_Black.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    str(resource_dir() / "fonts" / "NotoSans-Black.ttf"),         # shipped in the desktop app
]
# Hindi / Devanagari (path, index inside .ttc)
HINDI_FONTS = [
    ("/System/Library/Fonts/Kohinoor.ttc", 3),                 # Kohinoor Devanagari Bold
    ("/System/Library/Fonts/Supplemental/DevanagariMT.ttc", 1),
    (str(WINFONTS / "NirmalaB.ttf"), 0), (str(WINFONTS / "Nirmala.ttc"), 1), (str(WINFONTS / "mangalb.ttf"), 0),
    ("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansDevanagari-Bold.ttf", 0),
    ("/usr/share/fonts/noto/NotoSansDevanagari-Bold.ttf", 0),
    ("/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf", 0),
    (str(resource_dir() / "fonts" / "NotoSansDevanagari-Bold.ttf"), 0),   # shipped in the desktop app
]
EMOJI_FONTS = [
    "/System/Library/Fonts/Apple Color Emoji.ttc",
    str(WINFONTS / "seguiemj.ttf"),
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf",
]


def bold_font(configured: str | None = None) -> str:
    if configured and Path(configured).exists():
        return configured
    f = _first(BOLD_FONTS)
    if not f:
        raise SystemExit("No bold font found. Set captions.font in config.yaml to a .ttf file "
                         "(see docs/SETUP.md).")
    return f


def hindi_font() -> tuple[str, int] | None:
    return _first(HINDI_FONTS)


def emoji_font() -> str | None:
    return _first(EMOJI_FONTS)


# ---------- video ----------

@lru_cache(maxsize=None)
def _encoders() -> str:
    try:
        return subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        raise SystemExit("ffmpeg is not installed. See docs/SETUP.md.")


def encoder_args(bitrate: str) -> list[str]:
    """Hardware H.264 encoder when there is one (much faster), else libx264."""
    enc = _encoders()
    if IS_MAC and "h264_videotoolbox" in enc:
        return ["-c:v", "h264_videotoolbox", "-b:v", bitrate, "-profile:v", "high"]
    if "h264_nvenc" in enc and shutil.which("nvidia-smi"):
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-b:v", bitrate]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]


def hwaccel_args() -> list[str]:
    """Decode on the GPU/media engine where it's reliable (macOS)."""
    return ["-hwaccel", "videotoolbox"] if IS_MAC else []


# ---------- speech-to-text ----------

def whisper_backend() -> str:
    return "mlx" if APPLE_SILICON else "faster-whisper"


def js_runtimes() -> dict:
    """yt-dlp needs a JavaScript runtime to download from YouTube (else HTTP 403).
    The desktop app ships deno; give yt-dlp its full path so it never picks up a broken system one."""
    rt = {}
    for name in ("deno", "node"):
        path = shutil.which(name)
        if path:
            rt[name] = {"path": path} if FROZEN else {}
    return rt


def text_shaping_ok() -> bool:
    """Hindi needs complex text shaping (Pillow + raqm + fribidi)."""
    try:
        from PIL import features
        return bool(features.check("raqm"))
    except Exception:
        return False
