#!/usr/bin/env python3
"""
INT-084 · Mejora 6 del informe en vivo: normalización de la API con alias
ES/EN retrocompatibles (niche ≡ nicho, mensaje ≡ message).

Hallazgo verificado antes de tocar (metodología del repo: código real, no
memoria): los adaptadores pesados ya normalizaban — guion_json.py::66 y
production_json.py::85 tienen «"nicho": ("nicho", "niche", "carpeta")» en sus
_ALIAS_ — pero:

  1. Los modos simples (idea/script/url/audio/product) IGNORABAN en silencio
     el campo `nicho`/`niche` del body: db.create_project recibía
     niche=niche_label, que solo se llenaba desde plantilla de nicho o perfil
     de marca → «campos ignorados» para integraciones externas.
  2. /api/chat solo leía `message`: un integrador ES que enviara `mensaje`
     recibía 400 «mensaje vacío».
  3. El mode canónico es «nicho»: mode «niche» devolvía 400 «modo inválido».

Contrato documentado en el docstring de create_project (main.py):
  · Precedencia del nicho: plantilla → perfil de marca → campo del body.
  · La clave canónica SIEMPRE gana si llegan ambas («nicho» sobre «niche»,
    «message» sobre «mensaje»).
  · Retrocompatible al 100%: nada de lo que funcionaba cambia.

Hermeticidad: la SQLite es la de sesión (conftest); /api/chat responde con el
motor regex local (sin NVIDIA/Gemini, probado en vivo en INT-028).
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import pytest
from starlette.testclient import TestClient

import config
import main


@pytest.fixture
def client():
    return TestClient(main.app)


# ═══════════════ 1 · el campo niche/nicho ya no se ignora en los modos ═══

def test_modo_idea_acepta_niche(client):
    r = client.post("/api/projects", json={
        "mode": "idea", "idea": "misterios del océano", "niche": "Misterio"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["niche"] == "Misterio"


def test_modo_idea_acepta_nicho_canonico(client):
    r = client.post("/api/projects", json={
        "mode": "idea", "idea": "curiosidades romanas", "nicho": "Historia"})
    assert r.status_code == 200, r.text
    assert r.json()["niche"] == "Historia"


def test_modo_script_acepta_niche(client):
    r = client.post("/api/projects", json={
        "mode": "script", "script": "GUION: escena uno\nescena dos",
        "niche": "Primitive Viral"})
    assert r.status_code == 200, r.text
    assert r.json()["niche"] == "Primitive Viral"


def test_canonica_nicho_gana_sobre_niche(client):
    r = client.post("/api/projects", json={
        "mode": "idea", "idea": "x", "nicho": "Canónica", "niche": "Alias"})
    assert r.status_code == 200, r.text
    assert r.json()["niche"] == "Canónica"


def test_nicho_recortado_a_60_como_contrato_guion(client):
    r = client.post("/api/projects", json={
        "mode": "idea", "idea": "x", "niche": "N" * 200})
    assert r.status_code == 200, r.text
    assert len(r.json()["niche"]) == 60


def test_sin_nicho_sigue_vaciendo_como_antes(client):
    """Retrocompatibilidad: sin campo, niche queda falsy como siempre
    (NULL/«» — la UI lo muestra como «sin nicho» vía `or ''`)."""
    r = client.post("/api/projects", json={"mode": "idea", "idea": "x"})
    assert r.status_code == 200, r.text
    assert not r.json()["niche"]


# ═══════════════ 2 · alias del MODE: «niche» ≡ «nicho» ═══════════════════

def test_modo_alias_niche_pasa_validacion(client):
    """Con mode «niche» el rechazo jamás puede ser «modo inválido»."""
    r = client.post("/api/projects", json={"mode": "niche", "idea": "x"})
    assert r.status_code == 400
    assert "modo inválido" not in r.json()["detail"]


def test_modo_alias_niche_crea_proyecto_nicho(client):
    tpl = _primer_template(client)
    if not tpl:
        pytest.skip("catálogo de nichos vacío en la sesión de tests")
    r = client.post("/api/projects", json={
        "mode": "niche", "niche_template": tpl["id"]})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["mode"] == "nicho"
    assert p["niche"] == tpl.get("name")


def test_plantilla_gana_sobre_campo_body(client):
    """Precedencia honesta documentada: plantilla → perfil → campo body."""
    tpl = _primer_template(client)
    if not tpl:
        pytest.skip("catálogo de nichos vacío en la sesión de tests")
    r = client.post("/api/projects", json={
        "mode": "nicho", "niche_template": tpl["id"],
        "niche": "el body NO pisa a la plantilla"})
    assert r.status_code == 200, r.text
    assert r.json()["niche"] == tpl.get("name")


def _primer_template(client) -> dict | None:
    try:
        tpls = client.get("/api/niches").json()
    except Exception:
        return None
    if isinstance(tpls, list) and tpls:
        return tpls[0]
    if isinstance(tpls, dict) and tpls.get("templates"):
        return tpls["templates"][0]
    return None


# ═══════════════ 3 · /api/chat: mensaje ≡ message ════════════════════════

def test_chat_acepta_mensaje_es(client):
    r = client.post("/api/chat", json={"mensaje": "crea un video de prueba"})
    assert r.status_code == 200, r.text          # antes: 400 «mensaje vacío»
    assert "reply" in r.json()


def test_chat_canonica_message_sigue_funcionando(client):
    r = client.post("/api/chat", json={"message": "estado de la fábrica"})
    assert r.status_code == 200, r.text
    assert "reply" in r.json()


def test_chat_canonica_gana_sobre_alias(client):
    """Si llegan ambas, «message» (canónica) es la procesada — no el alias."""
    r = client.post("/api/chat", json={
        "message": "estado de la fábrica",
        "mensaje": "crea un video del imperio romano"})
    assert r.status_code == 200, r.text
    # el reply ejecuta la canónica (consulta de estado), no la destructiva
    assert r.json().get("action") != "create_video"


def test_chat_vacio_sigue_400(client):
    r = client.post("/api/chat", json={})
    assert r.status_code == 400
    assert "mensaje vacío" in r.json()["detail"]


# ═══════════════ 4 · contrato de versión (INT-080) ══════════════════════

def test_version_2_39_0():
    assert config.APP_VERSION == "2.44.0"   # INT-089: telemetría HF por llamada
