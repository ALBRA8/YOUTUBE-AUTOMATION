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
(recuperación perezosa): perder el lease NO consume attempts (el asset
pudo generarse igualmente), pero SÍ cicla `lease_cycles` — al agotar
MAX_LEASE_CYCLES el job pasa a dead (un worker que muriera en cada claim
reciclaría el job para siempre: §reintentos — no reintentar infinitamente).

Los UPDATE de heartbeat/fail son condicionales (status+job_token) dentro
de BEGIN IMMEDIATE: un heartbeat/fail zombi que llega DESPUÉS de que otro
worker reclamó el job ya no puede robarle el claim (TOCTOU cerrado).
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
MAX_LEASE_CYCLES = 3                # expiraciones de lease antes de dead (anti zombie-loop)
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

    Idempotente: conserva los done (no re-trabaja assets ya subidos) y los
    claimed con lease VIGENTE (trabajo en vuelo no se descarta); borra los
    pendientes (queued/dead y claimed con lease vencido) para regenerarlos
    con los prompts actuales."""
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
        con.execute(
            """DELETE FROM flow_jobs WHERE project_id=? AND (
               status IN ('queued','dead')
               OR (status='claimed' AND
                   (lease_until IS NULL OR lease_until < ?)))""",
            (pid, now))
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

def _recover_en_con(con, cutoff: str) -> int:
    """Barrido de leases vencidos sobre una conexión YA en transacción.

    Dos fases: (1) los que agotan MAX_LEASE_CYCLES pasan a dead — un worker
    que muriera en cada claim reciclaría el job para siempre (anti
    zombie-loop); (2) el resto vuelve a queued. La pérdida del lease NO
    consume attempts. Devuelve cuántos jobs se reencolaron/marcaron dead."""
    con.execute(
        """UPDATE flow_jobs SET status='dead', lease_cycles=lease_cycles+1,
           worker=NULL, job_token=NULL, lease_until=NULL, updated_at=?,
           error=?
           WHERE status='claimed' AND lease_until IS NOT NULL
           AND lease_until < ? AND lease_cycles + 1 >= ?""",
        (cutoff,
         "lease expirado y agotado: el worker murió repetidamente "
         "sin completar el job",
         cutoff, MAX_LEASE_CYCLES))
    cur = con.execute(
        """UPDATE flow_jobs SET status='queued', lease_cycles=lease_cycles+1,
           worker=NULL, job_token=NULL, lease_until=NULL, updated_at=?
           WHERE status='claimed' AND lease_until IS NOT NULL
           AND lease_until < ?""", (cutoff, cutoff))
    return cur.rowcount


def recover_expired() -> int:
    """Jobs claimed con lease vencido → queued (worker muerto) o dead si
    agotó MAX_LEASE_CYCLES. Devuelve cuántos se recuperaron. Atomic:
    BEGIN IMMEDIATE (mismo lock que claim_next)."""
    cutoff = _iso(_now())
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        n = _recover_en_con(con, cutoff)
        con.commit()
        return n
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def claim_next(worker: str, pid: str | None = None) -> dict | None:
    """Claim ATÓMICO del siguiente job (imagen antes que video, escena
    ascendente). BEGIN IMMEDIATE evita dobles claims entre workers."""
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        cutoff = _iso(_now())
        _recover_en_con(con, cutoff)  # barrido anti-zombie (2 fases, ver arriba)
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
    """Renueva el lease SOLO si el job sigue claimed con ESE token. BEGIN
    IMMEDIATE + UPDATE condicional: sin TOCTOU (un heartbeat antiguo que
    compite contra un re-claim ya no puede robar el lease del nuevo worker)."""
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = _claimed_by_token(con, job_id, token)
        if not row:
            con.rollback()
            return None
        lease_until = _iso(_now() + timedelta(seconds=HEARTBEAT_EXTEND_S))
        cur = con.execute(
            """UPDATE flow_jobs SET lease_until=?, updated_at=?
               WHERE id=? AND status='claimed' AND job_token=?""",
            (lease_until, _iso(_now()), job_id, token))
        if cur.rowcount != 1:
            con.rollback()
            return None
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
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
        cierre_p2 = bool(row["prompt_adapted"])  # [flow-adaptation v1]
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
    # [flow-adaptation v1] cierre del ciclo en el ledger: si el job completó
    # CON P2, la adaptación FUNCIONÓ (evidencia operacional 'si funcionó').
    # Jamás tumba la operación de la cola si la memoria falla (patrón _mem_obs).
    if cierre_p2:
        try:
            from services import flow_adaptation
            flow_adaptation.registrar_cierre(
                job_id, "P2 funcionó: asset validado y guardado",
                detalle=str(asset_path))
        except Exception:  # noqa: BLE001 — observabilidad, nunca crítico
            pass
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
    """Reintenta (queued) o marca dead al agotar max_attempts. BEGIN
    IMMEDIATE + UPDATE condicional por token: un fail antiguo que compite
    contra un re-claim no puede tumbar el claim del nuevo worker (TOCTOU
    cerrado; antes un fail tardío silenciosamente reencolaba el job que
    otro worker ya estaba generando → trabajo Flow duplicado)."""
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = _claimed_by_token(con, job_id, token)
        if not row:
            con.rollback()
            return None
        attempts = int(row["attempts"] or 0) + 1
        max_attempts = int(row["max_attempts"] or 2)
        status = "dead" if attempts >= max_attempts else "queued"
        cur = con.execute(
            """UPDATE flow_jobs SET status=?, attempts=?, error=?,
               worker=NULL, job_token=NULL, lease_until=NULL, updated_at=?
               WHERE id=? AND status='claimed' AND job_token=?""",
            (status, attempts, (error or "")[:500], _iso(_now()),
             job_id, token))
        if cur.rowcount != 1:
            con.rollback()
            return None
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    _mem_obs(f"job flow {row['kind']} escena {row['scene_number']} falló "
             f"(intento {attempts}/{max_attempts}): {(error or '')[:120]}",
             job_id)
    # [flow-adaptation v1] JOB vs ATTEMPT: al quedar dead un job de VIDEO, la
    # capa operacional Flow Adaptation examina la EVIDENCIA (texto del error)
    # y, SOLO si la clasificación y la política de retry lo permiten, otorga
    # el único intento extra (con P2 cuando existe estrategia segura S1/S2).
    # Jamás tumba la operación de la cola si la capa falla (patrón _mem_obs).
    adaptacion = None
    if status == "dead" and row["kind"] == "video":
        try:
            from services import flow_adaptation
            adaptacion = flow_adaptation.procesar_fallo_job(job_id)
        except Exception:  # noqa: BLE001 — la capa nunca rompe la cola
            adaptacion = None
    out = {"ok": True, "status": status, "attempts": attempts,
           "max_attempts": max_attempts}
    if adaptacion:
        out["adaptacion"] = adaptacion
    return out


def _mem_obs(contenido: str, job_id: str) -> None:
    """Gancho MemoryDV (episodio de proveedor): cada fallo de job es una
    observación para la consolidación (patrón → aprendizaje). Jamás tumba
    la operación de la cola si la memoria falla."""
    try:
        from services import memorydv
        memorydv.record_observation(contenido, source="flow_jobs.fail",
                                    scope="provider",
                                    evidence=[{"kind": "flow_job",
                                               "ref": job_id}],
                                    confidence=0.6)
    except Exception:  # noqa: BLE001 — observabilidad, nunca crítico
        pass


# ── [flow-adaptation v1] P1/P2 — capa operacional Flow Adaptation ────────────

def set_adapted_prompt(job_id: str, prompt_adapted: str,
                       motivo: str = "") -> dict | None:
    """Escribe P2 (prompt ADAPTADO) en flow_jobs.prompt_adapted.

    Contrato P1/P2 (garantía anti-invasión de la capa creativa):
      - P1 vive en la columna `prompt` (fuente única: build_script_json,
        blindada por el contrato P1 del docstring del módulo) y NUNCA se
        sobrescribe, se borra ni se modifica aquí.
      - P2 SOLO sirve para la ejecución operacional en Flow: la extensión
        inyecta job.prompt_adapted si existe; si no, P1.
      - UNA sola oportunidad de adaptación por job: si P2 ya existe NO se
        sobrescribe (devuelve None) — evita bucles de adaptación.
      - Solo jobs kind='video' (no se comparte política con imagen) y no
        done. Devuelve {ok, ...} o None si el job no es elegible.
    """
    p2 = (prompt_adapted or "").strip()
    if not p2:
        return None
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT * FROM flow_jobs WHERE id=?", (job_id,)).fetchone()
        if not row or row["kind"] != "video" or row["status"] == "done":
            con.rollback()
            return None
        if row["prompt_adapted"]:
            con.rollback()  # una sola adaptación por job (anti-bucle)
            return None
        con.execute(
            """UPDATE flow_jobs SET prompt_adapted=?, updated_at=?
               WHERE id=?""",
            (p2[:2000], _iso(_now()), job_id))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    _mem_obs(f"P2 operacional establecido para job video escena "
             f"{row['scene_number']}: {motivo[:120]}", job_id)
    return {"ok": True, "job_id": job_id,
            "p1_intacto": row["prompt"], "p2": p2[:2000],
            "motivo": (motivo or "")[:300]}


def requeue_for_adaptation(job_id: str) -> dict | None:
    """Reencola un job VIDEO dead para su ÚNICO intento extra con P2.

    Política anti-bucle: attempts = max_attempts - 1 (queda UN intento),
    lease_cycles intacto (MAX_LEASE_CYCLES del contrato sigue mandando).
    Solo jobs dead de video. Devuelve {ok, attempts, max_attempts} o None."""
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT * FROM flow_jobs WHERE id=?", (job_id,)).fetchone()
        if not row or row["kind"] != "video" or row["status"] != "dead":
            con.rollback()
            return None
        max_attempts = int(row["max_attempts"] or 2)
        con.execute(
            """UPDATE flow_jobs SET status='queued',
               attempts=?, worker=NULL, job_token=NULL, lease_until=NULL,
               updated_at=? WHERE id=?""",
            (max_attempts - 1, _iso(_now()), job_id))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return {"ok": True, "job_id": job_id, "status": "queued",
            "attempts": max_attempts - 1, "max_attempts": max_attempts}


# ── estado ────────────────────────────────────────────────────────────────────

def status_for_project(pid: str) -> dict:
    with db.connect() as con:
        rows = con.execute(
            """SELECT id, kind, scene_number, part, status, attempts,
               max_attempts, lease_cycles, worker, error, asset_path,
               lease_until, created_at, updated_at
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
