"""
YOUTUBE AUTOMATION v2.0 — Base de datos SQLite
Modelo inspirado en Labsia (projects + scenes) y ampliado para modo fábrica,
publicación y cola de la extensión Chrome. Todo local, sin créditos.
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from config import DB_PATH


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL DEFAULT 'Sin título',
    status        TEXT NOT NULL DEFAULT 'draft',
    -- draft|queued|scripting|images|tts|align|render|subtitles|ready|failed|published
    mode          TEXT NOT NULL DEFAULT 'idea',          -- script|idea|url|audio
    style         TEXT NOT NULL DEFAULT 'auto',
    format        TEXT NOT NULL DEFAULT 'short',         -- short|long
    voice         TEXT,
    tts_provider  TEXT,
    source_url    TEXT,
    video_url     TEXT,
    thumbnail_url TEXT,
    youtube_id    TEXT,
    error         TEXT,
    progress      INTEGER NOT NULL DEFAULT 0,
    step_label    TEXT,
    meta          TEXT NOT NULL DEFAULT '{}',            -- JSON libre
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scenes (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    idx          INTEGER NOT NULL DEFAULT 0,
    title        TEXT NOT NULL DEFAULT '',
    narration    TEXT NOT NULL DEFAULT '',
    image_prompt TEXT NOT NULL DEFAULT '',
    image_path   TEXT,
    audio_path   TEXT,
    duration     REAL NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'pending',        -- pending|image|audio|done|failed
    meta         TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS kv (            -- ajustes + config fábrica + ideas
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS jobs (          -- trabajos pipeline en curso/histórico
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'pipeline',       -- pipeline|render|publish|import
    status     TEXT NOT NULL DEFAULT 'running',        -- running|done|failed|cancelled
    progress   INTEGER NOT NULL DEFAULT 0,
    step       TEXT,
    message    TEXT,
    error      TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ext_images (    -- cola Plan B desde la extensión Chrome
    id         TEXT PRIMARY KEY,
    project_id TEXT,
    url        TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'imagefx',
    used       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS avatars (       -- personajes consistentes del canal
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',  -- personalidad / rol del personaje
    appearance   TEXT NOT NULL DEFAULT '{}',-- JSON: piel, ojos, cabello, cuerpo, vestuario
    voice        TEXT,                      -- voz edge-tts asociada
    tts_provider TEXT,                      -- edge | gemini
    style        TEXT,                      -- estilo visual por defecto
    image_path   TEXT,                      -- retrato generado
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scenes_project ON scenes(project_id, idx);
"""


def init_db() -> None:
    with connect() as con:
        con.executescript(SCHEMA)
        _migrate(con)


def _migrate(con: sqlite3.Connection) -> None:
    """Migraciones incrementales seguras (ALTER solo si falta la columna)."""
    cols = [r[1] for r in con.execute("PRAGMA table_info(projects)").fetchall()]
    if "avatar_id" not in cols:
        con.execute("ALTER TABLE projects ADD COLUMN avatar_id TEXT")
    if "platforms" not in cols:
        con.execute("ALTER TABLE projects ADD COLUMN platforms TEXT NOT NULL DEFAULT '[]'")


# ── helpers genéricos ─────────────────────────────────────────────────────
def row_to_dict(row: sqlite3.Row, parse_json: bool = True) -> dict:
    d = dict(row)
    if parse_json and "meta" in d and isinstance(d.get("meta"), str):
        try:
            d["meta"] = json.loads(d["meta"] or "{}")
        except json.JSONDecodeError:
            d["meta"] = {}
    return d


def kv_get(key: str, default: Any = None) -> Any:
    with connect() as con:
        row = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return default


def kv_set(key: str, value: Any) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO kv(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )


# ── proyectos ─────────────────────────────────────────────────────────────
def create_project(**fields) -> dict:
    pid = new_id()
    fields = {"id": pid, "created_at": now(), "updated_at": now(), **fields}
    fields = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
              for k, v in fields.items()}
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    with connect() as con:
        con.execute(f"INSERT INTO projects({cols}) VALUES({marks})", tuple(fields.values()))
    return get_project(pid)


def get_project(pid: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if not row:
        return None
    d = row_to_dict(row)
    if isinstance(d.get("platforms"), str):
        try:
            d["platforms"] = json.loads(d["platforms"] or "[]")
        except json.JSONDecodeError:
            d["platforms"] = []
    return d


def update_project(pid: str, **fields) -> None:
    fields["updated_at"] = now()
    fields = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
              for k, v in fields.items()}
    sets = ", ".join(f"{k}=?" for k in fields)
    with connect() as con:
        con.execute(f"UPDATE projects SET {sets} WHERE id=?", (*fields.values(), pid))


def list_projects(limit: int = 100) -> list[dict]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM projects ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        d = row_to_dict(r)
        if isinstance(d.get("platforms"), str):
            try:
                d["platforms"] = json.loads(d["platforms"] or "[]")
            except json.JSONDecodeError:
                d["platforms"] = []
        out.append(d)
    return out


def delete_project(pid: str) -> None:
    with connect() as con:
        con.execute("DELETE FROM scenes WHERE project_id=?", (pid,))
        con.execute("DELETE FROM jobs WHERE project_id=?", (pid,))
        con.execute("DELETE FROM projects WHERE id=?", (pid,))


