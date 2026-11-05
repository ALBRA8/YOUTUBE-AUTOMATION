#!/usr/bin/env python3
"""
INT-086 · Sistema Modular de Plantillas de Nicho y Organización Limpia
de Proyectos (inspirado en Sloth).

Cubre los 5 frentes de la tarea:
  A. pipeline/project_workspace.py — estructura estándar
     data/projects/<nicho>_<slug>_<id8>/ con fuentes/, guion/, voz/,
     clips/, out/ + marca.json; retrocompatibilidad transparente con
     data/output/<pid> (resolve_workspace).
  B. services/niche_templates.py — catálogo de 5 plantillas
     (cocina-recetas, crochet-manualidades, ugc-producto, viral-short,
     miniaturas) auto-sembrado en data/presets/niche_templates.json.
  C. marca.json — identidad de canal (nicho, tono, voz_default, cierre)
     e inyección automática del cierre en la última escena (guion + TTS +
     subtítulos la heredan), idempotente y honesta.
  D. API — GET /api/templates (catálogo con icono/descripción/config) y
     POST /api/projects con template_id (herencia con precedencia
     body > plantilla) + DELETE que purga el workspace.
  E. Contrato de versión 2.40.0 (INT-080: bump por cambio funcional).

Aislamiento: conftest redirige DATA_DIR/OUTPUT_DIR/PROJECTS_DIR/DB a un
tmp de sesión; pytest NUNCA toca backend/data real. Integración REAL:
GET /api/templates y POST/DELETE /api/projects contra la app FastAPI.

Dual-mode: pytest (fixtures client/tmp_path/monkeypatch) y script directo.
"""
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
import database as db  # noqa: E402
import main  # noqa: E402
from pipeline import project_workspace as pws  # noqa: E402
from services import niche_templates as ntpl  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

OK, FAIL = 0, 0
ESPERADAS = ("cocina-recetas", "crochet-manualidades", "ugc-producto",
             "viral-short", "miniaturas")


def check(nombre: str, cond: bool, extra: str = ""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))
    if not ok:  # bajo pytest esto falla DE VERDAD (no falso verde)
        raise AssertionError(nombre + (f" — {extra}" if extra else ""))


@pytest.fixture
def client():
    return TestClient(main.app)


PROYECTO = {"id": "a1b2c3d4e5f6", "title": "Pastel de Choclo 🍰",
            "niche": "cocina", "mode": "nicho", "meta": {}}


