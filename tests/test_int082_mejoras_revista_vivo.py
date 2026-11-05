#!/usr/bin/env python3
"""
INT-082 · Mejoras 3/4/7 del informe de revisión en vivo (2026-11-03).
Cada test congela UNA mejora verificada contra el servidor real :8000.

· Mejora 3 (P1): preflight ligero del botón Crear — endpoint
  /api/doctor/preflight_creacion + gate en el panel: si falta la voz (TTS)
  o ffmpeg, avisa ANTES de gastar guion e imágenes de un proyecto que
  moriría a mitad del pipeline (caso real: «El imperio romano», 7 escenas
  mudas descubiertas tarde).
· Mejora 4 (P2): cache-busting unificado — las TRES versiones de assets de
  index.html (style.css, auth.js, app.js) salen del token __APP_VERSION__
  sustituido en servidor por la única constante config.APP_VERSION (INT-080).
  Antes: 3 versiones a mano en 3 sitios (2.25.0 / 2.5.0 / 2.36.0).
· Mejora 7 (P2): cabeceras de seguridad HTTP (nosniff universal, X-Frame-
  Options DENY, CSP básica, Referrer-Policy) + soporte HEAD en / (antes
  405 Method Not Allowed: los monitores veían la fábrica «caída»).
"""
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import pytest
from starlette.testclient import TestClient

import config
import main
from services import doctor as doctor_svc


@pytest.fixture
def client():
    return TestClient(main.app)


def _todo_disponible(monkeypatch):
    """Entorno ideal: TTS importable, ffmpeg/ffprobe presentes, clave Gemini."""
    monkeypatch.setattr(doctor_svc, "_import_ok", lambda m: True)
    monkeypatch.setattr(doctor_svc.shutil, "which", lambda c: "/usr/bin/" + c)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key-int082")


# ═════════════════════ Mejora 3 · preflight ligero del botón Crear ════════

def test_preflight_todo_ok_sin_blockers(client, monkeypatch):
    _todo_disponible(monkeypatch)
    monkeypatch.setattr(config, "TTS_PROVIDER", "edge")
    d = client.get("/api/doctor/preflight_creacion").json()
    assert set(d) >= {"ok", "blockers", "warns", "summary", "tts_provider"}
    assert d["ok"] is True
    assert d["blockers"] == []
    assert d["tts_provider"] == "edge"


def test_preflight_edge_sin_instalar_es_blocker(client, monkeypatch):
    """El caso raíz del informe: sin voz el proyecto muere en el paso locución."""
    _todo_disponible(monkeypatch)
    monkeypatch.setattr(config, "TTS_PROVIDER", "edge")

    def _sin_edge(m):
        return m != "edge_tts"
    monkeypatch.setattr(doctor_svc, "_import_ok", _sin_edge)

    d = client.get("/api/doctor/preflight_creacion").json()
    assert d["ok"] is False
    ids = [b["id"] for b in d["blockers"]]
    assert "tts" in ids
    b_tts = next(b for b in d["blockers"] if b["id"] == "tts")
    assert "edge-tts" in b_tts["detail"] and "pip install" in b_tts["hint"]


def test_preflight_gemini_sin_clave_es_blocker(client, monkeypatch):
    _todo_disponible(monkeypatch)
    monkeypatch.setattr(config, "TTS_PROVIDER", "gemini")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")

    d = client.get("/api/doctor/preflight_creacion").json()
    assert d["ok"] is False
    assert any(b["id"] == "tts" and "GEMINI_API_KEY" in b["detail"]
               for b in d["blockers"])


def test_preflight_gemini_sin_google_genai_es_blocker(client, monkeypatch):
    _todo_disponible(monkeypatch)
    monkeypatch.setattr(config, "TTS_PROVIDER", "gemini")

    def _sin_genai(m):
        return m != "google.genai"
    monkeypatch.setattr(doctor_svc, "_import_ok", _sin_genai)

    d = client.get("/api/doctor/preflight_creacion").json()
    assert d["ok"] is False
    assert any(b["id"] == "tts" for b in d["blockers"])


def test_preflight_ffmpeg_ausente_es_blocker(client, monkeypatch):
    _todo_disponible(monkeypatch)
    monkeypatch.setattr(config, "TTS_PROVIDER", "edge")
    monkeypatch.setattr(doctor_svc.shutil, "which", lambda c: None)

    d = client.get("/api/doctor/preflight_creacion").json()
    ids = {b["id"] for b in d["blockers"]}
    assert {"ffmpeg", "ffprobe"} <= ids


