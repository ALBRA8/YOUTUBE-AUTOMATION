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

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import config

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
def _output_dir() -> Path:
    return Path(config.OUTPUT_DIR)


def registro_path(production_id: str) -> Path:
    return _output_dir() / production_id / "registro.json"


def _nichos_path() -> Path:
    return Path(config.DATA_DIR) / ARCHIVO_NICHOS


def _json_carga(ruta: Path, defecto: Any) -> Any:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def _json_guarda(ruta: Path, datos: Any) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


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
    data/output/* y devuelve max+1 (1 si no hay ninguno). Determinista."""
    raiz = Path(raiz) if raiz else _output_dir()
    maximo = 0
    if raiz.is_dir():
        for d in raiz.iterdir():
            reg = _json_carga(d / "registro.json", None)
            if (isinstance(reg, dict)
                    and reg.get("nicho_id") == nicho_id
                    and isinstance(reg.get("numero_serie"), int)):
                maximo = max(maximo, reg["numero_serie"])
    return maximo + 1


def crear(production_id: str, nicho_id: str, titulo_historia: str, *,
          nicho_nombre: str = "", estado: str = "DRAFT",
          numero_serie: int | None = None) -> dict:
    """Crea (o completa) el registro de una producción con la convención
    de nombres. Idempotente: si ya existe, se respeta su numero_serie."""
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
