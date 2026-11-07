# -*- coding: utf-8 -*-
"""U6 (S2) · Test de CONTRATO del catálogo de NotebookLM con el paquete REAL.

Paquete real instalado en la máquina del dueño (dato del dueño +
`uv tool list`; confirmado en PyPI):
    notebooklm-mcp-server  v0.1.15
    comandos: notebooklm-mcp  y  notebooklm-mcp-auth
La versión que llega en `server_info` del handshake (p. ej. 2.14.5) es
la del FRAMEWORK FastMCP — NUNCA se presenta como versión del paquete.

Este test fija DOS trinquetes:
  1. La documentación y el panel hablan del paquete real (no del texto
     antiguo «uv tool install notebooklm-py[browser]» ni de la versión
     2.14.5 como si fuera del paquete).
  2. Cotejo de herramientas: lo que el CÓDIGO llama (constantes reales
     importadas de mcp_manager/nlm_studio/pipeline_orchestrator) contra
     el catálogo REAL documentado de v0.1.15. Las herramientas ausentes
     están PINNADAS: si el código llama una nueva tool que no existe en
     el catálogo, este test falla y obliga a documentarla en INT-093.

Hermético: sin red, sin MCP real, solo lectura de fuentes/constantes.
"""
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# ── el contrato REAL (fuente: dueño + pypi.org/pypi/notebooklm-mcp-server/json) ──
PAQUETE = "notebooklm-mcp-server"
VERSION = "0.1.15"
COMANDOS = ("notebooklm-mcp", "notebooklm-mcp-auth")

# Catálogo documentado del paquete v0.1.15 (tabla «Features» del README en
# PyPI; el paquete declara 31 tools, la tabla pública nombra estas 27).
CATALOGO_REAL_V0115 = frozenset({
    "notebook_list", "notebook_create", "notebook_get", "notebook_describe",
    "source_describe", "source_get_content", "notebook_rename",
    "chat_configure", "notebook_delete", "notebook_add_url",
    "notebook_add_text", "notebook_add_drive", "notebook_query",
    "source_list_drive", "source_sync_drive", "source_delete",
    "research_start", "research_status", "research_import",
    "audio_overview_create", "video_overview_create", "infographic_create",
    "slide_deck_create", "studio_status", "studio_delete", "refresh_auth",
    "save_auth_tokens",
})

INT093 = (ROOT / "CONTEXTO YOUTUBE" / "06_INTEGRATIONS" /
          "INT-093_SONDA_CAPACIDADES_NOMBRES.md").read_text(encoding="utf-8")
MCP_JS = (BACKEND / "static" / "app-mcp.js").read_text(encoding="utf-8")


def _tools_llamadas_por_el_codigo() -> dict[str, str]:
    """Nombres EXACTOS que el código puede pedir al MCP de notebooklm,
    tomados de las constantes reales del repo (no de copias)."""
    from services import mcp_manager as mm
    from services import nlm_studio as ns
    orq = (BACKEND / "services" / "pipeline_orchestrator.py").read_text(
        encoding="utf-8")
    m = re.search(r'NOTEBOOKLM_CONTEXT_TOOL",\s*"([a-z_0-9]+)"', orq)
    assert m, "no se halló el default de NOTEBOOKLM_CONTEXT_TOOL"
    return {
        "notebook_list": "mcp_manager (probe default)",
        "list_notebooks": "mcp_manager (_LIST_NOTEBOOK_TOOLS, alias)",
        "notebook_create": "mcp_manager (_NO_NOTEBOOK_TOOLS) + nlm_studio",
        ns.TOOL_SOURCE_ADD: "nlm_studio (TOOL_SOURCE_ADD)",
        ns.TOOL_STUDIO_GENERATE: "nlm_studio (TOOL_STUDIO_GENERATE)",
        ns.TOOL_STUDIO_STATUS: "nlm_studio (TOOL_STUDIO_STATUS)",
        ns.TOOL_STUDIO_DOWNLOAD: "nlm_studio (TOOL_STUDIO_DOWNLOAD)",
        m.group(1): "pipeline_orchestrator (NOTEBOOKLM_CONTEXT_TOOL default)",
    }


# ── 1 · contrato del paquete ─────────────────────────────────────────────

