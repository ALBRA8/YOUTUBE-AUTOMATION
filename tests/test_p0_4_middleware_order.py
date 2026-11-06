import os
import sys
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import security
from main import app


@pytest.mark.asyncio
async def test_options_preflight_and_headers_with_master_key():
    """P0-4: Con MASTER_API_KEY activa:
    (a) OPTIONS preflight de la extensión devuelve 200 con cabeceras CORS (no 401 sin CORS);
    (b) respuestas 401 y 403 llevan X-Content-Type-Options: nosniff.
    """
    ext_origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"

    # Activar clave maestra para el test
    os.environ["MASTER_API_KEY"] = "supersecret_master_key_123"
    security.reload()
    assert security.enabled() is True

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            # (a) Preflight OPTIONS desde la extensión
            resp_options = await client.options(
                "/api/projects",
                headers={
                    "Origin": ext_origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "X-API-Key, Content-Type",
                }
            )
            assert resp_options.status_code == 200, f"OPTIONS preflight falló con {resp_options.status_code}: {resp_options.text}"
            assert resp_options.headers.get("access-control-allow-origin") == ext_origin
            assert "x-content-type-options" in resp_options.headers
            assert resp_options.headers["x-content-type-options"] == "nosniff"

            # (b) Respuesta 401 sin clave debe llevar X-Content-Type-Options: nosniff
            resp_401 = await client.get("/api/projects")
            assert resp_401.status_code == 401
            assert resp_401.headers.get("x-content-type-options") == "nosniff"

            # (c) Respuesta 403 por CSRF con clave válida pero origen externo
            resp_403 = await client.post(
                "/api/projects",
                headers={
                    "X-API-Key": "supersecret_master_key_123",
                    "Origin": "https://evil.example.com",
                    "Content-Type": "application/json"
                },
                content=b"{}"
            )
            assert resp_403.status_code == 403
            assert resp_403.headers.get("x-content-type-options") == "nosniff"

    finally:
        os.environ.pop("MASTER_API_KEY", None)
        security.reload()
