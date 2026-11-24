"""Web app: paste a link, watch it clip, manage tracked creators. Standard library only.

    clipcutter serve            -> http://localhost:8787
"""
from __future__ import annotations

import json
import mimetypes
import queue
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import analyze, config, pipeline, system, tracker, updater, writer

UI = Path(__file__).with_name("web.html")


class Jobs:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.items: dict[str, dict] = {}
        self.q: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        self.save_lock = threading.Lock()
        self.path = Path(cfg["work_dir"]) / "jobs.json"
        self._load()
        threading.Thread(target=self._worker, daemon=True).start()

    def _load(self) -> None:
        """Jobs survive an app restart: unfinished ones go back in the queue (cached steps are skipped)."""
        try:
            saved = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        for job in sorted(saved, key=lambda j: j["created"]):
            if job["status"] in ("running", "queued"):
                job.update(status="queued", step="Resuming after restart…", pct=0, started=None)
                self.q.put(job["id"])
            self.items[job["id"]] = job

    def save(self) -> None:
        with self.save_lock:   # worker + request threads both save; one temp file at a time
            with self.lock:
                data = sorted(self.items.values(), key=lambda j: -j["created"])[:50]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, default=str))
            tmp.replace(self.path)

    def add(self, kind: str, label: str, **params) -> dict:
        job = {"id": uuid.uuid4().hex[:8], "kind": kind, "label": label, "params": params,
               "status": "queued", "log": [], "created": time.time(), "out": None,
               "step": "Waiting in line…", "pct": 0, "started": None, "finished": None}
        with self.lock:
            self.items[job["id"]] = job
        self.q.put(job["id"])
        self.save()
        return job

    def _log(self, job: dict, msg: str) -> None:
        print(msg, flush=True)
        job["log"].append(str(msg))
        del job["log"][:-200]

    def _worker(self) -> None:
        while True:
            job = self.items[self.q.get()]
            if job.get("cancel"):
                job.update(status="stopped", step="Stopped before starting", finished=time.time())
                self.save()
                continue
            job["status"] = "running"
            job["started"] = time.time()
            job["step"], job["pct"] = "Starting…", 0
            pipeline.progress = lambda step, pct, j=job: j.update(step=step, pct=round(pct, 1))
            pipeline.on_source = lambda title, j=job: j.update(title=title)
            pipeline.cancelled = lambda j=job: bool(j.get("cancel"))
            analyze.on_model_progress = lambda text, j=job: j.update(step=text)
            self.save()
            pipeline.log = lambda m, j=job: self._log(j, f"[{time.strftime('%H:%M:%S')}] {m}")
            try:
                cfg = json.loads(json.dumps(self.cfg))
                p = job["params"]
                if p.get("clips"):
                    cfg["clips"] = int(p["clips"])
                if job["kind"] == "run":
                    out_dir, index = pipeline.run(p["url"], cfg)
                    job["out"] = {"dir": str(out_dir), "clips": len(index)}
                elif job["kind"] == "track":
                    tracker.run(cfg, backfill=1, log=lambda m, j=job: self._log(j, m))
                job["status"] = "done"
                job["pct"] = 100
                if job["kind"] == "track":
                    job["step"] = "Check finished"
            except pipeline.Cancelled:
                self._log(job, "stopped by user")
                job["status"], job["step"] = "stopped", "Stopped. Clips made so far are kept."
            except BaseException as e:  # noqa: BLE001 (SystemExit from tracker included)
                self._log(job, f"error: {type(e).__name__}: {e}")
                (Path(self.cfg["work_dir"]) / "errors.log").open("a").write(traceback.format_exc())
                job["status"] = "failed"
                job["step"] = f"{type(e).__name__}: {e}"[:200]
            job["finished"] = time.time()
            self.save()

    def cancel(self, job_id: str) -> dict:
        job = self.items.get(job_id)
        if not job:
            raise KeyError("no such job")
        if job["status"] in ("running", "queued"):
            job["cancel"] = True
            job["step"] = "Stopping after the current step…"
            self.save()
        return job

    def public(self) -> list[dict]:
        with self.lock:
            jobs = sorted(self.items.values(), key=lambda j: -j["created"])[:20]
        return [{k: v for k, v in j.items() if k != "params"} | {"log": j["log"][-30:]} for j in jobs]


def all_clips(cfg: dict) -> list[dict]:
    root = Path(cfg["output_dir"])
    clips = []
    for idx in root.glob("**/index.json"):
        try:
            for c in json.loads(idx.read_text()):
                c["src"] = "/files/" + str((idx.parent / c["file"]).relative_to(root))
                c["mtime"] = (idx.parent / c["file"]).stat().st_mtime
                clips.append(c)
        except (OSError, ValueError):
            continue
    return sorted(clips, key=lambda c: -c["mtime"])


