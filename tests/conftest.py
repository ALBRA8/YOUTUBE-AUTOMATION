"""tests/conftest.py — infraestructura pytest (FIX-A).

El repo tiene DOS niveles de testing (ver tests/README.md):

  Nivel 1 · Baterías standalone (fuente de verdad histórica): scripts
  autoejecutables que corren TODO el flujo a nivel de módulo y terminan con
  ``sys.exit(...)``. Se ejecutan con ``python3 tests/run_all.py`` (un
  proceso python3 por batería) o directamente. NO son módulos pytest: un
  ``sys.exit`` durante el import mata la recolección (INTERNALERROR).

  Nivel 2 · Tests pytest nativos (funciones ``test_*`` coleccionables).

Este conftest hace tres cosas:

  a) ``collect_ignore``: excluye de pytest las baterías standalone
     documentadas (siguen siendo la fuente de verdad vía run_all.py).
  b) AISLAMIENTO DE SESIÓN: redirige DATA_DIR / OUTPUT_DIR / TMP_DIR /
     DB_PATH (SQLite) / MUSIC_DIR / TEMP_DIR del backend a un directorio
     temporal de sesión. ``pytest`` NUNCA toca ``backend/data`` real.
  c) Fixture autouse ligera: restaura cwd y ``os.environ`` tras cada test.

POR QUÉ ESTE MECANISMO DE AISLAMIENTO (investigación FIX-A):

  * ``backend/config.py`` resuelve las rutas POR VALOR a import-time:
    ``BASE_DIR = Path(__file__).parent`` → ``DATA_DIR = BASE_DIR/"data"``;
    NO soporta env vars para rutas (solo para claves/modelos/límites) y
    además hace ``mkdir`` de data/output/tmp al importar.
  * ``backend/database.py`` hace ``from config import DB_PATH`` (binding
    por valor) y ejecuta ``init_db()`` a import-time (última línea).
  * Los servicios hacen ``from config import DATA_DIR, TMP_DIR`` etc.
    (binding por valor en SU import-time).
  * Varias baterías pytest-compatibles purgan ``sys.modules``
    (config/database/services/pipeline) e inyectan fakes; al purgar y
    re-importar, config.py se re-ejecuta y REAPUNTARÍA al backend/data
    real para todo lo que venga después.

Por eso el parche se aplica en ``pytest_configure`` (que corre ANTES de la
recolección y de cualquier import de test) Y se reinstala tras cada
(re)import de ``config``/``database`` del backend mediante un meta-path
hook. Idempotente: reaplicar es una no-operación.
"""
from __future__ import annotations

import importlib.machinery
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"

# ─────────────────────────────────────────────────────────────────────────
# (a) Baterías standalone excluidas de la recolección pytest
# ─────────────────────────────────────────────────────────────────────────
# Rutas RELATIVAS a tests/. Convención del repo: estas baterías son scripts
# autoejecutables (ejecutan la batería completa a nivel de módulo y cierran
# con sys.exit(...) — con o sin guard __main__, pero SIEMPRE con todo el
# flujo ya ejecutado en el import) y se corren con ``python3
# tests/run_all.py``, que las lanza en subprocess aislados. Bajo pytest un
# ``sys.exit`` a nivel de módulo produce SystemExit durante la recolección
# → INTERNALERROR. La fuente de verdad sigue siendo run_all.py; aquí SOLO
# se excluyen del modo pytest (no se convierten, no se tocan).
STANDALONE_BATTERIES = [
    # ── 16 detectadas en la auditoría (worklog REPO-SYNC-2026-10-27) ──
    "security/test_config_security.py",      # sys.exit tras batería a nivel de módulo
    "security/test_csrf.py",
    "security/test_docs_auth.py",
    "security/test_input_limits.py",
    "security/test_job_identity.py",
    "security/test_project_isolation.py",
    "security/test_project_path_security.py",
    "security/test_ssrf.py",
    "test_burn_subtitles_resilience.py",
    "test_gobernanza.py",
    "test_hands.py",
    "test_hands_chaos.py",
    "test_hands_contract.py",
    "test_hands_operators.py",
    "test_security_hardening.py",
    "test_typography.py",
    # ── adicionales detectadas por FIX-A (patrón distinto, misma naturaleza:
    #    registradas en BATERIAS de run_all.py y rompen la recolección) ──
    "test_int028_general_agent.py",  # sys.exit(resumen()) SIN guard __main__
                                     # a nivel de módulo (65 checks).
    "test_live_boot.py",             # levanta uvicorn REAL vía subprocess bash
                                     # (timeout 300 s por script) a nivel de
                                     # módulo + sys.exit sin guard; el propio
                                     # README la excluye del modo pytest.
    # ── scripts sin NINGÚN test pytest (0 funciones test_*) que envenenan
    #    estado del proceso al IMPORTARSE (colección) ──
    "test_10_escenas.py",            # batería standalone (run_all): parchea
                                     # config a SU tmp a nivel de módulo; bajo
                                     # pytest deja config.DB_PATH/OUTPUT_DIR/
                                     # DATA_DIR/TMP_DIR apuntando a su tmp para
                                     # TODA la suite (fallo cascada en
                                     # golden_fixture/int058/doctors).
    "test_live_execution.py",        # script LIVE de la máquina del usuario
                                     # (REPO_ROOT = D:/PROYECTOS/... hardcodeado,
                                     # 0 funciones test_*): fija
                                     # os.environ["FLOW_MCP_ENABLED"] al importarse.
    "test_live_execution_2.py",      # ídem (env a nivel de módulo).
    "test_live_execution_c2.py",     # ídem (env + config.FLOW_MCP_ENABLED=True
                                     # a nivel de módulo). Vía LIVE correcta:
                                     # python3 tests/test_live_execution*.py.
]
collect_ignore = list(STANDALONE_BATTERIES)

