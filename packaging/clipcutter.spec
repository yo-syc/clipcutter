# PyInstaller spec for the ClipCutter desktop app.  Build with packaging/build_mac.sh or build_windows.ps1.
# Needs packaging/vendor/ (python packaging/fetch_vendor.py) and packaging/build/icon.* (make_icons.py).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

HERE = Path(SPECPATH)
ROOT = HERE.parent
VENDOR = HERE / "vendor"
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")
APPLE_SILICON = IS_MAC and __import__("platform").machine() == "arm64"
VERSION = __import__("os").environ.get("CLIPCUTTER_VERSION", "0.1.0")

# yt-dlp version, so the app can compare it with a downloaded update without importing yt_dlp twice
(HERE / "build").mkdir(exist_ok=True)
(HERE / "build" / "yt_dlp_version.txt").write_text(__import__("yt_dlp.version").version.__version__)

datas = [
    (str(HERE / "build" / "yt_dlp_version.txt"), "."),
    (str(ROOT / "src" / "clipcutter" / "web.html"), "clipcutter"),
    (str(ROOT / "config.example.yaml"), "."),
    (str(VENDOR / "fonts"), "fonts"),
]
if (ROOT / "assets").is_dir():
    datas.append((str(ROOT / "assets"), "assets"))
binaries = [(str(p), "bin") for p in (VENDOR / "bin").iterdir()]
binaries += [(str(p), "lib") for p in (VENDOR / "lib").iterdir()]

hiddenimports = [m for m in collect_submodules("clipcutter") if not m.startswith("clipcutter.site")]
hiddenimports += collect_submodules("yt_dlp")      # extractors are imported lazily

# speech-to-text: mlx-whisper on Apple Silicon, faster-whisper everywhere else
whisper_pkgs = ["mlx", "mlx_whisper"] if APPLE_SILICON else ["faster_whisper", "ctranslate2"]
for pkg in whisper_pkgs + ["certifi", "tiktoken", "tiktoken_ext"]:
    d, b, h = collect_all(pkg)
    datas += [x for x in d if "/include/" not in x[0].replace("\\", "/") and "/cmake/" not in x[0].replace("\\", "/")]
    binaries += b
    hiddenimports += h
if APPLE_SILICON:
    # core.so loads the top-level copy of libmlx.dylib, which looks for mlx.metallib right next to itself
    metallib = [d for d in datas if d[0].endswith("mlx.metallib")]
    datas = [d for d in datas if not d[0].endswith("mlx.metallib")] + [(metallib[0][0], ".")]
else:
    datas += collect_data_files("faster_whisper")   # silero VAD model

# facecam.py: OpenCV's Haar cascade XML files (cv2.data.haarcascades)
datas += [d for d in collect_data_files("cv2") if "haarcascade" in d[0]]

excludes = [
    "torch", "torchvision", "torchaudio",   # mlx-whisper imports torch only to convert models
    "sympy", "networkx", "IPython", "matplotlib", "pytest", "tkinter.test",
    "clipcutter.site", "fastapi", "uvicorn", "starlette", "uvloop", "watchfiles",
]

a = Analysis(
    [str(HERE / "app_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
cli = Analysis(
    [str(HERE / "cli_entry.py")],
    pathex=[str(ROOT / "src")],
    hiddenimports=hiddenimports,
    excludes=excludes,
)
pyz = PYZ(a.pure)
cli_pyz = PYZ(cli.pure)

icon = str(HERE / "build" / ("icon.icns" if IS_MAC else "icon.ico"))
# UTF-8 mode: Windows defaults files to cp1252, and clip JSON/captions contain emoji and Hindi
UTF8 = [("X utf8", None, "OPTION")]   # exact spelling: "X utf8_mode=1" is silently ignored
app_exe = EXE(
    pyz, a.scripts, UTF8,
    exclude_binaries=True,
    name="ClipCutter",
    console=False,            # no terminal window; logs go to <data folder>/logs/clipcutter.log
    icon=icon,
    upx=False,
    codesign_identity=None,
    entitlements_file=None,
)
cli_exe = EXE(
    cli_pyz, cli.scripts, UTF8,
    exclude_binaries=True,
    name="clipcutter-cli",
    console=True,             # for `clipcutter-cli doctor` etc. and the CI smoke test
    icon=icon,
    upx=False,
)
coll = COLLECT(
    app_exe, cli_exe,
    a.binaries, a.datas, cli.binaries, cli.datas,
    name="ClipCutter",
    upx=False,
)
if IS_MAC:
    app = BUNDLE(
        coll,
        name="ClipCutter.app",
        icon=icon,
        bundle_identifier="com.pandeymynk.clipcutter",
        version=VERSION,
        info_plist={
            "CFBundleName": "ClipCutter",
            "CFBundleDisplayName": "ClipCutter",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.video",
        },
    )
