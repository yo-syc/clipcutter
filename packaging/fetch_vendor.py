"""Download the tools the desktop app ships with into packaging/vendor/ (standard library only).

    python packaging/fetch_vendor.py [--fribidi PATH]

vendor/bin    ffmpeg, ffprobe, deno            (static builds for this OS + CPU)
vendor/lib    libfribidi (Hindi text shaping for Pillow's raqm)
vendor/fonts  Noto Sans Black + Noto Sans Devanagari Bold (+ OFL license)
"""
from __future__ import annotations

import argparse
import io
import platform
import shutil
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path

VENDOR = Path(__file__).resolve().parent / "vendor"
IS_MAC, IS_WIN = sys.platform == "darwin", sys.platform.startswith("win")
ARM = platform.machine().lower() in ("arm64", "aarch64")

NOTO = "https://cdn.jsdelivr.net/gh/notofonts/notofonts.github.io/fonts"
FONTS = {
    "NotoSans-Black.ttf": f"{NOTO}/NotoSans/hinted/ttf/NotoSans-Black.ttf",
    "NotoSansDevanagari-Bold.ttf": f"{NOTO}/NotoSansDevanagari/hinted/ttf/NotoSansDevanagari-Bold.ttf",
    "OFL.txt": "https://raw.githubusercontent.com/notofonts/devanagari/main/OFL.txt",
}
DENO = "https://github.com/denoland/deno/releases/latest/download/deno-{}.zip"


def get(url: str) -> bytes:
    print("  get", url, flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "clipcutter-build"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def final_url(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "clipcutter-build"})   # (HEAD gives 404 here)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.geturl()


def unzip_member(data: bytes, name: str, dest: Path) -> None:
    """Extract the file whose basename is `name` from a zip into dest (any folder depth)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        m = next(i for i in z.namelist() if i.rsplit("/", 1)[-1] == name)
        dest.write_bytes(z.read(m))
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def ffmpeg(bin_dir: Path) -> None:
    if IS_MAC:   # static macOS builds (arm64 + Intel) by Martin Riedl
        arch = "arm64" if ARM else "amd64"
        ff = final_url(f"https://ffmpeg.martin-riedl.de/redirect/latest/macos/{arch}/release/ffmpeg.zip")
        unzip_member(get(ff), "ffmpeg", bin_dir / "ffmpeg")
        unzip_member(get(ff.replace("/ffmpeg.zip", "/ffprobe.zip")), "ffprobe", bin_dir / "ffprobe")
    elif IS_WIN:  # static GPL build (has libx264) by BtbN
        data = get("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip")
        unzip_member(data, "ffmpeg.exe", bin_dir / "ffmpeg.exe")
        unzip_member(data, "ffprobe.exe", bin_dir / "ffprobe.exe")
    else:
        raise SystemExit("desktop builds are for macOS and Windows")


def deno(bin_dir: Path) -> None:
    triple = ("aarch64-apple-darwin" if ARM else "x86_64-apple-darwin") if IS_MAC else "x86_64-pc-windows-msvc"
    name = "deno.exe" if IS_WIN else "deno"
    unzip_member(get(DENO.format(triple)), name, bin_dir / name)


def fribidi(lib_dir: Path, src: str | None) -> None:
    if IS_MAC:
        cands = [src] if src else [f"{p}/lib/libfribidi.0.dylib" for p in ("/opt/homebrew", "/usr/local")]
        path = next((Path(c) for c in cands if c and Path(c).exists()), None)
        if not path:
            raise SystemExit("libfribidi not found: brew install fribidi")
        # Pillow dlopen()s "libfribidi.dylib" by bare name
        shutil.copyfile(path.resolve(), lib_dir / "libfribidi.dylib")
    elif IS_WIN:
        path = Path(src or r"C:\msys64\mingw64\bin\libfribidi-0.dll")
        if not path.exists():
            raise SystemExit(f"{path} not found: pacman -S mingw-w64-x86_64-fribidi (MSYS2), or pass --fribidi")
        for name in ("fribidi.dll", "fribidi-0.dll", "libfribidi-0.dll"):   # names Pillow may look for
            shutil.copyfile(path, lib_dir / name)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fribidi", help="path to libfribidi (.dylib / .dll)")
    args = ap.parse_args()
    shutil.rmtree(VENDOR, ignore_errors=True)
    bin_dir, lib_dir, font_dir = (VENDOR / d for d in ("bin", "lib", "fonts"))
    for d in (bin_dir, lib_dir, font_dir):
        d.mkdir(parents=True)
    print("ffmpeg + ffprobe"); ffmpeg(bin_dir)
    print("deno"); deno(bin_dir)
    print("libfribidi"); fribidi(lib_dir, args.fribidi)
    print("fonts")
    for name, url in FONTS.items():
        (font_dir / name).write_bytes(get(url))
    for f in sorted(VENDOR.rglob("*")):
        if f.is_file():
            print(f"  {f.relative_to(VENDOR)}  {f.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
