#!/usr/bin/env python3
"""
INT-079 · El botón «＋ Nuevo video» (y TODO el asistente Crear) no hacía nada.

Causa raíz verificada en vivo (navegador headless + stack trace):
    ReferenceError: renderWizardBrandProfileBar is not defined
        at renderCreate (app.js:695)
        at nav (app.js:68)
INT-042 añadió la llamada `${renderWizardBrandProfileBar()}` dentro de
renderCreate() pero la definición NUNCA existió en git (git log -S = 1 commit).
El botón «🏢 Administrar Canales y Marcas» de Ajustes tenía la misma herida
(openBrandProfilesModal sin definir).

INT-092 · estado actual de los contratos:
  · El wizard de 4 pasos y su barra de Brand Profile se PURGARON — la
    creación vive SOLO en el modal rápido de Inicio (sin perfil de marca).
  · openBrandProfilesModal sigue viva (botón 🏢 de Ajustes).
  · Los escáneres anti-función-fantasma (handlers inline + interpolaciones
    ${...}) siguen siendo la garantía estructural: si alguien vuelve a
    invocar una función inexistente, la suite rompe aquí y no en producción.
"""
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
STATIC = BACKEND / "static"
sys.path.insert(0, str(BACKEND))  # INT-082: el contrato de versión lee config.APP_VERSION

import config  # noqa: E402
# INT-088: app.js es ahora un loader; el código vive en 5 módulos. Los
# contratos «definida en el frontend» se leen sobre la concatenación de todos.
FRONTEND_FILES = ("app.js", "app-core.js", "app-projects.js", "app-mcp.js",
                  "app-wizard.js", "app-player.js")
APP_JS = "\n".join((STATIC / f).read_text(encoding="utf-8") for f in FRONTEND_FILES)
AUTH_JS = (STATIC / "auth.js").read_text(encoding="utf-8")
INDEX_HTML = (STATIC / "index.html").read_text(encoding="utf-8")

