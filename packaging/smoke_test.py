"""CI smoke test for a built app: make a short local test video and clip it with the bundled CLI.

    python packaging/smoke_test.py <path to clipcutter-cli>

Uses only the standard library and the app's own ffmpeg/ffprobe, so it tests the bundle, not the runner.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

cli = Path(sys.argv[1]).resolve()
app_root = cli.parent.parent if cli.parent.name == "MacOS" else cli.parent
ext = ".exe" if sys.platform.startswith("win") else ""
ffmpeg = next(app_root.rglob(f"bin/ffmpeg{ext}"))
ffprobe = next(app_root.rglob(f"bin/ffprobe{ext}"))
work = Path(tempfile.mkdtemp(prefix="cc-smoke-"))
sample = work / "sample.mp4"

# 90 s test pattern; the tone gets loud for a few seconds every 30 s so the scorer finds a moment
subprocess.run([str(ffmpeg), "-v", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=90",
                "-f", "lavfi", "-i", "aevalsrc=0.05*sin(2*PI*440*t)*(1+12*between(mod(t\\,30)\\,20\\,24)):s=44100:d=90",
                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(sample)], check=True)

subprocess.run([str(cli), "run", str(sample), "--clips", "1", "--llm", "templates",
                "--whisper", "mlx-community/whisper-tiny-mlx"], cwd=work, check=True)

clips = sorted(work.glob("output/**/clip_01.mp4"))
assert clips, f"no clip made in {work / 'output'}"
info = json.loads(subprocess.run([str(ffprobe), "-v", "error", "-print_format", "json", "-show_streams",
                                  "-show_format", str(clips[0])], capture_output=True, text=True, check=True).stdout)
v = next(s for s in info["streams"] if s["codec_type"] == "video")
dur = float(info["format"]["duration"])
print(f"clip: {clips[0]}  {v['width']}x{v['height']}  {dur:.1f}s")
assert (v["width"], v["height"]) == (1080, 1920), "clip is not 9:16 1080x1920"
assert dur >= 5, "clip is too short"
assert any(s["codec_type"] == "audio" for s in info["streams"]), "clip has no audio"
print("smoke test passed")
