# Setup guide

ClipCutter runs on **macOS, Windows and Linux**. It's fastest on Apple Silicon Macs (M1–M5), because both video
and speech-to-text run on the Mac's hardware.

You need four things: **Git**, **uv** (installs Python for you), **ffmpeg** (video), and **Node.js** (YouTube
downloads need it). The setup scripts below install them for you.

---

## Option A: one command (recommended)

### macOS / Linux

```bash
git clone https://github.com/pandeymynk/clipcutter.git
cd clipcutter
bash scripts/setup.sh
```

### Windows (PowerShell)

```powershell
git clone https://github.com/pandeymynk/clipcutter.git
cd clipcutter
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

When it finishes, start the app:

```bash
uv run clipcutter serve
```

Then open **http://localhost:8787**, paste a YouTube link, and press **Make clips ⚡**.

---

## Option B: step by step

### macOS

1. Install [Homebrew](https://brew.sh) if you don't have it.
2. Install the tools:
   ```bash
   brew install uv ffmpeg node fribidi
   ```
   (`fribidi` makes Hindi captions render correctly.)
3. In the project folder:
   ```bash
   uv sync
   uv run clipcutter doctor
   ```

### Windows 10 / 11

1. Open **PowerShell** and install the tools with winget:
   ```powershell
   winget install --id astral-sh.uv -e
   winget install --id Gyan.FFmpeg -e
   winget install --id OpenJS.NodeJS.LTS -e
   winget install --id Git.Git -e
   ```
2. **Close and reopen PowerShell**, so the new commands are found.
3. In the project folder:
   ```powershell
   uv sync
   uv run clipcutter doctor
   ```

Notes for Windows:
- Captions use Arial Black, Hindi uses Nirmala UI, and emoji use Segoe UI Emoji. All of these ship with Windows.
- If `doctor` says *Hindi text shaping* is missing, Hindi captions still work, but some matras may sit in the wrong
  place. Hinglish hooks (Roman letters) are not affected.
- With an NVIDIA GPU, video encoding (NVENC) and speech-to-text (CUDA) are used automatically. Otherwise the CPU is used.

### Linux (Ubuntu / Debian)

```bash
sudo apt update
sudo apt install -y ffmpeg nodejs git libfribidi0 fonts-dejavu-core fonts-noto-color-emoji fonts-noto-core
curl -LsSf https://astral.sh/uv/install.sh | sh     # installs uv
uv sync
uv run clipcutter doctor
```

(`fonts-noto-core` includes Noto Sans Devanagari for Hindi captions.)

---

## Check your install

```bash
uv run clipcutter doctor
```

You should see ✅ for ffmpeg, the JS runtime, the caption font and speech-to-text. ⚠️ items are optional.

| Problem | Fix |
|---|---|
| `HTTP Error 403` when downloading from YouTube | Install Node.js (or Deno), then restart the app |
| Hindi captions show boxes □□□ | Install a Devanagari font (Linux: `fonts-noto-core`) |
| Hindi matras in the wrong place | macOS: `brew install fribidi`. Linux: `apt install libfribidi0` |
| Clips render slowly | Close other heavy apps (video renders, games); `doctor` shows whether a hardware encoder is used |
| `ffmpeg not found` | Install ffmpeg, then open a new terminal |

---

## Using it

### Web app (easiest)

```bash
uv run clipcutter serve          # http://localhost:8787
```

- **Clip a link:** paste a link, choose how many clips, then press Make clips. A loader shows each step, and clips appear in the
  Library as soon as each one is ready.
- **Library:** every clip with its virality score, plus **Copy caption** and **Download** buttons.
- **Creators:** add channel links. Their new videos get clipped automatically (press *Check all now*, or run the tracker below).

To use it from your phone on the same Wi-Fi: `uv run clipcutter serve --host 0.0.0.0`, then open `http://<your-computer-ip>:8787`.

### Command line

```bash
uv run clipcutter run "https://www.youtube.com/watch?v=..." --clips 3
uv run clipcutter run my_stream.mp4 --layout split --style genz

uv run clipcutter discover "gta 6 live"              # find popular channels
uv run clipcutter add https://www.youtube.com/@name --keyword gta
uv run clipcutter track --every 30                   # check creators every 30 min and clip new videos
```

### Settings

Copy `config.example.yaml` to `config.yaml` and change what you like: number of clips, clip length, layout
(`auto`, `blur`, `crop`, `split`), style (`genz`, `hype`, `clean`), caption size and colour, and more.

### AI-written hooks (optional)

By default, hooks come from built-in Gen Z lines (free, in English or Hinglish depending on the video). For hooks
written from what's actually said in the clip, use either:

- **Claude** (best quality, about ₹1 or less per video with Haiku): set `ANTHROPIC_API_KEY` before starting
  - macOS / Linux: `export ANTHROPIC_API_KEY=sk-ant-...`
  - Windows: `setx ANTHROPIC_API_KEY sk-ant-...` (then open a new terminal)
  - For the cheapest option, set `llm.model: claude-haiku-5-5` in `config.yaml`.
- **Ollama** (free, runs locally): install from [ollama.com](https://ollama.com), run `ollama pull llama3.2`, and set
  `llm.provider: ollama` in `config.yaml`.

---

## Using it with an AI coding agent (Antigravity, Claude Code, Cursor, …)

Open the folder in your agent. The agent reads **[AGENTS.md](../AGENTS.md)** automatically. It explains the setup
commands, the code map, how to test, and the known pitfalls. Then just ask, for example:

> "Set this project up on my machine and run `clipcutter doctor`."
> "Clip this video into 3 clips: https://youtube.com/watch?v=…"
> "Add auto-posting to YouTube Shorts."

---

## Please clip responsibly

Only post clips of content you own or have permission to use (for example, a streamer's official clipper
program). Re-uploading other people's videos without permission leads to copyright strikes.
