#!/usr/bin/env python3
"""
LIVE TEST 2: YOUTUBE-AUTOMATION x GoogleFlowMCP (Scene Asset Resolver End-to-End)

Prueba real en vivo con Google Flow vía MCP:
- 1 referencia local real (backend/data/output/_live_mcp_test_01/scene_01.png)
- Proyecto aislado: _live_mcp_test_02
- Subida de activo mediante flow_upload_file ('crystal_orb')
- Inyección de mención @{crystal_orb} en el prompt
- Generación de imagen real vía Nano Banana
- Descarga y verificación del PNG en disco (> 4096 bytes)
- Liberación de .flow.lock
"""
import asyncio
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path("D:/PROYECTOS/YOUTUBE AUTOMATION")
BACKEND_DIR = REPO_ROOT / "backend"
VENV_PACKAGES = BACKEND_DIR / ".venv" / "Lib" / "site-packages"

sys.path.insert(0, str(VENV_PACKAGES))
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(REPO_ROOT))

# Activar temporalmente el feature flag en el proceso
os.environ["FLOW_MCP_ENABLED"] = "1"

import config
from pipeline import images as imgs_pipeline
from services import flow_mcp_client


async def run_live_test_2():
    print("=== LIVE TEST 2: YOUTUBE-AUTOMATION x GoogleFlowMCP (Scene Asset Resolver) ===")
    print(f"FLOW_MCP_ENABLED: {config.FLOW_MCP_ENABLED}")
    print(f"flow_mcp_client.available(): {flow_mcp_client.available()}")
    assert flow_mcp_client.available(), "flow_mcp_client no está disponible con flag activo"

    ref_file = (BACKEND_DIR / "data" / "output" / "_live_mcp_test_01" / "scene_01.png").resolve()
    assert ref_file.is_file(), f"Imagen de referencia no encontrada: {ref_file}"
    print(f"Imagen de referencia local: {ref_file} ({ref_file.stat().st_size} bytes)")

    project_id = "_live_mcp_test_02r"
    project = {
        "id": project_id,
        "format": "short",
        "style": "cinematic"
    }

    # Definir escena con referencia real y nombre explícito
    scene = {
        "id": 1,
        "image_prompt": "Transform this artifact into a radiant cosmic galaxy orb surrounded by stardust, 8k resolution, cinematic lighting",
        "references": [
            {
                "path": str(ref_file),
                "name": "crystal_orb",
                "required": True,
            }
        ]
    }

    print(f"Proyecto de prueba: {project_id}")
    print(f"Prompt base: {scene['image_prompt']}")
    print(f"Referencia declarada: {scene['references']}")
    print("Iniciando generate_scene_image con resolución de assets...")

    start_time = time.time()
    out_path, method = await imgs_pipeline.generate_scene_image(scene, project, 1)
    duration = time.time() - start_time

    print(f"\n--- RESULTADO DE LA EJECUCIÓN ({duration:.2f}s) ---")
    print(f"Método devuelto: {method}")
    print(f"Ruta resultante: {out_path}")
    print(f"Existe en disco: {out_path.is_file()}")

    if out_path.is_file():
        size = out_path.stat().st_size
        print(f"Tamaño del archivo: {size} bytes ({size / 1024:.1f} KB)")
        verified = flow_mcp_client.verify_image_file(out_path)
        print(f"Verificación de imagen válida: {verified}")
    else:
        print("ERROR: El archivo no existe.")

    # Verificación de cerrojos huérfanos
    lock_dir = REPO_ROOT / "tools" / "GoogleFlowMCP" / ".flow.lock"
    print(f"Cerrojo .flow.lock presente tras ejecución: {lock_dir.exists()}")

    # Verificar que el método sea exactamente flow_mcp y el archivo sea válido
    if method == "flow_mcp" and out_path.is_file() and out_path.stat().st_size > 4096:
        print("\n>>> DICTAMEN: PASS <<<")
        return 0
    else:
        print(f"\n>>> DICTAMEN: FAIL (Método: {method}) <<<")
        return 1


if __name__ == "__main__":
    ret = asyncio.run(run_live_test_2())
    sys.exit(ret)