def make_handler(cfg: dict, jobs: Jobs):
    out_root = Path(cfg["output_dir"]).resolve()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                body = UI.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/app":
                self._json({"app": "clipcutter", "desktop": system.FROZEN, "ytdlp": updater.current_version(),
                            "data_dir": str(Path.cwd())})
            elif path == "/api/ai":
                ai = config.load_ai()
                k = ai.get("api_key", "")
                self._json({"services": {n: {"name": s["name"], "keys": s["keys"], "model": s["model"]}
                                         for n, s in writer.AI_SERVICES.items()},
                            "current": {"service": ai.get("service"), "model": ai.get("api_model"),
                                        "key": (k[:4] + "…" + k[-4:]) if len(k) > 12 else ("set" if k else "")}})
            elif path == "/api/state":
                self._json({"jobs": jobs.public(), "clips": all_clips(cfg), "creators": tracker.summary(cfg)})
            elif path.startswith("/files/"):
                self._file(out_root / unquote(path[len("/files/"):]))
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                data = self._body()
                if path == "/api/run":
                    url = (data.get("url") or "").strip()
                    if not url.startswith("http"):
                        return self._json({"error": "paste a full link (https://…)"}, 400)
                    return self._json(jobs.add("run", url, url=url, clips=data.get("clips")))
                if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                    return self._json(jobs.cancel(path.split("/")[3]))
                if path == "/api/ai":
                    service, key = data.get("service"), (data.get("key") or "").strip()
                    if not service:   # remove the key
                        config.save_ai(None, None)
                        msg = "AI key removed. Built-in hooks will be used."
                    else:
                        if service not in writer.AI_SERVICES or len(key) < 10:
                            return self._json({"error": "pick a service and paste the whole key"}, 400)
                        svc = writer.AI_SERVICES[service]
                        trial = {"api_base": svc["base"], "api_key": key,
                                 "api_model": (data.get("model") or "").strip()
                                 or writer.pick_model(service, svc["base"], key)}
                        try:
                            writer.test_key(trial)
                        except Exception as e:  # noqa: BLE001
                            reason = getattr(e, "code", None)
                            hint = {401: "the key is wrong or expired", 403: "the key is wrong, or it has no access to this model",
                                    404: "model not found, try another model name", 410: "that model was retired, leave the model box empty",
                                    429: "free limit reached, try again later"}.get(reason, str(e)[:160])
                            return self._json({"error": f"Key didn't work: {hint}"}, 400)
                        config.save_ai(service, key, trial["api_model"])
                        msg = f"Saved ✓ Hooks will now be written by {svc['name']} ({trial['api_model']})."
                    for k in ("api_base", "api_key", "api_model", "api_service"):
                        cfg["llm"].pop(k, None)
                    config.apply_ai(cfg)
                    writer._FAILED.discard("openai")
                    return self._json({"ok": True, "msg": msg})
                if path == "/api/update-downloader":
                    return self._json(updater.update())
                if path == "/api/track":
                    return self._json(jobs.add("track", "check all creators for new videos"))
                if path == "/api/creators":
                    c = tracker.add(data["url"].strip(), data.get("name") or None,
                                    data.get("keyword") or None, bool(data.get("permission")))
                    return self._json(c)
                if path == "/api/creators/remove":
                    return self._json({"removed": tracker.remove(data["who"])})
            except SystemExit as e:
                return self._json({"error": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            self._json({"error": "not found"}, 404)

        def _file(self, p: Path):
            p = p.resolve()
            if out_root not in p.parents or not p.is_file():
                return self._json({"error": "not found"}, 404)
            size = p.stat().st_size
            start, end = 0, size - 1
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                a, _, b = rng[6:].partition("-")
                start = int(a) if a else max(0, size - int(b))
                end = int(b) if a and b else size - 1
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(p.name)[0] or "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            with p.open("rb") as f:
                f.seek(start)
                left = end - start + 1
                try:
                    while left > 0:
                        chunk = f.read(min(1 << 20, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass

    return H


def make_server(port: int = 8787, host: str = "127.0.0.1", cfg_path: str | None = None) -> ThreadingHTTPServer:
    cfg = config.load(cfg_path)
    jobs = Jobs(cfg)
    return ThreadingHTTPServer((host, port), make_handler(cfg, jobs))


def serve(port: int = 8787, host: str = "127.0.0.1", cfg_path: str | None = None) -> None:
    srv = make_server(port, host, cfg_path)
    print(f"ClipCutter running at http://localhost:{port}  (ctrl+c to stop)", flush=True)
    srv.serve_forever()
