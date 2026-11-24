#!/usr/bin/env bash
# Build ClipCutter.app and a .dmg for this Mac's CPU (Apple Silicon; Intel Macs are unsupported: no onnxruntime wheels).
#   packaging/build_mac.sh            -> dist/ClipCutter-<version>-mac-<arch>.dmg
# Needs: uv, Homebrew (for libfribidi). Everything else is downloaded.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${CLIPCUTTER_VERSION:-$(grep -m1 '^version' pyproject.toml | cut -d'"' -f2)}"
export CLIPCUTTER_VERSION="$VERSION"
ARCH="$(uname -m)"   # arm64 | x86_64

brew list fribidi >/dev/null 2>&1 || brew install fribidi
uv sync --frozen
[ -f packaging/vendor/bin/ffmpeg ] || uv run --no-project python packaging/fetch_vendor.py
uv run python packaging/make_icons.py

rm -rf build/pyinstaller dist/ClipCutter dist/ClipCutter.app
uv run --with "pyinstaller>=6.10" pyinstaller packaging/clipcutter.spec \
    --noconfirm --distpath dist --workpath build/pyinstaller

APP=dist/ClipCutter.app
# Ad-hoc signature (free). Without an Apple Developer ID the first open needs right-click -> Open.
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

DMG="dist/ClipCutter-${VERSION}-mac-${ARCH}.dmg"
STAGE="build/dmg"
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "ClipCutter" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"
echo "built $DMG ($(du -h "$DMG" | cut -f1))"