# ── escenas ───────────────────────────────────────────────────────────────
def replace_scenes(pid: str, scenes: list[dict]) -> None:
    with connect() as con:
        con.execute("DELETE FROM scenes WHERE project_id=?", (pid,))
        for i, sc in enumerate(scenes):
            con.execute(
                """INSERT INTO scenes(id, project_id, idx, title, narration,
                   image_prompt, duration, status, meta)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (new_id(), pid, i, sc.get("title", ""), sc.get("narration", ""),
                 sc.get("image_prompt", ""), sc.get("duration", 0),
                 sc.get("status", "pending"), json.dumps(sc.get("meta", {}))),
            )


def get_scenes(pid: str) -> list[dict]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM scenes WHERE project_id=? ORDER BY idx", (pid,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def update_scene(scene_id: str, **fields) -> None:
    fields = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
              for k, v in fields.items()}
    sets = ", ".join(f"{k}=?" for k in fields)
    with connect() as con:
        con.execute(f"UPDATE scenes SET {sets} WHERE id=?", (*fields.values(), scene_id))


def reorder_scenes(pid: str, scene_ids: list[str]) -> None:
    with connect() as con:
        for i, sid in enumerate(scene_ids):
            con.execute("UPDATE scenes SET idx=? WHERE id=? AND project_id=?", (i, sid, pid))


# ── jobs ──────────────────────────────────────────────────────────────────
def create_job(project_id: str, kind: str = "pipeline") -> str:
    jid = new_id()
    with connect() as con:
        con.execute(
            "INSERT INTO jobs(id, project_id, kind, created_at, updated_at) VALUES(?,?,?,?,?)",
            (jid, project_id, kind, now(), now()),
        )
    return jid


def update_job(jid: str, **fields) -> None:
    fields["updated_at"] = now()
    sets = ", ".join(f"{k}=?" for k in fields)
    with connect() as con:
        con.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), jid))


def get_job(jid: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    return row_to_dict(row) if row else None


def active_job_for_project(pid: str) -> dict | None:
    with connect() as con:
        row = con.execute(
            "SELECT * FROM jobs WHERE project_id=? AND status='running' "
            "ORDER BY created_at DESC LIMIT 1", (pid,)
        ).fetchone()
    return row_to_dict(row) if row else None


# ── cola de la extensión Chrome (Plan B imágenes) ─────────────────────────
def add_ext_image(url: str, project_id: str | None = None, source: str = "imagefx") -> str:
    eid = new_id()
    with connect() as con:
        con.execute(
            "INSERT INTO ext_images(id, project_id, url, source, created_at) VALUES(?,?,?,?,?)",
            (eid, project_id, url, source, now()),
        )
    return eid


def take_ext_image(project_id: str | None = None) -> dict | None:
    q = "SELECT * FROM ext_images WHERE used=0"
    args: list = []
    if project_id:
        q += " AND (project_id IS NULL OR project_id=?)"
        args.append(project_id)
    q += " ORDER BY created_at LIMIT 1"
    with connect() as con:
        row = con.execute(q, args).fetchone()
        if not row:
            return None
        con.execute("UPDATE ext_images SET used=1 WHERE id=?", (row["id"],))
    return dict(row)


def count_ext_images(project_id: str | None = None) -> int:
    with connect() as con:
        if project_id:
            row = con.execute(
                "SELECT COUNT(*) c FROM ext_images WHERE used=0 "
                "AND (project_id IS NULL OR project_id=?)", (project_id,)).fetchone()
        else:
            row = con.execute("SELECT COUNT(*) c FROM ext_images WHERE used=0").fetchone()
    return row["c"]


# ── avatars (personajes consistentes) ──────────────────────────────────────
def create_avatar(**fields) -> dict:
    aid = new_id()
    fields = {"id": aid, "created_at": now(), "updated_at": now(), **fields}
    fields = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v)
              for k, v in fields.items()}
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    with connect() as con:
        con.execute(f"INSERT INTO avatars({cols}) VALUES({marks})", tuple(fields.values()))
    return get_avatar(aid)


def get_avatar(aid: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM avatars WHERE id=?", (aid,)).fetchone()
    return _avatar_dict(row) if row else None


def list_avatars() -> list[dict]:
    with connect() as con:
        rows = con.execute("SELECT * FROM avatars ORDER BY created_at DESC").fetchall()
    return [_avatar_dict(r) for r in rows]


def update_avatar(aid: str, **fields) -> None:
    fields["updated_at"] = now()
    fields = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v)
              for k, v in fields.items()}
    sets = ", ".join(f"{k}=?" for k in fields)
    with connect() as con:
        con.execute(f"UPDATE avatars SET {sets} WHERE id=?", (*fields.values(), aid))


def delete_avatar(aid: str) -> None:
    with connect() as con:
        con.execute("DELETE FROM avatars WHERE id=?", (aid,))
    # los proyectos conservan avatar_id huérfano → el pipeline lo ignora


def _avatar_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if isinstance(d.get("appearance"), str):
        try:
            d["appearance"] = json.loads(d["appearance"] or "{}")
        except json.JSONDecodeError:
            d["appearance"] = {}
    return d


# ── KPIs para el dashboard ────────────────────────────────────────────────
def stats() -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with connect() as con:
        q = lambda sql, *a: con.execute(sql, a).fetchone()["c"]  # noqa: E731
        return {
            "total": q("SELECT COUNT(*) c FROM projects"),
            "today": q("SELECT COUNT(*) c FROM projects WHERE created_at LIKE ?", today + "%"),
            "ready": q("SELECT COUNT(*) c FROM projects WHERE status='ready'"),
            "published": q("SELECT COUNT(*) c FROM projects WHERE youtube_id IS NOT NULL"),
            "failed": q("SELECT COUNT(*) c FROM projects WHERE status='failed'"),
            "minutes": round(q(
                "SELECT COALESCE(SUM(duration),0) c FROM ("
                " SELECT (j.value) AS duration FROM projects p, json_each(p.meta,'$.durations') j)"
            ) / 60, 1),
        }


init_db()