# ─────────────────────────────────────────────────────────────────────────
# (b) Aislamiento de sesión del backend
# ─────────────────────────────────────────────────────────────────────────
_SESSION_TMP: Path | None = None
_FINDER: "_BackendConfigFinder | None" = None


def _is_under(path, parent) -> bool:
    """True si ``path`` es (o está dentro de) ``parent``. Tolerante a str/Path."""
    try:
        p, base = Path(path).resolve(), Path(parent).resolve()
    except (TypeError, ValueError, OSError):
        return False
    return p == base or base in p.parents


def _apply_redirection(session_tmp: Path) -> None:
    """Reaplica la redirección de rutas sobre ``config`` (y ``database``).

    Idempotente; se llama desde pytest_configure y desde el hook de import
    tras cada re-exec de backend/config.py."""
    data_dir = session_tmp / "backend_data"
    for sub in (data_dir, data_dir / "output", data_dir / "tmp",
                data_dir / "music"):
        sub.mkdir(parents=True, exist_ok=True)

    import config as cfg  # noqa: PLC0415 — import perezoso intencional

    old_data = Path(cfg.DATA_DIR)
    cfg.DATA_DIR = data_dir
    cfg.OUTPUT_DIR = data_dir / "output"
    cfg.TMP_DIR = data_dir / "tmp"
    cfg.DB_PATH = data_dir / "yt_automation.db"
    cfg.MUSIC_DIR = data_dir / "music"
    # Globals que config.py congeló POR VALOR desde el DATA_DIR original a
    # import-time: re-derívarlos SOLO si apuntaban bajo el data real (así no
    # se pisa ninguna configuración explícita del entorno/máquina del usuario).
    if _is_under(cfg.YT_CLIENT_SECRET, old_data):
        cfg.YT_CLIENT_SECRET = str(data_dir / "client_secret.json")
    if _is_under(cfg.YT_TOKEN_FILE, old_data):
        cfg.YT_TOKEN_FILE = str(data_dir / "token.json")
    if _is_under(cfg.GOOGLE_PROFILE_GLOBAL, old_data):
        cfg.GOOGLE_PROFILE_GLOBAL = data_dir / "google_profile_global"

    # NOTA DELIBERADA: aquí NO se toca database.DB_PATH. database.py hace
    # `from config import DB_PATH` (binding por valor) en SU PROPIO import:
    # si database se importa DESPUÉS de un parche de config (patrón de las
    # baterías standalone: parchean config y LUEGO importan database para
    # obtener una DB privada), el binding natural ya coge el valor parcheado.
    # Forzar aquí database.DB_PATH = config.DB_PATH ROMPERÍA ese contrato
    # (y dejaría una SQLite sin esquema). Los fakes que inyectan las
    # baterías (SimpleNamespace) simplemente no se ven afectados.


class _RedirectAfterExecLoader:
    """Envuelve el loader real de config/database del backend y reaplica la
    redirección justo después de ejecutar el módulo."""

    def __init__(self, inner):
        self._inner = inner

    def create_module(self, spec):
        return self._inner.create_module(spec)

    def exec_module(self, module):
        self._inner.exec_module(module)
        if _SESSION_TMP is not None:
            _apply_redirection(_SESSION_TMP)

    def __getattr__(self, name):
        # delega el resto de la interfaz de Loader (get_data, is_package…)
        return getattr(self._inner, name)


