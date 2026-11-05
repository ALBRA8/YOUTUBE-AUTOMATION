#!/usr/bin/env python3
"""
INT-080 · Arreglos de la auditoría de 5 ángulos (frontend/API/pipeline/seguridad/
integridad). Cada test congela UN hallazgo verificado con evidencia archivo:línea.

Cobertura: renders dual-mode + whitelist, contención M5 de video_url, puerta
legítima del modo audio (antes PATCH→403), casts 400-no-500, SSRF studio-preview,
whitelist border_color, fuente única de versión, FPS robusto, _PROJECT_COLS,
helper is_broll + tolerancia del CTA, contratos frontend y conftest c1.
"""
import sys
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import pytest
from starlette.testclient import TestClient

import config
import database as db
import main
from pipeline import video as pipeline_video

PID = "a1b2c3d4e5f6"
FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42FAKE_VIDEO_PAYLOAD_INT080"


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_int080.db")
    db.init_db()
    yield


@pytest.fixture
def client():
    return TestClient(main.app)


# ── B1 · /api/renders/{file_name}: inline por defecto + ?download=1 + .mp4 ──
def test_renders_dual_mode_and_whitelist(client, tmp_path, monkeypatch):
    renders = tmp_path / "renders"
    renders.mkdir()
    mp4 = renders / "clip_01.mp4"
    mp4.write_bytes(FAKE_MP4)
    (renders / "notas.txt").write_text("no es video")
    monkeypatch.setattr(main.viral_clipper, "RENDERS_DIR", renders)

    res = client.get("/api/renders/clip_01.mp4")
    assert res.status_code == 200
    assert res.headers["content-disposition"].startswith("inline")  # antes: attachment forzado
    assert res.content == FAKE_MP4

    res_dl = client.get("/api/renders/clip_01.mp4?download=1")
    assert res_dl.headers["content-disposition"].startswith("attachment")

    res_txt = client.get("/api/renders/notas.txt")
    assert res_txt.status_code == 404  # whitelist de extensión

    res_missing = client.get("/api/renders/fantasma.mp4")
    assert res_missing.status_code == 404


# ── D1-CRITICAL · GET /video: contención M5 de video_url ────────────────────
def test_video_endpoint_containment(client, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "OUTPUT_DIR", tmp_path)
    fuera = tmp_path.parent / "fuera_del_repo.mp4"
    fuera.write_bytes(FAKE_MP4)

    # ruta FUERA de toda raíz segura → 404 (antes: FileResponse servía .env)
    with patch("main.db.get_project", return_value={"id": PID, "title": "t",
                                                    "video_url": str(fuera)}):
        assert client.get(f"/api/projects/{PID}/video").status_code == 404

    # bajo OUTPUT_DIR parcheado → 200 inline
    dentro = tmp_path / "final.mp4"
    dentro.write_bytes(FAKE_MP4)
    with patch("main.db.get_project", return_value={"id": PID, "title": "t",
                                                    "video_url": str(dentro)}):
        res = client.get(f"/api/projects/{PID}/video")
        assert res.status_code == 200
        assert res.headers["content-disposition"].startswith("inline")


# ── D1/B3 · clipper create-project valida el ORIGEN de video_url ───────────
def test_clipper_create_project_validates_video_url(client, monkeypatch):
    malas = ["/etc/passwd", "C:/Users/x/.env", str(BACKEND / ".env")]
    for vurl in malas:
        res = client.post("/api/clipper/create-project",
                          json={"title": "t", "video_url": vurl})
        assert res.status_code == 400, f"{vurl} debía ser rechazado"

    # URL relativa del propio backend (lo que envía la UI real) → OK
    res = client.post("/api/clipper/create-project",
                      json={"title": "Clip ok", "video_url": "/api/renders/short_123.mp4"})
    assert res.status_code == 200
    assert res.json()["project"]["video_url"] == "/api/renders/short_123.mp4"


# ── A1-CRITICAL · modo audio: puerta legítima (audio_path en el POST) ───────
def test_audio_mode_legitimate_door(client, tmp_path, monkeypatch):
    # archivo upload válido (TMP_DIR + prefijo voice_upload_ + extensión de audio)
    monkeypatch.setattr(main, "TMP_DIR", tmp_path)
    up = tmp_path / "voice_upload_ab12cd34_voz.mp3"
    up.write_bytes(b"ID3fake")

    res = client.post("/api/projects", json={"mode": "audio", "audio_path": str(up)})
    assert res.status_code == 200
    proj = db.get_project(res.json()["id"])
    assert proj["meta"].get("audio_path") == str(up)

    # ruta fuera de raíces → 400
    res_bad = client.post("/api/projects", json={
        "mode": "audio", "audio_path": str(BACKEND / ".env")})
    assert res_bad.status_code == 400

    # M6 intacto: meta_patch.audio_path sigue PROHIBIDO (403)
    res_patch = client.patch(f"/api/projects/{proj['id']}",
                             json={"meta_patch": {"audio_path": str(up)}})
    assert res_patch.status_code == 403


# ── B6 · casts de input → 400 (no 500) ──────────────────────────────────────
def test_casts_return_400_not_500(client):
    res = client.post("/api/clipper/analyze",
                      json={"url": "https://www.youtube.com/watch?v=abc",
                            "count": "abc"})
    assert res.status_code == 400
    assert "entero" in res.json()["detail"]


