"""Entry point of the desktop app (ClipCutter.app / ClipCutter.exe).

No arguments (double-click) -> desktop launcher: web app + browser + small window.
With arguments              -> the normal command line, e.g. `ClipCutter doctor`.
"""
import multiprocessing
import sys

from clipcutter import system

if __name__ == "__main__":
    multiprocessing.freeze_support()
    system.prepare_bundle()          # bundled ffmpeg/deno on PATH, libfribidi for Hindi (may re-exec once)
    args = [a for a in sys.argv[1:] if not a.startswith("-psn_")]   # old macOS Finder adds -psn_…
    if args:
        from clipcutter import updater
        updater.activate()
        sys.argv = [sys.argv[0], *args]
        import clipcutter
        clipcutter.main()
    else:
        from clipcutter import desktop
        desktop.main()
