"""INT-091 · Selector NATIVO de carpetas de Windows — libre elección de destino.

Cubre:
  A. POST /api/dialog/pick-folder: diálogo nativo mockeado (headless) —
     carpeta elegida, cancelado y SO sin GUI.
  B. POST /api/projects acepta custom_workspace_path (validación: relativa
     → 400, «Copy as path» con comillas → normalizada).
  C. Respeto ABSOLUTO de la ruta en project_workspace: workspace_path,
     resolve_workspace y create_workspace nacen EXACTAMENTE en la carpeta
     del usuario (no en data/projects/).
  D. workspace_info con flag «custom» + GET /api/projects/{pid}.
  E. open-folder apunta a la carpeta física del usuario.
  F. purge_workspace NUNCA borra la carpeta del usuario.
  G. Degradación honesta: meta vacía/ruta relativa → data/projects/ estándar.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
import database as db  # noqa: E402
import main  # noqa: E402
from pipeline import project_workspace as pws  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

OK, FAIL = 0, 0


def check(nombre: str, cond: bool, extra: str = ""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))
    if not ok:
        raise AssertionError(nombre + (f" — {extra}" if extra else ""))


@pytest.fixture
def client():
    return TestClient(main.app)


# ── A · endpoint del diálogo nativo (mockeado headless) ──────────────────
def test_dialogo_pick_folder_aceptado(client, tmp_path, monkeypatch):
    destino = tmp_path / "FRUTINOVELAS" / "Mi_Video"
    monkeypatch.setattr(main, "_pick_folder_dialog",
                        lambda: (True, str(destino)))
    r = client.post("/api/dialog/pick-folder")
    check("pick-folder → 200", r.status_code == 200, r.text[:200])
    check("ok true + path exacto", r.json().get("ok") is True
          and r.json().get("path") == str(destino), r.text[:200])


def test_dialogo_pick_folder_cancelado(client, monkeypatch):
    monkeypatch.setattr(main, "_pick_folder_dialog", lambda: (False, ""))
    r = client.post("/api/dialog/pick-folder")
    check("cancelado → ok false + cancelled true",
          r.json().get("ok") is False and r.json().get("cancelled") is True,
          r.text[:200])


def test_dialogo_pick_folder_sin_gui_honesto(client, monkeypatch):
    """Sin mock: en un servidor headless el diálogo real no está disponible
    y el endpoint responde honesto (ok false, cancelled true) SIN lanzar."""
    r = client.post("/api/dialog/pick-folder")
    check("sin GUI → honesto sin lanzar", r.status_code == 200
          and r.json().get("ok") is False and r.json().get("cancelled") is True,
          r.text[:200])


# ── B · validación de custom_workspace_path en POST /api/projects ────────
def test_custom_path_validacion(client):
    r = client.post("/api/projects", json={
        "mode": "idea", "idea": "x", "custom_workspace_path": "ruta/relativa"})
    check("ruta relativa → 400", r.status_code == 400, r.text[:200])
    check("mensaje claro al usuario", "ABSOLUTA" in r.text, r.text[:200])


def test_custom_path_copy_as_path_normalizado(client, tmp_path):
    """«Copy as path» de Windows llega con comillas perimetrales: el
    endpoint las recorta antes de persistir (custom_root ya es tolerante)."""
    destino = tmp_path / "Con Comillas"
    p = client.post("/api/projects", json={
        "mode": "idea", "idea": "comillas",
        "custom_workspace_path": f'"{destino}"'}).json()
    check("comillas recortadas en meta",
          p["meta"].get("custom_workspace_path") == str(destino),
          str(p.get("meta"))[:200])


# ── C · respeto absoluto de la ruta en el pipeline ───────────────────────
def test_proyecto_nace_en_carpeta_del_usuario(client, tmp_path):
    destino = tmp_path / "PROYECTOS" / "FRUTINOVELAS" / "Mi_Video"
    p = client.post("/api/projects", json={
        "mode": "idea", "idea": "pastel de choclo",
        "custom_workspace_path": str(destino)}).json()
    pid = p["id"]

    check("meta persiste custom_workspace_path",
          p["meta"].get("custom_workspace_path") == str(destino),
          str(p.get("meta"))[:200])
    check("workspace creado EXACTAMENTE en la ruta del usuario",
          p.get("workspace") == str(destino), str(p.get("workspace")))

    d = Path(p["workspace"])
    check("la carpeta del usuario existe", d.is_dir(), str(d))
    for sub in pws.SUBDIRS:
        check(f"subcarpeta {sub}/ en el disco del usuario", (d / sub).is_dir())
    check("marca.json nace en la carpeta del usuario",
          (d / "marca.json").is_file())
    check("data/projects/ NO recibió el workspace",
          not (Path(config.PROJECTS_DIR) / pws.workspace_name(
              {"id": pid, "niche": p.get("niche"), "title": p.get("title")})
          ).exists())

    # el workspace es custom_root Y resolve_workspace lo respeta
    check("custom_root devuelve la ruta del usuario",
          pws.custom_root({"meta": p["meta"]}) == destino)
    check("resolve_workspace respeta la ruta (aun sin legacy)",
          pws.resolve_workspace(p) == destino)


def test_workspace_info_flag_custom_y_get_pid(client, tmp_path):
    destino = tmp_path / "Destino" / "Video X"
    p = client.post("/api/projects", json={
        "mode": "idea", "idea": "visor", "custom_workspace_path": str(destino)}).json()
    r = client.get(f"/api/projects/{p['id']}")
    w = r.json().get("workspace") or {}
    check("GET /api/projects/{pid} trae workspace", bool(w), str(w)[:200])
    check("workspace_info.path = ruta del usuario", w.get("path") == str(destino),
          str(w.get("path")))
    check("workspace_info.custom = True", w.get("custom") is True)
    check("visibilidad de las 5 carpetas en el visor",
          set((w.get("carpetas") or {}).keys()) == set(pws.SUBDIRS))
    # sin custom → flag honesto False
    p2 = client.post("/api/projects", json={"mode": "idea", "idea": "estandar"}).json()
    w2 = (client.get(f"/api/projects/{p2['id']}").json().get("workspace") or {})
    check("proyecto estándar → custom False", w2.get("custom") is False)
    check("proyecto estándar → path canónico data/projects/",
          str(w2.get("path", "")).startswith(str(Path(config.PROJECTS_DIR))))


# ── E · open-folder apunta a la carpeta física del usuario ───────────────
def test_open_folder_apunta_a_carpeta_del_usuario(client, tmp_path, monkeypatch):
    import shutil as _shutil
    import subprocess as _subprocess
    destino = tmp_path / "Abrir" / "Mi Video"
    p = client.post("/api/projects", json={
        "mode": "idea", "idea": "abrir", "custom_workspace_path": str(destino)}).json()
    # sin explorador disponible → respuesta honesta, pero el PATH debe ser
    # exactamente la carpeta del usuario (no data/projects, no output/)
    monkeypatch.setattr(_shutil, "which", lambda x: None)
    monkeypatch.setattr(_subprocess, "Popen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no GUI")))
    monkeypatch.setattr(main, "_pick_folder_dialog", lambda: (True, str(destino)))
    r = client.post(f"/api/projects/{p['id']}/open-folder")
    check("open-folder → 200", r.status_code == 200, r.text[:200])
    check("path del response = carpeta del usuario",
          r.json().get("path") == str(destino), r.text[:200])


# ── F · purge NUNCA borra la carpeta del usuario ─────────────────────────
def test_purge_no_borra_carpeta_del_usuario(tmp_path):
    destino = tmp_path / "Usuario" / "Sagrado"
    proj = {"id": "purge" + "0" * 8, "meta": {"custom_workspace_path": str(destino)}}
    d = pws.create_workspace(proj)
    check("workspace creado en carpeta del usuario", d == destino and d.is_dir())
    pws.purge_workspace(proj)
    check("la carpeta del usuario SIGUE intacta tras purge", destino.is_dir())
    check("marca.json del usuario intacto", (destino / "marca.json").is_file())
    # contraste: proyecto estándar SÍ purga su vista canónica
    proj2 = {"id": "std" + "0" * 10, "niche": "n", "title": "t"}
    d2 = pws.create_workspace(proj2)
    check("estándar nace en data/projects/",
          str(d2).startswith(str(Path(config.PROJECTS_DIR))), str(d2))
    pws.purge_workspace(proj2)
    check("estándar se purga normal", not d2.exists())


# ── G · degradación honesta (sin custom o ruta inválida en meta) ─────────
def test_degradacion_honesta_a_estandar():
    check("sin meta → None", pws.custom_root({}) is None)
    check("meta vacía → None", pws.custom_root({"meta": {}}) is None)
    check("ruta vacía → None",
          pws.custom_root({"meta": {"custom_workspace_path": ""}}) is None)
    check("ruta relativa → None",
          pws.custom_root({"meta": {"custom_workspace_path": "rel/x"}}) is None)
    check("ruta con NUL → None",
          pws.custom_root({"meta": {"custom_workspace_path": "/a\x00b"}}) is None)
    check("ruta >500 chars → None",
          pws.custom_root({"meta": {"custom_workspace_path": "/" + "a" * 600}}) is None)
    # create_workspace con meta inválida → cae al estándar, sin lanzar
    proj = {"id": "deg" + "0" * 9, "niche": "n", "title": "t",
            "meta": {"custom_workspace_path": "relativa/no/absoluta"}}
    d = pws.create_workspace(proj)
    check("meta inválida → workspace estándar sin lanzar",
          str(d).startswith(str(Path(config.PROJECTS_DIR))), str(d))
    pws.purge_workspace(proj)
