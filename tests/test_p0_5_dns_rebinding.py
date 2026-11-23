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


def test_origin_allowed_rejects_external_host_origin_match():
    """P0-5: origin_allowed no debe aceptar Origin==Host cuando el Host es externo (DNS rebinding)."""
    # Host y Origin externos idénticos (escenario clásico de DNS rebinding)
    ext_host = "evil.attacker.example.com"
    ext_origin = f"http://{ext_host}:8000"

    # Debe ser RECHAZADO, nunca True
    allowed = security.origin_allowed(ext_origin, ext_host)
    assert allowed is False, f"Vulnerabilidad DNS Rebinding: origin_allowed aceptó host externo {ext_host}"

    # Hosts locales legítimos SÍ deben permitirse
    assert security.origin_allowed("http://localhost:8000", "localhost:8000") is True
    assert security.origin_allowed("http://127.0.0.1:8000", "127.0.0.1:8000") is True
    assert security.origin_allowed("http://[::1]:8000", "[::1]:8000") is True


@pytest.mark.asyncio
async def test_dns_rebinding_mutation_rejected_in_local_mode():
    """P0-5: Sin MASTER_API_KEY (modo local abierto), un ataque con Host y Origin externos debe rechazarse con 403."""
    # Asegurar que no hay MASTER_API_KEY activa
    os.environ.pop("MASTER_API_KEY", None)
    security.reload()
    assert security.enabled() is False

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        # Petición maliciosa simulando DNS rebinding (Host y Origin de atacante apuntando a 127.0.0.1)
        resp = await client.post(
            "/api/projects",
            headers={
                "Host": "evil.attacker.example.com",
                "Origin": "http://evil.attacker.example.com",
                "Content-Type": "application/json"
            },
            content=b"{}"
        )
        assert resp.status_code == 403, f"Ataque DNS rebinding no fue bloqueado, status: {resp.status_code}"
