# -*- coding: utf-8 -*-
"""Batería BD: Tests herméticos para:
2A: Filtrado y desduplicación de cookies para BASE_URL en mcp_manager.
2B: Extracción de build label de NotebookLM y orden de precedencia.
2C: Cadena de modelos de texto Gemini con fallback ante 404 NOT_FOUND.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config
from services import gemini_client, mcp_manager as mcpm, pipeline_orchestrator as po


# ==============================================================================
# 2A: FILTRADO Y DESDUPLICACIÓN DE COOKIES
# ==============================================================================

def test_2a_cookie_filtering_and_deduplication():
    """2A: _filter_and_dedupe_cookies descarta accounts.google.com y hosts no-google,
    y desduplica haciendo ganar al host más específico."""
    raw_cookies = [
        {"name": "SID", "value": "sid_generic", "domain": ".google.com"},
        {"name": "SID", "value": "sid_specific", "domain": "notebook.google.com"},
        {"name": "ACCOUNT_COOKIE", "value": "secret", "domain": "accounts.google.com"},
        {"name": "OTHER_HOST", "value": "val", "domain": "malicious.com"},
        {"name": "__Secure-1PSID", "value": "sec_1psid", "domain": ".google.com"},
        {"name": "THEME", "value": "dark", "domain": ".gstatic.com"},
    ]

    filtered = mcpm.MCPClientManager._filter_and_dedupe_cookies(raw_cookies)

    # 1. No debe contener cookies de accounts.google.com ni de otros hosts
    assert "ACCOUNT_COOKIE" not in filtered
    assert "OTHER_HOST" not in filtered

    # 2. Debe contener cookies válidas
    assert "__Secure-1PSID" in filtered
    assert filtered["__Secure-1PSID"] == "sec_1psid"
    assert filtered["THEME"] == "dark"

    # 3. Desduplicación: notebook.google.com debe ganar sobre .google.com para SID
    assert filtered["SID"] == "sid_specific"


def test_2a_sync_auth_json_with_filtering():
    """2A: _sync_auth_json persiste solo las cookies válidas y desduplicadas."""
    mgr = mcpm.MCPClientManager()
    with tempfile.TemporaryDirectory() as td:
        auth_file = Path(td) / "auth.json"
        raw_cookies = [
            {"name": "SID", "value": "gen", "domain": ".google.com"},
            {"name": "SID", "value": "win", "domain": "notebook.google.com"},
            {"name": "BAD", "value": "drop", "domain": "accounts.google.com"},
        ]
        ok = mgr._sync_auth_json(raw_cookies, target_path=auth_file)
        assert ok is True
        saved = json.loads(auth_file.read_text(encoding="utf-8"))
        assert saved["cookies"]["SID"] == "win"
        assert "BAD" not in saved["cookies"]


# ==============================================================================
# 2B: BUILD LABEL DERIVADO EN VIVO Y PRECEDENCIA
# ==============================================================================

def test_2b_extract_build_label_from_html():
    """2B: extract_build_label extrae el bl vivo de fragmentos HTML."""
    html_ok = """
    <html>
      <head>
        <script>
          window.WIZ_global_data = {
            "cfb2h": "boq_labs-tailwind-frontend_20261117.07_p0"
          };
        </script>
      </head>
      <body>NotebookLM</body>
    </html>
    """
    assert mcpm.extract_build_label(html_ok) == "boq_labs-tailwind-frontend_20261117.07_p0"

    html_none = "<html><body>No build label here</body></html>"
    assert mcpm.extract_build_label(html_none) is None


@pytest.mark.asyncio
async def test_2b_build_label_precedence():
    """2B: Precedencia: bl vivo > variable de entorno NOTEBOOKLM_BL > config.py."""
    mgr = mcpm.MCPClientManager()

    # Caso 1: Solo valor por defecto de config
    with patch.dict(os.environ, {}, clear=True):
        with patch.object(config, "DEFAULT_NOTEBOOKLM_BL", "boq_labs-tailwind-frontend_20261117.07_p0"):
            with patch.object(config, "NOTEBOOKLM_BL", "boq_labs-tailwind-frontend_20261117.07_p0"):
                mgr._live_bl = None
                env = {}
                with patch.object(mgr, "_resolve_command", return_value=(["mock"], None)):
                    with patch("asyncio.create_subprocess_exec", AsyncMock()) as mock_exec:
                        # Simulamos spawn para ver env
                        conn = await mgr._spawn("notebooklm")
                        call_kwargs = mock_exec.call_args.kwargs
                        assert call_kwargs["env"]["NOTEBOOKLM_BL"] == "boq_labs-tailwind-frontend_20261117.07_p0"

    # Caso 2: Variable de entorno NOTEBOOKLM_BL sobreescribe config
    with patch.dict(os.environ, {"NOTEBOOKLM_BL": "boq_labs-tailwind-frontend_20261119.01_p0"}):
        mgr._live_bl = None
        with patch.object(mgr, "_resolve_command", return_value=(["mock"], None)):
            with patch("asyncio.create_subprocess_exec", AsyncMock()) as mock_exec:
                conn = await mgr._spawn("notebooklm")
                call_kwargs = mock_exec.call_args.kwargs
                assert call_kwargs["env"]["NOTEBOOKLM_BL"] == "boq_labs-tailwind-frontend_20261119.01_p0"

    # Caso 3: bl vivo derivado de página gana sobre TODO
    with patch.dict(os.environ, {"NOTEBOOKLM_BL": "boq_labs-tailwind-frontend_20261119.01_p0"}):
        mgr._live_bl = "boq_labs-tailwind-frontend_20261120.99_p0"
        with patch.object(mgr, "_resolve_command", return_value=(["mock"], None)):
            with patch("asyncio.create_subprocess_exec", AsyncMock()) as mock_exec:
                conn = await mgr._spawn("notebooklm")
                call_kwargs = mock_exec.call_args.kwargs
                assert call_kwargs["env"]["NOTEBOOKLM_BL"] == "boq_labs-tailwind-frontend_20261120.99_p0"


# ==============================================================================
# 2C: CADENA DE MODELOS GEMINI CON FALLBACK Y REGISTRO
# ==============================================================================

@pytest.mark.asyncio
async def test_2c_gemini_fallback_chain_on_404():
    """2C: Si el modelo configurado devuelve 404, prueba el siguiente de GEMINI_TEXT_MODEL_FALLBACKS
    y recuerda el primero que funcione."""
    gemini_client.set_remembered_text_model(None)

    # Configuramos primaria = gemini-2.5-flash (fallará 404), fallbacks = [gemini-3.8-flash]
    with patch.object(config, "GEMINI_API_KEY", "test_key"):
        with patch.object(config, "GEMINI_TEXT_MODEL", "gemini-2.5-flash"):
            with patch.object(config, "GEMINI_TEXT_MODEL_FALLBACKS", ["gemini-3.8-flash"]):
                attempted_models = []

                class FakeResponse:
                    text = '{"title": "Test Title", "scenes": []}'

                def fake_generate_content(*args, **kwargs):
                    model_called = kwargs.get("model")
                    attempted_models.append(model_called)
                    if model_called == "gemini-2.5-flash":
                        err = Exception("404 NOT_FOUND. Model models/gemini-2.5-flash is no longer available.")
                        setattr(err, "code", 404)
                        raise err
                    return FakeResponse()

                mock_client = MagicMock()
                mock_client.models.generate_content.side_effect = fake_generate_content

                with patch.object(gemini_client, "client", return_value=mock_client):
                    result = await gemini_client.generate_json("prompt de prueba")

                    assert attempted_models == ["gemini-2.5-flash", "gemini-3.8-flash"]
                    assert result.get("title") == "Test Title"
                    # Verifica que recordó el modelo que funcionó
                    assert gemini_client.get_active_text_model() == "gemini-3.8-flash"

                    # Segunda llamada: ya debe usar directamente el recordado sin volver a probar el 404
                    attempted_models.clear()
                    await gemini_client.generate_json("segundo prompt")
                    assert attempted_models == ["gemini-3.8-flash"]


@pytest.mark.asyncio
async def test_2c_gemini_fallback_chain_all_fail_raises():
    """2C: Si todos los modelos de la cadena devuelven 404, relanza la excepción."""
    gemini_client.set_remembered_text_model(None)

    with patch.object(config, "GEMINI_API_KEY", "test_key"):
        with patch.object(config, "GEMINI_TEXT_MODEL", "gemini-fail-1"):
            with patch.object(config, "GEMINI_TEXT_MODEL_FALLBACKS", ["gemini-fail-2"]):
                def fake_fail(*args, **kwargs):
                    err = Exception("404 NOT_FOUND")
                    setattr(err, "code", 404)
                    raise err

                mock_client = MagicMock()
                mock_client.models.generate_content.side_effect = fake_fail

                with patch.object(gemini_client, "client", return_value=mock_client):
                    with pytest.raises(Exception) as exc_info:
                        await gemini_client.generate_json("prompt")
                    assert "404" in str(exc_info.value)


if __name__ == "__main__":
    import sys
    # Batería standalone (tests/run_all.py): plugin pytest para resumen parseable
    class _Resumen:
        def __init__(self) -> None:
            self.ok = self.fallos = 0

        def pytest_runtest_logreport(self, report):
            if report.when == "call":
                if report.passed:
                    self.ok += 1
                elif report.failed:
                    self.fallos += 1

    _res = _Resumen()
    _code = pytest.main([__file__, "-q"], plugins=[_res])
    print(f"\n{_res.ok} OK · {_res.fallos} fallos")
    sys.exit(int(_code))
