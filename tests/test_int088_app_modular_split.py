#!/usr/bin/env python3
"""
INT-088 · Refactor modular de app.js (SPA sin build, CERO cambio de comportamiento).

El monolito backend/static/app.js (~4300 líneas, v2.42.0) se divide en 5
módulos cohesivos que app.js —convertido en loader— inyecta dinámicamente
y en orden desde index.html:

    app-core.js  → estado S, api(), toast(), nav(), ajustes, agente, arranque
    app-projects.js → proyectos, crear/eliminar, job status, fábrica, publicar
    app-mcp.js   → panel MCP, SSO Google, Flow, NotebookLM, pipeline
    app-wizard.js → asistente Crear + selector de plantillas (INT-087)
    app-player.js → clipper, reproducción inline, hoja de contacto

Contratos congelados de esta batería:
  · index.html sigue cargando SOLO app.js?v=__APP_VERSION__ (token INT-082).
  · app.js es un loader: inyecta los 5 módulos propagando la versión para el
    cache-busting y llama a window.__appBoot() al terminar (definido en
    app-core.js, que espera __authReady igual que el boot del monolito).
  · Los 6 ficheros pasan node --check cuando node está disponible.
  · Nada se perdió ni se duplicó: las 189 funciones top-level del monolito
    siguen definidas exactamente una vez entre los 5 módulos.
  · Cada módulo expone sus funciones estrella (cohesión verificable).

Dual-mode: pytest y script directo.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
STATIC = BACKEND / "static"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402

OK, FAIL = 0, 0
LOADER = "app.js"
MODULES = ("app-core.js", "app-projects.js", "app-mcp.js", "app-wizard.js", "app-player.js")
# P1-2: Conteo real = 188 funciones top-level verificadas entre los 5 módulos sin duplicados.
# U2 (2026-11-07): 189 → 188 — salen gsessDisconnectedHTML/gsessWaitingHTML/
# gsessConnectedHTML (los 3 estados pintados a mano del Hub, sustituidos por el
# semáforo REAL de U1); entra ecoRowHTML + gsessConnectAll (Conectar todo).
# U3 (2026-11-07): 188 → 189 — entra avisoHumanoDe (línea humana de avisos
# conocidos de la consola, p. ej. FastMCP; el volcado crudo queda en Avanzado).
# U4 (2026-11-07): 189 → 192 — entran ecoNichoNidHTML (selector nicho+cuaderno
# en la tarjeta principal), mcpNichosCargar y mcpNichoChange (memoria por
# nicho en el registro Q4); sale el bloque nblm de mcpSvcHTML.
# U5 (2026-11-07): 192 → 193 — entra pipeGateApply (Run Full Pipeline
# deshabilitado con motivo exacto mientras U1 diga listo_para_pipeline=false).
N_FUNCS_REAL = 193

# funciones estrella por módulo (cohesión; suficientes para cazar desvíos)
STAR = {
    "app-core.js": (
        "const S = {", "async function api(", "function toast(", "function nav(",
        "function setTheme(", "function renderHome(", "function closeOverlay(",
        "function updatePills(", "async function renderSettings(",
        "function renderAgent(", "window.__appBoot = async function boot() {",
    ),
    "app-projects.js": (
        "function renderProjectCards(", "function renderProjects(",
        "async function createNichoVideo(", "function showProgress(",
        "async function startJob(", "async function preflightCrear(",
        "function renderFactory(", "function renderPublish(",
        "async function delProject(", "function renderHookCards(",
        "let PUB_PID = null;", "let _PROJ_NICHO = null;",
    ),
    "app-mcp.js": (
        "function renderMCP(", "function mcpGsessHTML(", "async function gsessRefresh(",
        "async function mcpConnect(", "async function mcpDisconnect(",
        "async function mcpListNotebooks(", "async function pipeRun(",
        "const PIPE_STAGES = {", "const G_LOGO_SVG =",
        "(async () => { try { await mcpRefresh(true); } catch {} })();",
    ),
    "app-wizard.js": (
        "const QC_STATE = {", "function openQuickCreateModal(",
        "function renderQuickCreateModal(", "async function executeQuickCreate(",
        "async function openBrandProfilesModal(", "async function qcPickDestino(",
        "async function renderAvatars(", "async function openVoiceGallery(",
        "async function openSubtitleSwitcher(", "async function generateQCHooks(",
    ),
    "app-player.js": (
        "let CLIPPER_STATE = {", "function renderClipper(",
        "async function clipperRunAnalysis(", "function playAudio(",
        "function initDrag(", "function showVideoModal(",
        "async function animateAvatarLivePortrait(", "async function lipsyncAvatarMuseTalk(",
        "window.clipperAdjustStart =", "window.clipperAdjustEnd =",
    ),
}


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


# ── 1 · el loader y su cadena de carga dinámica ─────────────────────────
def test_loader_contrato():
    js = _read(LOADER)
    index = _read("index.html")
    check("index.html sigue cargando solo app.js con el token INT-082",
          'src="static/app.js?v=__APP_VERSION__"' in index)
    check("index.html NO carga los módulos directamente",
          all(f'static/{m}' not in index for m in MODULES))
    check("el loader inyecta <script> dinámicamente (createElement)",
          "createElement('script')" in js and "appendChild" in js)
    for m in MODULES:
        check(f"el loader declara {m} en su lista de carga", f"'{m}'" in js)
    check("orden de carga core→projects→mcp→wizard→player",
          js.index("'app-core.js'") < js.index("'app-projects.js'")
          < js.index("'app-mcp.js'") < js.index("'app-wizard.js'")
          < js.index("'app-player.js'"))
    check("propaga la versión para el cache-busting (cascada INT-082)",
          "document.currentScript" in js and "?v=" in js)
    check("invoca __appBoot cuando terminan los módulos",
          "window.__appBoot" in js)
    check("el loader ya no es el monolito (api/toast/renderHome fuera)",
          "async function api(" not in js and "function toast(" not in js
          and "function renderHome(" not in js)


# ── 2 · módulos presentes, estrictos y con sintaxis válida ──────────────
def test_modulos_existentes_y_sintaxis():
    for m in MODULES:
        p = STATIC / m
        check(f"{m} existe y tiene contenido", p.is_file() and p.stat().st_size > 1000)
        txt = _read(m)
        check(f"{m} en modo estricto ('use strict')", "'use strict';" in txt[:600])
    node = shutil.which("node")
    if not node:
        check("node no disponible — se omite node --check", True)
        return
    bad = []
    for f in (LOADER,) + MODULES:
        r = subprocess.run([node, "--check", str(STATIC / f)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            bad.append(f"{f}: {r.stderr[:120]}")
    check("loader + 5 módulos: sintaxis JS válida (node --check)", not bad,
          "; ".join(bad))


# ── 3 · nada se perdió ni se duplicó en el split ─────────────────────────
def test_nada_se_perdio_ni_duplico():
    owner: dict[str, str] = {}
    dups: list[str] = []
    total = 0
    for m in MODULES:
        txt = _read(m)
        for n in re.findall(r"^(?:async )?function ([A-Za-z_$][\w$]*)", txt, re.M):
            total += 1
            if n in owner:
                dups.append(f"{n} en {owner[n]} y {m}")
            else:
                owner[n] = m
    check("sin colisiones de nombre entre módulos", not dups, "; ".join(dups[:5]))
    check(f"conteo de funciones top-level íntegro (esperadas {N_FUNCS_REAL})",
          total == N_FUNCS_REAL, f"encontradas {total}")
    check("suelo mínimo de funciones preservado", total >= 180, f"encontradas {total}")
    alljs = "\n".join(_read(f) for f in (LOADER,) + MODULES)
    for w in ("window.openQuickCreateModal", "window.startDirectCreation",
              "window.qcSwitchMode", "window.executeQuickCreate",
              "window.qcPickDestino", "window.clipperAdjustStart",
              "window.clipperAdjustEnd"):
        check(f"{w} sobrevive al split", f"{w} =" in alljs)


# ── 4 · cohesión: cada módulo expone lo suyo ─────────────────────────────
def test_cohesion_por_modulo():
    for m, syms in STAR.items():
        txt = _read(m)
        for s in syms:
            check(f"{m} define {s.split('(')[0].split(' =')[0].replace('window.', '')}",
                  s in txt)


# ── 5 · el boot conserva su semántica exacta ─────────────────────────────
def test_boot_orden_y_auth():
    core = _read("app-core.js")
    check("boot espera __authReady (login con clave maestra, igual que el monolito)",
          "await (window.__authReady || Promise.resolve());" in core)
    check("boot registra el tema y la navegación",
          "setTheme(S.theme);" in core and "$$('.nav-item').forEach" in core)
    check("boot pinta home y programa refrescos (INT-092: sin carga de plantillas)",
          "renderHome();" in core and "setInterval" in core
          and "loadTemplates();" not in core)
    check("boot ya NO se auto-ejecuta como IIFE (lo llama el loader)",
          "(async function boot() {" not in core)


# ── 6 · contrato de versión (cadena INT-080) ─────────────────────────────
def test_version():
    check("APP_VERSION 2.47.0 (INT-080: bump por cambio funcional — U1 resumen)",
          config.APP_VERSION == "2.47.0")


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
