#!/usr/bin/env python3
"""
INT-087 · Selector de Plantillas de Nicho en la UI (asistente Crear).

Cubre los 3 frentes de la tarea:
  A. app.js — tarjetas de las 5 plantillas (iconos 🍳🧶🛍️⚡🖼️) en el
     wizard de Crear (paso 1) Y en el modal de creación rápida 1-clic,
     alimentadas por GET /api/templates (carga perezosa + best-effort).
     Al hacer clic se AUTOCOMPLETAN nicho, voz, ritmo, subtítulos, estilo
     y el cierre de marca (marca.json) — toggle: 2º clic deselecciona.
  B. Payload — createProject() y quick-create envían template_id (y el
     nicho de la marca) a POST /api/projects, que ya crea el workspace
     modular con marca.json (INT-086).
  C. Contratos — catálogo con pacing canónico (fast/normal/slow, el
     lexicon de resolve_scene_count y de las tarjetas de ritmo de la UI)
     + etiqueta humana «ritmo»; cache-busting app.js?v=__APP_VERSION__.

Método: contratos de fuente congelados (app.js/index.html), API REAL con
TestClient (catálogo + creación con plantilla) y validación de sintaxis
JS vía node --check cuando node está disponible.

Dual-mode: pytest (fixture client) y script directo.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
import main  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

OK, FAIL = 0, 0
ESPERADAS = ("cocina-recetas", "crochet-manualidades", "ugc-producto",
             "viral-short", "miniaturas")
CANON_PACING = {"fast", "normal", "slow"}


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


# ── A. contratos de fuente del selector (app.js) ─────────────────────────
def test_selector_js_fuente():
    js = (BACKEND / "static" / "app.js").read_text(encoding="utf-8")
    check("catálogo cargado desde GET /api/templates",
          "fetch('/api/templates')" in js and "loadTemplates" in js)
    check("carga perezosa + caché local",
          "TPLS_LOADED" in js and "let TPLS = []" in js)
    check("tarjetas con clase tpl-card e icono de la plantilla",
          "tpl-card" in js and "data-tpl=" in js and "t.icono" in js)
    check("selector en el wizard (paso 1) y en el modal rápido",
          "renderTplCards('w')" in js and "renderTplCards('qc')" in js)
    check("clic autocompleta nicho, voz, ritmo, subtítulos y estilo",
          "W.nicheLabel" in js and "W.voice = t.voice" in js
          and "W.pacing = t.pacing" in js and "W.subtitles = t.subtitle_style" in js
          and "W.format = t.format" in js)
    check("modal rápido autocompleta su estado",
          "QC_STATE.tpl" in js and "QC_STATE.pacing = t.pacing" in js
          and "QC_STATE.voice = t.voice" in js)
    check("payload del wizard envía template_id + nicho de marca",
          "body.template_id = W.tpl" in js and "body.niche = W.nicheLabel" in js)
    check("payload del modal rápido envía template_id",
          "body.template_id = QC_STATE.tpl" in js)
    check("toggle: 2º clic deselecciona",
          "=== id) ? '' : id" in js)
    check("cierre de marca visible en la tarjeta seleccionada",
          "cierre.frase" in js)
    check("boot carga el catálogo", "loadTemplates();  // INT-087" in js)


def test_app_js_sintaxis_node():
    """node --check sobre app.js (si node existe): el selector no rompe la SPA."""
    node = shutil.which("node")
    if not node:
        check("node no disponible — se omite la validación de sintaxis", True)
        return
    r = subprocess.run([node, "--check", str(BACKEND / "static" / "app.js")],
                       capture_output=True, text=True)
    check("app.js sintaxis válida (node --check)", r.returncode == 0,
          r.stderr[:200])


# ── B. API real: catálogo y creación desde la UI ─────────────────────────
def test_get_templates_para_ui(client):
    res = client.get("/api/templates")
    check("GET /api/templates → 200", res.status_code == 200)
    ts = res.json()
    ids = {t.get("id") for t in ts}
    check("las 5 plantillas con icono + nombre + descripción",
          set(ESPERADAS) <= ids
          and all(t.get("icono") and t.get("nombre") and t.get("descripcion")
                  for t in ts))


def test_catalogo_pacing_canonico():
    """El pacing de las plantillas usa el canon fast/normal/slow (el mismo
    lexicon de resolve_scene_count y de las tarjetas de ritmo de la UI) y
    trae etiqueta humana «ritmo» para el detalle de la tarjeta."""
    from services import niche_templates as ntpl
    for t in ntpl.list_templates():
        check(f"{t['id']}: pacing canónico",
              t.get("pacing") in CANON_PACING, str(t.get("pacing")))
        check(f"{t['id']}: etiqueta ritmo para la tarjeta",
              bool(t.get("ritmo")))


def test_flujo_ui_crea_proyecto_con_plantilla(client):
    """Simula el payload EXACTO que construye createProject() al hacer clic
    en una tarjeta: template_id + niche de la marca heredados."""
    res = client.post("/api/projects", json={
        "mode": "idea", "idea": "arepas rellenas de queso en 30s",
        "template_id": "cocina-recetas", "niche": "cocina"})
    check("POST con template_id+niche → 200", res.status_code == 200,
          str(res.status_code))
    p = res.json()
    try:
        meta = p.get("meta") or {}
        check("meta.template_id fijado", meta.get("template_id") == "cocina-recetas")
        check("pacing canónico heredado (slow)", meta.get("pacing") == "slow",
              str(meta.get("pacing")))
        check("voice autocompletada (es-CO-SalomeNeural)",
              p.get("voice") == "es-CO-SalomeNeural", str(p.get("voice")))
        check("nicho de la marca en project.niche", p.get("niche") == "cocina",
              str(p.get("niche")))
        ws = Path(p["workspace"])
        marca = json.loads((ws / "marca.json").read_text(encoding="utf-8"))
        check("workspace + marca.json con cierre de canal",
              ws.is_dir() and marca.get("cierre", {}).get("frase"))
    finally:
        client.delete(f"/api/projects/{p['id']}")
    check("limpieza: proyecto y workspace purgados",
          client.get(f"/api/projects/{p['id']}").status_code == 404
          and not Path(p["workspace"]).exists())


def test_dashboard_sirve_app_js_con_cache_busting(client):
    """El HTML raíz referencia app.js?v=<versión> (INT-082): al subir de
    versión el navegador descarga el selector nuevo sin cachestale."""
    res = client.get("/")
    check("GET / → 200", res.status_code == 200)
    html = res.text
    check("cache-busting por versión activo",
          f'app.js?v={config.APP_VERSION}' in html,
          f'app.js?v={config.APP_VERSION}')


# ── C. contrato de versión (cadena INT-080) ──────────────────────────────
def test_version():
    check("APP_VERSION 2.42.0 (INT-080: bump por cambio funcional)",
          config.APP_VERSION == "2.42.0")


if __name__ == "__main__":  # modo script directo
    _ok = True
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn(TestClient(main.app)) if "client" in _fn.__code__.co_varnames else _fn()
            except Exception as _e:  # noqa: BLE001
                _ok = False
                print(f"✗ {_name}: {_e}")
    print(f"\n{'OK' if _ok else 'FALLOS'} — {OK} checks · {FAIL} fallos")
    sys.exit(0 if _ok else 1)
