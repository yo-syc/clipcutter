"""Keep yt-dlp fresh in the desktop app.

Sites change often and old yt-dlp versions stop working. The app bundle is frozen (read-only, signed),
so a newer yt-dlp is downloaded from PyPI into the user's data folder and put in front of the bundled
copy on the next start. If the new copy fails to import, the bundled one is used.

    activate()        call once at startup, before anything imports yt_dlp
    update()          download the newest yt-dlp if it's newer (takes effect after a restart)
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import urllib.request
import zipfile

from . import system

PYPI = "https://pypi.org/pypi/yt-dlp/json"
_active: str | None = None   # version folder in use, if not the bundled one


def _ver(v: str) -> tuple[int, ...]:
    out = []
    for part in v.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits or 0))
    return tuple(out)


def bundled_version() -> str:
    """yt-dlp version shipped inside the app (written by activate())."""
    try:
        return (system.ytdlp_dir() / "bundled.txt").read_text().strip()
    except OSError:
        return current_version()


def current_version() -> str:
    try:
        from yt_dlp import version
        return version.__version__
    except Exception:
        return "?"


def _installed() -> str | None:
    f = system.ytdlp_dir() / "current.txt"
    try:
        v = f.read_text().strip()
    except OSError:
        return None
    return v if (system.ytdlp_dir() / v / "yt_dlp").is_dir() else None


def _bundled() -> str:
    """Version of the yt-dlp frozen into the app, read from a file written at build time.
    (Importing yt_dlp here and again later would apply its urllib3 patch twice and break downloads.)"""
    try:
        return (system.resource_dir() / "yt_dlp_version.txt").read_text().strip()
    except OSError:
        return "0"


def activate() -> str:
    """Use the downloaded yt-dlp if it is newer than the bundled one. Returns the version in use.
    Must run before anything imports yt_dlp."""
    global _active
    if not system.FROZEN or "yt_dlp" in sys.modules:
        return current_version()
    bundled = _bundled()
    try:
        system.ytdlp_dir().mkdir(parents=True, exist_ok=True)
        (system.ytdlp_dir() / "bundled.txt").write_text(bundled)
    except OSError:
        pass
    v = _installed()
    if not v or _ver(v) <= _ver(bundled):
        return bundled
    path = str(system.ytdlp_dir() / v)
    sys.path.insert(0, path)
    try:
        import yt_dlp  # noqa: F401
        import yt_dlp.extractor.youtube  # noqa: F401  (the part that breaks most)
        _active = v
        return v
    except Exception as e:  # noqa: BLE001
        print(f"downloaded yt-dlp {v} failed to load ({e}); using the bundled {bundled}", flush=True)
        sys.path.remove(path)
        for name in [m for m in sys.modules if m == "yt_dlp" or m.startswith("yt_dlp.")]:
            del sys.modules[name]
        (system.ytdlp_dir() / "current.txt").unlink(missing_ok=True)   # don't try the broken one again
        return bundled


def update(log=print) -> dict:
    """Download the newest yt-dlp wheel from PyPI if it's newer than what we have."""
    if not system.FROZEN:
        return {"ok": False, "msg": "Running from source: update with `uv lock --upgrade-package yt-dlp && uv sync`."}
    have = current_version()
    try:
        with urllib.request.urlopen(PYPI, timeout=20) as r:
            meta = json.load(r)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "msg": f"Couldn't reach PyPI: {e}"}
    latest = meta["info"]["version"]
    if _ver(latest) <= _ver(have) or latest == _installed():
        return {"ok": True, "msg": f"Downloader is up to date ({have}).", "version": have, "restart": latest == _installed() and latest != have}
    wheel = next((f for f in meta["urls"] if f["packagetype"] == "bdist_wheel" and f["filename"].endswith("py3-none-any.whl")), None)
    if not wheel:
        return {"ok": False, "msg": f"No wheel for yt-dlp {latest} on PyPI."}
    log(f"downloading yt-dlp {latest}…")
    try:
        with urllib.request.urlopen(wheel["url"], timeout=120) as r:
            data = r.read()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "msg": f"Download failed: {e}"}
    if hashlib.sha256(data).hexdigest() != wheel["digests"]["sha256"]:
        return {"ok": False, "msg": "Download was corrupted (checksum mismatch). Try again."}
    root = system.ytdlp_dir()
    dest = root / latest
    tmp = root / f".{latest}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for m in z.namelist():
            if m.startswith("yt_dlp/"):
                z.extract(m, tmp)
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    (root / "current.txt").write_text(latest)
    for old in root.iterdir():   # keep only the new one
        if old.is_dir() and old.name not in (latest, _active):   # the one in use stays until restart
            shutil.rmtree(old, ignore_errors=True)
    log(f"yt-dlp {latest} ready; restart ClipCutter to use it")
    return {"ok": True, "msg": f"Downloader updated {have} → {latest}. Restart ClipCutter to use it.",
            "version": latest, "restart": True}
