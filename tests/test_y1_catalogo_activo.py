# -*- coding: utf-8 -*-
"""Y1 · GET /api/mcp/catalogo/{service} — catálogo COMPLETO de la conexión viva.

SOLO LECTURA y hermético: el endpoint lee la conexión YA activa del backend
(conn.tools del handshake MCP) y NUNCA conecta, nunca lanza procesos de
servidores MCP y nunca ejecuta una tool. Tests con dobles:
  (a) conectado → catálogo completo (description completa + inputSchema íntegro);
  (b) no conectado → 409 «conecta primero desde el panel» y connect NUNCA se llama;
  (c) servicio desconocido → 404.

Ejecutar: python3 -m pytest tests/test_y1_catalogo_activo.py -q
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services import mcp_manager as mcpm  # noqa: E402
from services.mcp_manager import ST_CONNECTED, manager  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)

# description > 120 chars: si el endpoint recortara (como /api/mcp/status),
# este test lo caza — el catálogo debe entregar la descripción COMPLETA.
DESC_LARGA = ("Añade una nota de texto al cuaderno indicado. " * 6).strip()
SCHEMA = {"type": "object",
          "properties": {"notebook_id": {"type": "string"},
                         "text": {"type": "string"},
                         "title": {"type": "string", "default": None}},
          "required": ["notebook_id", "text"]}


def _conn_fake():
    return SimpleNamespace(
        state=ST_CONNECTED,
        server_info={"name": "notebooklm-mcp-server", "version": "2.14.5"},
        tools=[{"name": "notebook_add_text", "description": DESC_LARGA,
                "inputSchema": dict(SCHEMA)}],
        auth="ok")


@pytest.fixture
def conns_vacias(monkeypatch):
    """Gestor SIN conexiones vivas y con connect vigilado: si el endpoint
    intentara conectar, el test grita."""
    vigilante = AsyncMock(return_value={"state": "connected"})
    monkeypatch.setattr(manager, "_conns", {})
    monkeypatch.setattr(manager, "connect", vigilante)
    return vigilante


def test_y1_conectado_devuelve_catalogo_completo(monkeypatch):
    """(a) Con conexión viva (doble): description COMPLETA e inputSchema
    íntegro — no el recorte de 120 caracteres de /api/mcp/status."""
    monkeypatch.setitem(manager._conns, "notebooklm", _conn_fake())

    r = client.get("/api/mcp/catalogo/notebooklm")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["service"] == "notebooklm"
    assert data["server_info"]["name"] == "notebooklm-mcp-server"
    (tool,) = data["tools"]
    assert tool["name"] == "notebook_add_text"
    assert tool["description"] == DESC_LARGA      # COMPLETA, sin recorte
    assert tool["inputSchema"] == SCHEMA          # íntegro (required incluido)
    manager.connect.assert_not_awaited() if hasattr(manager.connect, "assert_not_awaited") else None


def test_y1_no_conectado_error_claro_y_no_conecta(conns_vacias):
    """(b) Sin conexión viva → 409 con «conecta primero desde el panel»;
    el endpoint NUNCA llama a connect (no lanza procesos duplicados)."""
    r = client.get("/api/mcp/catalogo/notebooklm")
    assert r.status_code == 409, r.text
    assert "conecta primero desde el panel" in r.json()["detail"]
    conns_vacias.assert_not_awaited()             # SOLO LECTURA de verdad


def test_y1_servicio_desconocido_404(conns_vacias):
    """(c) Servicio desconocido → 404, sin intentar nada."""
    r = client.get("/api/mcp/catalogo/desconocido")
    assert r.status_code == 404, r.text
    conns_vacias.assert_not_awaited()


def test_y1_tools_catalog_modo_solo_lectura(monkeypatch):
    """El método manager.tools_catalog(service, auto_connect=False) se niega
    a conectar (contrato que el endpoint aprovecha); el default histórico
    (auto_connect=True) queda intacto para la vía --modo-local."""
    from services.mcp_manager import MCPManagerError

    vigilante = AsyncMock(return_value={"state": ST_CONNECTED})
    monkeypatch.setattr(manager, "_conns", {})
    monkeypatch.setattr(manager, "connect", vigilante)
    with pytest.raises(MCPManagerError) as e:
        import asyncio
        asyncio.run(manager.tools_catalog("google-flow", auto_connect=False))
    assert e.value.code == "NOT_CONNECTED"
    vigilante.assert_not_awaited()
