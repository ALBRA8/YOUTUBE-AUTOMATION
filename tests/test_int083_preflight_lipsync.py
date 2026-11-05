#!/usr/bin/env python3
"""
INT-083 · El preflight del botón Crear avisa del lip-sync ANTES de gastar.

Hallazgo real (calibración en vivo 2026-10-31 en config.py): sin HF_TOKEN los
3 Spaces de lip-sync video-to-video (ByteDance/LatentSync —GATED—, Wav2Lip,
video-retalking) devuelven 401 y el fail-open de INT-075 continúa con el video
ORIGINAL ⇒ los proyectos con avatar salen SIN sincronización labial sin que
el creador lo sepa (solo un log.warning). Este INT lleva ese aviso al panel:

· run_preflight_creacion() añade el warn id="lipsync" cuando el lip-sync está
  habilitado pero va a saltarse (gradio_client ausente) o fallar (sin token).
· HF_TOKEN pasa a EDITABLE_KEYS + SECRET_KEYS: se guarda desde ⚙️ Ajustes
  y queda enmascarado en la API (nunca completo).
· avatar_motion.hf_token(): envoltorio público para el doctor (sin tocar la
  privada; nunca se loguea).

Filosofía INT-082 intacta: el lipsync ausente es WARN (degradación con
gracia), jamás blocker — el render sigue siendo válido sin labios.
Hermeticidad: cero red, cero HF; todo por monkeypatch determinista.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import pytest
from starlette.testclient import TestClient

import config
import main
from services import avatar_motion as am
from services import doctor as doctor_svc


def _patch_imports(monkeypatch, ok_map: dict):
    """_import_ok selectivo: lo que no esté en ok_map se considera instalado."""
    monkeypatch.setattr(doctor_svc, "_import_ok",
                        lambda m: ok_map.get(m, True))


def _base_ok(monkeypatch):
    """Entorno sano: TTS importable, ffmpeg presente, sin warns heredados."""
    _patch_imports(monkeypatch, {})
    monkeypatch.setattr(doctor_svc.shutil, "which", lambda c: "/usr/bin/" + c)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key-int083")
    monkeypatch.setattr(config, "TTS_PROVIDER", "edge")


# ═══════════════ 1 · sin HF_TOKEN + v2v activo ⇒ warn 401 (caso raíz) ════

def test_v2v_activo_sin_token_avisa_401(monkeypatch):
    _base_ok(monkeypatch)
    monkeypatch.setattr(am, "v2v_enabled", lambda: True)
    monkeypatch.setattr(am, "hf_lipsync_enabled", lambda: True)
    monkeypatch.setattr(am, "hf_token", lambda: "")
    d = doctor_svc.run_preflight_creacion()
    w = [x for x in d["warns"] if x["id"] == "lipsync"]
    assert len(w) == 1
    assert "401" in w[0]["detail"]
    assert "sincronización labial" in w[0]["detail"]
    assert "LatentSync" in w[0]["hint"]
    assert d["ok"] is True          # warn: degrada con gracia, NO bloquea
    assert d["blockers"] == []


# ═══════════════ 2 · token presente ⇒ sin warn de lipsync ════════════════

def test_token_presente_sin_warn(monkeypatch):
    _base_ok(monkeypatch)
    monkeypatch.setattr(am, "v2v_enabled", lambda: True)
    monkeypatch.setattr(am, "hf_lipsync_enabled", lambda: True)
    monkeypatch.setattr(am, "hf_token", lambda: "hf_test_token_int083")
    d = doctor_svc.run_preflight_creacion()
    assert not any(x["id"] == "lipsync" for x in d["warns"])


# ═══════════════ 3 · gradio_client ausente ⇒ warn de instalación ═════════

def test_gradio_client_ausente_avisa_instalacion(monkeypatch):
    _base_ok(monkeypatch)
    _patch_imports(monkeypatch, {"gradio_client": False})
    monkeypatch.setattr(am, "v2v_enabled", lambda: True)
    monkeypatch.setattr(am, "hf_lipsync_enabled", lambda: True)
    monkeypatch.setattr(am, "hf_token", lambda: "hf_test_token_int083")
    d = doctor_svc.run_preflight_creacion()
    w = [x for x in d["warns"] if x["id"] == "lipsync"]
    assert len(w) == 1
    assert "gradio_client" in w[0]["detail"]
    assert "fail-open" in w[0]["detail"]


# ═══════════════ 4 · lipsync desactivado ⇒ sin warn (decisión explícita) ═

def test_lipsync_desactivado_sin_warn(monkeypatch):
    _base_ok(monkeypatch)
    monkeypatch.setattr(am, "v2v_enabled", lambda: False)
    monkeypatch.setattr(am, "hf_lipsync_enabled", lambda: False)
    monkeypatch.setattr(am, "hf_token", lambda: "")
    d = doctor_svc.run_preflight_creacion()
    assert not any(x["id"] == "lipsync" for x in d["warns"])


# ═══════════════ 5 · solo avatar HF sin token ⇒ warn cuota ZeroGPU ═══════

def test_solo_avatar_hf_sin_token_avisa_cuota(monkeypatch):
    _base_ok(monkeypatch)
    monkeypatch.setattr(am, "v2v_enabled", lambda: False)
    monkeypatch.setattr(am, "hf_lipsync_enabled", lambda: True)
    monkeypatch.setattr(am, "hf_token", lambda: "")
    d = doctor_svc.run_preflight_creacion()
    w = [x for x in d["warns"] if x["id"] == "lipsync"]
    assert len(w) == 1
    assert "ZeroGPU" in w[0]["detail"]
    assert "401" not in w[0]["detail"]   # no confundir con el caso v2v


# ═══════════════ 6 · endpoint HTTP expone el warn y sigue ok ═════════════

def test_endpoint_preflight_expone_warn_lipsync(client, monkeypatch):
    _base_ok(monkeypatch)
    monkeypatch.setattr(am, "v2v_enabled", lambda: True)
    monkeypatch.setattr(am, "hf_lipsync_enabled", lambda: True)
    monkeypatch.setattr(am, "hf_token", lambda: "")
    c = TestClient(main.app)
    d = c.get("/api/doctor/preflight_creacion").json()
    assert set(d) >= {"ok", "blockers", "warns", "summary", "tts_provider"}
    assert d["ok"] is True
    assert any(x["id"] == "lipsync" for x in d["warns"])


# ═══════════════ 7 · avatar_motion roto ⇒ el preflight jamás tumba ═══════

def test_avatar_motion_exploding_no_tumba_preflight(monkeypatch):
    _base_ok(monkeypatch)
    def _boom():
        raise RuntimeError("fallo simulado del conector")
    monkeypatch.setattr(am, "v2v_enabled", _boom)
    monkeypatch.setattr(am, "hf_lipsync_enabled", lambda: True)
    monkeypatch.setattr(am, "hf_token", lambda: "")
    d = doctor_svc.run_preflight_creacion()   # no debe lanzar
    assert not any(x["id"] == "lipsync" for x in d["warns"])
    assert d["ok"] is True


# ═══════════════ 8 · HF_TOKEN configurable y enmascarado desde ⚙️ ════════

def test_hf_token_en_editable_y_secret_keys():
    assert "HF_TOKEN" in config.EDITABLE_KEYS
    assert "HF_TOKEN" in config.SECRET_KEYS


def test_hf_token_envoltorio_publico_coincide():
    assert isinstance(am.hf_token(), str)
    assert am.hf_token() == am._hf_token()


# ═══════════════ 9 · contrato de versión (INT-080 cache-busting) ═════════

def test_version_bump_2_39_0():
    assert config.APP_VERSION == "2.42.0"   # INT-087: selector de plantillas en la UI
    assert tuple(int(p) for p in config.APP_VERSION.split(".")) >= (2, 37, 0)


# ═══════════════ 10 · GET /api/config expone estado HF enmascarado ═══════

def test_get_config_hf_sin_token(client, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    c = TestClient(main.app).get("/api/config").json()
    assert c["hf_token_set"] is False
    assert c["hf_token_masked"] == ""


def test_get_config_hf_con_token_enmascarado_sin_fuga(client, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_demo_token_1234567890abcdef")
    c = TestClient(main.app).get("/api/config").json()
    assert c["hf_token_set"] is True
    m = c["hf_token_masked"]
    assert m and "…" in m
    assert "hf_demo_token_1234567890abcdef" not in m   # nunca el token completo


# ═══════════════ 11 · POST /api/config: enmascarado no pisa el token ═════

def test_post_config_hf_enmascarado_no_pisa(client, monkeypatch):
    llamadas = []
    monkeypatch.setattr(config, "save_env", lambda u: llamadas.append(dict(u)))
    monkeypatch.setattr(config, "reload", lambda: None)
    r = TestClient(main.app).post("/api/config",
                                  json={"HF_TOKEN": "hf_abcd…wxyz"})
    assert r.status_code == 400            # "nada que guardar"
    assert llamadas == []                  # save_env jamás invocado


def test_post_config_hf_token_nuevo_se_guarda(client, monkeypatch):
    llamadas = []
    monkeypatch.setattr(config, "save_env", lambda u: llamadas.append(dict(u)))
    monkeypatch.setattr(config, "reload", lambda: None)
    r = TestClient(main.app).post("/api/config",
                                  json={"HF_TOKEN": "hf_token_nuevo_int083"})
    assert r.status_code == 200
    assert llamadas and llamadas[0]["HF_TOKEN"] == "hf_token_nuevo_int083"
    assert "hf_token_nuevo_int083" not in r.text   # el valor no se eco-complete


@pytest.fixture
def client():
    return TestClient(main.app)
