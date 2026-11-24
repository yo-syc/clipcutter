# AGENTS.md — instructions for AI coding agents

This file is for AI agents (Antigravity, Claude Code, Cursor, Codex, Gemini CLI, Copilot, Windsurf, …).
Humans: start with [README.md](README.md) and [docs/SETUP.md](docs/SETUP.md).

## What this project is

ClipCutter turns a long video or stream (YouTube, Twitch, Kick, any site yt-dlp supports, or a local file)
into short vertical 9:16 clips: a **hook** first (the peak moment, zoomed, with big text and a bass hit),
then the **main** part (setup, then payoff), plus Gen Z word-by-word captions. It also writes a title,
post caption and hashtags. Everything runs locally; the only optional paid piece is an LLM for hook text.

## Setup and run (do this first)

```bash
# needs: uv, ffmpeg, Node.js (or Deno). See docs/SETUP.md per OS.
uv sync                              # install Python deps into .venv
uv run clipcutter doctor             # checks ffmpeg, JS runtime, fonts, Hindi support, speech model
uv run clipcutter serve              # web app at http://localhost:8787
uv run clipcutter run <url-or-file> --clips 2    # command-line, one video
```

The fastest end-to-end check is `uv run clipcutter run "https://www.youtube.com/watch?v=aqz-KE-bpKQ" --clips 1`
(Big Buck Bunny, Creative Commons). Output lands in `output/<source-id>/clip_01.mp4` + `clip_01.json`.

There is no unit-test suite yet. Verify changes by running the pipeline on a short video and looking at
frames, e.g. `ffmpeg -ss 3 -i output/<id>/clip_01.mp4 -frames:v 1 frame.png`.

## Code map (`src/clipcutter/`)

