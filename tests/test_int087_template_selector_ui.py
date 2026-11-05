#!/usr/bin/env python3
"""
INT-087 · Plantillas de nicho: API + flujo de creación (la UI se purgó en INT-092).

Historia:
  · INT-087 añadió el selector de plantillas al wizard y al modal rápido.
  · INT-092 lo PURGÓ de la UI: las tarjetas genéricas estorbaban la pantalla
    y la creación vive SOLO en Inicio (modal rápido 1-clic sin plantillas).

Cubre:
  A. Purga honesta de la UI — en los statics NO queda el selector
     (tpl-card, renderTplCards, pickTemplate, loadTemplates, QC_STATE.tpl)
     y el boot no precarga el catálogo.
  B. Contratos — catálogo con pacing canónico (fast/normal/slow, el lexicon
     de resolve_scene_count) + etiqueta humana «ritmo»; cache-busting
     app.js?v=__APP_VERSION__.
  C. API REAL con TestClient — GET /api/templates sigue vivo (backend) y
     POST /api/projects acepta template_id+niche exactamente igual que
     antes: purgar la UI NO cambió el contrato del backend.

Método: contratos de fuente congelados (app-wizard.js/app-core.js — INT-088
dividió app.js en módulos), API REAL con TestClient y validación de sintaxis
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


# ── A. purga del selector en la UI (INT-092) — el backend NO se toca ─────
def test_selector_ui_purgada():
    """INT-092: las tarjetas de plantillas genéricas estorbaban la pantalla.
    El wizard de 4 pasos y el selector murieron; el modal rápido NO trae
    plantillas. El catálogo API sigue vivo para el backend/integraciones."""
    js = "\n".join((BACKEND / "static" / f).read_text(encoding="utf-8")
                   for f in ("app-wizard.js", "app-projects.js", "app-core.js"))
    for simbolo in ("renderTplCards", "pickTemplate", "tplCardHTML",
                    "loadTemplates", "TPLS_LOADED", "QC_STATE.tpl",
                    "body.template_id = QC_STATE.tpl"):
        check(f"sin rastro del selector: {simbolo}", simbolo not in js)
    check("sin tarjetas tpl-card en la UI", "tpl-card" not in js
          and "data-tpl=" not in js)
    core_js = (BACKEND / "static" / "app-core.js").read_text(encoding="utf-8")
    check("boot ya no precarga el catálogo", "loadTemplates();" not in core_js)
    # el modal rápido sigue siendo la única puerta de creación en Inicio
    check("las 5 modalidades de Inicio abren el modal rápido",
          js.count("openQuickCreateModal('") >= 5)
    check("el modal rápido mantiene destino INT-091 y la voz INT-092",
          "qcPickDestino" in js and "QC_STATE.voice" in js)


def test_app_js_sintaxis_node():
    """node --check sobre app.js (loader) y los 5 módulos (INT-088): si node
    existe, ningún trozo de la SPA puede quedar con sintaxis rota."""
    node = shutil.which("node")
    if not node:
        check("node no disponible — se omite la validación de sintaxis", True)
        return
    bad = []
    for f in ("app.js", "app-core.js", "app-projects.js", "app-mcp.js",
              "app-wizard.js", "app-player.js"):
        r = subprocess.run([node, "--check", str(BACKEND / "static" / f)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            bad.append(f"{f}: {r.stderr[:120]}")
    check("app.js + 5 módulos: sintaxis válida (node --check)", not bad,
          "; ".join(bad))


# ── B. API real: catálogo y creación (contratos backend intactos) ────────
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
    lexicon de resolve_scene_count) y trae etiqueta humana «ritmo»."""
    from services import niche_templates as ntpl
    for t in ntpl.list_templates():
        check(f"{t['id']}: pacing canónico",
              t.get("pacing") in CANON_PACING, str(t.get("pacing")))
        check(f"{t['id']}: etiqueta ritmo para la tarjeta",
              bool(t.get("ritmo")))


def test_flujo_ui_crea_proyecto_con_plantilla(client):
    """El payload EXACTO que la UI enviaba al clicar una tarjeta sigue
    siendo válido: template_id + niche de la marca heredados (contrato
    backend intacto tras la purga UI de INT-092)."""
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
    versión el navegador descarga la UI nueva sin cachestale."""
    res = client.get("/")
    check("GET / → 200", res.status_code == 200)
    html = res.text
    check("cache-busting por versión activo",
          f'app.js?v={config.APP_VERSION}' in html,
          f'app.js?v={config.APP_VERSION}')


# ── C. contrato de versión (cadena INT-080) ──────────────────────────────
def test_version():
    check("APP_VERSION 2.46.0 (INT-080: bump por cambio funcional)",
          config.APP_VERSION == "2.46.0")


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
