"""
AUDITORÍA MULTI-FUENTE 2026-11 — secretos fuera de los logs (regresión).

Antes, _retry() loggeaba la excepción EN CRUDO: los errores de la API de
Gemini pueden ECOAR la API key («API key not valid. …[AIza…]», la URL del
request con ?key=…, un Bearer…). Ahora todo lo que llega a log pasa por
gemini_client._sanitize_error(), que redacta la credencial configurada y
los patrones de credencial conocidos. Todo con DOBLES: sin red, sin
credenciales reales.
"""
import asyncio
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
from services import gemini_client as gc  # noqa: E402

FAKE_KEY = "AIzaSyFakeFakeFakeFakeFakeFakeFakeFake"


@pytest.fixture()
def with_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", FAKE_KEY, raising=False)
    return FAKE_KEY


# ── 1 · redacciones unitarias ──────────────────────────────────────────────
def test_redacta_la_api_key_configurada(with_key):
    s = gc._sanitize_error(f"API key not valid. Please pass a valid API key. [{FAKE_KEY}]")
    assert FAKE_KEY not in s and gc._REDACTED in s


def test_redacta_formato_google_aisa_desconocido(with_key):
    s = gc._sanitize_error("request to v1beta?key=AIzaSyOtRaClaveDesconocida12345 falló")
    assert "AIzaSyOtRaClaveDesconocida12345" not in s and gc._REDACTED in s


def test_redacta_bearer(with_key):
    s = gc._sanitize_error("Unauthorized: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.trampa")
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in s
    assert "Bearer " in s and gc._REDACTED in s


def test_redacta_params_de_url(with_key):
    s = gc._sanitize_error(
        "GET https://generativelanguage.googleapis.com/v1beta/models"
        "?api_key=supersecreto123&key=otrosecreto99&x=1 → 400")
    assert "supersecreto123" not in s and "otrosecreto99" not in s
    assert "x=1" in s  # los params benignos NO se tocan


def test_no_toca_texto_normal(with_key):
    original = "Connection reset by peer (errno 104)"
    assert gc._sanitize_error(original) == original


def test_jamas_lanza(with_key):
    assert isinstance(gc._sanitize_error(None), str)
    assert isinstance(gc._sanitize_error(123), str)


def test_key_corta_no_redacta_inocuos(with_key, monkeypatch):
    # una "key" de <8 chars no se busca (evitar redacciones absurdas)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "abc", raising=False)
    assert gc._sanitize_error("el modelo abc no respondió") == "el modelo abc no respondió"


# ── 2 · regresión: _retry ya no loggea el error en crudo ───────────────────
def test_retry_loggea_sanitizado(with_key, monkeypatch, caplog):
    import logging as _logging
    llamadas = {"n": 0}

    async def siempre_falla():
        llamadas["n"] += 1
        raise RuntimeError(f"quota exceeded for key {FAKE_KEY}")

    async def sleep_instante(_):
        return None

    monkeypatch.setattr(gc.asyncio, "sleep", sleep_instante)
    with caplog.at_level(_logging.WARNING, logger="gemini"):
        with pytest.raises(RuntimeError):
            asyncio.run(gc._retry(siempre_falla, tries=3, base=0.0))
    assert llamadas["n"] == 3  # reintentó 2 veces antes de rendirse
    assert FAKE_KEY not in caplog.text, "FUGA: la API key llegó al log en crudo"
    assert gc._REDACTED in caplog.text
