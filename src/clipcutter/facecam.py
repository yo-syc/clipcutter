"""Find the streamer's facecam overlay so the clip can use the split layout
(facecam on top, gameplay below) automatically."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from . import system


def _frames(video: Path, start: float, end: float, n: int = 10) -> list[np.ndarray]:
    import cv2

    out = []
    for t in np.linspace(start, max(start + 0.5, end), n):
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", *system.hwaccel_args(), "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
             "-vf", "scale=960:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True,
        ).stdout
        if raw:
            img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                out.append(img)
    return out


def detect(video: Path, start: float, end: float) -> list[float] | None:
    """Facecam box [x, y, w, h] (fractions of the frame) from the video itself, or None."""
    return find(_frames(video, start, end))


def detect_files(paths: list[Path]) -> list[float] | None:
    """Same, from saved still frames (e.g. YouTube storyboard frames), upscaled so small faces are found."""
    import cv2

    frames = []
    for p in paths:
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            frames.append(cv2.resize(img, (img.shape[1] * 3, img.shape[0] * 3), interpolation=cv2.INTER_CUBIC))
    return find(frames, min_neighbors=4)


def find(frames: list, min_neighbors: int = 6) -> list[float] | None:
    """A facecam is a small face that stays in the same spot in most frames
    (a full-screen "just chatting" face is not a facecam)."""
    import cv2

    if not frames:
        return None
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    H, W = frames[0].shape[:2]
    # every small face in every frame (game characters and on-screen people appear too)
    faces_all = []
    for i, f in enumerate(frames):
        for x, y, w, h in cascade.detectMultiScale(f, scaleFactor=1.1, minNeighbors=min_neighbors,
                                                   minSize=(int(W * 0.03),) * 2):
            if w <= W * 0.14:   # bigger = a full-screen camera shot, not a webcam overlay
                faces_all.append((i, x + w / 2, y + h / 2, w, h))
    # group faces by position: the facecam is the spot that has a face in the most frames
    clusters: list[list] = []
    for fc in faces_all:
        for c in clusters:
            cx0, cy0 = np.median([g[1] for g in c]), np.median([g[2] for g in c])
            if abs(fc[1] - cx0) < W * 0.06 and abs(fc[2] - cy0) < H * 0.09:
                c.append(fc)
                break
        else:
            clusters.append([fc])
    best = max(clusters, key=lambda c: len({g[0] for g in c}), default=None)
    if not best or len({g[0] for g in best}) < max(3, len(frames) * 0.35):
        return None
    cx, cy, fw, fh = np.median(np.array([g[1:] for g in best]), axis=0)
    if abs(cx - W / 2) < W * 0.2 and abs(cy - H / 2) < H * 0.25:
        return None  # centered face = the video itself is a camera shot, not a webcam overlay
    # expand the face box to a webcam-shaped crop (~ 4:3), clamp to frame
    cw, ch = min(fw * 3.2, W * 0.5), min(fh * 2.6, H * 0.6)
    x0 = max(0.0, min(cx - cw / 2, W - cw))
    y0 = max(0.0, min(cy - ch / 2, H - ch))
    return [round(x0 / W, 4), round(y0 / H, 4), round(cw / W, 4), round(ch / H, 4)]
