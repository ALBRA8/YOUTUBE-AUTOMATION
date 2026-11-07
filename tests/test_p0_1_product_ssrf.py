# -*- coding: utf-8 -*-
"""H1b · Regresión SSRF del modo producto — HERMÉTICA (sin red real).

La versión anterior de este test dejaba correr la cadena de fallback de
generate_scene_image tras el rechazo del product image_url, y esa cadena
llegaba al plan B (_zai_image → CLI `z-ai` externo, hasta 120 s por intento,
generación real vía servicio externo). Lento, externo y no-hermético: aquí
lo que se prueba es el RECHAZO de la URL de producto, no la generación de
imágenes, así que los planes de generación van con DOBLES DE PRUEBA:

  · flow_mcp_client.available → False (ya estaba)
  · gemini_client sin clave (ya estaba, GEMINI_API_KEY="")
  · pipeline.images._zai_image → doble async que devuelve False (H1b)
  · sin imagen de extensión en BD (no hay)

Con eso la cadena termina en el placeholder PIL local y el test mide SOLO
que product_raw.png jamás se crea desde una URL SSRF (file://, loopback,
169.254.x, LAN privada).

Ejecutar: python3 -m pytest tests/test_p0_1_product_ssrf.py -q
"""
import asyncio
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config
import services.flow_mcp_client as flow_mcp_client
from pipeline import images as pipeline_images
from pipeline.images import generate_scene_image


@pytest.mark.asyncio
async def test_product_mode_ssrf_rejected(tmp_path, monkeypatch):
    """Verifica que el modo producto rechace SSRF (file://, loopback, 169.254.x)
    usando security.safe_fetch_bytes sin descargar nada no permitido.
    """
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(flow_mcp_client, "available", lambda: False)

    # H1b · doble de prueba: el plan B (CLI z-ai externo, hasta 120 s) se
    # sustituye por "no disponible" — la cadena degrada a placeholder local
    # sin tocar red. Que el plan B se INTENTE es comportamiento normal del
    # pipeline tras el rechazo del producto; lo que prohíbe el test es que
    # salga a la red real.
    async def _zai_doble(prompt, out, fmt):
        return False

    monkeypatch.setattr(pipeline_images, "_zai_image", _zai_doble)

    (tmp_path / "output").mkdir(parents=True, exist_ok=True)

    project_id = "test_ssrf_proj"
    proj_dir = tmp_path / "output" / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)

    bad_urls = [
        "file:///etc/passwd",
        "http://127.0.0.1:8000/api/config",
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.1/admin",
    ]

    for bad_url in bad_urls:
        project = {
            "id": project_id,
            "style": "minimal",
            "mode": "product",
            "format": "short",
            "meta": {
                "product_data": {
                    "image_url": bad_url
                }
            }
        }
        scene = {
            "title": "hook",
            "image_prompt": "A bottle on a table"
        }
        # generate_scene_image captura la excepción internamente y registra warning
        # pero NUNCA debe haber descargado o creado el product_raw.png con contenido SSRF
        raw_prod = proj_dir / "scenes" / "product_raw.png"
        if raw_prod.is_file():
            raw_prod.unlink()

        out, method = await generate_scene_image(scene, project, 0)
        # raw_prod no debe existir porque la URL debe ser rechazada por safe_fetch_bytes
        assert not raw_prod.is_file(), (
            f"raw_prod no debe haberse creado para URL SSRF {bad_url}")
        # y la escena termina en placeholder local (sin ningún plan de red)
        assert out.is_file() and method == "placeholder", (
            f"esperado placeholder local hermético, llegó: {method}")


if __name__ == "__main__":
    asyncio.run(test_product_mode_ssrf_rejected(Path("tests/tmp_p01"), None))
    print("PASS: test_product_mode_ssrf_rejected")
