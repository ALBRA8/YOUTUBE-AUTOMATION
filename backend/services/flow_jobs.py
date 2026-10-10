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
from services import execution_contract as ec

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
    # [execution-contract v1] el spec viaja verbatim al job (tercera capa del
    # contrato; jamás edita prompt/prompt_adapted) y el contract_result
    # persistido vuelve como dict para observabilidad.
    try:
        d["execution_spec"] = json.loads(d["execution_spec"]) \
            if d.get("execution_spec") else None
    except (TypeError, ValueError):
        d["execution_spec"] = None
    try:
        d["contract_result"] = json.loads(d["contract_result"]) \
            if d.get("contract_result") else None
    except (TypeError, ValueError):
        d["contract_result"] = None
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
    # [execution-contract v1] formato del proyecto para derivar aspect_ratio
    # del spec (short→9:16 / long→16:9); build_script_json lo normaliza.
    project_format = data.get("format") or (project.get("format") or "short")

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
                spec = ec.build_execution_spec(sc, kind="image",
                                               project_format=project_format)
                con.execute(
                    """INSERT INTO flow_jobs(id, project_id, kind, scene_number,
                       part, prompt, prompt_meta, execution_spec, exec_state,
                       status, attempts, max_attempts, created_at, updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (db.new_id(), pid, "image", no, 1,
                     _image_prompt_text(sc.get("image_prompt")),
                     json.dumps(meta, ensure_ascii=False),
                     json.dumps(spec, ensure_ascii=False),
                     ec.EXEC_STATE_QUEUED,
                     "queued", 0, MAX_ATTEMPTS["image"], now, now))
                created += 1
                images += 1
            vp = sc.get("video_prompt")
            if vp and ("video", no, 1) not in done_prev:
                spec = ec.build_execution_spec(sc, kind="video",
                                               project_format=project_format)
                con.execute(
                    """INSERT INTO flow_jobs(id, project_id, kind,
                       scene_number, part, prompt, prompt_meta,
                       execution_spec, exec_state, status,
                       attempts, max_attempts, created_at, updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (db.new_id(), pid, "video", no, 1,
                     _video_prompt_text(vp),
                     json.dumps(meta, ensure_ascii=False),
                     json.dumps(spec, ensure_ascii=False),
                     ec.EXEC_STATE_QUEUED,
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
               lease_until=?, updated_at=?,
               exec_state=CASE WHEN exec_state IS NULL OR exec_state=?
                          THEN ? ELSE exec_state END
               WHERE id=?""",
            (worker, token, lease_until, cutoff, ec.EXEC_STATE_QUEUED,
             ec.EXEC_STATE_CLAIMED, row["id"]))
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


def _spec_of_row(row) -> dict | None:
    """execution_spec parseado de la fila del job (None honesto si ausente
    o inválido — jamás un spec inventado)."""
    try:
        raw = row["execution_spec"]
    except (KeyError, IndexError):
        return None
    if not raw:
        return None
    try:
        s = json.loads(raw)
        return s if isinstance(s, dict) else None
    except (TypeError, ValueError):
        return None


def complete(job_id: str, token: str, data: bytes) -> dict | None:
    """Valida y guarda el asset; valida el CONTRATO (§13) y marca done.

    Devuelve {ok, asset_path, project_done, renderable, contract} o None si
    el token/estado no es válido (409). Lanza ValueError si el asset no pasa
    validación (422) o si INCUMPLE EL CONTRATO (CONTRACT_VIOLATION →
    ASSET_INVALID terminal: el job queda dead, jamás reencola, jamás DONE —
    un asset de 5s con spec de 8s no puede terminar en done)."""
    if not data:
        raise ValueError("body vacío: envía el binario del asset")
    violation = None
    barrier_error = None
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

        # [execution-contract v1.1] §7.1 — BARRERA PRE-GENERACIÓN (backstop
        # server-side, corrige CF-E2E-01): un video cuyo spec exige
        # verificación pre-generación (o una fila legacy sin spec) JAMÁS
        # acepta un asset si su exec_state nunca alcanzó CONTROLS_VERIFIED
        # (huella del consentimiento del servidor vía /generate-consent).
        # Llegar aquí sin esa huella significa que la generación se disparó
        # burlando el gate (extensión vieja, resume zombi, retry sin
        # re-gate): fail-closed → dead CONFIG_UNVERIFIABLE, sin asset, sin
        # DONE, sin reencolar (el ValueError posterior da 422 y un fail()
        # extra da 409 por token limpiado).
        if kind == "video":
            bspec = _spec_of_row(row)
            if bspec is None or ec.required_gate_controls(bspec):
                _orden_post_gate = {ec.EXEC_STATE_VERIFIED,
                                    ec.EXEC_STATE_SUBMITTED,
                                    ec.EXEC_STATE_OBSERVED,
                                    ec.EXEC_STATE_DOWNLOADED,
                                    ec.EXEC_STATE_ASSET_OK,
                                    ec.EXEC_STATE_CONTRACT_OK,
                                    ec.EXEC_STATE_DONE}
                if (row["exec_state"] or "") not in _orden_post_gate:
                    razon = ("fila sin execution_spec (legacy): regenerar "
                             "la cola con enqueue_project"
                             if bspec is None else
                             "controles required="
                             + ",".join(ec.required_gate_controls(bspec)))
                    registro = {"kind": "pre_generation_gate_barrier",
                                "verdict": ec.CONFIG_UNVERIFIABLE,
                                "exec_state_observed": row["exec_state"],
                                "razon": razon}
                    con.execute(
                        """UPDATE flow_jobs SET status='dead',
                           exec_state=?, contract_result=?, error=?,
                           worker=NULL, job_token=NULL, lease_until=NULL,
                           updated_at=? WHERE id=?""",
                        (ec.EXEC_STATE_CONFIG_UNVERIFIABLE,
                         json.dumps(registro, ensure_ascii=False),
                         ("CONFIG_UNVERIFIABLE: asset entregado sin gate "
                          "pre-generación verificado (§7.1) — " + razon)[:500],
                         _iso(_now()), job_id))
                    con.commit()
                    barrier_error = ("CONFIG_UNVERIFIABLE: asset entregado "
                                     "sin consentimiento contractual del "
                                     "gate (§7.1) — " + razon)

        if barrier_error is None:
            if kind == "image":
                asset_path = _save_image(flow_dir, no, data)
            else:
                asset_path = _save_video(flow_dir, no, part, data)

            # [execution-contract v1] §13 — REQUESTED vs OBSERVED FLOW vs ACTUAL
            # ASSET. El spec viaja en la fila (columna execution_spec); la
            # medición real del MP4 con ffprobe manda sobre cualquier promesa.
            contract_result = None
            spec = None
            if kind == "video" and row["execution_spec"]:
                try:
                    spec = json.loads(row["execution_spec"])
                except (TypeError, ValueError):
                    spec = None
            if spec is not None:
                actual = ec.probe_asset(asset_path)
                observed = None
                try:
                    observed = json.loads(row["contract_result"] or "null") \
                        if isinstance(row["contract_result"], str) else None
                except (TypeError, ValueError):
                    observed = None
                contract_result = ec.validate_asset_contract(
                    spec, actual=actual,
                    observed=(observed or {}).get("observed_flow")
                    if isinstance(observed, dict) else None,
                    outputs_count=1)
                if contract_result["verdict"] == ec.CONTRACT_VIOLATION:
                    violation = contract_result

            if violation is not None:
                # §13: CONTRACT_VIOLATION → NO DONE. Terminal ASSET_INVALID:
                # dead inmediato (fail() posterior con este token dará 409 y la
                # extensión no reintentará), contract_result persistido, error
                # estructurado que flow_adaptation clasifica sin adaptar prompt.
                con.execute(
                    """UPDATE flow_jobs SET status='dead', exec_state=?,
                       contract_result=?, error=?, worker=NULL, job_token=NULL,
                       lease_until=NULL, updated_at=? WHERE id=?""",
                    (ec.EXEC_STATE_ASSET_INVALID,
                     json.dumps(violation, ensure_ascii=False),
                     ec.contract_error_prefix(violation)[:500], _iso(_now()),
                     job_id))
                con.commit()
            else:
                con.execute(
                    """UPDATE flow_jobs SET status='done', asset_path=?, error=NULL,
                       exec_state=?, contract_result=?, lease_until=?, updated_at=?
                       WHERE id=?""",
                    (str(asset_path), ec.EXEC_STATE_CONTRACT_OK,
                     json.dumps(contract_result, ensure_ascii=False)
                     if contract_result else None,
                     None, _iso(_now()), job_id))
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
    if barrier_error is not None:
        _mem_obs(f"job flow video escena {no} BARRERA §7.1: "
                 f"asset sin consentimiento del gate ({barrier_error[:120]})",
                 job_id, scope="config")
        raise ValueError(barrier_error)
    if violation is not None:
        _mem_obs(f"job flow video escena {no} ASSET_INVALID: "
                 f"{violation.get('summary', '')[:160]}", job_id)
        raise ValueError(ec.contract_error_prefix(violation))
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
            "project_done": project_done, "renderable": renderable,
            "contract": contract_result}


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
    otro worker ya estaba generando → trabajo Flow duplicado).

    [execution-contract v1] §10 — clasificación del error:
      - CONFIG_UNSUPPORTED/UNVERIFIABLE/MISMATCH (gate de configuración) y
        ASSET_INVALID (contrato del asset) → TERMINAL dead inmediato
        (exec_state CONFIG_*/ASSET_INVALID): jamás reintentan
        (retry_on_config_error=false) y jamás entran a Flow Adaptation
        (CONFIG ERROR != PROMPT ADAPTATION).
      - [execution-contract v1.1] §7.1 — FLOW_WATCHDOG_TIMEOUT: el veredicto
        LOCAL del watchdog de la extensión (prefijo explícito nuevo o
        marcadores legacy "watchdog:"/"timeout-local:") se etiqueta como
        agotamiento local, JAMÁS como PROVIDER_FAILURE (CF-E2E-01/H: un
        watchdog no determina root cause del proveedor sin evidencia
        externa). Semántica de cola intacta: reintenta por attempts.
      - resto → PROVIDER_FAILURE: SOLO errores con evidencia de proveedor
        tras una generación efectivamente disparada (el gate §7.1 garantiza
        que llegar aquí implica controles required VERIFIED o ausentes)."""
    err = (error or "")
    config_terminal = None
    for st in (ec.EXEC_STATE_CONFIG_UNSUPPORTED,
               ec.EXEC_STATE_CONFIG_UNVERIFIABLE,
               ec.EXEC_STATE_CONFIG_MISMATCH,
               ec.EXEC_STATE_ASSET_INVALID):
        if err.startswith(f"{st}:"):
            config_terminal = st
            break
    watchdog_local = (err.startswith(ec.EXEC_STATE_WATCHDOG + ":")
                      or err.startswith("watchdog:")
                      or err.startswith("timeout-local:"))
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = _claimed_by_token(con, job_id, token)
        if not row:
            con.rollback()
            return None
        attempts = int(row["attempts"] or 0) + 1
        max_attempts = int(row["max_attempts"] or 2)
        if config_terminal:
            status = "dead"  # §6/§9: terminal, independiente de attempts
            exec_state = config_terminal
        else:
            status = "dead" if attempts >= max_attempts else "queued"
            exec_state = (ec.EXEC_STATE_WATCHDOG if watchdog_local
                          else ec.EXEC_STATE_PROVIDER_FAILURE)
        cur = con.execute(
            """UPDATE flow_jobs SET status=?, attempts=?, error=?,
               exec_state=?, worker=NULL, job_token=NULL, lease_until=NULL,
               updated_at=?
               WHERE id=? AND status='claimed' AND job_token=?""",
            (status, attempts, err[:500], exec_state, _iso(_now()),
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
             job_id,
             scope="config" if config_terminal
             else ("local" if watchdog_local else "provider"))
    # [execution-contract v1] §10: los estados terminales de configuración
    # JAMÁS entran en Flow Adaptation (un error de configuración no se
    # resuelve adaptando el prompt ni reintentando idéntico).
    if config_terminal:
        out = {"ok": True, "status": status, "attempts": attempts,
               "max_attempts": max_attempts, "exec_state": exec_state,
               "config_terminal": True}
        return out
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


def _mem_obs(contenido: str, job_id: str, *, scope: str = "provider") -> None:
    """Gancho MemoryDV (episodio de proveedor/config/local): cada fallo de
    job es una observación para la consolidación (patrón → aprendizaje).
    scope honesto (§7.1): "provider" SOLO para fallos con evidencia de
    proveedor; "local" para watchdog; "config" para terminales del
    contrato. Jamás tumba la operación de la cola si la memoria falla."""
    try:
        from services import memorydv
        memorydv.record_observation(contenido, source="flow_jobs.fail",
                                    scope=scope,
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

def set_exec_state(job_id: str, token: str, state: str,
                   detail: str = "", evidence: dict | None = None) -> dict | None:
    """[execution-contract v1] §9 — progreso fino de la máquina de estados,
    reportado por la extensión/HANDS durante la ejecución mecánica.

    BEGIN IMMEDIATE + UPDATE condicional por token (mismo nonce que
    heartbeat/complete/fail). Valida la transición (progress_allowed: solo
    hacia adelante, jamás retrocede — la evidencia de un intento no rebobina
    el estado de otro). El estado de la COLA (status) sigue mandando: este
    progreso es observabilidad contractual, no control de lease.
    Devuelve {ok, exec_state} / {ok: False, error: illegal_transition} /
    None (token inválido, 409)."""
    if not state or not isinstance(state, str):
        return {"ok": False, "error": "invalid_state"}
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = _claimed_by_token(con, job_id, token)
        if not row:
            con.rollback()
            return None
        current = row["exec_state"]
        if not ec.progress_allowed(current, state):
            con.rollback()
            return {"ok": False, "error": "illegal_transition",
                    "current": current, "requested": state}
        # [execution-contract v1.1] §7.1 — GENERATION_SUBMITTED y
        # CONTROLS_VERIFIED son estados del SERVIDOR para videos con
        # controles required pre-generación (CF-E2E-01): VERIFIED solo se
        # alcanza vía /generate-consent (el juez es el backend, jamás el
        # cliente), y SUBMITTED solo desde VERIFIED. Cualquier salto desde
        # QUEUED/CAPS/CONFIGURED (extensión vieja, resume zombi, retry sin
        # re-gate) se rechaza: sin consentimiento no hay generación.
        if row["kind"] == "video":
            spec = _spec_of_row(row)
            if ec.required_gate_controls(spec or {}) \
                    and state in (ec.EXEC_STATE_VERIFIED,
                                  ec.EXEC_STATE_SUBMITTED) \
                    and current != ec.EXEC_STATE_VERIFIED:
                con.rollback()
                return {"ok": False, "error": "contract_gate_required",
                        "current": current, "requested": state,
                        "detail": ("CONTROLS_VERIFIED solo vía "
                                   "/generate-consent; GENERATION_SUBMITTED "
                                   "exige CONTROLS_VERIFIED (§7.1)")}
        con.execute(
            """UPDATE flow_jobs SET exec_state=?, updated_at=?
               WHERE id=? AND status='claimed' AND job_token=?""",
            (state, _iso(_now()), job_id, token))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return {"ok": True, "exec_state": state, "detail": (detail or "")[:300],
            "evidence_registered": isinstance(evidence, dict)}


# ── [execution-contract v1.1] §7.1 — consentimiento de generación ────────────

def generation_consent(job_id: str, token: str,
                       evidence: dict | None = None) -> dict | None:
    """CONSENTIMIENTO DE GENERACIÓN — la corrección de CF-E2E-01
    (PRE-GENERATION CONTRACT GATE NOT ENFORCED, P0).

    Puerta OBLIGATORIA antes de GENERATION_SUBMITTED para jobs de VIDEO:
    la capa mecánica (extensión vía bridge, o HANDS) envía capabilities +
    control_results y el BACKEND re-evalúa el gate con
    execution_contract.config_gate — el juez del contrato es el servidor,
    no el cliente (el espejo JS es pre-filtro, jamás autoridad).

    Flujo obligatorio (§7.1 del mandato):
      DISCOVER → COMPARE → CONFIGURE → READ BACK → VERIFY
        → SOLO SI los required están VERIFIED → GENERATION_SUBMITTED.

    Comportamiento:
      - ALLOW  → exec_state avanza a CONTROLS_VERIFIED (transición
                 validada) y devuelve {ok, allowed: True, decision}.
      - DENY   → TERMINAL inmediato: status dead + exec_state CONFIG_* +
                 error con prefijo CONFIG_* (flow_adaptation lo clasifica
                 J/K/L sin adaptar prompt ni reintentar) + contract_result
                 con el registro completo del gate. Devuelve
                 {ok, allowed: False, decision, detail}.
      - Video sin execution_spec → DENY CONFIG_UNVERIFIABLE (fail-closed:
                 sin contrato no hay verificación posible; toda fila
                 encolada por esta versión lleva spec — una fila legacy
                 sin spec debe regenerarse con enqueue_project).
      - kind != video → ALLOW sin tocar exec_state (el gate de
                 configuración es una rama de video; las imágenes se
                 validan post-hoc con PIL).

    allow_inherited_state=false (política del spec): un valor que YA estaba
    seleccionado en la sesión de Flow solo cuenta si la capa mecánica lo
    configuró y releyó en ESTA ejecución (control_results.configured).
    Los 5s observados en una sesión son capacidad observada de ESA sesión,
    jamás una regla universal del proveedor (no hay conversión silenciosa
    de duración en ninguna capa).

    Devuelve None si el token/claim no es válido (409). Jamás toca P1/P2."""
    ev = evidence if isinstance(evidence, dict) else {}
    caps = ev.get("capabilities") if isinstance(ev.get("capabilities"), dict) \
        else {}
    ctrl = ev.get("control_results") \
        if isinstance(ev.get("control_results"), dict) else {}
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = _claimed_by_token(con, job_id, token)
        if not row:
            con.rollback()
            return None
        kind = row["kind"]
        if kind != "video":
            con.commit()
            return {"ok": True, "allowed": True,
                    "decision": ec.ALLOW_GENERATE,
                    "exec_state": row["exec_state"],
                    "detail": "rama no video: gate de configuración no aplica"}
        spec = _spec_of_row(row)
        if spec is None:
            decision = {"decision": ec.CONFIG_UNVERIFIABLE,
                        "detail": "execution_spec ausente o inválido en la "
                                  "fila del job — sin contrato no se genera "
                                  "(fail-closed §7.1)",
                        "control_results": {}}
        else:
            decision = ec.config_gate(spec, caps, ctrl)
        if decision["decision"] == ec.ALLOW_GENERATE:
            current = row["exec_state"]
            if current != ec.EXEC_STATE_VERIFIED and ec.progress_allowed(
                    current, ec.EXEC_STATE_VERIFIED):
                con.execute(
                    """UPDATE flow_jobs SET exec_state=?, updated_at=?
                       WHERE id=? AND status='claimed' AND job_token=?""",
                    (ec.EXEC_STATE_VERIFIED, _iso(_now()), job_id, token))
            con.commit()
            return {"ok": True, "allowed": True,
                    "decision": ec.ALLOW_GENERATE,
                    "exec_state": ec.EXEC_STATE_VERIFIED,
                    "detail": (decision.get("detail") or "")[:300]}
        # DENY → terminal inmediato (mismo tratamiento que fail CONFIG_*):
        # dead sin reencolar, sin adaptación, sin DONE (§6/§9/§10).
        estado = decision["decision"]
        detalle_txt = decision.get("detail") or "gate denegó la generación"
        registro = {"kind": "pre_generation_gate",
                    "decision": estado,
                    "detail": detalle_txt,
                    "capabilities": caps,
                    "control_results": ctrl,
                    "client_decision": ev.get("client_decision"),
                    "schema_version": spec.get("schema_version")
                    if isinstance(spec, dict) else None}
        con.execute(
            """UPDATE flow_jobs SET status='dead', exec_state=?,
               contract_result=?, error=?, worker=NULL, job_token=NULL,
               lease_until=NULL, updated_at=? WHERE id=?""",
            (estado,
             json.dumps(registro, ensure_ascii=False),
             (f"{estado}: {detalle_txt}")[:500],
             _iso(_now()), job_id))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    _mem_obs(f"job flow video escena {row['scene_number']} CONSENT DENY: "
             f"{estado} — {detalle_txt[:120]}", job_id, scope="config")
    return {"ok": True, "allowed": False, "decision": estado,
            "exec_state": estado, "detail": detalle_txt[:300]}


def status_for_project(pid: str) -> dict:
    with db.connect() as con:
        rows = con.execute(
            """SELECT id, kind, scene_number, part, status, attempts,
               max_attempts, lease_cycles, worker, error, asset_path,
               lease_until, exec_state, created_at, updated_at
               FROM flow_jobs WHERE project_id=? ORDER BY
               CASE kind WHEN 'image' THEN 0 ELSE 1 END, scene_number, part""",
            (pid,)).fetchall()
    counts = {"queued": 0, "claimed": 0, "done": 0, "dead": 0}
    exec_counts: dict[str, int] = {}
    jobs = []
    for r in rows:
        d = dict(r)
        counts[d["status"]] = counts.get(d["status"], 0) + 1
        es = d.get("exec_state") or "—"
        exec_counts[es] = exec_counts.get(es, 0) + 1
        jobs.append(d)
    return {"ok": True, "project_id": pid, "counts": counts,
            "exec_counts": exec_counts, "jobs": jobs}
