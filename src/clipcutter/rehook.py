"""Rewrite hooks/titles/captions for analyses made with an older writer (keeps moment ids and timings).

    uv run python -m clipcutter.rehook data/videos/<key>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import config, writer


def rehook(vdir: Path, cfg: dict) -> int:
    f = vdir / "analysis.json"
    a = json.loads(f.read_text())
    used: set[str] = set()
    for m in a["moments"]:
        meta = writer.write(m["transcript"], [], cfg, seed=int(m["peak"]), title=a["title"], avoid=used)
        used.add(meta["hook"].lower())
        m.update(meta)
        m["post_caption"] = f"{meta['description']} {' '.join(meta['hashtags'])}".strip()
    f.write_text(json.dumps(a, ensure_ascii=False))
    return len(a["moments"])


if __name__ == "__main__":
    cfg = config.load()
    for d in sys.argv[1:]:
        print(d, rehook(Path(d), cfg), "moments re-hooked")
