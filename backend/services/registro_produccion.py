"""v1.0 · Registro local de producciones y convención de nombres (minidramas).

DECISIONES DEL DUEÑO (2026-11-07) que este módulo codifica:
  1. Los AVATARES solo se registran en Flow (sin cuaderno de NotebookLM).
  2. UN cuaderno de NotebookLM por NICHO (genera historias distintas);
     nunca un cuaderno por historia.
  3. UN proyecto de Flow por historia/novela.

FUENTE DE VERDAD: el ID estable. Los nombres son ETIQUetas legibles.
  - Producción: data/output/<production_id>/registro.json
      {production_id, nicho_id, titulo_historia, numero_serie,
       nombre_flow, flow_project_id, flow_project_nombre_observado,
       notebook_id_nicho, estado, creado_en, actualizado_en,
       limitaciones: [str]}
  - Nicho: data/registro_nichos.json (un cuaderno por nicho)
      {nicho_id: {notebook_id, nombre_cuaderno, actualizado_en}}

CONVENCIÓN DE NOMBRES (determinista): "FRUTINOVELAS · S003 · Título"
  — nicho en MAYÚSCULAS saneado; S + nº de serie a 3 dígitos asignado en
  secuencia POR NICHO (S001, S002…); título saneado (sin «·», espacios
  colapsados) truncado con «…» para respetar la longitud máxima total.

REGLAS DURAS:
  - Idempotencia (2.5): si el registro ya tiene flow_project_id, NUNCA se
    crea otro proyecto (registrar_flow_proyecto no llama al creador).
  - Avatares (2.4): flow_character_id se rellena con
    universos.vincular_flow; este módulo NO crea cuadernos de avatares.
  - El nombre se pasa a Flow SOLO si la sonda (INT-093) marcó SOPORTADO;
    si no, el nombre vive solo en local y se anota la limitación (3.1).
  - Toda creación real de Flow está detrás de config.FLOW_REGISTRO_SYNC
    (apagada por defecto) — los tests usan dobles, nunca Flow real.

Hermético: solo I/O local bajo config.DATA_DIR/OUTPUT_DIR leídos en
tiempo de llamada (respetan el aislamiento de tests/conftest.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import config

logger = logging.getLogger("registro_produccion")

_LOCK_MASTER = threading.Lock()
_LOCKS_NICHO: dict[str, threading.Lock] = {}


def _get_nicho_lock(nicho_id: str) -> threading.Lock:
    with _LOCK_MASTER:
        if nicho_id not in _LOCKS_NICHO:
            _LOCKS_NICHO[nicho_id] = threading.Lock()
        return _LOCKS_NICHO[nicho_id]

ARCHIVO_NICHOS = "registro_nichos.json"
ESTADOS = ("DRAFT", "READY", "GENERANDO", "RENDERIZADO", "QA_OK", "ERROR")
LONGITUD_MAX = 80
SEP = "·"


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── convención de nombres (2.3) ──────────────────────────────────────────
def _sanea(texto: str, *, mayusculas: bool = False,
           quitar_sep: bool = True) -> str:
    """Saneamiento determinista: sin «·» (salvo quitar_sep=False, p. ej.
    el nombre del cuaderno «NICHO · X»), sin saltos, espacios colapsados,
    sin bordes. `mayusculas` aplica upper (nicho)."""
    t = unicodedata.normalize("NFC", str(texto or ""))
    if quitar_sep:
        t = t.replace(SEP, " ")
    t = t.replace("\n", " ").replace("\r", " ")
    t = re.sub(r"\s+", " ", t).strip()
    if mayusculas:
        t = t.upper()
    return t


def nombre_produccion(nicho: str, numero: int, titulo: str,
                      max_len: int = LONGITUD_MAX) -> str:
    """«FRUTINOVELAS · S003 · Título» — puro y determinista."""
    nicho_s = _sanea(nicho, mayusculas=True) or "SIN_NICHO"
    serie = f"S{max(1, int(numero)):03d}"
    prefijo = f"{nicho_s} {SEP} {serie} {SEP} "
    restante = max_len - len(prefijo)
    titulo_s = _sanea(titulo)
    if restante <= 1:
        return (prefijo + titulo_s)[:max_len].rstrip()
    if len(titulo_s) > restante:
        titulo_s = titulo_s[:restante - 1].rstrip() + "…"
    return f"{prefijo}{titulo_s}" if titulo_s \
        else prefijo.rstrip().rstrip(SEP).rstrip()


# ── rutas y helpers de disco ─────────────────────────────────────────────
ID_PRODUCCION_RE = re.compile(r"^[A-Za-z0-9._-]+$")
LONGITUD_MAX_ID = 80


def validar_production_id(production_id: str) -> str:
    """Valida que production_id sea seguro y contenga solo [A-Za-z0-9._-].
    Rechaza vacío, >80 chars, separadores / y \\, '..' y rutas absolutas."""
    p = str(production_id or "").strip()
    if not p:
        raise ValueError("production_id no puede ser vacío")
    if len(p) > LONGITUD_MAX_ID:
        raise ValueError(f"production_id demasiado largo (> {LONGITUD_MAX_ID})")
    if "/" in p or "\\" in p:
        raise ValueError(f"production_id contiene separadores de ruta: {p!r}")
    if ".." in p:
        raise ValueError(f"production_id no puede contener '..': {p!r}")
    if Path(p).is_absolute() or re.match(r"^[a-zA-Z]:", p):
        raise ValueError(f"production_id no puede ser ruta absoluta: {p!r}")
    if not ID_PRODUCCION_RE.fullmatch(p):
        raise ValueError(f"production_id con caracteres inválidos: {p!r}")
    return p


def _output_dir() -> Path:
    return Path(config.OUTPUT_DIR)


def registro_path(production_id: str) -> Path:
    pid = validar_production_id(production_id)
    root = _output_dir().resolve()
    target = (root / pid / "registro.json").resolve()
    if root not in target.parents:
        raise ValueError("ruta resuelta fuera de OUTPUT_DIR")
    return target


def _nichos_path() -> Path:
    return Path(config.DATA_DIR) / ARCHIVO_NICHOS


def _json_carga(ruta: Path, defecto: Any) -> Any:
    if not ruta.is_file():
        return defecto
    try:
        raw = ruta.read_text(encoding="utf-8")
        return json.loads(raw)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning("JSON corrupto detectado en %s: %s", ruta, e)
        return defecto
    except OSError as e:
        logger.warning("Error de I/O leyendo %s: %s", ruta, e)
        return defecto


def _json_guarda(ruta: Path, datos: Any) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    contenido = json.dumps(datos, ensure_ascii=False, indent=2) + "\n"
    tmp_path = ruta.with_name(f"{ruta.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        tmp_path.write_text(contenido, encoding="utf-8")
        os.replace(tmp_path, ruta)
    except Exception:
        if tmp_path.is_file():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


# ── registro por producción (2.1) ────────────────────────────────────────
def leer(production_id: str) -> dict | None:
    """Registro de la producción, o None si no existe. Nunca lanza."""
    reg = _json_carga(registro_path(production_id), None)
    return reg if isinstance(reg, dict) else None


def guardar(registro: dict) -> dict:
    """Persiste el registro; estampa actualizado_en. ValueError si falta
    la clave estable (production_id)."""
    pid = str(registro.get("production_id") or "").strip()
    if not pid:
        raise ValueError("registro sin production_id (la clave es el ID)")
    registro["actualizado_en"] = _ahora()
    registro.setdefault("creado_en", registro["actualizado_en"])
    registro.setdefault("limitaciones", [])
    _json_guarda(registro_path(pid), registro)
    return registro


def siguiente_numero(nicho_id: str, raiz: Path | None = None) -> int:
    """Nº de serie siguiente para el nicho: escanea los registro.json de
    data/output/* y devuelve max+1 (1 si no hay ninguno). Determinista.
    Si detecta JSON corrupto, registra el aviso y no reutiliza números."""
    raiz = Path(raiz) if raiz else _output_dir()
    maximo = 0
    corruptos_sin_numero = 0
    if raiz.is_dir():
        for d in raiz.iterdir():
            reg_file = d / "registro.json"
            if not reg_file.is_file():
                continue
            raw = ""
            try:
                raw = reg_file.read_text(encoding="utf-8")
                reg = json.loads(raw)
                if (isinstance(reg, dict)
                        and reg.get("nicho_id") == nicho_id
                        and isinstance(reg.get("numero_serie"), int)):
                    maximo = max(maximo, reg["numero_serie"])
            except (ValueError, json.JSONDecodeError) as err:
                logger.warning("JSON corrupto detectado en %s: %s", reg_file, err)
                m_num = re.search(r'"numero_serie"\s*:\s*(\d+)', raw)
                m_nicho = re.search(r'"nicho_id"\s*:\s*"([^"]+)"', raw)
                if m_num and (not m_nicho or m_nicho.group(1) == nicho_id):
                    maximo = max(maximo, int(m_num.group(1)))
                else:
                    corruptos_sin_numero += 1
    maximo += corruptos_sin_numero
    return maximo + 1


def crear(production_id: str, nicho_id: str, titulo_historia: str, *,
          nicho_nombre: str = "", estado: str = "DRAFT",
          numero_serie: int | None = None) -> dict:
    """Crea (o completa) el registro de una producción con la convención
    de nombres. Idempotente: si ya existe, se respeta su numero_serie.
    Usa bloqueo por nicho para evitar carreras en concurrencia."""
    with _get_nicho_lock(nicho_id):
        previo = leer(production_id) or {}
        numero = int(previo.get("numero_serie") or numero_serie
                     or siguiente_numero(nicho_id))
        nicho_n = nicho_nombre or nicho_id
        registro = {
            "production_id": production_id,
            "nicho_id": nicho_id,
            "titulo_historia": titulo_historia,
            "numero_serie": numero,
            "nombre_flow": previo.get("nombre_flow")
            or nombre_produccion(nicho_n, numero, titulo_historia),
            "flow_project_id": previo.get("flow_project_id"),
            "flow_project_nombre_observado": previo.get(
                "flow_project_nombre_observado"),
            "notebook_id_nicho": previo.get("notebook_id_nicho"),
            "estado": estado if estado in ESTADOS else "DRAFT",
            "limitaciones": previo.get("limitaciones", []),
        }
        return guardar(registro)


def anota_limitacion(production_id: str, detalle: str) -> dict:
    """Anota una limitación honesta en el registro (p. ej. «Flow no acepta
    nombre de proyecto: el nombre vive solo en local»)."""
    reg = leer(production_id)
    if reg is None:
        raise ValueError(f"sin registro para {production_id}")
    if detalle not in reg.setdefault("limitaciones", []):
        reg["limitaciones"].append(detalle)
    return guardar(reg)


# ── registro por nicho (2.2) — UN cuaderno por nicho ─────────────────────
def registro_nicho(nicho_id: str) -> dict | None:
    datos = _json_carga(_nichos_path(), {})
    entrada = datos.get(nicho_id) if isinstance(datos, dict) else None
    return entrada if isinstance(entrada, dict) else None


def registrar_nicho(nicho_id: str, notebook_id: str,
                    nombre_cuaderno: str) -> dict:
    """Asigna el cuaderno del nicho. UN cuaderno por nicho: si ya había
    uno distinto se REEMPLAZA y se conserva la fecha del cambio."""
    datos = _json_carga(_nichos_path(), {})
    datos = datos if isinstance(datos, dict) else {}
    entrada = {"notebook_id": str(notebook_id).strip(),
               "nombre_cuaderno": _sanea(nombre_cuaderno, quitar_sep=False),
               "actualizado_en": _ahora()}
    datos[nicho_id] = entrada
    _json_guarda(_nichos_path(), datos)
    return entrada


def propaga_notebook(production_id: str) -> dict:
    """Rellena notebook_id_nicho del registro desde el registro del nicho
    (una producción nunca lleva cuaderno propio)."""
    reg = leer(production_id)
    if reg is None:
        raise ValueError(f"sin registro para {production_id}")
    nicho = registro_nicho(reg["nicho_id"])
    reg["notebook_id_nicho"] = nicho["notebook_id"] if nicho else None
    return guardar(reg)


# ── avatares (2.4) — SOLO Flow, sin cuaderno ─────────────────────────────
def vincular_avatar_flow(lib_id: str, flow_project_id: str | None,
                         flow_character_id: str | None) -> dict:
    """Rellena flow_character_id/flow_project_id del avatar de la
    biblioteca delegando en universos.vincular_flow. Los avatares NO
    tienen cuaderno: esta función jamás toca registro_nichos.json."""
    from services import universos
    return universos.vincular_flow(lib_id, flow_project_id,
                                   flow_character_id)


# ── vinculación idempotente del proyecto de Flow (2.5) ───────────────────
def registrar_flow_proyecto(production_id: str, crear_proyecto: Callable,
                            *, nombres_soportados: str | None = None) -> dict:
    """Vincula el proyecto de Flow del registro, IDEMPOTENTE (2.5): si ya
    hay flow_project_id devuelve YA_VINCULADO sin llamar a `crear_proyecto`.

    `crear_proyecto(nombre_flow)` (doble en tests; en producción, el puente
    MCP real detrás del flag del PASO 3) devuelve {flow_project_id,
    nombre_observado}.

    `nombres_soportados` es el veredicto de la sonda INT-093: SOPORTADO →
    se guarda el nombre observado; NO_SOPORTADO / NOT_DEMONSTRATED / None →
    el nombre vive solo en local y se anota la limitación."""
    reg = leer(production_id)
    if reg is None:
        raise ValueError(f"sin registro para {production_id}")
    if reg.get("flow_project_id"):
        return {"estado": "YA_VINCULADO",
                "flow_project_id": reg["flow_project_id"]}
    res = crear_proyecto(reg["nombre_flow"]) or {}
    flow_id = str(res.get("flow_project_id") or "").strip()
    if not flow_id:
        detalle = "crear_proyecto no entrego flow_project_id: no se vincula proyecto"
        if detalle not in reg.setdefault("limitaciones", []):
            reg["limitaciones"].append(detalle)
        guardar(reg)
        return {"estado": "ERROR",
                "flow_project_id": None,
                "detalle": detalle}

    reg["flow_project_id"] = flow_id
    if nombres_soportados == "SOPORTADO":
        reg["flow_project_nombre_observado"] = (
            res.get("nombre_observado") or reg["nombre_flow"])
    else:
        reg["flow_project_nombre_observado"] = None
        detalle = (f"Flow no recibe el nombre (sonda: "
                   f"{nombres_soportados or 'sin sonda'}); el nombre vive "
                   "solo en el registro local")
        if detalle not in reg.setdefault("limitaciones", []):
            reg["limitaciones"].append(detalle)   # UN solo guardar: no se
    guardar(reg)                                  # pisa la anotación
    return {"estado": "VINCULADO",
            "flow_project_id": reg["flow_project_id"],
            "nombre_observado": reg["flow_project_nombre_observado"]}


# ── conexión con Flow (3.1) — APAGADA por defecto ────────────────────────
def sincronizar_flow(production_id: str, crear_proyecto: Callable, *,
                     nombres_soportados: str | None = None,
                     sinc_activa: bool | None = None) -> dict:
    """Gate 3.1: SOLO crea/vincula el proyecto de Flow si
    config.FLOW_REGISTRO_SYNC está activa (APAGADA por defecto; el dueño
    la activa en su máquina). Los tests pasan `sinc_activa` o monkeypatchean
    config y SIEMPRE usan un doble en `crear_proyecto` — nunca Flow real.

    El nombre se pasa a Flow SOLO si la sonda INT-093 marcó SOPORTADO;
    si no, `registrar_flow_proyecto` guarda el nombre solo en local y
    anota la limitación."""
    activa = (bool(getattr(config, "FLOW_REGISTRO_SYNC", False))
              if sinc_activa is None else bool(sinc_activa))
    if not activa:
        return {"estado": "APAGADO",
                "detalle": "config.FLOW_REGISTRO_SYNC=0: no se crea nada"}
    return registrar_flow_proyecto(production_id, crear_proyecto,
                                   nombres_soportados=nombres_soportados)


# ── adaptador REAL con el MCP de Flow (R5) — detrás de FLOW_REGISTRO_SYNC ─
ARCHIVO_SONDA = "sonda_nombres.json"
_RE_PROP_NOMBRE = re.compile(r"flow_new_project acepta '([A-Za-z_]+)'")


def _ruta_sonda_defecto() -> Path:
    """Informe de la sonda INT-093 que el dueño guarda en la raíz del repo
    (tools/sonda_capacidades_nombres.py --salida sonda_nombres.json);
    configurable con config.SONDA_NOMBRES_JSON."""
    return Path(getattr(config, "SONDA_NOMBRES_JSON",
                        Path(config.DATA_DIR).parent / ARCHIVO_SONDA))


def leer_sonda(ruta: Path | None = None) -> dict:
    """Lee el informe guardado de la sonda INT-093 y responde a q1
    (¿flow_new_project acepta nombre?) con {"veredicto", "prop"}:

    - "veredicto": SOPORTADO | NO_SOPORTADO | NOT_DEMONSTRATED (tal cual
      lo dejó la sonda; JAMÁS se inventa o se amplía aquí).
    - "prop": la propiedad exacta del esquema (p. ej. 'name') SOLO si el
      detalle marca que flow_new_project la acepta; None si el soporte es
      solo vía tool de renombrar (esa vía no se usa en la creación).

    Sin informe, ilegible o sin la pregunta → NOT_DEMONSTRATED (honesto:
    sin capacidad demostrada, el nombre NO viaja a Flow)."""
    ruta = Path(ruta) if ruta else _ruta_sonda_defecto()
    out: dict = {"veredicto": "NOT_DEMONSTRATED", "prop": None}
    try:
        informe = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("sonda INT-093 ilegible en %s (%s): NOT_DEMONSTRATED",
                       ruta, type(exc).__name__)
        return out
    if not isinstance(informe, dict):
        return out
    preguntas = ((informe.get("servicios") or {}).get("google-flow") or {}
                 ).get("preguntas") or []
    for p in preguntas:
        if not isinstance(p, dict) or p.get("id") != "q1_flow_proyecto_nombre":
            continue
        veredicto = str(p.get("veredicto") or "").strip()
        out["veredicto"] = veredicto or "NOT_DEMONSTRATED"
        if veredicto == "SOPORTADO":
            m = _RE_PROP_NOMBRE.search(str(p.get("detalle") or ""))
            out["prop"] = m.group(1) if m else None
        break
    return out


def adaptador_crear_proyecto(nombre_flow: str, *, timeout: float = 30.0,
                             ruta_sonda: Path | None = None) -> dict:
    """R5 · Adaptador real para registrar_flow_proyecto: crea el proyecto
    vía flow_mcp_client.new_project y devuelve {flow_project_id,
    nombre_observado} en el formato que registrar_flow_proyecto espera.

    El nombre SOLO se pasa al MCP si leer_sonda() devolvió SOPORTADO con
    propiedad de nombre en el esquema; con el informe ausente (o
    NO_SOPORTADO) el proyecto se crea SIN nombre — el nombre vive solo en
    el registro local y registrar_flow_proyecto anota la limitación.

    Cualquier fallo del MCP (FlowMCPError, timeout, node ausente…) NO
    explota: devuelve flow_project_id None → registrar_flow_proyecto lo
    convierte en ERROR + limitación anotada (R1: sin estado falso).

    SÍNCRONO (asyncio.run): llamar desde script/hilo propio, nunca dentro
    de un event loop. En tests NO se llama aquí: se usa sincronizar_flow
    con dobles o se monkeypatchea flow_mcp_client.new_project."""
    sonda = leer_sonda(ruta_sonda)
    prop = sonda["prop"] if sonda["veredicto"] == "SOPORTADO" else None
    nombre = str(nombre_flow or "").strip() or None
    enviar = nombre if (prop and nombre) else None
    from services import flow_mcp_client as fmc
    try:
        raw = asyncio.run(fmc.new_project(timeout=timeout, name=enviar,
                                          name_prop=prop or "name"))
    except (fmc.FlowMCPError, RuntimeError, OSError) as exc:
        # FlowMCPError cubre las tipadas del cliente MCP (auth, timeout,
        # respuesta); RuntimeError, el asyncio.run en un event loop; OSError,
        # spawn/I/O del subproceso. Un bug de otro tipo SÍ explota: visible.
        logger.warning("adaptador_crear_proyecto: el MCP falló (%s): %s",
                       type(exc).__name__, exc)
        return {"flow_project_id": None, "nombre_observado": None,
                "error": f"{type(exc).__name__}: {exc}"}
    return {"flow_project_id": str(raw or "").strip() or None,
            "nombre_observado": enviar}


def sincronizar_flow_real(production_id: str, *,
                          ruta_sonda: Path | None = None,
                          sinc_activa: bool | None = None,
                          timeout: float = 30.0) -> dict:
    """R5 · Entrada REAL de la conexión con Flow: gate FLOW_REGISTRO_SYNC
    (apagado por defecto) + adaptador MCP + veredicto de la sonda leído
    del informe guardado (sonda_nombres.json; ausente → NOT_DEMONSTRATED
    → sin nombre a Flow). Guarda flow_project_id en el registro; es
    idempotente (2.5: nunca un segundo proyecto).

    SOPORTADO solo vía renombrar (sin propiedad de nombre en
    flow_new_project) se trata aquí como sin nombre en la creación: la
    limitación queda anotada en el registro. En tests NUNCA se llama con
    Flow real: se monkeypatchea flow_mcp_client.new_project (doble)."""
    sonda = leer_sonda(ruta_sonda)
    nombres = sonda["veredicto"]
    if sonda["veredicto"] == "SOPORTADO" and not sonda["prop"]:
        nombres = None   # renombrar ≠ nombre en la creación
    return sincronizar_flow(
        production_id,
        lambda n: adaptador_crear_proyecto(n, timeout=timeout,
                                           ruta_sonda=ruta_sonda),
        nombres_soportados=nombres,
        sinc_activa=sinc_activa)


# ── punto de paso común del registro (Q1) ────────────────────────────────
def registrar_proyecto_creado(project: dict | None) -> None:
    """Q1 · PUNTO DE PASO COMÚN: registra en el registro de producciones
    TODO proyecto recién creado vía database.create_project — las 14 vías
    (API /api/projects, A2A, clipper, MCP crear_video / guion_json /
    production_json, agente general, scheduler de fábrica, arnés YouTube)
    cruzan por ahí, así que no hay que parchear llamada por llamada.

    Idempotente: si el proyecto ya tiene registro (p. ej. los sitios que
    registran por su cuenta vía _post_create_init) es un no-op — nunca
    duplica numero_serie ni reescribe.

    BEST-EFFORT y JAMÁS lanza: una falla del registro no puede invalidar
    la creación del proyecto (misma doctrina que _post_create_init, R4).
    Captura SOLO excepciones tipadas (trinquete P2-2): ValueError del
    validador de IDs (R2), OSError de I/O, TypeError/KeyError de datos
    inesperados y RuntimeError. Un bug de otro tipo SÍ explota (visible).
    """
    if not isinstance(project, dict):
        return
    pid = str(project.get("id") or "").strip()
    if not pid:
        return
    try:
        if leer(pid):          # ya registrado (idempotente, 2.5/Q1)
            return
        crear(
            production_id=pid,
            nicho_id=str(project.get("niche") or "").strip() or "general",
            titulo_historia=str(project.get("title") or "").strip()
            or "Sin título",
        )
    except (ValueError, OSError, TypeError, KeyError, RuntimeError) as exc:
        logger.warning("registro automático de %s omitido (%s: %s)",
                       pid, type(exc).__name__, exc)


# ── disparo de la sincronización al empezar la fase Flow (Q3) ────────────
LIMITACION_Q7 = ("Q3 · Flow genera sobre el proyecto ACTIVO y no queda "
                 "demostrado que la generación se dirija al proyecto "
                 "creado (sonda q7 != SOPORTADO): el flow_project_id "
                 "queda registrado pero la generación NO se redirige")


def leer_sonda_q7(ruta: Path | None = None) -> str:
    """Q3 · Lee el veredicto q7 del informe guardado de la sonda INT-093
    (¿flow_new_project cambia el proyecto activo sobre el que generan las
    demás herramientas?). Sin informe, ilegible o sin la pregunta →
    NOT_DEMONSTRATED (honesto: sin demostración NO se dirige generación)."""
    ruta = Path(ruta) if ruta else _ruta_sonda_defecto()
    try:
        informe = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "NOT_DEMONSTRATED"
    if not isinstance(informe, dict):
        return "NOT_DEMONSTRATED"
    preguntas = ((informe.get("servicios") or {}).get("google-flow") or {}
                 ).get("preguntas") or []
    for p in preguntas:
        if isinstance(p, dict) \
                and p.get("id") == "q7_flow_new_project_cambia_activo":
            return str(p.get("veredicto") or "NOT_DEMONSTRATED")
    return "NOT_DEMONSTRATED"


def disparo_sync_flow(production_id: str, *,
                      ruta_sonda: Path | None = None,
                      sinc_activa: bool | None = None,
                      timeout: float = 30.0) -> dict:
    """Q3 · DISPARO de la sincronización con Flow cuando empieza la fase
    Flow de una producción (lo llama flow_jobs.enqueue_project desde un
    hilo — el adaptador usa asyncio.run y NO puede correr dentro de un
    event loop, por eso el disparo nunca va inline).

    - Gate FLOW_REGISTRO_SYNC (apagado por defecto): con el flag apagado
      NO toca nada (ni MCP ni registro) — el sistema no cambia.
    - NUNCA bloquea ni hace fallar la producción: captura solo excepciones
      tipadas (trinquete P2-2) y devuelve un dict de estado; el fallo del
      MCP ya es dato (R1: ERROR + limitación, sin estado falso).
    - Si la sonda no demuestra que la generación se dirige al proyecto
      creado (q7 != SOPORTADO), la generación NO se redirige: el id se
      registra y la limitación queda anotada (NOT_DEMONSTRATED honesto).
      Segundo disparo (idempotente, 2.5) → YA_VINCULADO sin re-anotar.

    En tests NUNCA Flow real: doble en flow_mcp_client.new_project
    (monkeypatch) o sinc_activa con dobles de alto nivel."""
    activa = (bool(getattr(config, "FLOW_REGISTRO_SYNC", False))
              if sinc_activa is None else bool(sinc_activa))
    if not activa:
        return {"estado": "APAGADO",
                "detalle": "config.FLOW_REGISTRO_SYNC=0: no se toca nada"}
    try:
        res = sincronizar_flow_real(production_id, ruta_sonda=ruta_sonda,
                                    sinc_activa=True, timeout=timeout)
    except (ValueError, OSError, RuntimeError) as exc:
        logger.warning("disparo_sync_flow(%s): sincronización no lanzada "
                       "(%s: %s)", production_id, type(exc).__name__, exc)
        return {"estado": "ERROR_DISPARO",
                "error": f"{type(exc).__name__}: {exc}"}
    if res.get("flow_project_id") and res.get("estado") != "YA_VINCULADO":
        try:
            if leer_sonda_q7(ruta_sonda) != "SOPORTADO":
                anota_limitacion(production_id, LIMITACION_Q7)
        except (ValueError, OSError, RuntimeError) as exc:
            logger.warning("disparo_sync_flow(%s): limitación q7 no "
                           "anotada (%s)", production_id,
                           type(exc).__name__)
    return res


# ── listado (endpoint GET /api/registro, 3.2) ────────────────────────────
def listar_producciones() -> list[dict]:
    """Lista todas las producciones registradas (solo lectura): id, nicho,
    nombre, flow_project_id y notebook_id del nicho."""
    out: list[dict] = []
    raiz = _output_dir()
    if not raiz.is_dir():
        return out
    for d in sorted(raiz.iterdir()):
        reg = _json_carga(d / "registro.json", None)
        if not isinstance(reg, dict) or not reg.get("production_id"):
            continue
        nicho = registro_nicho(reg.get("nicho_id") or "")
        out.append({
            "production_id": reg["production_id"],
            "nicho_id": reg.get("nicho_id"),
            "nombre_flow": reg.get("nombre_flow"),
            "numero_serie": reg.get("numero_serie"),
            "flow_project_id": reg.get("flow_project_id"),
            "notebook_id_nicho": (nicho or {}).get("notebook_id"),
            "estado": reg.get("estado"),
        })
    return out