| file | job |
|---|---|
| `__init__.py` | CLI (`run`, `serve`, `add`, `track`, `discover`, `creators`, `doctor`, `dashboard`) |
| `pipeline.py` | the main flow: ingest → analyze → transcript → score → write hooks → render, with progress callbacks |
| `ingest.py` | yt-dlp downloads: full video (≤2 h) or audio-only (longer), platform captions (json3) → words |
| `analyze.py` | loudness, scene cuts, chat log parsing, speech-to-text (mlx-whisper / faster-whisper) |
| `score.py` | per-second signals → candidate moments → snap to sentence boundaries → pick N non-overlapping |
| `writer.py` | hook, title, caption, hashtags: Claude API, a free OpenAI-compatible key (NVIDIA/Groq/OpenRouter/Gemini, saved from the web app's "AI key" box into `ai-settings.json`), Ollama, or built-in templates (English + Hinglish) |
| `render.py` | caption/hook overlay PNGs (Pillow, emoji + Hindi), ffmpeg filter graph, 9:16 layouts |
| `facecam.py` | finds a webcam overlay so the clip can use the split layout |
| `system.py` | **all OS differences**: fonts, video encoder, hw decoding, whisper backend, JS runtime |
| `tracker.py` | creator tracker: `creators.yaml` + SQLite state, auto-clips new uploads |
| `server.py` + `web.html` | web app (stdlib HTTP server, one job worker thread, jobs persisted in `.work/jobs.json`) |
| `dashboard.py` | static HTML dashboard for the tracker |
| `cloud.py` | **website engine**: text-first analysis (captions + chat + "most replayed"), `render_moment`, editor edits |
| `site/app.py` | website API (FastAPI): accounts, plans/quotas, videos, clips, editor options |
| `site/worker.py` | website worker: analyse → render, live-chat enrichment thread, cleanup |
| `site/db.py` | SQLite schema + plans (`PLANS`) |
| `site/static/index.html` | landing page + app (single file, vanilla JS), PWA files next to it |
| `live.py` | **live mode**: ffmpeg records HLS in N-min segments, Twitch IRC / YouTube live-chat capture, per-segment clipping |
| `translit.py` | Devanagari Hindi -> Roman Hinglish for captions |
| `campaigns.py` | clipping-campaign presets (`--campaign`): on-screen label, CTA end card, logo overlay, censored captions, exact post caption. See docs/CAMPAIGNS.md |
| `config.py` | defaults; users override with `config.yaml` (see `config.example.yaml`) |
| `desktop.py` | **desktop app** launcher: chdir to the per-user data folder, start the web app, open the browser, small Tk window |
| `updater.py` | desktop app: downloads a newer yt-dlp wheel from PyPI into the data folder; `activate()` puts it before the bundled one |

## Desktop app (one-click install)

```bash
packaging/build_mac.sh                                         # -> dist/ClipCutter-<ver>-mac-<arch>.dmg
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1   # -> dist\ClipCutter-<ver>-windows-x64-setup.exe
```
PyInstaller (`packaging/clipcutter.spec`) bundles Python + deps; `packaging/fetch_vendor.py` downloads static ffmpeg/ffprobe,
deno, libfribidi and Noto fonts into `packaging/vendor/`. Two executables share one folder: `ClipCutter` (windowed:
`packaging/app_entry.py`, no args = desktop launcher) and `clipcutter-cli` (console, same CLI as `uv run clipcutter`).
CI: `.github/workflows/desktop.yml` builds mac arm64 and Windows (no Intel Mac: onnxruntime has no macOS x86_64 wheels), smoke-tests (`doctor` + `packaging/smoke_test.py`),
and a `v*` tag makes a **draft** release. User guide: [docs/INSTALL.md](docs/INSTALL.md).

## Website (multi-user)

```bash
uv run clipcutter site          # http://localhost:8000
uv run clipcutter site-worker   # in another terminal (one or many)
uv run clipcutter site-plan you@example.com creator --days 30   # give a plan (until payments exist)
```
Design: [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md) · deploy: [docs/DEPLOY.md](docs/DEPLOY.md).
Key rule: the website never downloads a whole video. It analyses text, then downloads only the ~60 s of a clip.

## How a clip is made (local CLI)

1. **Ingest:** for a URL, `ingest.py` downloads the full video once (fast, ~1 min for 20 min of video) plus the
   platform's **own captions** (YouTube `*-orig` auto-captions, json3 with per-word timing).
2. **Transcript:** if captions exist, no speech-to-text runs at all. Otherwise whisper transcribes the
   whole video in 5-minute chunks (≤90 min) or only candidate windows (longer streams).
3. **Signals per second:** loudness spikes, scene-cut rate, chat message spikes (if a chat log exists),
   speech hype (English + Hindi hype words, `!`, fast talking). `score.combine` weights them (`config.weights`).
4. **Moments:** top peaks, then `score.shape` snaps start/end to sentence boundaries (15–55 s).
5. **Hook text:** `writer.write` (LLM if configured, else templates matched to language and topic).
6. **Render:** `render.render` builds one ffmpeg filter graph: hook segment (zoomed) + main segment,
   then the layout (blur / crop / split facecam), then a PNG-sequence overlay (captions + hook box), plus a
   synthesized bass "boom" and loudness normalization to -14 LUFS.

## Rules and gotchas (learned the hard way)

- **YouTube downloads:** yt-dlp must have a JS runtime (`system.js_runtimes()` → node/deno), or YouTube returns
  HTTP 403. Resolve formats and download with the **same `YoutubeDL` instance**: info resolved by one
  instance and downloaded by another also gets 403.
- **Don't download per-clip sections for normal videos.** `download_ranges` + `force_keyframes_at_cuts`
  re-encodes from the network and took 6+ min per clip. Download the whole video once (≤2 h) and cut locally.
- **Prefer platform captions over whisper.** They are instant and spell names right ("GTA 6").
- **Hindi text:** Pillow needs raqm + **libfribidi** to join Devanagari correctly. On macOS, `__init__._enable_hindi_text`
  re-execs with `DYLD_FALLBACK_LIBRARY_PATH` pointing at Homebrew's lib. When cleaning caption words, keep
  `ऀ-ॿ`: Devanagari vowel signs are not `\w`, so a plain `[^\w]` regex deletes the matras.
- **Whisper loops** on music/silence in Hindi audio. Keep `temperature=(0.0, 0.4)` and
  `hallucination_silence_threshold=2.0` in `analyze.transcribe_window`.
- **OpenCV must stay `<5`**: v5 removed `CascadeClassifier`, which `facecam.py` uses.
- **Facecam rule:** only a small (<14% width), off-centre, stable face counts as a webcam overlay. A full-screen
  talking head must not trigger the split layout (it duplicates the face).
- **Web app jobs** are persisted and resume after a restart. Finished clips are skipped on resume
  (matched by start/end). `index.json` is rewritten after every clip so the UI shows clips as they finish.
- **Live recording:** YouTube live serves video and audio as separate HLS streams. Resolve both URLs with yt-dlp and
  let ffmpeg read + mux + segment them (`live._start_recorder`); piping yt-dlp to stdout fails for split formats.
  URLs expire (~6 h), so the session restarts the recorder while the stream is still live. Each run gets a fresh folder.
- **Live chat:** YouTube gift items (`giftMessageViewModel`) have no timestamp; they take the previous message's
  wall time. In live mode chat is mapped by wall-clock (`wall0`), never by the stream's own offsets.
- **Live quality gate:** `score.recommended` decides; weak moments are skipped before rendering (saves CPU + credits).
- **Campaign clips:** skip the just-chatting part of a stream with `--from`/`--to` (loudness alone picks intros/watch-alongs), and check frames before posting: briefs reject non-gameplay, misleading hooks and low quality.
- **Never block the pipeline on the LLM.** Any writer error falls back to the next provider, then templates (once per run).
- **Free model names change.** NVIDIA retired `meta/llama-3.3-70b-instruct` in Aug 2026. `writer.pick_model` asks the
  service's `/models` list when a key is saved; don't hard-code one model as the only choice.
- **Desktop bundle paths:** in the app, `system.FROZEN` is true and `system.BUNDLE` is `sys._MEIPASS`. `system.prepare_bundle()`
  puts `BUNDLE/bin` (ffmpeg, ffprobe, deno) first on PATH, so plain `"ffmpeg"` calls work; read-only files come from
  `system.resource_dir()` / `system.assets_dir()` (never `Path(__file__).parents[…]`, which points outside the bundle).
  User data goes in `system.user_data_dir()` (`~/Library/Application Support/ClipCutter`, `%APPDATA%\ClipCutter`).
- **Pillow loads libfribidi by bare name** (`libfribidi.dylib` on mac, `fribidi*.dll` on Windows). The mac app re-execs once
  with `DYLD_FALLBACK_LIBRARY_PATH=BUNDLE/lib` (dyld reads it only at start); Windows puts `BUNDLE/lib` on PATH.
- **mlx in PyInstaller:** `core.so` loads the top-level `libmlx.dylib`, which needs `mlx.metallib` next to it, else the app
  dies with SIGTRAP on `import mlx`. The spec moves the metallib to the bundle root.
- **Never import yt_dlp twice in one process** (e.g. import, delete from `sys.modules`, import again): its requests handler
  patches urllib3 on import, and a second patch breaks every download ("Urllib3PercentREOverride has no attribute sub").
  `updater.activate()` reads the bundled version from `yt_dlp_version.txt` for that reason.
- **Windowed Windows app:** no console, so `prepare_bundle()` hides ffmpeg console windows (CREATE_NO_WINDOW) and stdout
  goes to `<data>/logs/clipcutter.log`. Output is forced to UTF-8 (✅ and Hindi crash cp1252 pipes).
- **OS-specific code goes in `system.py` only.** Don't hard-code `/System/Library/...` or `videotoolbox` anywhere else.

## Conventions

- Python 3.12, standard library first; new dependencies need a good reason (this tool is meant to be cheap and local).
- Keep user-facing text short and friendly; hooks and captions default to Gen Z style (`style: genz`).
- `output/`, `.work/`, `config.yaml`, `creators.yaml` are user data: never commit them.
- Only clip content the user has rights to. Keep the per-creator `permission` flag, and gate any future auto-posting on it.

## Roadmap (good next tasks)

- LLM moment selection: send the full transcript to Claude and get back self-contained segments with scores (Opus-Clip style).
- Auto-posting via official APIs (YouTube Data API, Instagram Graph API, TikTok Content Posting API), gated by `permission`.
- GTA 6 game-event detection (WASTED / BUSTED / wanted-stars screens).
- Live mode: record a live stream in chunks and clip while it is still live.
- Tests: a tiny generated sample video + golden checks for `score.py` and `ingest.caption_words`.
