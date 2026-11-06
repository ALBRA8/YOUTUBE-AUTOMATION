# -*- coding: utf-8 -*-
"""P0-2d — regresión SSRF de los endpoints hermanos.

Los tres puntos de entrada de URL externa del backend que no pasaban por
la guardia central hoy SÍ la usan; aquí se demuestra con URLs venenosas:

  · scrape_product_info (services/ugc_ad_generator.py) — funel ÚNICO de
    /api/product/scrape (main.py ~2976) y de la creación de proyecto en
    modo producto (main.py ~1211).
  · product_studio_preview (/api/product/studio-preview, main.py ~3246).
  · fetch_stock_video_pexels (services/broll_overlay.py) — el link de
    descarga viene del JSON de Pexels; debe validarse igual.

Cobertura de redirect-revalidado: tests/security/test_ssrf.py (batería
propia de security, _SafeRedirectHandler). Aquí se comprueba que NINGÚN
endpoint hermano toca red para URLs prohibidas.

Ejecutar: python3 -m pytest tests/test_p0_2_ssrf_siblings.py -q
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest

import security
from services import ugc_ad_generator


MALAS = [
    "file:///etc/passwd",
    "http://127.0.0.1:8000/api/config",
    "http://169.254.169.254/latest/meta-data/",
    "http://192.168.1.1/admin",
    "http://[::1]:8000/",
    "http://10.0.0.5/interno",
]


def test_validar_url_rechaza_todas_las_malas():
    for bad in MALAS:
        with pytest.raises(ValueError):
            security.validar_url(bad)


def test_scrape_producto_no_toca_red_con_url_mala(monkeypatch):
    """scrape_product_info degrada con el fallback del slug y NUNCA abre red."""
    def _prohibido(*a, **k):  # si safe_fetch_bytes intentara descargar...
        raise AssertionError("safe_fetch_bytes intentó abrir red con URL mala")
    monkeypatch.setattr(security, "_OPENER", type("X", (), {"open": _prohibido})())
    for bad in [m for m in MALAS if m.startswith("http")]:
        info = ugc_ad_generator.scrape_product_info(bad)
        assert info["is_url"] is True and info["image_url"] is None
        assert info["name"], "fallback del slug esperado"


def test_scrape_producto_rechaza_file_y_texto_estructurado():
    # file:// no es http(s): scrape lo trata como texto estructurado (is_url False)
    info = ugc_ad_generator.scrape_product_info("file:///etc/passwd")
    assert info["is_url"] is False


@pytest.mark.asyncio
async def test_studio_preview_rechaza_urls_malas():
    """El endpoint studio responde 400 con URL prohibida, sin descargar."""
    import main
    from fastapi import HTTPException
    for bad in MALAS:
        with pytest.raises(HTTPException) as e:
            await main.product_studio_preview({"image_url": bad})
        assert e.value.status_code == 400, bad


@pytest.mark.asyncio
async def test_broll_valida_link_pexels_antes_de_descargar(tmp_path, monkeypatch):
    """Un 'best_link' interno dentro del JSON de Pexels NO se descarga."""
    import httpx
    from services import broll_overlay

    class _Resp:
        def __init__(self, payload=None, content=b""):
            self._payload = payload
            self.status_code = 200
            self.content = content
        def json(self):
            return self._payload

    enlace_malo = "http://169.254.169.254/latest/meta-data/clip.mp4"

    class _Client:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False
        async def get(self, url, **k):
            if "api.pexels.com" in url:
                return _Resp(payload={"videos": [{"video_files": [
                    {"link": enlace_malo, "width": 1080, "height": 1920}]}]})
            raise AssertionError(f"descarga SIN validar: {url}")

    monkeypatch.setattr(broll_overlay.httpx, "AsyncClient", _Client)
    destino = tmp_path / "broll.mp4"
    ok = await broll_overlay.fetch_stock_video_pexels(
        "naturaleza", destino, orientation="portrait")
    assert ok is False, "el enlace interno no debió descargarse"
    assert not destino.exists()


@pytest.mark.asyncio
async def test_broll_link_publico_sigue_funcionando(tmp_path, monkeypatch):
    """Camino feliz: link público válido se descarga (regresión de la guardia)."""
    from services import broll_overlay

    class _Resp:
        def __init__(self, payload=None, content=b""):
            self._payload = payload
            self.status_code = 200
            self.content = content
        def json(self):
            return self._payload

    enlace_ok = "https://videos.pexels.com/video-files/123/clip.mp4"

    class _Client:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False
        async def get(self, url, **k):
            if "api.pexels.com" in url:
                return _Resp(payload={"videos": [{"video_files": [
                    {"link": enlace_ok, "width": 1080, "height": 1920}]}]})
            assert url == enlace_ok
            return _Resp(content=b"x" * 20000)

    # sin API key en entorno → fetch retorna False antes de la red;
    # forzamos la clave vía monkeypatch de os.getenv dentro del módulo.
    monkeypatch.setattr(broll_overlay, "PEXELS_API_KEY", "clave-test")
    monkeypatch.setattr(broll_overlay.httpx, "AsyncClient", _Client)
    destino = tmp_path / "broll_ok.mp4"
    ok = await broll_overlay.fetch_stock_video_pexels(
        "naturaleza", destino, orientation="portrait")
    assert ok is True and destino.exists()


def test_opener_de_security_revalida_redirects():
    """La guardia central usa _SafeRedirectHandler (redirects revalidados)."""
    handler = security._SafeRedirectHandler()
    req = security._urq.Request("http://ejemplo-publico.invalid/a")
    with pytest.raises(ValueError):
        # un redirect hacia 169.254.169.254 debe ser rechazado por la guardia
        handler.redirect_request(
            req, None, 302, "Found",
            {"Location": "http://169.254.169.254/latest/meta-data/"},
            "http://169.254.169.254/latest/meta-data/")
