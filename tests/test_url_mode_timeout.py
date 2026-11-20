"""
AUDITORÍA MULTI-FUENTE 2026-11 — TimeoutExpired → UrlModeError (regresión).

Antes, un yt-dlp colgado escapaba de url_mode._run() como
subprocess.TimeoutExpired CRUDO: ningún llamador lo presentaba al usuario y
el endpoint de modo URL respondía 500 sin contexto. Ahora _run() lo traduce
a UrlModeError (el tipo que todos los llamadores ya saben mostrar). Todo
hermético: el "yt-dlp colgado" es un proceso python real en un sandbox.
"""
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from services import url_mode  # noqa: E402


def test_run_traduce_timeout_a_urlmodeerror():
    colgado = [sys.executable, "-c", "import time; time.sleep(2)"]
    with pytest.raises(url_mode.UrlModeError) as ei:
        url_mode._run(colgado, timeout=0.3)
    msg = str(ei.value)
    assert "excedió" in msg and "0.3" in msg
    # ya NO es un TimeoutExpired crudo (ni su subclase)
    assert not isinstance(ei.value, subprocess.TimeoutExpired)


def test_run_cadena_la_causa_original():
    colgado = [sys.executable, "-c", "import time; time.sleep(2)"]
    with pytest.raises(url_mode.UrlModeError) as ei:
        url_mode._run(colgado, timeout=0.3)
    assert isinstance(ei.value.__cause__, subprocess.TimeoutExpired)


def test_run_normal_sigue_devolviendo_completedprocess():
    rapido = [sys.executable, "-c", "print('hola')"]
    out = url_mode._run(rapido, timeout=10)
    assert out.returncode == 0 and out.stdout.strip() == "hola"


def test_run_fallo_normal_no_se_toca():
    """Un returncode != 0 sigue volviendo como CompletedProcess: la
    traducción a UrlModeError la hacen los llamadores con stderr."""
    falla = [sys.executable, "-c", "import sys; sys.exit(3)"]
    out = url_mode._run(falla, timeout=10)
    assert out.returncode == 3


def test_fetch_metadata_envuelve_timeout(monkeypatch):
    """Contrato de extremo a extremo del modo URL: un yt-dlp colgado acaba
    en UrlModeError (jamás TimeoutExpired crudo) al llamar fetch_metadata.
    El timeout real de fetch_metadata es 60 s: se SIMULA el cuelgue
    interceptando subprocess.run para mantener el test hermético y rápido."""
    import asyncio
    from services import url_mode as um

    real_run = subprocess.run

    def fake_run(cmd, **kw):
        if kw.get("timeout") == 60:  # exactamente el timeout de fetch_metadata
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        return real_run(cmd, **kw)

    monkeypatch.setattr(um.subprocess, "run", fake_run)
    monkeypatch.setattr(um, "_guard_ssrf", lambda url: url)  # sin red real
    with pytest.raises(url_mode.UrlModeError):
        asyncio.run(um.fetch_metadata("https://example.com/v?id=x", None))