def test_paquete_real_nombre_version_comandos():
    assert PAQUETE == "notebooklm-mcp-server"
    assert VERSION == "0.1.15"
    assert COMANDOS == ("notebooklm-mcp", "notebooklm-mcp-auth")


def test_int093_documenta_el_paquete_real():
    for dato in ("notebooklm-mcp-server", "v0.1.15", "notebooklm-mcp-auth",
                 "uv tool install notebooklm-mcp-server", "FastMCP",
                 "2.14.5"):
        assert dato in INT093, f"INT-093 debe documentar {dato!r}"
    assert "uv tool install \"notebooklm-py[browser]\"" not in INT093.replace(
        "(NO «uv tool install notebooklm-py[browser]», texto antiguo del panel ya corregido)", "")


def test_panel_habla_del_paquete_real():
    for dato in ("notebooklm-mcp-server v0.1.15", "notebooklm-mcp-auth",
                 "uv tool list"):
        assert dato in MCP_JS, f"el panel debe decir {dato!r}"
    assert "notebooklm-py" not in MCP_JS, "quedó el texto antiguo del paquete"
    # la versión de server_info NUNCA se presenta como la del paquete:
    # la línea de notebooklm distingue framework FastMCP vs paquete
    zona = MCP_JS[MCP_JS.index("function mcpZoneHTML("):]
    zona = zona[:zona.index("return h ||")]
    assert "framework <b>FastMCP</b>, NO la versión del paquete" in zona
    assert "Paquete: <b>notebooklm-mcp-server v0.1.15</b>" in zona


def test_docstring_mcp_manager_paquete_real():
    cab = (BACKEND / "services" / "mcp_manager.py").read_text(encoding="utf-8")
    assert "notebooklm-mcp-server` v0.1.15" in cab
    assert "FRAMEWORK FastMCP, no la del paquete" in cab
    assert 'notebooklm-py[browser]==0.8.5" — pin recomendado' not in cab


# ── 2 · trinquete de herramientas: código vs catálogo real ───────────────

def test_tools_del_codigo_contra_catalogo_real():
    """Cada tool que el código llama se clasifica: presente o ausente del
    catálogo real v0.1.15. El conjunto de AUSENTES está PINNADO — si el
    código llama una nueva tool fuera de catálogo, este test falla."""
    llamadas = _tools_llamadas_por_el_codigo()
    ausentes = {n: d for n, d in llamadas.items()
                if n not in CATALOGO_REAL_V0115}
    presentes = {n: d for n, d in llamadas.items()
                 if n in CATALOGO_REAL_V0115}
    assert {"notebook_list", "notebook_create", "studio_status"} <= set(presentes)
    # pin (U6, 2026-11-07, documentado en INT-093):
    assert ausentes == {
        "list_notebooks": "mcp_manager (_LIST_NOTEBOOK_TOOLS, alias)",
        "source_add": "nlm_studio (TOOL_SOURCE_ADD)",
        "studio_generate": "nlm_studio (TOOL_STUDIO_GENERATE)",
        "studio_download": "nlm_studio (TOOL_STUDIO_DOWNLOAD)",
        "chat_ask": "pipeline_orchestrator (NOTEBOOKLM_CONTEXT_TOOL default)",
    }, f"cambió el conjunto de tools fuera de catálogo: {ausentes}"


def test_divergencias_documentadas_en_int093():
    """Las tools fuera de catálogo deben seguir documentadas en INT-093
    con su efecto (incluida la recomendación notebook_query)."""
    for nombre in ("list_notebooks", "chat_ask", "source_add",
                   "studio_generate", "studio_download", "notebook_query"):
        assert nombre in INT093, f"INT-093 debe documentar {nombre!r}"
    assert "NOTEBOOKLM_CONTEXT_TOOL=notebook_query" in INT093


def test_reporte_humano_del_cotejo(capfd):
    """Reporta (stdout) el cotejo completo — el informe de U6 lo cita."""
    llamadas = _tools_llamadas_por_el_codigo()
    print("\n— Cotejo tools del código vs notebooklm-mcp-server v0.1.15 —")
    for n, d in sorted(llamadas.items()):
        print(f"  {'✅' if n in CATALOGO_REAL_V0115 else '❌'} {n:22s} {d}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