# ── B4/D · studio-preview: SSRF cerrado (file:// e IP privadas → 400) ──────
def test_studio_preview_ssrf_blocked(client):
    for evil in ("file:///etc/passwd", "http://127.0.0.1:8000/api/config",
                 "http://169.254.169.254/latest/meta-data"):
        res = client.post("/api/product/studio-preview", json={"image_url": evil})
        assert res.status_code == 400, f"{evil} debía ser rechazado"


# ── B5 · circle-pip: border_color whitelisteado (path traversal de escritura)
def test_circle_pip_border_color_whitelist(client, tmp_path, monkeypatch):
    retrato = tmp_path / "retrato.png"
    retrato.write_bytes(b"\x89PNG fake")
    monkeypatch.setattr(main.db, "get_avatar",
                        lambda aid: {"id": aid, "image_path": str(retrato)})
    monkeypatch.setattr("services.avatar_pip.create_circle_avatar",
                        lambda *a, **k: None)  # INT-080: no procesamos imagen real
    res = client.post(f"/api/avatars/{PID}/circle-pip",
                      json={"border_color": "../../../evil"})
    assert res.status_code == 400
    res_ok = client.post(f"/api/avatars/{PID}/circle-pip", json={"border_color": "cyan"})
    assert res_ok.status_code == 200


# ── E4 · versión: única fuente de verdad ────────────────────────────────────
def test_app_version_single_source(client):
    assert config.APP_VERSION == "2.45.0"   # INT-092: limpieza de UI + tema coherente
    assert main.app.version == config.APP_VERSION
    res = client.get("/api/health")
    assert res.json()["version"] == config.APP_VERSION
    src = (BACKEND / "main.py").read_text(encoding="utf-8")
    assert '"version": "2.20.0"' not in src  # no queda hardcode residual


# ── C8 · FPS robusto ────────────────────────────────────────────────────────
def test_fps_never_crashes_boot(monkeypatch):
    monkeypatch.setenv("FPS", "29.97")
    import importlib
    cfg = importlib.reload(config)
    assert isinstance(cfg.FPS, int) and cfg.FPS > 0
    monkeypatch.setenv("FPS", "30")
    importlib.reload(config)
    assert config.FPS == 30


# ── E5 · _PROJECT_COLS conoce brand_profile_id ──────────────────────────────
def test_project_cols_include_brand_profile_id():
    assert "brand_profile_id" in db._PROJECT_COLS


# ── C2 · helper is_broll + skip de Flow en b-roll ──────────────────────────
def test_is_broll_helper_and_orchestrator_skip():
    assert pipeline_video.is_broll({"type": "product_broll"}) is True
    assert pipeline_video.is_broll({"type": "Broll"}) is True        # case-insensitive
    assert pipeline_video.is_broll({"meta": {"type": "product"}}) is True
    assert pipeline_video.is_broll({"type": "avatar"}) is False
    assert pipeline_video.is_broll({}) is False                      # legacy
    orch_src = (BACKEND / "pipeline" / "orchestrator.py").read_text(encoding="utf-8")
    assert "video.is_broll(sc)" in orch_src  # el PASO 3.5 lo consume


# ── C3 · tolerancia estricta del CTA (contrato fuente) ─────────────────────
def test_final_scene_strict_tolerance_contract():
    src = (BACKEND / "pipeline" / "video.py").read_text(encoding="utf-8")
    assert "tol = 0.05 if not not_final else CLIP_TOL" in src
    assert "return_exceptions=True" in src  # C7: renders sin huérfanos


# ── A2/F1 · frontend: sin doble prefijo ni meta_patch de audio_path ────────
# INT-088: el frontend vive en app.js (loader) + 5 módulos app-*.js; los
# contratos se verifican sobre la concatenación de los 6 ficheros.
def test_frontend_contracts():
    src = "\n".join(
        (BACKEND / "static" / f).read_text(encoding="utf-8")
        for f in ("app.js", "app-core.js", "app-projects.js", "app-mcp.js",
                  "app-wizard.js", "app-player.js"))
    assert "api('/api/" not in src                    # los 5 dobles prefijos muertos
    assert "meta_patch: { audio_path" not in src      # los 2 PATCH 403 eliminados
    assert "auto_emojis: autoEmojis" in src           # toggles del clipper viajan
    assert "kMap" in src                              # toast normaliza error/success
    assert "document.removeEventListener('keydown', qcEscClose)" in src


# ── D2 · vector ?api_key= eliminado del auth_guard ─────────────────────────
def test_query_api_key_vector_removed():
    src = (BACKEND / "main.py").read_text(encoding="utf-8")
    assert 'query_params.get("api_key"' not in src


# ── E1 · conftest excluye la batería LIVE c1 ───────────────────────────────
def test_conftest_excludes_live_c1():
    src = (BACKEND.parent / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert '"test_live_execution_c1.py"' in src


# ── E3 · numpy declarado ───────────────────────────────────────────────────
def test_numpy_declared():
    req = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
    assert "numpy" in req


if __name__ == "__main__":
    test_renders_dual_mode_and_whitelist(
        TestClient(main.app), Path(__import__("tempfile").mkdtemp()),
        __import__("unittest").mock.MagicMock())
    print("(usa pytest para la batería completa)")
