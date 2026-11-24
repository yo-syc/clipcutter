"""Database: SQLite (WAL) to start; the queue is just rows (no Redis). See docs/SYSTEM_DESIGN.md."""
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DATA = Path(os.environ.get("CLIPCUTTER_DATA", "data")).resolve()
DB_PATH = DATA / "clipcutter.db"

PLANS = {
    # clips per month, max video length (s), watermark, live minutes per session, label, price per month / year (₹)
    "free":    {"clips": 10,  "max_len": 3 * 3600,  "watermark": True,  "live_min": 30,  "label": "Free",    "month": 0,    "year": 0},
    "starter": {"clips": 50,  "max_len": 24 * 3600, "watermark": False, "live_min": 720, "label": "Starter", "month": 199,  "year": 1990},
    "creator": {"clips": 150, "max_len": 24 * 3600, "watermark": False, "live_min": 720, "label": "Creator", "month": 499,  "year": 4990},
    "pro":     {"clips": 500, "max_len": 24 * 3600, "watermark": False, "live_min": 720, "label": "Pro",     "month": 1499, "year": 14990},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL,
  plan TEXT NOT NULL DEFAULT 'free', plan_until REAL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created REAL NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS videos (            -- shared by all users (cache)
  key TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT, duration REAL,
  status TEXT NOT NULL DEFAULT 'queued',      -- queued | working | ready | failed
  step TEXT, pct REAL DEFAULT 0, error TEXT, claimed REAL, created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS user_videos (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, video_key TEXT NOT NULL REFERENCES videos(key),
  created REAL NOT NULL, PRIMARY KEY (user_id, video_key));
CREATE TABLE IF NOT EXISTS clips (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  video_key TEXT NOT NULL REFERENCES videos(key), moment_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',      -- queued | working | done | failed | expired
  step TEXT, pct REAL DEFAULT 0, path TEXT, error TEXT, watermark INTEGER NOT NULL DEFAULT 0,
  priority INTEGER NOT NULL DEFAULT 0, claimed REAL, created REAL NOT NULL, updated REAL NOT NULL,
  UNIQUE (user_id, video_key, moment_id));
CREATE TABLE IF NOT EXISTS live_sessions (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  url TEXT NOT NULL, title TEXT, status TEXT NOT NULL DEFAULT 'queued',   -- queued | recording | ended | failed | stopped
  step TEXT, clips INTEGER NOT NULL DEFAULT 0, stop INTEGER NOT NULL DEFAULT 0, error TEXT,
  created REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS clips_queue ON clips(status, priority DESC, created);
CREATE INDEX IF NOT EXISTS videos_queue ON videos(status, created);
CREATE INDEX IF NOT EXISTS clips_user ON clips(user_id, created);
"""


def connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)  # autocommit; explicit BEGIN when needed
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    return con


@contextmanager
def tx():
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def init() -> None:
    con = connect()
    con.executescript(SCHEMA)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(videos)")}
    if "enrich" not in cols:   # phase-2 live-chat state: NULL | pending | working | done | skipped
        con.execute("ALTER TABLE videos ADD COLUMN enrich TEXT")
        con.execute("ALTER TABLE videos ADD COLUMN enrich_claimed REAL")
    ccols = {r["name"] for r in con.execute("PRAGMA table_info(clips)")}
    if "opts" not in ccols:   # editor choices (JSON)
        con.execute("ALTER TABLE clips ADD COLUMN opts TEXT")
    if "meta" not in ccols:   # live clips carry their own hook/caption (no analysis.json)
        con.execute("ALTER TABLE clips ADD COLUMN meta TEXT")
    con.close()


def month_start(ts: float | None = None) -> float:
    t = time.localtime(ts or time.time())
    return time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))


def plan_of(user: sqlite3.Row) -> dict:
    name = user["plan"]
    if name != "free" and user["plan_until"] and user["plan_until"] < time.time():
        name = "free"  # paid plan expired
    return {"name": name, **PLANS.get(name, PLANS["free"])}


def clips_used(con: sqlite3.Connection, user_id: int) -> int:
    """Clips this calendar month that count: anything not failed (failed = refunded)."""
    return con.execute("SELECT COUNT(*) FROM clips WHERE user_id=? AND created>=? AND status!='failed'",
                       (user_id, month_start())).fetchone()[0]