# ── A. estructura estándar del workspace ─────────────────────────────────
def test_estructura_estandar(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    ws = pws.create_workspace(dict(PROYECTO))
    nombre = ws.name
    check("nombre <nicho>_<slug>_<id8>",
          nombre == "cocina_pastel-de-choclo_a1b2c3d4", nombre)
    for sub in ("fuentes", "guion", "voz", "clips", "out"):
        check(f"subcarpeta {sub}/", (ws / sub).is_dir())
    marca = json.loads((ws / "marca.json").read_text(encoding="utf-8"))
    check("marca.json real en la raíz", marca.get("nicho") == "cocina", str(marca))
    # idempotente: re-crear no rompe ni duplica
    ws2 = pws.create_workspace(dict(PROYECTO),
                               marca={"nicho": "cocina", "cierre": {}})
    check("create_workspace idempotente", ws2 == ws
          and json.loads((ws / "marca.json").read_text(encoding="utf-8"))
          .get("nicho") == "cocina")


def test_retrocompatibilidad_legacy(tmp_path, monkeypatch):
    """Proyecto legacy (solo output/<pid>) → resolve_workspace devuelve el
    almacén físico intacto; con workspace → devuelve la vista organizada."""
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    legacy = tmp_path / "output" / PROYECTO["id"]
    legacy.mkdir(parents=True)
    check("legacy sin workspace → output/<pid>",
          pws.resolve_workspace(dict(PROYECTO)) == legacy)
    ws = pws.create_workspace(dict(PROYECTO))
    check("con workspace → data/projects/<nombre>",
          pws.resolve_workspace(dict(PROYECTO)) == ws)
    check("legacy NO se movió ni renombró", legacy.is_dir())


def test_purge_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    ws = pws.create_workspace(dict(PROYECTO))
    pws.purge_workspace(dict(PROYECTO))
    check("purge elimina la vista", not ws.exists())


# ── B. catálogo de plantillas ────────────────────────────────────────────
def test_catalogo_5_plantillas():
    ts = ntpl.list_templates()
    ids = tuple(t["id"] for t in ts)
    check("las 5 plantillas del catálogo", all(e in ids for e in ESPERADAS),
          str(ids))
    for t in ts:
        check(f"plantilla {t['id']} con icono+descripción+config",
              bool(t.get("icono")) and bool(t.get("descripcion"))
              and "format" in t and "voice" in t)
    check("auto-siembra en data/presets/niche_templates.json",
          ntpl.PRESETS_PATH.is_file(), str(ntpl.PRESETS_PATH))
    check("get_template desconocida → None",
          ntpl.get_template("no-existe") is None
          and ntpl.get_template("") is None)


# ── C. marca.json + cierre automático ────────────────────────────────────
def test_inject_cierre(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    proj = db.create_project(title="Test cierre", mode="nicho",
                             niche="cocina", meta={})
    pid = proj["id"]
    try:
        db.replace_scenes(pid, [
            {"idx": 0, "title": "Gancho", "narration": "Este pastel es fácil."},
            {"idx": 1, "title": "Cierre", "narration": "Y así quedó el pastel."},
        ])
        marca = {"nicho": "cocina", "cierre": {
            "red": "Instagram", "cuenta": "@cocina.facil",
            "frase": "Sígueme en Instagram para la receta completa"}}
        pws.create_workspace(dict(proj), marca=marca)
        proj = db.get_project(pid)

        check("cierre inyectado en la última escena",
              pws.inject_cierre(proj) is True)
        escenas = db.get_scenes(pid)
        check("la frase quedó al final de la narración",
              escenas[-1]["narration"].endswith(
                  "Sígueme en Instagram para la receta completa"),
              escenas[-1]["narration"])
        check("primera escena intacta",
              escenas[0]["narration"] == "Este pastel es fácil.")
        check("meta.cierre_inyectado",
              (db.get_project(pid).get("meta") or {}).get("cierre_inyectado") is True)
        check("idempotente: 2ª llamada no duplica",
              pws.inject_cierre(db.get_project(pid)) is False
              and db.get_scenes(pid)[-1]["narration"].count("Sígueme") == 1)
        # honesta: si la frase ya estaba, no duplica
        db.replace_scenes(pid, [
            {"idx": 0, "title": "Única", "narration":
                "Ya dije: Sígueme en Instagram para la receta completa"}])
        p2 = db.get_project(pid)
        p2["meta"] = {}
        db.update_project(pid, meta={})
        check("frase ya presente → no duplica",
              pws.inject_cierre(p2) is False)
        # modo audio: la voz es del usuario — no se toca
        db.update_project(pid, mode="audio")
        check("modo audio → nunca inyecta",
              pws.inject_cierre(db.get_project(pid)) is False)
    finally:
        db.delete_project(pid)


def test_inject_cierre_sin_marca(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    proj = db.create_project(title="Sin cierre", mode="idea", meta={})
    try:
        check("sin marca.json/cierre → no-op", pws.inject_cierre(proj) is False)
    finally:
        db.delete_project(proj["id"])


# ── D. API: catálogo + creación con plantilla ────────────────────────────
def test_get_templates(client):
    res = client.get("/api/templates")
    check("GET /api/templates → 200", res.status_code == 200, str(res.status_code))
    ts = res.json()
    ids = {t.get("id") for t in ts}
    check("lista las 5 con icono y descripción",
          set(ESPERADAS) <= ids
          and all(t.get("icono") and t.get("descripcion") for t in ts),
          str(ids))


def test_post_projects_con_template(client):
    """Proyecto con template_id=cocina-recetas hereda marca.json, voz,
    subtítulos y ritmo de la plantilla (precedencia: body > plantilla)."""
    res = client.post("/api/projects", json={
        "mode": "idea", "idea": "pastel de choclo en 3 pasos",
        "template_id": "cocina-recetas"})
    check("POST /api/projects → 200", res.status_code == 200,
          f"{res.status_code} {res.text[:200]}")
    p = res.json()
    pid = p["id"]
    try:
        meta = p.get("meta") or {}
        check("meta.template_id", meta.get("template_id") == "cocina-recetas")
        check("hereda voz de la plantilla",
              p.get("voice") == "es-CO-SalomeNeural", str(p.get("voice")))
        check("hereda subtítulos (minimal) y ritmo canónico (slow)",
              meta.get("subtitle_style") == "minimal"
              and meta.get("pacing") == "slow", str(meta))
        ws = Path(p["workspace"])
        check("workspace devuelto y creado", ws.is_dir(), str(ws))
        marca = json.loads((ws / "marca.json").read_text(encoding="utf-8"))
        check("marca.json heredado de la plantilla",
              marca.get("nicho") == "cocina"
              and marca.get("voz_default") == "es-CO-SalomeNeural"
              and marca.get("cierre", {}).get("red") == "Instagram", str(marca))
    finally:
        client.delete(f"/api/projects/{pid}")
    check("DELETE purga el proyecto y su workspace",
          client.get(f"/api/projects/{pid}").status_code == 404
          and not Path(p["workspace"]).exists())


def test_post_projects_body_gana_sobre_plantilla(client):
    """La voz explícita del body SIEMPRE gana sobre la plantilla."""
    res = client.post("/api/projects", json={
        "mode": "idea", "idea": "prueba de precedencia",
        "template_id": "viral-short", "voice": "es-ES-AlvaroNeural"})
    check("POST con voice propio → 200", res.status_code == 200,
          str(res.status_code))
    p = res.json()
    try:
        check("body gana: voice del usuario respetado",
              p.get("voice") == "es-ES-AlvaroNeural", str(p.get("voice")))
        check("plantilla aplicada en lo no elegido: hormozi + pacing fast",
              (p.get("meta") or {}).get("subtitle_style") == "hormozi"
              and (p.get("meta") or {}).get("pacing") == "fast")
    finally:
        client.delete(f"/api/projects/{p['id']}")


def test_template_id_desconocido_400(client):
    res = client.post("/api/projects", json={
        "mode": "idea", "idea": "x", "template_id": "no-existe"})
    check("template_id desconocido → 400", res.status_code == 400,
          str(res.status_code))


def test_proyecto_sin_plantilla_tiene_workspace(client):
    """Retrocompat: un proyecto normal (sin template_id) también recibe
    su workspace organizado con marca.json mínima desde el proyecto."""
    res = client.post("/api/projects", json={
        "mode": "idea", "idea": "curiosidades del océano", "nicho": "misterio"})
    check("POST sin plantilla → 200", res.status_code == 200, str(res.status_code))
    p = res.json()
    try:
        ws = Path(p["workspace"])
        check("workspace creado igualmente", ws.is_dir())
        marca = json.loads((ws / "marca.json").read_text(encoding="utf-8"))
        check("marca mínima desde el nicho del proyecto",
              marca.get("nicho") == "misterio", str(marca))
    finally:
        client.delete(f"/api/projects/{p['id']}")


# ── E. sync_artifacts (vista organizada) ─────────────────────────────────
ES_POSIX = (sys.platform != "win32")


def test_sync_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    pid = PROYECTO["id"]
    legacy = tmp_path / "output" / pid
    (legacy / "clips").mkdir(parents=True)
    (legacy / "voice_full.wav").write_bytes(b"RIFFfake")
    (legacy / "words.json").write_text("[]", encoding="utf-8")
    (legacy / "clips" / "clip_00.mp4").write_bytes(b"clip")
    (legacy / f"{pid}_final.mp4").write_bytes(b"mp4")
    (legacy / "contact_sheet.jpg").write_bytes(b"jpg")
    (legacy / "thumb.jpg").write_bytes(b"jpg")
    ws = pws.create_workspace(dict(PROYECTO))
    pub = pws.sync_artifacts(dict(PROYECTO))
    # INT-086b · cross-platform: se verifica que el artefacto EXISTA en la
    # vista (symlink en POSIX; symlink|hardlink|copia en Windows) — solo en
    # POSIX se exige además que sea symlink.
    check("voz/narracion.wav expuesto",
          (ws / "voz" / "narracion.wav").exists(), str(pub))
    check("voz/voz.json expuesto", (ws / "voz" / "voz.json").exists())
    check("clips/ expuesto",
          (ws / "clips").is_symlink() if ES_POSIX else (ws / "clips").is_dir())
    check("out/video_final.mp4 expuesto",
          (ws / "out" / "video_final.mp4").exists())
    if ES_POSIX:  # en el sandbox Linux el mecanismo CANÓNICO es el symlink
        check("mecanismo canónico symlink en POSIX",
              (ws / "voz" / "narracion.wav").is_symlink()
              and (ws / "voz" / "voz.json").is_symlink()
              and (ws / "out" / "video_final.mp4").is_symlink())
    check("out/contact_sheet.png copiado",
          (ws / "out" / "contact_sheet.png").is_file())
    check("portada.png copiado", (ws / "portada.png").is_file())
    check("sin plantilla → guion aún no publicado",
          not (ws / "guion" / "guion.md").exists())
    # idempotente: segunda pasada no revienta
    pub2 = pws.sync_artifacts(dict(PROYECTO))
    check("sync idempotente", isinstance(pub2, dict))


def test_link_fallback_windows(tmp_path, monkeypatch):
    """INT-086b · cadena symlink → hardlink → copia cuando os.symlink lanza
    OSError (WinError 1314: en Windows sin Developer Mode/Admin el
    privilegio de symlink no está otorgado)."""
    target = tmp_path / "voice_full.wav"
    target.write_bytes(b"RIFFfake")
    link = tmp_path / "narracion.wav"
    check("con symlink disponible → symlink",
          pws._link(target, link) == "symlink" and link.is_symlink())
    link.unlink()

    def _winerror_1314(*_a, **_k):
        raise OSError(1314, "A required privilege is not held by the client")

    monkeypatch.setattr(pws.os, "symlink", _winerror_1314)
    check("sin symlink → hardlink (instantáneo en NTFS)",
          pws._link(target, link) == "hardlink" and link.exists()
          and not link.is_symlink() and link.read_bytes() == b"RIFFfake")
    link.unlink()
    monkeypatch.setattr(pws.os, "link", _winerror_1314)
    check("sin symlink ni hardlink → copia",
          pws._link(target, link) == "copy" and link.is_file()
          and link.read_bytes() == b"RIFFfake")
    # directorio: sin symlink NO hay fallback (NTFS no tiene hardlinks de
    # carpeta y copiar clips duplicaría gigas) → la vista conserva lo suyo
    d = tmp_path / "clips_src"
    d.mkdir()
    out = tmp_path / "clips_view"
    check("directorio sin symlink → '' (sin copia de gigas)",
          pws._link(d, out) == "" and not out.exists())


def test_sync_artifacts_guion_desde_bd(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    proj = db.create_project(title="Guion sync", mode="idea", meta={})
    try:
        db.replace_scenes(proj["id"], [
            {"idx": 0, "title": "S1", "narration": "Hola mundo."}])
        p = db.get_project(proj["id"])
        pub = pws.sync_artifacts(p)
        ws = pws.workspace_path(p)
        md = (ws / "guion" / "guion.md").read_text(encoding="utf-8")
        check("guion.md generado desde BD",
              "## Escena 1 — S1" in md and "Hola mundo." in md, md)
        gj = json.loads((ws / "guion" / "guion.json").read_text(encoding="utf-8"))
        check("guion.json con las escenas",
              len(gj) == 1 and gj[0]["narration"] == "Hola mundo.")
        check("publicación reportada", "guion/guion.md" in pub)
    finally:
        db.delete_project(proj["id"])


# ── contratos de fuente y versión (cadena INT-080) ───────────────────────
def test_contratos_fuente_y_version():
    check("APP_VERSION 2.44.0 (INT-080: bump por cambio funcional)",
          config.APP_VERSION == "2.44.0")
    src_ws = (BACKEND / "pipeline" / "project_workspace.py").read_text(
        encoding="utf-8")
    check("firma pública del módulo workspace",
          "def generate_contact_sheet" not in src_ws
          and "def create_workspace" in src_ws
          and "def resolve_workspace" in src_ws
          and "def inject_cierre" in src_ws
          and "def sync_artifacts" in src_ws)
    src_ntpl = (BACKEND / "services" / "niche_templates.py").read_text(
        encoding="utf-8")
    check("catálogo define las 5 plantillas integradas",
          all(f'"{tid}"' in src_ntpl for tid in ESPERADAS))
    src_main = (BACKEND / "main.py").read_text(encoding="utf-8")
    check("endpoint GET /api/templates registrado",
          '@app.get("/api/templates")' in src_main)
    check("POST /api/projects acepta template_id",
          'body.get("template_id")' in src_main)
    src_orch = (BACKEND / "pipeline" / "orchestrator.py").read_text(
        encoding="utf-8")
    check("pipeline engancha inject_cierre y sync_artifacts",
          "project_workspace.inject_cierre" in src_orch
          and "project_workspace.sync_artifacts" in src_orch)
    src_conf = (BACKEND / "config.py").read_text(encoding="utf-8")
    check("PROJECTS_DIR en config y carpeta creada al arranque",
          'PROJECTS_DIR = DATA_DIR / "projects"' in src_conf
          and "PROJECTS_DIR, TMP_DIR" in src_conf)


class _FakeMP:
    """Shim mínimo del fixture monkeypatch para el modo script directo."""
    def __init__(self):
        self._undo = []

    def setattr(self, obj, name, val):
        self._undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, val)


if __name__ == "__main__":  # modo script directo
    _ok = True
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                if _name in ("test_estructura_estandar",
                             "test_retrocompatibilidad_legacy",
                             "test_purge_workspace", "test_sync_artifacts",
                             "test_sync_artifacts_guion_desde_bd"):
                    import tempfile
                    _tmp = Path(tempfile.mkdtemp())
                    _fn(_tmp / "p", _FakeMP())
                elif _name in ("test_get_templates", "test_post_projects_con_template",
                               "test_post_projects_body_gana_sobre_plantilla",
                               "test_template_id_desconocido_400",
                               "test_proyecto_sin_plantilla_tiene_workspace"):
                    _fn(TestClient(main.app))
                else:
                    _fn()
            except Exception as _e:  # noqa: BLE001
                _ok = False
                print(f"✗ {_name}: {_e}")
    print(f"\n{'OK' if _ok else 'FALLOS'} — {OK} checks · {FAIL} fallos")
    sys.exit(0 if _ok else 1)
