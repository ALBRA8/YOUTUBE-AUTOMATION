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
from pipeline.images import generate_scene_image


@pytest.mark.asyncio
async def test_product_mode_ssrf_rejected(tmp_path, monkeypatch):
    """Verifica que el modo producto rechace SSRF (file://, loopback, 169.254.x)
    usando security.safe_fetch_bytes sin descargar nada no permitido.
    """
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(flow_mcp_client, "available", lambda: False)
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
        assert not raw_prod.is_file(), f"raw_prod no debe haberse creado para URL SSRF {bad_url}"


if __name__ == "__main__":
    asyncio.run(test_product_mode_ssrf_rejected(Path("tests/tmp_p01"), None))
    print("PASS: test_product_mode_ssrf_rejected")
