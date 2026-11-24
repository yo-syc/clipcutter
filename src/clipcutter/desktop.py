"""Desktop app: double-click -> local web app starts and the browser opens.

A small window stays open while ClipCutter runs (close it to quit). User files live in
system.user_data_dir(), never inside the app.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from . import system, updater

PORT = 8787
UPDATE_EVERY = 24 * 3600   # check for a newer yt-dlp once a day


def _running_here(port: int) -> bool:
    """Is a ClipCutter already serving on this port (e.g. the app was opened twice)?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/app", timeout=2) as r:
            return json.load(r).get("app") == "clipcutter"
    except Exception:
        return False


def _free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _log_to_file(home: Path) -> Path:
    """A windowed app has no terminal: keep a log the user can send when something breaks."""
    logs = home / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / "clipcutter.log"
    if path.exists() and path.stat().st_size > 5_000_000:
        path.replace(logs / "clipcutter.old.log")
    f = open(path, "a", buffering=1, encoding="utf-8", errors="replace")
    sys.stdout = sys.stderr = f
    print(f"\n==== ClipCutter started {time.strftime('%Y-%m-%d %H:%M:%S')} ====", flush=True)
    return path


def _auto_update() -> None:
    stamp = system.ytdlp_dir() / "last_check"
    try:
        if time.time() - stamp.stat().st_mtime < UPDATE_EVERY:
            return
    except OSError:
        pass
    try:
        print("yt-dlp:", updater.update()["msg"], flush=True)
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.touch()
    except Exception as e:  # noqa: BLE001
        print(f"yt-dlp update check failed: {e}", flush=True)


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if system.IS_MAC:
        subprocess.Popen(["open", str(path)])
    elif system.IS_WIN:
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def main() -> None:
    home = system.user_data_dir()
    home.mkdir(parents=True, exist_ok=True)
    os.chdir(home)                       # output/, .work/, config.yaml, creators.yaml all live here
    log_path = _log_to_file(home) if system.FROZEN else None
    ytdlp = updater.activate()

    port = PORT
    if _running_here(port):
        webbrowser.open(f"http://localhost:{port}")
        return
    while not _free(port):
        port += 1
    url = f"http://localhost:{port}"

    from . import server
    srv = server.make_server(port, "127.0.0.1")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=_auto_update, daemon=True).start()
    print(f"ClipCutter running at {url}  (data: {home}, yt-dlp {ytdlp})", flush=True)
    if not os.environ.get("CLIPCUTTER_NO_BROWSER"):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception:   # no Tk: just keep serving
        while True:
            time.sleep(3600)

    root = tk.Tk()
    root.title("ClipCutter")
    root.resizable(False, False)
    bg, fg, accent = "#0e0e12", "#f2f2f5", "#ffe600"
    root.configure(bg=bg, padx=22, pady=18)
    tk.Label(root, text="ClipCutter is running", font=("Helvetica", 17, "bold"), bg=bg, fg=fg).pack(anchor="w")
    tk.Label(root, text=f"Open {url} in your browser.\nKeep this window open while clips are being made.",
             justify="left", bg=bg, fg="#a8a8b3").pack(anchor="w", pady=(4, 12))

    status = tk.StringVar(value=f"Downloader (yt-dlp): {ytdlp}")

    def do_update():
        status.set("Checking for a newer downloader…")

        def work():
            res = updater.update()
            root.after(0, lambda: status.set(res["msg"]))
        threading.Thread(target=work, daemon=True).start()

    def quit_app():
        srv.shutdown()
        root.destroy()

    def btn(text, cmd, primary=False):
        b = tk.Button(root, text=text, command=cmd, width=26, highlightbackground=bg,
                      font=("Helvetica", 13, "bold" if primary else "normal"))
        if primary and not system.IS_MAC:   # mac buttons ignore colours
            b.configure(bg=accent, fg="#000")
        b.pack(anchor="w", pady=3)

    btn("Open ClipCutter", lambda: webbrowser.open(url), primary=True)
    btn("Show my clips folder", lambda: open_folder(home / "output"))
    btn("Update downloader", do_update)
    if log_path:
        btn("Show log file", lambda: open_folder(log_path.parent))
    btn("Quit", quit_app)
    tk.Label(root, textvariable=status, bg=bg, fg="#a8a8b3", wraplength=300, justify="left").pack(anchor="w", pady=(10, 0))

    def on_close():
        if messagebox.askokcancel("Quit ClipCutter?", "Unfinished jobs carry on next time you open the app."):
            quit_app()
    root.protocol("WM_DELETE_WINDOW", on_close)
    if system.IS_MAC:
        root.createcommand("tk::mac::Quit", quit_app)
        root.createcommand("tk::mac::ReopenApplication", lambda: (root.deiconify(), webbrowser.open(url)))
    root.mainloop()
