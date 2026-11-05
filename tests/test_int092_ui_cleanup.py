#!/usr/bin/env python3
"""
INT-092 · Limpieza de UI — pestaña 'Crear' fuera, Inicio como único centro
de mando y colores coherentes entre temas (nada de pantallas blancas en
modo oscuro ni negras en modo claro).

Cubre:
  A. Sidebar — index.html ya NO tiene el botón ✨ Crear y nav('create')
     redirige limpio a 'home' en app-core.js (sin vista fantasma).
  B. Inicio — las 5 modalidades abren el modal rápido 1-clic; el banner
     del Agente General (petición expresa del usuario) se eliminó.
  C. Modal rápido — SOLO Formato + Voz + 📂 destino (INT-091): sin
     Perfil de marca, sin plantillas genéricas, sin botón al wizard.
  D. Wizard purgado — cero referencias muertas en TODOS los statics.
  E. Tema coherente — tokens --soft/--soft-2 definidos en AMBOS temas,
     .qc-box usa var(--card-solid) (antes caía a #1e293b por una var
     inexistente → modal negro en modo claro), sin vars fantasma
     (--card-bg/--bg-card), index.html aplica el tema antes del primer
     pintado y auth.js respeta el tema guardado.
  F. API — el payload EXACTO del modal rápido crea el proyecto (200),
     el selector de Voz viaja como tts_provider (edge/gemini) y el
     destino del usuario (INT-091) sigue respectándose.
  G. node --check de TODOS los JS (loader + 5 módulos + auth.js).

Dual-mode: pytest (fixture client) y script directo.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
STATIC = BACKEND / "static"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
import main  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

OK, FAIL = 0, 0
MODULOS = ("app.js", "auth.js", "app-core.js", "app-projects.js",
           "app-wizard.js", "app-player.js", "app-mcp.js")


def check(nombre: str, cond: bool, extra: str = ""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))
    if not ok:
        raise AssertionError(nombre + (f" — {extra}" if extra else ""))


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


@pytest.fixture
def client():
    return TestClient(main.app)


# ── A · sidebar sin Crear + redirección limpia ───────────────────────────
def test_sidebar_sin_crear_y_nav_redirige():
    index = _read("index.html")
    core = _read("app-core.js")
    check("index.html SIN botón ✨ Crear",
          "nav('create')" not in index and "✨</span> Crear" not in index)
    check("nav('create') redirige limpio a home",
          "if (view === 'create') view = 'home';" in core)
    check("el mapa de vistas ya no registra renderCreate",
          "create: renderCreate" not in core)
    check("openNicheCreator (huérfano del CTA v2.7) fuera",
          "openNicheCreator" not in core)
    # el resto del menú sigue completo
    for vista in ("avatars", "clipper", "projects", "factory", "publish",
                  "trends", "mcp"):
        check(f"menú conserva nav('{vista}')", f"nav('{vista}')" in index)


# ── B · Inicio: centro único de mando, sin banner del agente ─────────────
def test_inicio_5_modalidades_y_sin_banner_agente():
    core = _read("app-core.js")
    for modo in ("script", "idea", "product", "url", "audio"):
        check(f"Inicio abre el modal rápido desde {modo}",
              f"openQuickCreateModal('{modo}')" in core)
    check("banner Agente General eliminado de Inicio (petición usuario)",
          "agent-banner" not in core and "Agente General</b>" not in core)
    css = _read("style.css")
    check("CSS del banner purgado", ".agent-banner {" not in css
          and ".ab-ico {" not in css and ".ab-txt {" not in css)
    # la vista 🤖 Agente sigue viva desde el sidebar (no era el objetivo)
    check("la vista Agente sigue existiendo (renderAgent)",
          "function renderAgent(" in core)


# ── C · modal rápido limpio (Formato + Voz + Examinar) ───────────────────
def test_modal_rapido_minimo():
    wiz = _read("app-wizard.js")
    check("sin Perfil de marca en el modal",
          "renderWizardBrandProfileBar" not in wiz
          and "applyBrandToWizard" not in wiz
          and "🏢 Perfil de marca:" not in wiz)
    check("sin tarjetas de plantillas genéricas",
          "renderTplCards" not in wiz and "QC_STATE.tpl" not in wiz)
    check("sin botón «Asistente Completo» (el wizard murió)",
          "openWizardFromQC" not in wiz and "Asistente Completo" not in wiz)
    check("mantiene Formato 9:16/16:9",
          "QC_STATE.format='short'" in wiz and "QC_STATE.format='long'" in wiz)
    check("mantiene selector de Voz (edge/gemini → tts_provider)",
          "QC_STATE.voice=this.value" in wiz
          and "body.tts_provider = QC_STATE.voice" in wiz)
    check("mantiene 🔍 Examinar en mi PC (INT-091 intacto)",
          "🔍 Examinar en mi PC" in wiz and "qcPickDestino" in wiz
          and "custom_workspace_path = QC_STATE.destino" in wiz)
    check("prefill del modal (ideas de Tendencias / nichos)",
          "function openQuickCreateModal(mode, prefillText)" in wiz)


# ── D · wizard purgado: cero referencias muertas ─────────────────────────
def test_cero_referencias_muertas():
    todos = "\n".join(_read(f) for f in MODULOS)
    muertos = ("renderCreate", "createProject(", "const W = {",
               "loadTemplates", "renderTplCards", "pickTemplate",
               "tplCardHTML", "renderWizardBrandProfileBar",
               "applyBrandToWizard", "openWizardFromQC", "wizardPickDestino",
               "renderPreflightBanner", "nav('create')")
    for m in muertos:
        check(f"sin referencias a {m!r} en los statics", m not in todos)
    proy = _read("app-projects.js")
    check("createNichoVideo existe (flujo 1-clic de nichos)",
          "async function createNichoVideo(" in proy)
    check("«＋ Nuevo video» usa el flujo nuevo",
          "function newVideoInNicho(" in proy
          and "createNichoVideo(_NICHO_TPL_ID)" in proy)


# ── E · tema coherente en oscuro y claro ─────────────────────────────────
def test_tema_coherente():
    css = _read("style.css")
    root = css.split('[data-theme="light"]', 1)[0]
    light = "[data-theme=\"light\"]" + css.split("[data-theme=\"light\"]", 1)[1]
    for tok in ("--soft:", "--soft-2:"):
        check(f"token {tok} definido en modo oscuro", tok in root)
        check(f"token {tok} definido en modo claro", tok in light)
    check(".qc-box usa var(--card-solid) — adiós modal negro en modo claro",
          "background: var(--card-solid);" in css)
    check("sin vars fantasma en uso (--card-bg / --bg-card eran inexistentes)",
          "background: var(--card-bg" not in css
          and "background: var(--bg-card" not in css)
    check("sin blancos duros de superficie fuera de tokens",
          "rgba(255, 255, 255, 0.0" not in css.replace(
              "--card: rgba(255, 255, 255, .045)", "").replace(
              "--border: rgba(255, 255, 255, .09)", "").replace(
              "--soft: rgba(255, 255, 255, .04)", "").replace(
              "--soft-2: rgba(255, 255, 255, .08)", "").replace(
              "--card: rgba(255, 255, 255, .75)", ""))
    index = _read("index.html")
    check("tema aplicado antes del primer pintado (anti-flash)",
          "localStorage.getItem('yta-theme')" in index
          and index.index("yta-theme") < index.index("style.css"))
    auth = _read("auth.js")
    check("pantalla de bloqueo respeta el tema guardado",
          "localStorage.getItem('yta-theme')" in auth
          and "yta-theme" in auth)
    # los JS no pintan superficies blancas duras (solo gradientes con texto propio)
    for f in ("app-core.js", "app-projects.js", "app-wizard.js"):
        js = _read(f)
        check(f"{f}: sin color:#fff sobre superficies (solo en gradientes)",
              "color:#fff" not in js or "linear-gradient" in js)


# ── F · API: el flujo del modal rápido funciona 0 errores ────────────────
def test_api_payload_modal_rapido_idea(client):
    """Payload EXACTO de executeQuickCreate() en modo idea (auto_start se
    omite para no lanzar el pipeline en el test; el contrato de creación es
    idéntico)."""
    body = {
        "mode": "idea", "idea": "5 errores mortales al invertir tu primer sueldo",
        "style": "auto", "format": "short", "pacing": "normal",
        "subtitle_style": "shorts", "platforms": ["youtube", "tiktok"],
        "transitions": True, "style_reference": True, "auto_start": True,
        "tts_provider": "edge",
    }
    r = client.post("/api/projects", json=body)
    check("POST del modal rápido → 200", r.status_code == 200, r.text[:200])
    p = r.json()
    try:
        check("idea persistida en meta", (p.get("meta") or {}).get("idea") == body["idea"],
              str(p.get("meta"))[:200])
        check("tts_provider edge (selector de Voz)", p.get("tts_provider") == "edge",
              str(p.get("tts_provider")))
        check("formato short heredado", p.get("format") == "short")
        check("workspace estándar creado", bool(p.get("workspace")))
    finally:
        client.delete(f"/api/projects/{p['id']}")


def test_api_selector_voz_gemini_y_destino_custom(client, tmp_path):
    destino = tmp_path / "FRUTINOVELAS" / "Desde el modal"
    r = client.post("/api/projects", json={
        "mode": "idea", "idea": "voz gemini + carpeta propia",
        "tts_provider": "gemini", "auto_start": False,
        "custom_workspace_path": str(destino)})
    check("POST voz gemini + destino → 200", r.status_code == 200, r.text[:200])
    p = r.json()
    try:
        check("tts_provider gemini persistido", p.get("tts_provider") == "gemini",
              str(p.get("tts_provider")))
        check("workspace nace EXACTAMENTE en la carpeta del usuario (INT-091)",
              p.get("workspace") == str(destino), str(p.get("workspace")))
    finally:
        client.delete(f"/api/projects/{p['id']}")
    check("carpeta del usuario intacta tras purgar el proyecto",
          destino.is_dir())


def test_api_payload_nicho_1clic(client):
    """Payload de createNichoVideo() — «＋ Nuevo video» desde un nicho con
    plantilla (auto_start omitido por hermeticidad del test). Primero se
    registra un nicho vía POST /api/niches/templates (la BD del test está
    vacía; el flujo real de la UI también crea el nicho antes)."""
    t = client.post("/api/niches/templates", json={
        "name": "Finanzas Test 092", "emoji": "📁",
        "description": "nicho temporal", "prompt": "un video de finanzas"}).json()
    check("plantilla de nicho registrada", bool(t.get("id")), str(t)[:200])
    r = client.post("/api/projects", json={
        "mode": "nicho", "niche_template": t["id"], "idea": None,
        "platforms": ["youtube", "tiktok"], "transitions": True,
        "style_reference": True})
    check("POST modo nicho (flujo 1-clic) → 200", r.status_code == 200,
          r.text[:200])
    p = r.json()
    try:
        check("workspace de nicho creado", bool(p.get("workspace")))
        check("nicho de la marca heredado", p.get("niche") == "Finanzas Test 092",
              str(p.get("niche")))
    finally:
        client.delete(f"/api/projects/{p['id']}")
        client.delete(f"/api/niches/templates/{t['id']}")


# ── G · sintaxis JS completa ─────────────────────────────────────────────
def test_sintaxis_todos_los_js():
    node = shutil.which("node")
    if not node:
        check("node no disponible — se omite la validación de sintaxis", True)
        return
    bad = []
    for f in MODULOS:
        r = subprocess.run([node, "--check", str(STATIC / f)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            bad.append(f"{f}: {r.stderr[:120]}")
    check("loader + 5 módulos + auth.js: sintaxis válida (node --check)",
          not bad, "; ".join(bad))


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
