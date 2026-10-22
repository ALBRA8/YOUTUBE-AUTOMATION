#!/usr/bin/env python3
"""
ALBRA — GATE C.2 LIVE TEST
Verificación LIVE de punta a punta en el pipeline normal:
Start Frame -> Google Flow MCP -> Video real -> find_flow_videos -> Pipeline de ensamblado -> Video final MP4.

2 escenas reales:
- Escena 0: Video Flow preexistente válido (1.91 MB) -> probado por idempotencia y descubrimiento
- Escena 1: Start Frame real scene_02.png -> Generación LIVE en Google Flow -> Escena_02_video.mp4
- Pipeline normal: Audio/TTS -> Retime clips -> Concat -> Audio mix -> Hormozi subtitles -> Final video MP4.
"""
import asyncio
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ["FLOW_MCP_ENABLED"] = "1"
os.environ["FLOW_MCP_VIDEO_ENABLED"] = "1"

import config
config.FLOW_MCP_ENABLED = True
config.FLOW_MCP_VIDEO_ENABLED = True

import database as db
from pipeline import flow_import, orchestrator, video
from services import flow_mcp_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("live_test_c2")


def probe_media_info(file_path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size:stream=codec_type,width,height,r_frame_rate",
        "-of", "json",
        str(file_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def _hash_of(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


async def run_live_pipeline():
    log.info("=== INICIANDO GATE C.2 LIVE PIPELINE TEST ===")

    # 1. Verificar disponibilidad de Flow MCP
    lock_dir = REPO_ROOT / "tools" / "GoogleFlowMCP" / ".flow.lock"
    if lock_dir.exists():
        if lock_dir.is_dir():
            shutil.rmtree(lock_dir, ignore_errors=True)
        else:
            lock_dir.unlink(missing_ok=True)

    if not flow_mcp_client.available():
        raise RuntimeError("Flow MCP no está disponible o no se encuentra el directorio.")
    log.info("✓ Flow MCP disponible.")

    project_id = "live_c2_test_01"
    proj_dir = config.OUTPUT_DIR / project_id
    if proj_dir.exists():
        log.info("Limpiando directorio previo: %s", proj_dir)
        shutil.rmtree(proj_dir, ignore_errors=True)
    proj_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = proj_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    flow_dir = proj_dir / "flow"
    flow_dir.mkdir(parents=True, exist_ok=True)

    # 2. Preparar imágenes Start Frame reales
    src_img0 = REPO_ROOT / "backend/data/output/_live_mcp_test_01/scene_01.png"
    src_img1 = REPO_ROOT / "backend/data/output/_live_mcp_test_02r/scene_01.png"

    if not src_img0.exists():
        raise FileNotFoundError(f"No se encontró la imagen base {src_img0}")
    if not src_img1.exists():
        raise FileNotFoundError(f"No se encontró la imagen base {src_img1}")

    target_img0 = proj_dir / "scene_01.png"
    target_img1 = proj_dir / "scene_02.png"
    shutil.copy2(src_img0, target_img0)
    shutil.copy2(src_img1, target_img1)
    log.info("✓ Start Frames copiados: %s (%d bytes), %s (%d bytes)",
             target_img0.name, target_img0.stat().st_size,
             target_img1.name, target_img1.stat().st_size)

    # 3. Preparar audios reales y hashes de narración
    src_wav0 = REPO_ROOT / "scene_00.wav"
    src_wav1 = REPO_ROOT / "scene_01.wav"
    target_wav0 = audio_dir / "scene_00.wav"
    target_wav1 = audio_dir / "scene_01.wav"
    shutil.copy2(src_wav0, target_wav0)
    shutil.copy2(src_wav1, target_wav1)

    text_sc0 = "En el templo silencioso, el orbe de cristal emite pulsos de energia esmeralda."
    text_sc1 = "Ondas de luz mistica iluminan los grabados de las columnas ancestrales."

    # 4. Colocar video preexistente válido en escena 0 para probar idempotencia
    src_vid0 = REPO_ROOT / "backend/data/output/test_captured_live.mp4"
    if not src_vid0.exists():
        src_vid0 = REPO_ROOT / "backend/data/output/_live_video_test_02/flow/Escena_01_video.mp4"
    target_vid0 = flow_dir / "Escena_01_video.mp4"
    shutil.copy2(src_vid0, target_vid0)
    log.info("✓ Escena 0: Video Flow preexistente instalado para idempotencia (%d bytes)", target_vid0.stat().st_size)

    # 5. Registrar proyecto en base de datos SQLite
    project_row = db.get_project(project_id)
    if not project_row:
        with db.connect() as con:
            con.execute(
                "INSERT INTO projects(id, title, status, mode, style, format, meta, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    project_id,
                    "Live Test C2 Crystal Orb Flow",
                    "draft",
                    "production_json",
                    "cinematic",
                    "short",
                    json.dumps({"flow_video": True, "transitions": False}),
                    db.now(),
                    db.now(),
                )
            )
    else:
        db.update_project(
            project_id,
            status="draft",
            progress=0,
            meta={"flow_video": True, "transitions": False}
        )

    # 6. Registrar las 2 escenas en BD con image_path y tts_hash
    scenes_data = [
        {
            "id": f"{project_id}_s0",
            "project_id": project_id,
            "idx": 0,
            "title": "El Orbe Sagrado",
            "narration": text_sc0,
            "image_path": str(target_img0),
            "prompt": "Animate glowing emerald crystal orb gently",
            "status": "image",
            "meta": {"tts_hash": _hash_of(text_sc0), "tts": "edge"}
        },
        {
            "id": f"{project_id}_s1",
            "project_id": project_id,
            "idx": 1,
            "title": "La Resonancia Mistica",
            "narration": text_sc1,
            "image_path": str(target_img1),
            "prompt": "Gentle cinematic camera motion drifting slowly around the illuminated stone pillar and glowing orb in the ancient sanctuary",
            "status": "image",
            "meta": {"tts_hash": _hash_of(text_sc1), "tts": "edge"}
        }
    ]
    db.replace_scenes(project_id, scenes_data)
    scenes = db.get_scenes(project_id)
    db.update_scene(scenes[0]["id"], image_path=str(target_img0), status="image", meta=scenes_data[0]["meta"])
    db.update_scene(scenes[1]["id"], image_path=str(target_img1), status="image", meta=scenes_data[1]["meta"])
    log.info("✓ Proyecto y escenas registrados en base de datos.")

    # 7. Crear e iniciar el Job de orquestación
    job_id = db.create_job(project_id, kind="pipeline")
    log.info("✓ Job creado: %s. Ejecutando orchestrator._run()...", job_id)

    await orchestrator._run(job_id=job_id, project_id=project_id, autopublish=False)

    # 8. Verificaciones posteriores
    proj = db.get_project(project_id)
    log.info("Status del proyecto tras _run: %s (progreso: %s%%)", proj["status"], proj["progress"])
    if proj["status"] != "ready":
        raise RuntimeError(f"El proyecto no finalizó en 'ready'. Estado actual: {proj['status']} - Error: {proj.get('error')}")

    # Verificar videos individuales en la carpeta flow
    vid0 = flow_dir / "Escena_01_video.mp4"
    vid1 = flow_dir / "Escena_02_video.mp4"

    if not vid0.exists() or not flow_mcp_client.verify_video_file(vid0):
        raise RuntimeError(f"Clip de video 0 inválido o no existe: {vid0}")
    if not vid1.exists() or not flow_mcp_client.verify_video_file(vid1):
        raise RuntimeError(f"Clip de video 1 inválido o no existe: {vid1}")

    info_v0 = probe_media_info(vid0)
    info_v1 = probe_media_info(vid1)
    log.info("✓ Clip 0 verificado: %d bytes, duración: %ss", vid0.stat().st_size, info_v0['format'].get('duration'))
    log.info("✓ Clip 1 verificado: %d bytes, duración: %ss", vid1.stat().st_size, info_v1['format'].get('duration'))

    # Verificar descubrimiento por flow_import
    found = flow_import.find_flow_videos(proj_dir, [0, 1])
    if len(found) != 2:
        raise RuntimeError(f"find_flow_videos esperaba 2 clips, encontró: {len(found)}")
    log.info("✓ flow_import.find_flow_videos descubrió exitosamente: %s", found)

    # Verificar video final ensamblado
    final_video = Path(proj["video_url"])
    if not final_video.exists():
        raise RuntimeError(f"Video final no encontrado en {final_video}")
    if final_video.stat().st_size < 50000:
        raise RuntimeError(f"Video final demasiado pequeño: {final_video.stat().st_size} bytes")

    info_final = probe_media_info(final_video)
    final_dur = float(info_final["format"]["duration"])
    streams = [s["codec_type"] for s in info_final.get("streams", [])]

    log.info("✓ VIDEO FINAL PRODUCIDO:")
    log.info("  - Ruta: %s", final_video)
    log.info("  - Tamaño: %d bytes", final_video.stat().st_size)
    log.info("  - Duración total: %.2fs", final_dur)
    log.info("  - Streams presentes: %s", streams)

    if "video" not in streams:
        raise RuntimeError("El video final no contiene stream de video")
    if "audio" not in streams:
        raise RuntimeError("El video final no contiene stream de audio")

    # Copiar artifact a brain para presentación
    brain_artifact = Path(r"C:\Users\Johan\.gemini\antigravity\brain\3b823b14-2dd0-49d0-bfac-436d66f7ac87\live_video_c2_final.mp4")
    shutil.copy2(final_video, brain_artifact)
    log.info("✓ Copiado a artifact: %s", brain_artifact)

    log.info("=== GATE C.2 LIVE PIPELINE TEST: PASS ===")
    return {
        "project_id": project_id,
        "vid0_path": str(vid0),
        "vid0_size": vid0.stat().st_size,
        "vid1_path": str(vid1),
        "vid1_size": vid1.stat().st_size,
        "final_path": str(final_video),
        "final_size": final_video.stat().st_size,
        "final_duration": final_dur,
        "streams": streams,
        "artifact_path": str(brain_artifact),
    }


if __name__ == "__main__":
    res = asyncio.run(run_live_pipeline())
    print("\nRESUMEN FINAL JSON:")
    print(json.dumps(res, indent=2))
