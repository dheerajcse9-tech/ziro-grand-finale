import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterable

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS subjects(id TEXT NOT NULL, tenant_id TEXT NOT NULL, name TEXT NOT NULL, description TEXT DEFAULT '', created_at REAL, PRIMARY KEY(tenant_id, id));
CREATE TABLE IF NOT EXISTS topics(id TEXT NOT NULL, tenant_id TEXT NOT NULL, subject_id TEXT NOT NULL, name TEXT NOT NULL, description TEXT DEFAULT '', position INTEGER DEFAULT 0, sample_questions TEXT DEFAULT '[]', created_at REAL, PRIMARY KEY(tenant_id, id));
CREATE TABLE IF NOT EXISTS resources(
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, subject_id TEXT NOT NULL, topic_id TEXT NOT NULL,
  type TEXT NOT NULL, title TEXT NOT NULL, url TEXT, file_path TEXT, youtube_id TEXT,
  origin TEXT DEFAULT 'uploaded', transcript_origin TEXT, attribution TEXT DEFAULT '',
  status TEXT DEFAULT 'pending', status_detail TEXT DEFAULT '', chunk_count INTEGER DEFAULT 0,
  content_hash TEXT, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS escalations(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, session_id TEXT, user_id TEXT,
  question TEXT NOT NULL, standalone_question TEXT, subject_id TEXT, topic_id TEXT, reason TEXT,
  evidence TEXT DEFAULT '[]', status TEXT DEFAULT 'pending', teacher_answer TEXT, teacher_id TEXT,
  teacher_note TEXT, created_at REAL, resolved_at REAL);
CREATE TABLE IF NOT EXISTS resolutions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, escalation_id INTEGER, question TEXT NOT NULL,
  answer TEXT NOT NULL, subject_id TEXT, topic_id TEXT, sources TEXT DEFAULT '[]', approved_by TEXT,
  status TEXT DEFAULT 'approved', created_at REAL);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL, user_id TEXT,
  role TEXT NOT NULL, content TEXT NOT NULL, payload TEXT, subject_id TEXT, topic_id TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS sessions(session_id TEXT NOT NULL, tenant_id TEXT NOT NULL, state TEXT DEFAULT '{}', updated_at REAL, PRIMARY KEY(session_id, tenant_id));
CREATE TABLE IF NOT EXISTS agent_configs(tenant_id TEXT PRIMARY KEY, config TEXT NOT NULL, updated_at REAL);
CREATE TABLE IF NOT EXISTS eval_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL, llm_mode TEXT, metrics TEXT, results TEXT);
CREATE TABLE IF NOT EXISTS video_segments(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, resource_id TEXT NOT NULL, title TEXT NOT NULL, topic TEXT DEFAULT '', subtopic TEXT DEFAULT '',
  start_s REAL NOT NULL, end_s REAL NOT NULL, explanation TEXT NOT NULL, keywords TEXT DEFAULT '[]', questions TEXT DEFAULT '[]', transcript_text TEXT DEFAULT '',
  verification TEXT DEFAULT 'unverified', content_hash TEXT, indexed_hash TEXT, UNIQUE(resource_id, start_s, end_s));
CREATE TABLE IF NOT EXISTS agent_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, run_id TEXT NOT NULL, session_id TEXT, seq INTEGER NOT NULL, ts REAL, t_ms INTEGER,
  type TEXT NOT NULL, agent TEXT NOT NULL, status TEXT NOT NULL, title TEXT DEFAULT '', escalation_id INTEGER, data TEXT DEFAULT '{}');
CREATE INDEX IF NOT EXISTS ix_ev_run ON agent_events(tenant_id, run_id, seq);
CREATE INDEX IF NOT EXISTS ix_res_tenant ON resources(tenant_id, topic_id);
CREATE INDEX IF NOT EXISTS ix_esc_tenant ON escalations(tenant_id, status);
CREATE INDEX IF NOT EXISTS ix_msg_sess ON messages(tenant_id, session_id);
"""


@contextmanager
def conn():
    c = sqlite3.connect(get_settings().db_path, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    get_settings().db_path.parent.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)
        if "duration_s" not in [r[1] for r in c.execute("PRAGMA table_info(resources)")]:
            c.execute("ALTER TABLE resources ADD COLUMN duration_s REAL")
        if "filename" not in [r[1] for r in c.execute("PRAGMA table_info(resources)")]:
            c.execute("ALTER TABLE resources ADD COLUMN filename TEXT")
        if "timestamp_source" not in [r[1] for r in c.execute("PRAGMA table_info(video_segments)")]:
            c.execute("ALTER TABLE video_segments ADD COLUMN timestamp_source TEXT DEFAULT ''")


def rows(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(sql, tuple(params)).fetchall()]


def row(sql: str, params: Iterable[Any] = ()) -> dict | None:
    r = rows(sql, params)
    return r[0] if r else None


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with conn() as c:
        return c.execute(sql, tuple(params)).lastrowid


def now() -> float:
    return time.time()


def dumps(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False)


def loads(s: str | None, default: Any = None) -> Any:
    try:
        return json.loads(s) if s else default
    except json.JSONDecodeError:
        return default
