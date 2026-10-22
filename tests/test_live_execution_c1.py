#!/usr/bin/env python3
"""
LIVE TEST C.1: Ejecución Real de Video desde el Pipeline de YOUTUBE-AUTOMATION.

Ruta física evaluada:
  scene.image_path (scene_01.png)
      ↓
  pipeline bridge (generate_scene_video)
      ↓
  flow_mcp_client.upload_file("crystal_orb_c1")
      ↓
  flow_mcp_client.generate_video(start_frame="crystal_orb_c1")
      ↓
  GoogleFlowMCP (flow_generate_video)
      ↓
  CDP :9333 → Google Flow (Fotogramas → Iniciar → Video)
      ↓
  MP4 stream download
      ↓
  output/_live_video_test_02/flow/Escena_01_video.mp4
      ↓
  flow_import.find_flow_videos()
      ↓
  ffprobe validation
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config
config.FLOW_MCP_ENABLED = True

from pipeline import flow_import, images as imgs_pipeline
from services import flow_mcp_client


async def run_live_test_c1():
    print("=" * 70)
    print("=== ALBRA · GATE C.1 LIVE VIDEO TEST ===")
    print("=" * 70)

    # 1. Configuración de entrada
    project_id = "_live_video_test_02"
    proj_dir = REPO_ROOT / "backend" / "data" / "output" / project_id
    flow_dir = proj_dir / "flow"
    flow_dir.mkdir(parents=True, exist_ok=True)

    start_frame_path = REPO_ROOT / "backend" / "data" / "output" / "_live_mcp_test_01" / "scene_01.png"
    if not start_frame_path.exists():
        raise FileNotFoundError(f"Start Frame origen ausente: {start_frame_path}")
    start_frame_bytes = start_frame_path.stat().st_size
    print(f"[1] Start Frame verificado: {start_frame_path} ({start_frame_bytes:,} bytes)")

    target_mp4 = flow_dir / "Escena_01_video.mp4"
    if target_mp4.exists() and flow_mcp_client.verify_video_file(target_mp4):
        print(f"[1b] Video target preexistente verificado: {target_mp4} ({target_mp4.stat().st_size:,} bytes)")

    # 2. Verificar cliente Flow MCP disponible
    available = flow_mcp_client.available()
    print(f"[2] flow_mcp_client.available(): {available}")
    if not available:
        raise RuntimeError("GoogleFlowMCP no está disponible")

    # 3. Datos de Escena y Proyecto para el Pipeline Bridge
    prompt_c1 = (
        "Animate the starting image naturally while preserving the exact subject, "
        "composition, environment, lighting and visual identity. Add subtle cinematic "
        "camera movement and realistic environmental motion with smooth temporal consistency."
    )
    scene = {
        "idx": 0,
        "image_path": str(start_frame_path),
        "video_prompt": prompt_c1,
    }
    project = {
        "id": project_id,
        "format": "short",
        "output_dir": str(proj_dir),
    }
    asset_name = "crystal_orb_c1"

    # 4. Invocación de alto nivel a través del Pipeline Bridge
    print(f"[3] Invocando pipeline bridge: generate_scene_video()...")
    start_time = time.time()
    generated_mp4 = await imgs_pipeline.generate_scene_video(
        scene=scene,
        project=project,
        idx=0,
        start_frame_path=start_frame_path,
        asset_name=asset_name,
        prompt=prompt_c1,
        aspect="9:16",
        timeout=900.0,
    )
    elapsed_sec = round(time.time() - start_time, 2)
    print(f"[4] generate_scene_video completado en {elapsed_sec}s -> {generated_mp4}")

    # 5. Verificación física del archivo destino
    if not generated_mp4 or not generated_mp4.exists():
        raise RuntimeError(f"El archivo MP4 no fue creado en {generated_mp4}")
    mp4_bytes = generated_mp4.stat().st_size
    print(f"[5] Archivo generado verificado: {generated_mp4} ({mp4_bytes:,} bytes)")

    # 6. Validación exhaustiva con ffprobe
    print(f"[6] Validando stream con ffprobe...")
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration,size,bit_rate:stream=codec_name,codec_type,width,height,r_frame_rate,nb_frames",
        "-of", "json",
        str(generated_mp4),
    ]
    probe_run = subprocess.run(cmd, capture_output=True, text=True, check=True)
    probe_info = json.loads(probe_run.stdout)

    video_stream = next((s for s in probe_info.get("streams", []) if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in probe_info.get("streams", []) if s.get("codec_type") == "audio"), None)
    format_info = probe_info.get("format", {})

    duration = float(format_info.get("duration", 0))
    width = video_stream.get("width") if video_stream else 0
    height = video_stream.get("height") if video_stream else 0
    codec_name = video_stream.get("codec_name") if video_stream else "unknown"

    print(f"    - Duración: {duration:.2f} s")
    print(f"    - Resolución: {width}x{height}")
    print(f"    - Video Codec: {codec_name}")
    print(f"    - Audio Presente: {'SÍ (' + audio_stream.get('codec_name') + ')' if audio_stream else 'NO'}")

    assert duration > 0.0, "Duración debe ser mayor a 0"
    assert width > 0 and height > 0, "Resolución inválida"
    assert codec_name in ("h264", "hevc", "vp9", "av1"), f"Codec inesperado: {codec_name}"

    # 7. Verificación del consumidor del pipeline (flow_import.find_flow_videos)
    print(f"[7] Verificando detección nativa por flow_import.find_flow_videos()...")
    flow_videos = flow_import.find_flow_videos(proj_dir, [0])
    print(f"    find_flow_videos() devolvió: {flow_videos}")
    assert 0 in flow_videos, "Escena 0 no fue detectada por find_flow_videos"
    assert flow_videos[0].resolve() == generated_mp4.resolve(), "La ruta detectada no coincide con el target generado"
    print("    [OK] PASS: El pipeline consumidor detecta el video de Flow directamente")

    # 8. Verificación del Lock (.flow.lock)
    lock_file = REPO_ROOT / "tools" / "GoogleFlowMCP" / ".flow.lock"
    lock_active = lock_file.exists()
    print(f"[8] Estado de .flow.lock: {'ACTIVO' if lock_active else 'LIBERADO (Clean)'}")
    assert not lock_active, ".flow.lock quedó retenido indebidamente"

    report = {
        "status": "PASS",
        "project_id": project_id,
        "scene_index": 0,
        "start_frame_path": str(start_frame_path),
        "start_frame_bytes": start_frame_bytes,
        "asset_name": asset_name,
        "video_output_path": str(generated_mp4),
        "video_bytes": mp4_bytes,
        "duration_sec": duration,
        "resolution": f"{width}x{height}",
        "video_codec": codec_name,
        "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
        "elapsed_sec": elapsed_sec,
        "lock_clean": not lock_active,
    }
    print("\n" + "=" * 70)
    print("=== LIVE TEST C.1 COMPLETADO: GATE C.1 — PASS ===")
    print("=" * 70)
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    asyncio.run(run_live_test_c1())
