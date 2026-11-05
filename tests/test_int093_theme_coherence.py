#!/usr/bin/env python3
"""
INT-093 · Coherencia de color entre temas — nada de pantallas blancas en
modo oscuro ni negras en modo claro (petición expresa del usuario).

El síntoma: elementos diseñados solo para el tema oscuro (texto claro
saturado, blancos translúcidos) seguían pintándose en modo claro y
viceversa → pantallas mezcladas ilegibles.

Cubre:
  A. Tokens de estado con override en el tema CLARO — --ok/--warn/--err/
     --gold/--accent2 existen en :root (oscuro) Y en [data-theme=light]
     con valores legibles sobre blanco (enlaces, badges, chips de estado).
  B. Overlays SIEMPRE oscuros fijos — .vc-st.ok/.gold/.err/.work viven
     sobre la miniatura de video (rgba(8,10,20,.74)) en ambos temas, así
     que usan color LITERAL y no les afecta el override claro.
  C. Literales ilegibles purgados — .clipper-advice-box ya no pinta
     #a7f3d0 (menta claro invisible sobre blanco) ni .doc-warn #ffd479;
     ambos usan tokens de tema.
  D. Hover coherentes — .clipper-tag-pill:hover usa fondo SÓLIDO
     var(--accent) (el blanco sobre translúcido era ilegible en claro) y
     .clipper-trim-btn:hover respeta la convención de la app (texto
     blanco sobre acento, no #000).
  E. Chips inline de app-projects.js con tokens — Contradicción/Dato
     Chocante usan var(--warn)/var(--err) con fallback, los chips de
     retención var(--ok,#10b981); nada de hex de estado pelado.
  F. Chips dorados de estado a token — .pipe-chip.dispatched y
     .vg-card.active-preview usan var(--gold,#e6b800).
  G. Sintaxis — node --check de app-projects.js y style.css sin restos
     de los literales purgados.

Dual-mode: pytest y script directo.
"""
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
STATIC = BACKEND / "static"

OK, FAIL = 0, 0


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


def _light_block(css: str) -> str:
    """Devuelve el bloque [data-theme='light'] completo."""
    i = css.find('[data-theme="light"]')
    assert i != -1, "no existe [data-theme='light']"
    j = css.find("}", i)
    depth = 1
    k = j + 1
    while k < len(css) and depth:
        if css[k] == "{":
            depth += 1
        elif css[k] == "}":
            depth -= 1
        k += 1
    return css[i:k]


# ── A · tokens de estado con override claro ──────────────────────────────
def test_tokens_estado_en_ambos_temas():
    css = _read("style.css")
    light = _light_block(css)
    for tok in ("--ok:", "--warn:", "--err:", "--gold:", "--accent2:"):
        check(f"tema claro define {tok.rstrip(':')}", tok in light)
    # y siguen existiendo en :root (oscuro)
    root = css[: css.find('[data-theme="light"]')]
    for tok in ("--ok:", "--warn:", "--err:", "--gold:", "--accent2:"):
        check(f"tema oscuro define {tok.rstrip(':')}", tok in root)
    # valores claros legibles (más oscuros que los de :root)
    check("--accent2 claro ≈ #00897b (enlaces legibles sobre blanco)",
          "#00897b" in light)


# ── B · overlays siempre-oscuros con color literal ───────────────────────
def test_overlays_siempre_oscuros_fijos():
    css = _read("style.css")
    for cls, literal in ((".vc-st.ok", "#2bd976"), (".vc-st.gold", "#ffd400"),
                         (".vc-st.err", "#ff5470"), (".vc-st.work", "#00e0c6")):
        idx = css.find(cls + " {")
        check(f"{cls} existe", idx != -1)
        regla = css[idx: css.find("}", idx)]
        check(f"{cls} usa literal {literal} (overlay siempre oscuro)",
              f"color: {literal}" in regla, regla[:90])
        check(f"{cls} ya no depende de var() de tema",
              "var(--ok" not in regla and "var(--gold" not in regla
              and "var(--err" not in regla and "var(--accent2" not in regla,
              regla[:90])


# ── C · literales ilegibles purgados ─────────────────────────────────────
def test_legibles_purgados():
    css = _read("style.css")
    check(".clipper-advice-box usa var(--ok) (antes #a7f3d0 invisible en claro)",
          "color: var(--ok)" in css.split(".clipper-advice-box")[1][:200])
    check("#a7f3d0 solo sobrevive en comentarios (nunca en declaraciones)",
          "color: #a7f3d0" not in css and "color:#a7f3d0" not in css)
    dw = css.split(".doc-warn")[1][:120]
    check(".doc-warn usa var(--warn) (antes #ffd479 invisible en claro)",
          "var(--warn)" in dw, dw)
    check(".doc-warn ya no pinta #ffd479", "color: #ffd479" not in dw)


# ── D · hovers coherentes ────────────────────────────────────────────────
def test_hovers_coherentes():
    css = _read("style.css")
    pill = css.split(".clipper-tag-pill:hover")[1][:160]
    check(".clipper-tag-pill:hover con fondo SÓLIDO var(--accent)",
          "var(--accent)" in pill, pill)
    trim = css.split(".clipper-trim-btn:hover")[1][:160]
    check(".clipper-trim-btn:hover texto blanco (convención de la app)",
          "color: #fff" in trim and "color: #000" not in trim, trim)


# ── E · chips inline de app-projects.js con tokens ───────────────────────
def test_chips_inline_app_projects():
    js = _read("app-projects.js")
    check("Contradicción usa var(--warn,#fb923c)", "var(--warn,#fb923c)" in js)
    check("Dato Chocante usa var(--err,#f87171)", "var(--err,#f87171)" in js)
    check("sin hex de estado pelado en badges de hooks",
          "color:#fb923c" not in js and "color:#f87171" not in js)
    check("chips de retención usan var(--ok,#10b981)",
          js.count("var(--ok,#10b981)") >= 2)


# ── F · dorados de estado a token ────────────────────────────────────────
def test_dorados_a_token():
    css = _read("style.css")
    check(".pipe-chip.dispatched usa var(--gold,#e6b800)",
          "var(--gold, #e6b800)" in css.split(".pipe-chip.dispatched")[1][:160])
    check(".vg-card.active-preview usa var(--gold,#e6b800)",
          "var(--gold, #e6b800)" in css.split(".vg-card.active-preview")[1][:160])
    check("#e6b800 solo como fallback de var(--gold) (nunca pelado)",
          css.count("#e6b800") == css.count("var(--gold, #e6b800)"))


# ── G · sintaxis y limpieza ──────────────────────────────────────────────
def test_sintaxis_y_limpieza():
    node = shutil.which("node")
    if node:
        r = subprocess.run([node, "--check", str(STATIC / "app-projects.js")],
                           capture_output=True, text=True)
        check("app-projects.js: sintaxis válida (node --check)",
              r.returncode == 0, r.stderr[:120])
    js = _read("app-projects.js")
    check("sin comentarios de INT rotos (ediciones atómicas)",
          js.count("/* INT-093") == 2)


if __name__ == "__main__":  # modo script directo
    _ok = True
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
            except Exception as _e:  # noqa: BLE001
                _ok = False
                print(f"✗ {_name}: {_e}")
    print(f"\n{'OK' if _ok else 'FALLOS'} — {OK} checks · {FAIL} fallos")
    sys.exit(0 if _ok else 1)
