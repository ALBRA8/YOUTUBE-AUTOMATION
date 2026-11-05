"""INT-090 · Biblioteca de Personajes y Blindaje de Universos + AGENTE 2
(visor visual del workspace y endpoint open-folder) — brigada de auditoría.

Cubre:
  A. Biblioteca canónica en backend/data/avatars/ (los 3 personajes del
     enunciado: cocardo / valeria / voz_narradora) con flow-linking.
  B. Resolución de universo y reglas de incompatibilidad.
  C. API: universo en avatares, biblioteca GET/PATCH, avatar_ids en
     POST /api/projects (incompatibles → HTTP 400 ANTES de gastar recursos).
  D. workspace_info + GET /api/projects/{pid} con visor.
  E. POST /api/projects/{pid}/open-folder (Windows os.startfile y honesto
     en servidores sin GUI).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
import database as db  # noqa: E402
import main  # noqa: E402
from services import universos  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

OK, FAIL = 0, 0
REPO_LIB = BACKEND / "data" / "avatars"


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


def _lib_tmp(tmp_path: Path, ids: dict[str, dict] | None = None) -> Path:
    """Biblioteca efímera para tests que escriben (flow-linking)."""
    lib = tmp_path / "avatars"
    default = {
        "cocardo": {"id": "cocardo", "nombre": "Cocardo", "universo": "animado",
                    "modelo": "nano-banana-2.1", "voz": "es-CO-GonzaloNeural",
                    "incompatible_con": ["real", "hiper"],
                    "flow_project_id": None, "flow_character_id": None},
        "valeria": {"id": "valeria", "nombre": "Valeria", "universo": "real",
                    "modelo": "veo-3.1", "voz": "es-CO-SalomeNeural",
                    "incompatible_con": ["animado", "hiper"],
                    "flow_project_id": None, "flow_character_id": None},
        "voz_narradora": {"id": "voz_narradora", "nombre": "Voz Narradora",
                          "universo": "neutro", "modelo": None, "voz": None,
                          "incompatible_con": [],
                          "flow_project_id": None, "flow_character_id": None},
    }
    for k, v in (ids or default).items():
        d = lib / k
        d.mkdir(parents=True, exist_ok=True)
        (d / "descripcion.json").write_text(
            json.dumps(v, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return lib


# ── A. biblioteca canónica del repo ──────────────────────────────────────
def test_biblioteca_canonica_del_repo():
    check("directorio data/avatars/ existe", REPO_LIB.is_dir())
    # FIX-WIN-003 · cross-platform por COMPONENTES del path (en Windows la
    # ruta usa «\» y endswith("data/avatars") falla). El conftest redirige
    # DATA_DIR a <sesión>/backend_data, así que el layout legítimo es uno de:
    #   repo real:  .../backend/data/avatars        → ("data", "avatars")
    #   sesión pytest: .../<sesión>/backend_data/avatars
    #                                    → ("backend_data", "avatars")
    check("universos.AVATARS_LIB apunta a data/avatars",
          Path(universos.AVATARS_LIB).parts[-2:] in
          (("data", "avatars"), ("backend_data", "avatars")),
          str(universos.AVATARS_LIB))
    # cargar leyendo del REPO real (no del DATA_DIR de la sesión de tests)
    orig = universos.AVATARS_LIB
    universos.AVATARS_LIB = REPO_LIB
    try:
        bib = universos.biblioteca()
        check("3 personajes canónicos", set(bib) >= {"cocardo", "valeria", "voz_narradora"},
              str(sorted(bib)))
        c, v, n = bib["cocardo"], bib["valeria"], bib["voz_narradora"]
        check("cocardo: universo animado", c["universo"] == "animado", str(c.get("universo")))
        check("cocardo: modelo nano-banana-2.1", c["modelo"] == "nano-banana-2.1", str(c.get("modelo")))
        check("cocardo: voz es-CO-GonzaloNeural", c["voz"] == "es-CO-GonzaloNeural", str(c.get("voz")))
        check("cocardo: incompatible con real+hiper",
              set(c["incompatible_con"]) == {"real", "hiper"}, str(c["incompatible_con"]))
        check("valeria: universo real", v["universo"] == "real")
        check("valeria: modelo veo-3.1", v["modelo"] == "veo-3.1")
        check("valeria: voz es-CO-SalomeNeural", v["voz"] == "es-CO-SalomeNeural")
        check("valeria: incompatible con animado+hiper",
              set(v["incompatible_con"]) == {"animado", "hiper"}, str(v["incompatible_con"]))
        check("voz_narradora: universo neutro", n["universo"] == "neutro")
        check("voz_narradora: compatible con todos",
              n["incompatible_con"] == [], str(n["incompatible_con"]))
        for k in ("cocardo", "valeria", "voz_narradora"):
            av = bib[k]
            check(f"{k}: soporta flow_project_id/flow_character_id",
                  "flow_project_id" in av and "flow_character_id" in av)
    finally:
        universos.AVATARS_LIB = orig


def test_universo_de_resolucion(tmp_path, monkeypatch):
    monkeypatch.setattr(universos, "AVATARS_LIB", _lib_tmp(tmp_path))
    # 1º: campo explícito de la DB
    check("explícito gana", universos.universo_de(
        {"name": "Valeria", "universo": "animado"}) == "animado")
    # 2º: match por slug del nombre contra la biblioteca
    check("slug «Cocardo 🐸» → animado",
          universos.universo_de({"name": "Cocardo 🐸"}) == "animado")
    check("slug «Voz Narradora» → neutro",
          universos.universo_de({"name": "Voz Narradora"}) == "neutro")
    # 3º: silencio honesto → neutro
    check("desconocido → neutro",
          universos.universo_de({"name": "Raro"}) == "neutro")
    check("None → neutro", universos.universo_de(None) == "neutro")


def test_reglas_de_incompatibilidad(tmp_path, monkeypatch):
    monkeypatch.setattr(universos, "AVATARS_LIB", _lib_tmp(tmp_path))
    check("animado vs real: guerra", universos.incompatibles("animado", "real"))
    check("real vs animado: guerra (simétrico)", universos.incompatibles("real", "animado"))
    check("real vs hiper: guerra", universos.incompatibles("real", "hiper"))
    check("animado vs hiper: guerra", universos.incompatibles("animado", "hiper"))
    check("animado vs animado: paz", not universos.incompatibles("animado", "animado"))
    check("neutro vs animado: paz", not universos.incompatibles("neutro", "animado"))
    check("neutro vs real: paz", not universos.incompatibles("real", "neutro"))
    check("neutro vs hiper: paz", not universos.incompatibles("hiper", "neutro"))


# ── C. API ───────────────────────────────────────────────────────────────
def test_api_avatar_con_universo(client, tmp_path, monkeypatch):
    monkeypatch.setattr(universos, "AVATARS_LIB", _lib_tmp(tmp_path))
    r = client.post("/api/avatars", json={"name": "Cocardo 🐸",
                                          "universo": "animado"})
    check("POST /api/avatars 200", r.status_code == 200, r.text[:200])
    check("universo persistido", r.json().get("universo") == "animado", r.text[:200])
    aid_ok = r.json()["id"]
    # invalido → 400 con mensaje
    r2 = client.post("/api/avatars", json={"name": "Raro", "universo": "wester"})
    check("universo inválido → 400", r2.status_code == 400, r2.text[:200])
    # PATCH universo
    r3 = client.patch(f"/api/avatars/{aid_ok}", json={"universo": "real"})
    check("PATCH universo 200", r3.status_code == 200, r3.text[:200])
    check("PATCH aplicado", r3.json().get("universo") == "real")
    r4 = client.patch(f"/api/avatars/{aid_ok}", json={"universo": "no"})
    check("PATCH universo inválido → 400", r4.status_code == 400)
    # listado resuelve universo nunca nulo
    r5 = client.get("/api/avatars")
    uni = {a["name"]: a["universo"] for a in r5.json()}
    check("listado trae universo resuelto", uni.get("Cocardo 🐸") == "real", str(uni))


def test_api_proyecto_incompatibles_400(client, tmp_path, monkeypatch):
    monkeypatch.setattr(universos, "AVATARS_LIB", _lib_tmp(tmp_path))
    a_anim = client.post("/api/avatars", json={"name": "Cocardo", "universo": "animado"}).json()
    a_real = client.post("/api/avatars", json={"name": "Valeria", "universo": "real"}).json()
    a_neutro = client.post("/api/avatars", json={"name": "Narradora", "universo": "neutro"}).json()
    # guerra animado+real → 400 con mensaje explicativo ANTES de gastar recursos
    r = client.post("/api/projects", json={
        "mode": "idea", "title": "Video cruzado",
        "avatar_ids": [a_anim["id"], a_real["id"]]})
    check("animado+real → 400", r.status_code == 400, r.text[:200])
    check("mensaje explica universos", "universos incompatibles" in r.text
          and "animado" in r.text and "real" in r.text, r.text[:300])
    # neutro no genera guerra → proyecto creado con reparto en meta
    r2 = client.post("/api/projects", json={
        "mode": "idea", "title": "Video compatible",
        "avatar_ids": [a_anim["id"], a_neutro["id"]]})
    check("animado+neutro → 200", r2.status_code == 200, r2.text[:300])
    p = r2.json()
    check("meta.avatar_ids guardado",
          (p.get("meta") or {}).get("avatar_ids") == [a_anim["id"], a_neutro["id"]],
          str(p.get("meta")))
    check("avatar_id primario = primero", p.get("avatar_id") == a_anim["id"])
    # lista con id desconocido → 400 estricto
    r3 = client.post("/api/projects", json={
        "mode": "idea", "avatar_ids": [a_anim["id"], "0" * 12]})
    check("avatar_ids desconocido → 400", r3.status_code == 400, r3.text[:200])
    check("menciona el id faltante", ("0" * 12) in r3.text)
    # avatar_ids no-lista → 400
    r4 = client.post("/api/projects", json={
        "mode": "idea", "avatar_ids": "cocardo"})
    check("avatar_ids no-lista → 400", r4.status_code == 400)
    # retrocompat: avatar_id único desconocido sigue silencioso (histórico)
    r5 = client.post("/api/projects", json={
        "mode": "idea", "title": "Retro", "avatar_id": "f" * 12})
    check("avatar_id único desconocido → 200 retro",
          r5.status_code == 200 and r5.json().get("avatar_id") is None,
          r5.text[:200])


def test_api_library_endpoints(client, tmp_path, monkeypatch):
    monkeypatch.setattr(universos, "AVATARS_LIB", _lib_tmp(tmp_path))
    r = client.get("/api/avatars/library")
    check("GET /api/avatars/library 200", r.status_code == 200, r.text[:200])
    data = r.json()
    check("expone catálogo de universos",
          set(data.get("universos", [])) == {"animado", "real", "hiper", "neutro"},
          str(data.get("universos")))
    check("expone reglas por universo",
          data.get("reglas", {}).get("animado") == ["hiper", "real"],
          str(data.get("reglas")))
    ids = {a["id"] for a in data.get("avatars", [])}
    check("expone los 3 personajes", ids == {"cocardo", "valeria", "voz_narradora"}, str(ids))
    # PATCH flow-linking persiste en disco
    r2 = client.patch("/api/avatars/library/cocardo", json={
        "flow_project_id": "proj_flow_123", "flow_character_id": "char_cocardo"})
    check("PATCH flow-linking 200", r2.status_code == 200, r2.text[:200])
    disco = json.loads((tmp_path / "avatars" / "cocardo" / "descripcion.json")
                       .read_text(encoding="utf-8"))
    check("flow_project_id persistido", disco["flow_project_id"] == "proj_flow_123", str(disco.get("flow_project_id")))
    check("flow_character_id persistido", disco["flow_character_id"] == "char_cocardo")
    r3 = client.get("/api/avatars/library")
    coc = next(a for a in r3.json()["avatars"] if a["id"] == "cocardo")
    check("GET refleja el enlace", coc["flow_project_id"] == "proj_flow_123")
    r4 = client.patch("/api/avatars/library/no-existe", json={"flow_project_id": "x"})
    check("id de biblioteca desconocido → 404", r4.status_code == 404)


# ── D. visor visual del workspace ────────────────────────────────────────
PROYECTO = {"id": "a1b2c3d4e5f6", "title": "Pastel de Choclo 🍰",
            "niche": "cocina", "mode": "nicho", "meta": {}}


def test_workspace_info(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    from pipeline import project_workspace as pws
    info = pws.workspace_info(dict(PROYECTO))
    check("workspace inexistente → existe False", info["existe"] is False)
    check("reporta las 5 carpetas", set(info["carpetas"]) ==
          {"fuentes", "guion", "voz", "clips", "out"}, str(info["carpetas"].keys()))
    check("sin workspace → carpetas vacías", all(v["n"] == 0 for v in info["carpetas"].values()))
    check("reporta legacy", "legacy" in info and info["legacy"]["existe"] is False)
    # crear → estado real
    ws = pws.create_workspace(dict(PROYECTO))
    (ws / "guion" / "guion.json").write_text("[]", encoding="utf-8")
    info2 = pws.workspace_info(dict(PROYECTO))
    check("existe True tras crear", info2["existe"] is True)
    check("marca.json detectada", info2["marca"] is True)
    check("guion/ cuenta 1 archivo", info2["carpetas"]["guion"]["n"] == 1
          and info2["carpetas"]["guion"]["items"] == ["guion.json"],
          str(info2["carpetas"]["guion"]))
    check("nombre canónico", info2["name"] == "cocina_pastel-de-choclo_a1b2c3d4",
          info2["name"])


def test_api_proyecto_trae_workspace(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    p = client.post("/api/projects", json={"mode": "idea", "title": "Con visor"}).json()
    det = client.get(f"/api/projects/{p['id']}").json()
    w = det.get("workspace")
    check("detalle trae workspace", isinstance(w, dict) and w.get("name"), str(w)[:200])
    check("workspace con 5 carpetas", len((w or {}).get("carpetas") or {}) == 5)
    check("ruta contenida en PROJECTS_DIR",
          str(w.get("path", "")).startswith(str(config.PROJECTS_DIR)), str(w.get("path")))


# ── E. open-folder ───────────────────────────────────────────────────────
def test_open_folder_endpoint(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    llamadas: list[Path] = []

    def fake_abrir(ruta):
        llamadas.append(Path(ruta))
        return True, "Explorador de archivos de Windows"

    monkeypatch.setattr(main, "_abrir_carpeta_sistema", fake_abrir)
    p = client.post("/api/projects", json={"mode": "idea", "title": "Abrir Carpeta"}).json()
    r = client.post(f"/api/projects/{p['id']}/open-folder")
    check("POST open-folder 200", r.status_code == 200, r.text[:200])
    body = r.json()
    check("abierto True", body.get("abierto") is True, r.text[:200])
    check("metodo Windows", body.get("metodo") == "Explorador de archivos de Windows")
    ws = Path(body.get("path", ""))
    check("ruta apunta al workspace canónico",
          str(ws).startswith(str(config.PROJECTS_DIR)), str(ws))
    check("el explorador recibió UNA carpeta existente",
          len(llamadas) == 1 and llamadas[0].is_dir(), str(llamadas))
    check("workspace auto-creado con las 5 carpetas",
          all((ws / s).is_dir() for s in
              ("fuentes", "guion", "voz", "clips", "out")))


def test_open_folder_honesto_sin_gui(client, tmp_path, monkeypatch):
    """En un servidor sin GUI responde honesto (abierto=False) sin lanzar."""
    import os as _os
    import shutil as _shutil
    import subprocess as _subprocess
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(_shutil, "which", lambda x: None)
    monkeypatch.setattr(_subprocess, "Popen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no GUI")))
    # FIX-WIN-003 · cross-platform: en Windows _abrir_carpeta_sistema llama
    # _os.startfile (mismo módulo «os» que importa internamente) ANTES de
    # consultar shutil.which/subprocess.Popen — sin este parche el test pasa
    # en Linux/Mac pero abre el Explorador REAL en Windows y da verde falso.
    # Forzamos SO sin startfile para que la rama sin GUI aplique en todos.
    monkeypatch.setattr(_os, "name", "posix")
    monkeypatch.delattr(_os, "startfile", raising=False)
    p = client.post("/api/projects", json={"mode": "idea", "title": "Sin GUI"}).json()
    r = client.post(f"/api/projects/{p['id']}/open-folder")
    check("sin GUI → 200", r.status_code == 200, r.text[:200])
    check("abierto False + motivo", r.json().get("abierto") is False
          and "explorador" in r.json().get("metodo", ""), r.text[:200])
    check("path incluido para el usuario", bool(r.json().get("path")))


def test_open_folder_guard_pid(client):
    check("pid inválido → 400",
          client.post("/api/projects/mal-pid/open-folder").status_code == 400)
    check("pid inexistente → 404",
          client.post("/api/projects/" + "0" * 12 + "/open-folder").status_code == 404)