def test_preflight_sin_gemini_con_pil_es_solo_warn(client, monkeypatch):
    """Filosofía $0: placeholders (PIL) degradan con gracia → warn, no blocker."""
    _todo_disponible(monkeypatch)
    monkeypatch.setattr(config, "TTS_PROVIDER", "edge")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")

    d = client.get("/api/doctor/preflight_creacion").json()
    assert d["ok"] is True                       # degradación elegante ≠ fallo
    assert d["blockers"] == []
    assert any(w["id"] == "imagen" for w in d["warns"])


# ═════════════════════ Mejora 4 · cache-busting unificado ═════════════════

def test_root_sirve_las_tres_tags_con_la_version_unica(client):
    html = client.get("/").text
    assert "__APP_VERSION__" not in html          # token sustituido en servidor
    vers = re.findall(r'static/(?:style\.css|auth\.js|app\.js)\?v=([^"]+)"', html)
    assert len(vers) == 3                          # style.css + auth.js + app.js
    assert set(vers) == {config.APP_VERSION}       # UNA sola constante para todo


def test_index_html_declara_solo_el_token():
    """La fuente (index.html) ya no lleva versiones a mano: 3 tags con token."""
    html = (BACKEND / "static" / "index.html").read_text(encoding="utf-8")
    assert len(re.findall(r'\?v=__APP_VERSION__', html)) == 3
    for vieja in ("v=2.25.0", "v=2.5.0", "v=2.36.0"):
        assert vieja not in html


# ═════════════════════ Mejora 7 · cabeceras de seguridad + HEAD ═══════════

def test_cabeceras_seguridad_en_el_html_del_panel(client):
    res = client.get("/")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    csp = res.headers["content-security-policy"]
    for frag in ("default-src 'self'", "frame-ancestors 'none'",
                 "script-src 'self' 'unsafe-inline'",
                 "https://fonts.googleapis.com", "https://fonts.gstatic.com",
                 "connect-src 'self'", "base-uri 'self'"):
        assert frag in csp, f"CSP sin {frag!r}"


def test_nosniff_en_respuestas_json_incluso_404(client):
    """El middleware es el más externo: estampa nosniff también en 404/401/403."""
    res = client.get("/api/ruta-inexistente-int082")
    assert res.status_code == 404
    assert res.headers["x-content-type-options"] == "nosniff"


def test_docs_sin_csp_swagger_sigue_funcionando(client):
    """/docs queda fuera de la CSP: el Swagger UI de FastAPI carga scripts CDN."""
    res = client.get("/docs")
    assert res.status_code == 200
    assert "content-security-policy" not in res.headers
    assert res.headers["x-content-type-options"] == "nosniff"


def test_head_en_raiz_aceptado_y_sin_cuerpo(client):
    """Antes: HEAD / → 405 Method Not Allowed (monitores veían la fábrica caída)."""
    res = client.head("/")
    assert res.status_code == 200
    assert res.content == b""
    assert int(res.headers["content-length"]) > 1000   # longitud real del HTML


def test_get_en_raiz_sigue_sirviendo_html_completo(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "<!DOCTYPE html>" in res.text
    assert "static/app.js?v=" in res.text


# ═════════════════════ Contrato frontend (panel) ══════════════════════════

def test_contrato_appjs_gate_antes_de_gastar():
    """El gate se ejecuta en createProject y startJob ANTES de la llamada que
    crea el proyecto / lanza el pipeline. (INT-088: el código vive ahora en
    app-projects.js; se lee la concatenación de todo el frontend.)"""
    appjs = "\n".join(
        (BACKEND / "static" / f).read_text(encoding="utf-8")
        for f in ("app.js", "app-core.js", "app-projects.js", "app-mcp.js",
                  "app-wizard.js", "app-player.js"))
    assert "/doctor/preflight_creacion" in appjs
    assert appjs.count("if (!(await preflightGate())) return;") == 2

    i_create = appjs.index("async function createProject()")
    assert appjs.index("preflightGate()", i_create) < \
        appjs.index("await api('/projects'", i_create)

    i_start = appjs.index("async function startJob(")
    assert appjs.index("preflightGate()", i_start) < \
        appjs.index("`/projects/${pid}/generate`", i_start)


def test_contrato_appjs_banner_y_cache():
    appjs = "\n".join(
        (BACKEND / "static" / f).read_text(encoding="utf-8")
        for f in ("app.js", "app-core.js", "app-projects.js", "app-mcp.js",
                  "app-wizard.js", "app-player.js"))
    assert "function renderPreflightBanner()" in appjs
    # el banner solo se pide en el paso final del asistente (botón 🚀)
    assert "renderPreflightBanner();" in appjs
    assert "(W.step === 4 || (W.mode === 'nicho' && W.step === 2))" in appjs
    # caché de 60 s para no sondear en cada clic + fail-open
    assert "60000" in appjs
    assert "catch { return null; }" in appjs


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
