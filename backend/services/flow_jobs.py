"""
Flow Jobs — cola persistente de generación de assets para la extensión Chrome.

Cierra el circuito REAL backend → extensión (Google Flow) → backend → render:

  1. enqueue_project() crea los jobs desde flow_export.build_script_json()
     (ÚNICA fuente de prompts — blindada por el contrato P1: el video_prompt
     del Creative Engine llega verbatim, flow_export nunca lo reemplaza).
  2. La extensión hace claim con GET /api/extension/flow/jobs/next
     (atómico: BEGIN IMMEDIATE + job_token nonce + lease por tipo).
  3. Heartbeat renueva el lease; complete sube el binario (PNG validado con
     PIL, MP4 validado con ffprobe) y lo guarda con la convención canónica:
         data/output/<pid>/flow/Escena_NN_flow.png
         data/output/<pid>/flow/Escena_NN_video_<part>.mp4
  4. Al completarse TODOS los jobs del proyecto, los assets se mapean a las
     escenas (image_path) y el endpoint dispara orchestrator.start_flow_render()
     automáticamente.

Semántica de fallos: fail() incrementa attempts; al agotar el máximo
(imagen 3, video 2) el job pasa a dead. Un job claimed cuyo lease expira
(worker muerto) vuelve a queued automáticamente en el próximo claim
(recuperación perezosa, sin contador de intentos).
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import database as db
from config import OUTPUT_DIR
from pipeline.flow_export import DEFAULT_BRAND, build_script_json

# ── parámetros del contrato (lease / reintentos) ─────────────────────────────
LEASE_S = {"image": 8 * 60, "video": 15 * 60}
MAX_ATTEMPTS = {"image": 3, "video": 2}
HEARTBEAT_EXTEND_S = 5 * 60          # heartbeat del worker cada ~30s
MIN_VIDEO_S = 0.3                    # igual que flow_import.find_flow_videos

IMG_FORMAT_EXT = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _token() -> str:
    return uuid.uuid4().hex


def _row_to_job(row) -> dict:
    d = dict(row)
    try:
        d["prompt_meta"] = json.loads(d.get("prompt_meta") or "{}")
    except (TypeError, ValueError):
        d["prompt_meta"] = {}
    return d


# ── helpers de prompt (fuente única: build_script_json) ──────────────────────

def _image_prompt_text(ip) -> str:
    """Aplana el image_prompt del ScriptData a un prompt textual para Flow."""
    if isinstance(ip, str):
        return ip.strip()
    if not isinstance(ip, dict):
        return ""
    parts: list[str] = []
    subj = ip.get("subjects")
    if isinstance(subj, list) and subj:
        parts.append("; ".join(str(s) for s in subj if s))
    for fld in ("environment", "lighting", "composition", "style"):
        v = ip.get(fld)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
        elif isinstance(v, list) and v:
            parts.append("; ".join(str(x) for x in v if x))
    return " | ".join(p for p in parts if p)


def _video_prompt_text(vp) -> str:
    """motion (+ cámara) del ScriptData — verbatim por contrato P1."""
    if isinstance(vp, str):
        return vp.strip()
    if not isinstance(vp, dict):
        return ""
    motion = (vp.get("motion") or "").strip()
    cam = (vp.get("camera_movement") or "").strip()
    return f"{motion}\nCamera: {cam}" if motion and cam else motion or cam


# ── encolado ─────────────────────────────────────────────────────────────────

def enqueue_project(pid: str, fmt: str = "transformacion",
                    brand: str | None = None,
                    character: str | None = None) -> dict:
    """(Re)genera la cola del proyecto desde build_script_json.

    Idempotente: borra jobs pendientes (queued/claimed) y conserva los done,
    para que re-encolar no re-trabaje assets ya subidos."""
    project = db.get_project(pid)
    if not project:
        raise LookupError(f"proyecto {pid} no existe")
    scenes = db.get_scenes(pid)
    if not scenes:
        raise ValueError("el proyecto no tiene escenas aún")

    data = build_script_json(project, scenes,
                             fmt=fmt if fmt in ("transformacion", "generic",
                                                "artesano") else "transformacion",
                             brand=brand if brand is not None else DEFAULT_BRAND,
                             character=character or None)

    now = _iso(_now())
    created = images = videos = 0
    with db.connect() as con:
        done_prev = {
            (r["kind"], int(r["scene_number"]), int(r["part"] or 1))
            for r in con.execute(
                """SELECT kind, scene_number, part FROM flow_jobs
                   WHERE project_id=? AND status='done'""", (pid,))
        }
        con.execute("DELETE FROM flow_jobs WHERE project_id=? "
                    "AND status != 'done'", (pid,))
        for sc in data["scenes"]:
            no = sc["scene_number"]
            meta = {"title": sc.get("title") or ""}
            if ("image", no, 1) not in done_prev:
                con.execute(
                    """INSERT INTO flow_jobs(id, project_id, kind, scene_number,
                       part, prompt, prompt_meta, status, attempts, max_attempts,
                       created_at, updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (db.new_id(), pid, "image", no, 1,
                     _image_prompt_text(sc.get("image_prompt")),
                     json.dumps(meta, ensure_ascii=False),
                     "queued", 0, MAX_ATTEMPTS["image"], now, now))
                created += 1
                images += 1
            vp = sc.get("video_prompt")
            if vp and ("video", no, 1) not in done_prev:
                con.execute(
                    """INSERT INTO flow_jobs(id, project_id, kind,
                       scene_number, part, prompt, prompt_meta, status,
                       attempts, max_attempts, created_at, updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (db.new_id(), pid, "video", no, 1,
                     _video_prompt_text(vp),
                     json.dumps(meta, ensure_ascii=False),
                     "queued", 0, MAX_ATTEMPTS["video"], now, now))
                created += 1
                videos += 1
    return {"ok": True, "project_id": pid, "created": created,
            "images": images, "videos": videos}


# ── claim atómico + recuperación de leases ───────────────────────────────────

def recover_expired() -> int:
    """Jobs claimed con lease vencido → queued (worker muerto). Devuelve
    cuántos se recuperaron. Llamado dentro de cada claim (BEGIN IMMEDIATE)."""
    cutoff = _iso(_now())
    with db.connect() as con:
        cur = con.execute(
            """UPDATE flow_jobs SET status='queued', worker=NULL,
               job_token=NULL, lease_until=NULL, updated_at=?
               WHERE status='claimed' AND lease_until IS NOT NULL
               AND lease_until < ?""", (cutoff, cutoff))
        return cur.rowcount


def claim_next(worker: str, pid: str | None = None) -> dict | None:
    """Claim ATÓMICO del siguiente job (imagen antes que video, escena
    ascendente). BEGIN IMMEDIATE evita dobles claims entre workers."""
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        cutoff = _iso(_now())
        con.execute(
            """UPDATE flow_jobs SET status='queued', worker=NULL,
               job_token=NULL, lease_until=NULL, updated_at=?
               WHERE status='claimed' AND lease_until IS NOT NULL
               AND lease_until < ?""", (cutoff, cutoff))
        if pid:
            row = con.execute(
                """SELECT * FROM flow_jobs WHERE status='queued' AND project_id=?
                   ORDER BY CASE kind WHEN 'image' THEN 0 ELSE 1 END,
                   scene_number, part, created_at LIMIT 1""", (pid,)).fetchone()
        else:
            row = con.execute(
                """SELECT * FROM flow_jobs WHERE status='queued'
                   ORDER BY CASE kind WHEN 'image' THEN 0 ELSE 1 END,
                   scene_number, part, created_at LIMIT 1""").fetchone()
        if not row:
            con.commit()
            return None
        kind = row["kind"]
        lease_until = _iso(_now() + timedelta(seconds=LEASE_S.get(kind, 600)))
        token = _token()
        con.execute(
            """UPDATE flow_jobs SET status='claimed', worker=?, job_token=?,
               lease_until=?, updated_at=? WHERE id=?""",
            (worker, token, lease_until, cutoff, row["id"]))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    job = _row_to_job(row)
    job.update({"job_token": token, "lease_until": lease_until,
                "worker": worker})
    return job


# ── heartbeat / complete / fail ───────────────────────────────────────────────

def _claimed_by_token(con, job_id: str, token: str):
    """Fila del job si está claimed con ESE token (nonce del claim). Si no, None."""
    if not token:
        return None
    row = con.execute(
        "SELECT * FROM flow_jobs WHERE id=? AND status='claimed' AND job_token=?",
        (job_id, token)).fetchone()
    return row


def heartbeat(job_id: str, token: str) -> dict | None:
    with db.connect() as con:
        row = _claimed_by_token(con, job_id, token)
        if not row:
            return None
        lease_until = _iso(_now() + timedelta(seconds=HEARTBEAT_EXTEND_S))
        con.execute("UPDATE flow_jobs SET lease_until=?, updated_at=? WHERE id=?",
                    (lease_until, _iso(_now()), job_id))
        return {"ok": True, "lease_until": lease_until}


def complete(job_id: str, token: str, data: bytes) -> dict | None:
    """Valida y guarda el asset; marca done. Devuelve {ok, asset_path,
    project_done, renderable} o None si el token/estado no es válido (409).
    Lanza ValueError si el asset no pasa validación (422)."""
    if not data:
        raise ValueError("body vacío: envía el binario del asset")
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = _claimed_by_token(con, job_id, token)
        if not row:
            con.rollback()
            return None
        pid = row["project_id"]
        kind = row["kind"]
        no = int(row["scene_number"])
        part = int(row["part"] or 1)
        flow_dir = OUTPUT_DIR / pid / "flow"
        flow_dir.mkdir(parents=True, exist_ok=True)

        if kind == "image":
            asset_path = _save_image(flow_dir, no, data)
        else:
            asset_path = _save_video(flow_dir, no, part, data)

        con.execute(
            """UPDATE flow_jobs SET status='done', asset_path=?, error=NULL,
               lease_until=NULL, updated_at=? WHERE id=?""",
            (str(asset_path), _iso(_now()), job_id))
        pending = con.execute(
            """SELECT COUNT(*) c FROM flow_jobs WHERE project_id=?
               AND status != 'done'""", (pid,)).fetchone()["c"]
        project_done = pending == 0
        renderable = False
        if project_done:
            renderable = _apply_assets_to_scenes(con, pid)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return {"ok": True, "project_id": pid, "asset_path": str(asset_path),
            "project_done": project_done, "renderable": renderable}


def _save_image(flow_dir: Path, no: int, data: bytes) -> Path:
    """PNG/JPEG/WEBP validado con PIL (evita HTML de error de Flow guardado
    como imagen). Guarda como Escena_NN_flow.<ext> (convención flow_import)."""
    from PIL import Image, ImageFile
    try:
        probe = Image.open(io.BytesIO(data))
        probe.verify()
        fmt = Image.open(io.BytesIO(data)).format or ""
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"no es una imagen válida ({exc})") from exc
    ext = IMG_FORMAT_EXT.get(fmt)
    if not ext:
        raise ValueError(f"formato de imagen no soportado: {fmt or 'desconocido'}")
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    out = flow_dir / f"Escena_{no:02d}_flow{ext}"
    out.write_bytes(data)
    return out


def _save_video(flow_dir: Path, no: int, part: int, data: bytes) -> Path:
    """MP4 validado con ffprobe (>MIN_VIDEO_S). WebM de Flow → 422: el job
    se reintenta (la extensión debe pedir MP4)."""
    from pipeline.video import probe_duration  # diferido (subprocess pesado)
    out = flow_dir / f"Escena_{no:02d}_video_{part}.mp4"
    tmp = out.with_suffix(".tmp.mp4")
    tmp.write_bytes(data)
    try:
        dur = probe_duration(tmp)
        if dur <= MIN_VIDEO_S:
            raise ValueError(f"video inválido o truncado (duración {dur:.2f}s)")
        tmp.replace(out)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return out


def _apply_assets_to_scenes(con, pid: str) -> bool:
    """Con el proyecto completo: mapea flow/Escena_NN_flow.* → scene.image_path
    (misma convención que flow_import). Devuelve True si TODAS las escenas
    quedaron con imagen en disco (condición de start_flow_render)."""
    scenes = con.execute(
        "SELECT id, idx FROM scenes WHERE project_id=? ORDER BY idx",
        (pid,)).fetchall()
    flow_dir = OUTPUT_DIR / pid / "flow"
    all_have = bool(scenes)
    for sc in scenes:
        no = int(sc["idx"]) + 1
        cands = sorted(flow_dir.glob(f"Escena_{no:02d}_flow.*"))
        if cands:
            con.execute(
                "UPDATE scenes SET image_path=?, status='image' WHERE id=?",
                (str(cands[0]), sc["id"]))
        elif not con.execute("SELECT image_path FROM scenes WHERE id=?",
                             (sc["id"],)).fetchone()["image_path"]:
            all_have = False
    return all_have


def fail(job_id: str, token: str, error: str) -> dict | None:
    """Reintenta (queued) o marca dead al agotar max_attempts."""
    with db.connect() as con:
        row = _claimed_by_token(con, job_id, token)
        if not row:
            return None
        attempts = int(row["attempts"] or 0) + 1
        max_attempts = int(row["max_attempts"] or 2)
        status = "dead" if attempts >= max_attempts else "queued"
        con.execute(
            """UPDATE flow_jobs SET status=?, attempts=?, error=?,
               worker=NULL, job_token=NULL, lease_until=NULL, updated_at=?
               WHERE id=?""",
            (status, attempts, (error or "")[:500], _iso(_now()), job_id))
        return {"ok": True, "status": status, "attempts": attempts,
                "max_attempts": max_attempts}


# ── estado ────────────────────────────────────────────────────────────────────

def status_for_project(pid: str) -> dict:
    with db.connect() as con:
        rows = con.execute(
            """SELECT id, kind, scene_number, part, status, attempts,
               max_attempts, worker, error, asset_path, lease_until,
               created_at, updated_at
               FROM flow_jobs WHERE project_id=? ORDER BY
               CASE kind WHEN 'image' THEN 0 ELSE 1 END, scene_number, part""",
            (pid,)).fetchall()
    counts = {"queued": 0, "claimed": 0, "done": 0, "dead": 0}
    jobs = []
    for r in rows:
        d = dict(r)
        counts[d["status"]] = counts.get(d["status"], 0) + 1
        jobs.append(d)
    return {"ok": True, "project_id": pid, "counts": counts, "jobs": jobs}
