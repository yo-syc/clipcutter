# Install ClipCutter (desktop app)

No Python, no ffmpeg, no terminal. Download one file, install, double-click.

## 1. Download

Go to the [Releases page](https://github.com/pandeymynk/clipcutter/releases/latest) and pick the file for your computer:

| Your computer | File |
|---|---|
| Mac with an Apple chip (M1, M2, M3, M4…) | `ClipCutter-<version>-mac-arm64.dmg` |
| Mac with an Intel chip | not supported right now (see below) |
| Windows 10 / 11 (64-bit) | `ClipCutter-<version>-windows-x64-setup.exe` |

Not sure which Mac you have? Apple menu  → **About This Mac**. "Chip: Apple M…" means Apple chip; "Processor: Intel" means Intel.
Intel Macs aren't supported at the moment: the speech-to-text engine's parts (onnxruntime) no longer ship for Intel Macs.

The download is big (about 350–450 MB) because everything is inside: the video tools, the downloader, fonts
(Hindi too) and the speech-to-text engine.

## 2. Install

### Mac

1. Open the `.dmg` file.
2. Drag **ClipCutter** onto the **Applications** folder.
3. Open **Applications** and double-click **ClipCutter**.

**"ClipCutter can't be opened because Apple cannot check it for malicious software"** (or "…developer cannot be verified"):
this shows up because the app isn't signed with a paid Apple certificate (see [below](#why-the-security-warnings)). To open it anyway:

- **Right-click** (or Control-click) ClipCutter in Applications → **Open** → **Open**. Or:
- Try to open it once, then go to **System Settings → Privacy & Security**, scroll down, and click **Open Anyway** next to
  the ClipCutter message. Enter your Mac password if asked.

You only need to do this the first time.

### Windows

1. Double-click `ClipCutter-…-setup.exe`.
2. **"Windows protected your PC"** (blue SmartScreen box): click **More info** → **Run anyway**.
   It appears because the installer isn't signed with a paid certificate (see [below](#why-the-security-warnings)).
3. Click through the installer. It installs for your user only, so no admin password is needed.
4. Open **ClipCutter** from the Start menu (or the desktop shortcut).

If Windows Firewall asks about ClipCutter, you can click **Cancel**: the app only talks to your own computer
(`localhost`). Allow it only if you want to open ClipCutter from your phone on the same Wi-Fi.

## 3. First run

- A small **ClipCutter** window opens and your browser opens **http://localhost:8787**. Keep the small window open
  while clips are being made; close it to quit.
- Paste a YouTube / Twitch / Kick link and press **Make clips**.
- **The first video takes longer.** If the video has no captions, ClipCutter downloads its speech-to-text model once
  (about 0.5–1.6 GB). The progress shows in the job card: "Downloading the speech model (first time only): 43%".
- Your clips are saved in:
  - Mac: `~/Library/Application Support/ClipCutter/output`
  - Windows: `%APPDATA%\ClipCutter\output`

  The small window has a **Show my clips folder** button. Uninstalling the app does **not** delete your clips.

## When downloads stop working

YouTube and other sites change often, and the downloader (yt-dlp) has to keep up. ClipCutter checks for a newer
downloader once a day by itself. If a link fails with a download error:

1. Click **↻ Update downloader** at the bottom of the web page (or **Update downloader** in the small window).
2. Quit ClipCutter and open it again.

If it still fails, the site may have changed in the last day or two: wait for a yt-dlp fix, then update again.
Nobody can promise every link works every day.

## Settings (optional)

Copy `config.example.yaml` from the [repo](https://github.com/pandeymynk/clipcutter/blob/main/config.example.yaml) to
your ClipCutter folder (paths above, one level up from `output`) as `config.yaml` and change what you want.

### Free AI key (optional)

Without a key, hooks and titles come from ClipCutter's built-in Gen Z lines. That's free and works offline. For an AI
writing hooks for each clip, add a **free** key:

1. Scroll to the **🔑 AI key** box at the bottom of the ClipCutter page.
2. Pick a service. **NVIDIA** (build.nvidia.com), **Groq**, **OpenRouter** and **Google Gemini** all have free keys.
3. Click **Get a free key →**, sign in there, create a key and copy it.
4. Paste it in the box and press **Test & save**. ClipCutter checks the key and picks a good model by itself.

The key stays on your computer (`ai-settings.json` in your ClipCutter folder). Never share it or show it in a video.
Free keys have rate limits. If a key stops working, ClipCutter falls back to built-in hooks, so clips still get made.

## Something's wrong?

- The small window has **Show log file**. The log is at `…/ClipCutter/logs/clipcutter.log`.
- Power users: the app has a command line too. Mac: `/Applications/ClipCutter.app/Contents/MacOS/clipcutter-cli doctor`.
  Windows: `"%LOCALAPPDATA%\Programs\ClipCutter\clipcutter-cli.exe" doctor`. It checks every part and prints ✅ / ❌.
- Open an issue on GitHub with the log.

## Why the security warnings?

macOS and Windows warn about apps that aren't **code-signed** by a verified, paying developer. ClipCutter is free
and open source, and signing costs money every year, so the builds are unsigned for now. The warnings go away only with:

| | What's needed | Rough cost |
|---|---|---|
| **Mac** | Apple Developer Program membership (gives a "Developer ID" certificate), then sign the app and send it to Apple for **notarization** (an automatic malware scan, free with the membership). | **US$99 / year** |
| **Windows** | A code-signing certificate from a certificate authority (Sectigo, DigiCert, SSL.com, …), now always on a hardware token or cloud HSM. Or Microsoft's Azure Trusted Signing where available to you. Even signed, a brand-new app can show SmartScreen until it builds up download reputation. | about **US$120–500 / year** (Azure Trusted Signing from about US$10 / month) |

Once a certificate exists, the build scripts (`packaging/build_mac.sh`, `packaging/build_windows.ps1`) are the place to add
signing; the GitHub workflow would read the certificate from repository secrets.

## For developers: build the installers yourself

PyInstaller can't cross-compile, so each OS builds its own installer.

```bash
# Mac (Apple Silicon). Needs uv + Homebrew.
packaging/build_mac.sh                 # -> dist/ClipCutter-<version>-mac-<arch>.dmg
```

```powershell
# Windows. Needs uv, MSYS2 (for libfribidi) and Inno Setup 6.
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1   # -> dist\ClipCutter-<version>-windows-x64-setup.exe
```

On GitHub, `.github/workflows/desktop.yml` builds Mac (Apple Silicon) and Windows, smoke-tests each build (`doctor` +
clipping a generated test video), and when you push a tag like `v0.2.0` puts all installers on a **draft** release.
Check it, then press **Publish**.
