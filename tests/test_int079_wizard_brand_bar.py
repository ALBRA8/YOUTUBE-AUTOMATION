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
(openBrandProfilesModal sin definir). Toda ruta hacia renderCreate() moría:
✨ Crear, ＋ Nuevo video en nicho, CTA de nichos, wizard rápido.

Estos tests congelan los contratos que fallaron, sobre la FUENTE estática del
frontend (sin navegador): si alguien vuelve a invocar una función inexistente,
la suite rompe aquí y no en producción.
"""
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
STATIC = BACKEND / "static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
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


def test_wizard_bar_defined_and_called_by_rendercreate():
    m = re.search(r"\bfunction\s+renderWizardBrandProfileBar\s*\(", APP_JS)
    assert m, "renderWizardBrandProfileBar debe estar DEFINIDA (INT-042 la llamaba sin definir)"
    assert "${renderWizardBrandProfileBar()}" in APP_JS, \
        "renderCreate debe seguir pintando la barra de Brand Profile"
    m2 = re.search(r"\basync\s+function\s+openBrandProfilesModal\s*\(", APP_JS)
    assert m2, "openBrandProfilesModal debe estar definida (botón de Ajustes)"
    assert 'onclick="openBrandProfilesModal' in APP_JS


def test_wizard_bar_cannot_crash_the_wizard_ever_again():
    """La barra es accesorio: sin perfiles → '' y cualquier error → ''.
    El asistente Crear no puede volver a morir por ella."""
    start = APP_JS.index("function renderWizardBrandProfileBar")
    body = APP_JS[start:start + 2500]
    assert re.search(r"\btry\s*\{", body), "la barra debe encapsular su cuerpo en try"
    assert re.search(r"if\s*\(!profiles\.length\)\s*return\s*''", body), \
        "sin perfiles → '' (wizard clásico intacto)"
    assert re.search(r"catch\s*\(\w+\)\s*\{\s*return\s*''", body), \
        "cualquier excepción → '' (nunca propagar)"


def test_brand_profiles_state_initialized_and_loaded_nonfatally():
    s_start = APP_JS.index("const S = {")
    s_block = APP_JS[s_start:APP_JS.index("};", s_start)]
    assert re.search(r"brandProfiles\s*:\s*\[\]", s_block), \
        "S debe inicializar brandProfiles: []"
    m = re.search(
        r"try\s*\{\s*S\.brandProfiles\s*=\s*\(await\s+api\('/brand-profiles'\)\)\.profiles\s*\|\|\s*\[\];\s*\}"
        r"\s*catch\s*\{", APP_JS)
    assert m, "refreshAll debe cargar /brand-profiles dentro de try/catch no-fatal"


def test_apply_brand_towizard_only_mutates_safe_fields():
    """El autofill 1-clic solo toca claves del wizard (nunca campos ajenos)."""
    start = APP_JS.index("function applyBrandToWizard")
    body = APP_JS[start:APP_JS.index("\n}", start)]
    touched = set(re.findall(r"\bW\.([A-Za-z_$][\w$]*)\s*=", body))
    assert touched <= {"subtitles", "style", "voice"}, \
        f"applyBrandToWizard solo puede mutar subtitles/style/voice; tocó: {touched}"
    assert re.search(r"if\s*\(!p\)\s*return;", body), "perfil inexistente → no-op"


def test_cache_bust_version_bumped():
    """El fix solo llega a los usuarios si la URL de app.js cambia (?v=)."""
    m = re.search(r'app\.js\?v=([\d.]+)', INDEX_HTML)
    assert m, "index.html debe referenciar app.js?v="
    version = tuple(int(x) for x in m.group(1).split("."))
    assert version >= (2, 36, 0), \
        f"app.js?v={m.group(1)} — sube la versión (>=2.36.0) para invalidar la caché del navegador"


if __name__ == "__main__":
    test_no_phantom_functions_in_inline_handlers()
    print("[OK] test_no_phantom_functions_in_inline_handlers")
    test_no_phantom_functions_in_interpolations()
    print("[OK] test_no_phantom_functions_in_interpolations")
    test_wizard_bar_defined_and_called_by_rendercreate()
    print("[OK] test_wizard_bar_defined_and_called_by_rendercreate")
    test_wizard_bar_cannot_crash_the_wizard_ever_again()
    print("[OK] test_wizard_bar_cannot_crash_the_wizard_ever_again")
    test_brand_profiles_state_initialized_and_loaded_nonfatally()
    print("[OK] test_brand_profiles_state_initialized_and_loaded_nonfatally")
    test_apply_brand_towizard_only_mutates_safe_fields()
    print("[OK] test_apply_brand_towizard_only_mutates_safe_fields")
    test_cache_bust_version_bumped()
    print("[OK] test_cache_bust_version_bumped")
    print("\nTODOS LOS TESTS INT-079 PASARON (7/7).")