class _BackendConfigFinder:
    """Meta-path finder: intercepta (re)imports de ``config``/``database``
    cuando resuelven a ficheros del backend y envuelve su loader para que
    las purgas de sys.modules de las baterías NO deshagan el aislamiento."""

    _NAMES = ("config", "database")

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in self._NAMES or _SESSION_TMP is None:
            return None
        spec = importlib.machinery.PathFinder.find_spec(
            fullname, [str(BACKEND_DIR)])
        if spec is None or spec.loader is None or not spec.origin:
            return None
        if not _is_under(spec.origin, BACKEND_DIR):
            return None  # no es el config/database del backend: no tocar
        spec.loader = _RedirectAfterExecLoader(spec.loader)
        return spec


def pytest_configure(config):
    """Corre ANTES de la recolección y de importar cualquier test module.

    Monta el directorio temporal de sesión y redirige el backend ANTES de
    que exista la primera oportunidad de importar config/database."""
    global _SESSION_TMP, _FINDER
    if _SESSION_TMP is not None:  # idempotente (p.ej. pytest primera pasada)
        return
    session_tmp = Path(tempfile.mkdtemp(prefix="p1work-pytest-"))
    _SESSION_TMP = session_tmp

    sys.meta_path.insert(0, _BackendConfigFinder())
    _FINDER = sys.meta_path[0]

    # backend/services/broll_overlay.py resuelve su propio TMP_DIR desde la
    # env var TEMP_DIR (default RELATIVO «temp_renders/» en la raíz del
    # repo, con mkdir a import-time). Redirigida a la sesión.
    os.environ.setdefault("TEMP_DIR", str(session_tmp / "temp_renders"))

    # Misma técnica que usan todas las baterías (sys.path.insert backend).
    sys.path.insert(0, str(BACKEND_DIR))

    # Importa config YA aislado (el hook re-aplicará la redirección tras
    # cualquier re-import) y database EN CACHÉ con la SQLite de sesión:
    # init_db() (import-time de database.py) crea el esquema sobre la DB
    # de la sesión, NUNCA sobre backend/data real. Al quedar database en
    # sys.modules desde aquí, todo el modo pytest comparte esa SQLite de
    # sesión (las baterías que quieran DB privada tienen su vía canónica:
    # run_all.py / ejecución directa, proceso fresco).
    _apply_redirection(session_tmp)
    import config as _cfgmod  # noqa: PLC0415
    import database as _dbmod  # noqa: F401,PLC0415 — init_db() en la sesión
    assert Path(_dbmod.DB_PATH) == Path(_cfgmod.DB_PATH), (
        "database.DB_PATH no quedó ligado a la SQLite de sesión")

    config._p1work_session_tmp = str(session_tmp)


def pytest_collection_finish(session):
    """Tras recolectar (todos los module-level de los test files ya han
    corrido) se REAFIRMA la redirección de sesión sobre config: varias
    baterías parchean config.DB_PATH/DATA_DIR a nivel de módulo apuntando
    a su tmp privado (patrón standalone para proceso fresco). Bajo pytest
    la SQLite canónica es la de sesión; reafirmar aquí garantiza que los
    imports LAZY en tiempo de test (p.ej. el subprocess de test_chaos lee
    config.DB_PATH en runtime) y cualquier runtime `import config` vean
    siempre la sesión, jamás backend/data real."""
    if _SESSION_TMP is not None:
        _apply_redirection(_SESSION_TMP)


def pytest_unconfigure(config):
    global _SESSION_TMP, _FINDER
    if _FINDER is not None and _FINDER in sys.meta_path:
        sys.meta_path.remove(_FINDER)
    _FINDER = None
    if _SESSION_TMP is not None:
        shutil.rmtree(_SESSION_TMP, ignore_errors=True)
        _SESSION_TMP = None


# ─────────────────────────────────────────────────────────────────────────
# (c) Fixtures
# ─────────────────────────────────────────────────────────────────────────
# Nombres/raíces de módulos de la app que las baterías purgan e inyectan
# como fakes (misma semántica que _reset_app_modules de las baterías).
def _is_app_module(name: str) -> bool:
    return name == "database" or name.split(".")[0] in (
        "config", "security", "services", "pipeline")