# ── definiciones y whitelists del escáner anti-fantasma ─────────────────────
DEFINED = set()
for _src in (APP_JS, AUTH_JS):
    DEFINED |= set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", _src))
    DEFINED |= set(re.findall(
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\()", _src))
    DEFINED |= set(re.findall(
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?[A-Za-z_$][\w$]*\s*=>", _src))
    DEFINED |= set(re.findall(r"\bwindow\.([A-Za-z_$][\w$]*)\s*=", _src))

BUILTIN = {
    "document", "window", "event", "Math", "String", "Number", "Boolean", "Array",
    "Object", "JSON", "Date", "RegExp", "parseInt", "parseFloat", "isNaN",
    "encodeURIComponent", "decodeURIComponent", "setTimeout", "setInterval",
    "clearTimeout", "clearInterval", "fetch", "URL", "Blob", "FileReader",
    "localStorage", "sessionStorage", "alert", "confirm", "prompt", "history",
    "navigator", "location", "this", "console", "Promise", "FormData", "Set",
    "Map", "WeakMap", "WeakSet", "Intl", "AbortController", "CustomEvent",
    "Event", "Audio", "Image", "requestAnimationFrame", "getComputedStyle",
    "matchMedia", "open", "close", "scrollTo", "structuredClone", "crypto",
}
KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function", "typeof",
            "new", "delete", "void", "in", "of", "else", "do", "try", "await", "async"}
# prosa española «palabra (paréntesis)» dentro de template literals → no es código
NOISE_INTERP = {"abajo"}

_CALL_RE = re.compile(r"(?<![\w$.?])([A-Za-z_$][\w$]*)\s*\(")  # excluye .método( y ?.método(


def _scan_calls(text: str) -> set:
    out = set()
    for m in _CALL_RE.finditer(text):
        if re.search(r"\bnew\s+$", text[max(0, m.start() - 4):m.start() + 1]):
            continue  # new Fn( → constructor
        out.add(m.group(1))
    return out


def _strip_strings(s: str) -> str:
    return re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "''", s)


# ── 1 · handlers inline on*="..." (scope global: ReferenceError real) ───────
def _handler_phantoms() -> set:
    calls = set()
    for src in (APP_JS, INDEX_HTML):
        for m in re.finditer(r"\bon[a-z]+\s*=\s*\"([^\"]+)\"", src):
            calls |= _scan_calls(m.group(1))
    return {n for n in calls
            if n not in DEFINED and n not in BUILTIN and n not in KEYWORDS}


# ── 2 · interpolaciones ${...} (scope de render: fantasma = nunca definida) ─
def _interp_phantoms() -> set:
    calls = set()
    for m in re.finditer(r"\$\{([^{}]*)\}", APP_JS):
        calls |= _scan_calls(_strip_strings(m.group(1)))
    return {n for n in calls
            if n not in DEFINED and n not in BUILTIN and n not in KEYWORDS
            and n not in NOISE_INTERP}


def test_no_phantom_functions_in_inline_handlers():
    """Cualquier on*="fn()" que referencie una función inexistente rompe aquí.
    (Habría cazado openBrandProfilesModal antes de INT-079.)"""
    phantoms = _handler_phantoms()
    assert not phantoms, f"Funciones fantasma en handlers inline: {sorted(phantoms)}"


def test_no_phantom_functions_in_interpolations():
    """Cualquier ${fn()} sin definición en el fichero rompe aquí.
    (Habría cazado renderWizardBrandProfileBar antes de INT-079.)"""
    phantoms = _interp_phantoms()
    assert not phantoms, f"Funciones fantasma en interpolaciones: {sorted(phantoms)}"


def test_wizard_bar_purgada_y_admin_de_ajustes_vivo():
    """INT-092: la barra de Brand Profile del wizard se purgó junto al
    asistente. Lo que SÍ sobrevive: openBrandProfilesModal (botón 🏢 de
    Ajustes) con su admin completo."""
    assert not re.search(r"\bfunction\s+renderWizardBrandProfileBar\s*\(", APP_JS), \
        "la barra del wizard debe estar purgada (INT-092)"
    assert "renderWizardBrandProfileBar" not in APP_JS
    m2 = re.search(r"\basync\s+function\s+openBrandProfilesModal\s*\(", APP_JS)
    assert m2, "openBrandProfilesModal debe estar definida (botón de Ajustes)"
    assert 'onclick="openBrandProfilesModal' in APP_JS


def test_la_barra_no_puede_matar_nada_porque_no_existe():
    """La lección INT-079, versión INT-092: no hay barra que pueda lanzar
    una ReferenceError — ni en la fuente ni en handlers ni en interpolaciones
    (los escáneres anti-fantasma de arriba son la garantía continua)."""
    assert "applyBrandToWizard" not in APP_JS
    for src_name in FRONTEND_FILES:
        src = (STATIC / src_name).read_text(encoding="utf-8")
        assert "renderWizardBrandProfileBar" not in src, src_name
    # la única puerta de creación es el modal rápido, sin barra
    wiz = (STATIC / "app-wizard.js").read_text(encoding="utf-8")
    assert "function renderQuickCreateModal()" in wiz
    assert "renderWizardBrandProfileBar" not in wiz


def test_brand_profiles_state_initialized_and_loaded_nonfatally():
    s_start = APP_JS.index("const S = {")
    s_block = APP_JS[s_start:APP_JS.index("};", s_start)]
    assert re.search(r"brandProfiles\s*:\s*\[\]", s_block), \
        "S debe inicializar brandProfiles: []"
    m = re.search(
        r"try\s*\{\s*S\.brandProfiles\s*=\s*\(await\s+api\('/brand-profiles'\)\)\.profiles\s*\|\|\s*\[\];\s*\}"
        r"\s*catch\s*\{", APP_JS)
    assert m, "refreshAll debe cargar /brand-profiles dentro de try/catch no-fatal"


def test_brand_admin_guarda_sin_wizard():
    """El autofill del wizard (applyBrandToWizard) se purgó con él; el admin
    de Ajustes guarda/borra perfiles vía su API propia sin tocar el wizard
    (que ya no existe)."""
    assert "applyBrandToWizard" not in APP_JS
    start = APP_JS.index("async function saveBrandProfile")
    body = APP_JS[start:APP_JS.index("\nasync ", start + 10)]
    assert "api('/brand-profiles'" in body
    assert "renderCreate" not in body and "W." not in body


def test_cache_bust_version_bumped():
    """El fix solo llega a los usuarios si la URL de app.js cambia (?v=).
    INT-082: la versión ya NO se mantiene a mano en index.html — la tag usa
    el token __APP_VERSION__ que el servidor sustituye por la ÚNICA constante
    config.APP_VERSION (garantía POR CONSTRUCCIÓN: cada release cambia las 3
    URLs de assets a la vez; adiós a los paneles con JS nuevo + CSS viejo).
    Aquí se congela el token y que la constante viva siga siendo >= 2.36.0."""
    m = re.search(r"app\.js\?v=([\w.]+)", INDEX_HTML)
    assert m, "index.html debe referenciar app.js?v="
    assert m.group(1) == "__APP_VERSION__", (
        "INT-082: la versión de assets sale del token único __APP_VERSION__ "
        "(sustituido en servidor por config.APP_VERSION); no escribir a mano")
    version = tuple(int(x) for x in config.APP_VERSION.split("."))
    assert version >= (2, 36, 0), \
        f"APP_VERSION={config.APP_VERSION} — sube la constante única (>=2.36.0) para invalidar la caché del navegador"


if __name__ == "__main__":
    test_no_phantom_functions_in_inline_handlers()
    print("[OK] test_no_phantom_functions_in_inline_handlers")
    test_no_phantom_functions_in_interpolations()
    print("[OK] test_no_phantom_functions_in_interpolations")
    test_wizard_bar_purgada_y_admin_de_ajustes_vivo()
    print("[OK] test_wizard_bar_purgada_y_admin_de_ajustes_vivo")
    test_la_barra_no_puede_matar_nada_porque_no_existe()
    print("[OK] test_la_barra_no_puede_matar_nada_porque_no_existe")
    test_brand_profiles_state_initialized_and_loaded_nonfatally()
    print("[OK] test_brand_profiles_state_initialized_and_loaded_nonfatally")
    test_brand_admin_guarda_sin_wizard()
    print("[OK] test_brand_admin_guarda_sin_wizard")
    test_cache_bust_version_bumped()
    print("[OK] test_cache_bust_version_bumped")
    print("\nTODOS LOS TESTS INT-079 PASARON (7/7).")