@pytest.fixture(autouse=True)
def _hermetic_per_test():
    """Red de seguridad ligera por test: restaura cwd, os.environ y los
    módulos de la app en sys.modules tras cada test.

    1. cwd/os.environ: tests y servicios mutan el directorio de trabajo o
       variables de entorno; sin restauración un test deja huella en los
       siguientes (contaminación de orden).
    2. sys.modules: varias baterías pytest-compatibles (test_autopublish,
       test_production_json, test_lanzar_preflight, test_merge_216_pyav…)
       inyectan ``sys.modules["database"] = SimpleNamespace(...)`` y purgan
       config/services/pipeline SIN restaurar; el fake queda visible para
       CUALQUIER test posterior (p.ej. flow_bridge muriendo con
       ``AttributeError: SimpleNamespace object has no attribute…``). Aquí
       se congela el estado de módulos de la app por test: lo que un test
       añade se elimina, y lo que sustituye se restaura al terminar.
       (El purgado intra-test de cada batería sigue funcionando igual.)"""
    cwd = os.getcwd()
    env = dict(os.environ)
    snap = {n: m for n, m in sys.modules.items() if _is_app_module(n)}
    try:
        yield
    finally:
        os.chdir(cwd)
        os.environ.clear()
        os.environ.update(env)
        added = [n for n in sys.modules if _is_app_module(n) and n not in snap]
        for n in added:
            sys.modules.pop(n, None)
        for n, m in snap.items():
            if sys.modules.get(n) is not m:
                sys.modules[n] = m


# ─────────────────────────────────────────────────────────────────────────
# (e) Guardia canónica por test (repo-sync FIX: defensa anti-veneno)
# ─────────────────────────────────────────────────────────────────────────
_CANON_ENV: dict | None = None
_CANON_CFG: dict | None = None


@pytest.fixture(autouse=True)
def _canon_guard():
    """Re-aplica el estado canónico ANTES de cada test: ``os.environ`` +
    attrs de ``config`` (y ``database.DB_PATH`` en espejo).

    Defensa en profundidad contra venenos de colección que no estén en la
    lista de exclusión (un ``os.environ["X"]="1"`` en el cuerpo de un
    test-file, una mutación de attr de config sin restaurar, etc.): el
    snapshot canónico se toma en la PRIMERA aplicación (primer test de la
    sesión, ya con el aislamiento de pytest_configure activo y antes de
    que cualquier test haya mutado nada) y se re-aplica al inicio de cada
    test. Idempotente y barato (un dict-update + unos setattr).

    NOTA: deliberately NO fuerza database.DB_PATH cuando database.py aún
    no se importó o fue inyectado como fake por una batería (mismo
    contrato que respeta _apply_redirection)."""
    global _CANON_ENV, _CANON_CFG
    import config as cfg  # noqa: PLC0415
    if _CANON_ENV is None:
        _CANON_ENV = dict(os.environ)
        _CANON_CFG = {k: v for k, v in vars(cfg).items()
                      if not k.startswith("__")}
    os.environ.clear()
    os.environ.update(_CANON_ENV)
    for k, v in _CANON_CFG.items():
        setattr(cfg, k, v)
    try:
        import database as _db  # noqa: PLC0415
    except Exception:  # fake inyectado por una batería: no tocar
        _db = None
    if _db is not None and _CANON_CFG is not None \
            and "DB_PATH" in _CANON_CFG \
            and not hasattr(_db, "_albra_fake"):
        _db.DB_PATH = _CANON_CFG["DB_PATH"]
    yield


@pytest.fixture
def fresh_db(tmp_path):
    """OPT-IN: SQLite prístina para UN test (nadie la usa de serie).

    Apunta config.DB_PATH + database.DB_PATH a un fichero nuevo dentro del
    tmp_path del test, ejecuta init_db() y restaura al terminar. Úsala en
    tests que necesitan garantía de NO compartir estado con el resto de la
    sesión (el resto de la sesión comparte la SQLite aislada de sesión, que
    es lo que espera el grueso de las baterías al portarse a pytest)."""
    import config as cfg  # noqa: PLC0415
    import database as db  # noqa: PLC0415

    old_cfg, old_db = cfg.DB_PATH, getattr(db, "DB_PATH", None)
    nuevo = tmp_path / "fresh.sqlite3"
    cfg.DB_PATH = nuevo
    if old_db is not None:
        db.DB_PATH = nuevo
    db.init_db()
    try:
        yield nuevo
    finally:
        cfg.DB_PATH = old_cfg
        if old_db is not None:
            db.DB_PATH = old_db
