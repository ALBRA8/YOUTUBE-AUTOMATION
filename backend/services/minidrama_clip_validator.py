"""v1.0 · Validador editorial de la Fase E — minidramas NotebookLM + Flow.

Qué es: módulo Python PURO (sin red, sin Flow, sin I/O) que valida la
ficha de un clip y un episodio completo contra las reglas del Master
Prompt transcritas en
`CONTEXTO YOUTUBE/05_TESTS/ESPECIFICACION_AUTOMATIZACION_MINIDRAMAS_NOTEBOOKLM_FLOW.md`
(§ Fase E). Es la implementación del Gate E a nivel EDITORIAL: no encola,
no llama a Flow, no toca orquestador, Flow Bridge ni HANDS.

Qué valida (por clip):
  1. Campos obligatorios presentes y no vacíos. Por defecto se reutilizan
     los nombres de campo YA EXISTENTES del Production JSON / ficha Fase E:
     `video_prompt`, `duration_target`, `initial_state`, `final_state`,
     `casting`, `story_function`. No se inventan nombres alternativos.
  2. Un solo párrafo en `video_prompt`: sin saltos de línea (definición
     determinista de "párrafo continuo" para un prompt que va a Flow).
  3. Nombres de personaje en MAYÚSCULAS: cada nombre del `casting` debe
     estar en forma mayúscula y cada aparición de ese nombre dentro de
     `video_prompt` debe ser la forma MAYÚSCULA (una aparición en otro
     caso falla; el nombre ausente del prompt falla como regla propia).
  4. Máximo de palabras HABLADAS (12 por defecto), contadas de forma
     DETERMINISTA según la definición escrita en la spec (§ Fase E,
     regla 4): solo cuentan los fragmentos entre comillas ("...", “…” o
     «...») atribuibles a un personaje; token = secuencia alfanumérica
     (acentos y ñ incluidas); números en cifra = 1 palabra, escritos en
     letras = sus tokens; compuesto con guion = 2 palabras; la raya de
     diálogo de apertura no añade tokens; muletillas cuentan.
     Si el límite se excede, el resultado DEVUELVE EL TEXTO QUE EXCEDE
     (`exceso`: las palabras a partir de la límite+1) junto al diálogo
     completo y el total contado.
  5. `final_state` presente y no vacío (estado final a 9.9 s). La
     verificación de que ese estado está DESCRITO dentro del párrafo es
     heurística y NO se intenta aquí (QA humano + Fase F).
  6. `duration_target` numérico > 0 e igual a la duración objetivo
     configurable (por defecto 10.0 s, exacto).

Qué valida (por episodio):
  - Exactamente `clips_por_episodio` clips (6 por defecto).
  - `clip_id` únicos; `episode_id` idéntico en todos los clips cuando
    están presentes.
  - Cada clip pasa sus reglas individuales con la duración objetivo
    configurada para TODO el episodio (configurable por clip solo vía
    llamada directa a `validar_clip`).

Fuera de alcance (explícitamente NO implementado en esta rebanada):
  biblia de personajes, aprobaciones, continuidad entre episodios,
  modo serie, validación de idioma español (heurística, QA humano) y
  cualquier interacción con Flow u orquestador.

Ejecutar: python3 -m pytest tests/test_minidrama_clip_validator.py -q
"""
from __future__ import annotations

import re
from typing import Any

__all__ = [
    "validar_clip",
    "validar_episodio",
    "extraer_dialogo",
    "contar_palabras_habladas",
    "CAMPOS_OBLIGATORIOS",
]

# Campos obligatorios por defecto: SOLO nombres ya existentes en el
# Production JSON / ficha Fase E (§4 de la spec: reutilizar y extender,
# no duplicar bajo nombres alternativos).
CAMPOS_OBLIGATORIOS = (
    "video_prompt",
    "duration_target",
    "initial_state",
    "final_state",
    "casting",
    "story_function",
)

# Token de palabra: alfanumérico con acentos/ñ/ü (español). Un compuesto
# con guion ("algo-bueno") produce DOS matches → 2 palabras, como define
# la spec. La cifra "2026" produce UN match → 1 palabra.
_RE_PALABRA = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")

# Fragmentos de diálogo hablado: comillas rectas, curvas o angulares.
_RE_DIALOGO = re.compile(r'«([^»]*?)»|"([^"]*?)"|“([^”]*?)”')


def extraer_dialogo(texto: str) -> list[str]:
    """Devuelve los fragmentos entre comillas ("...", “…” o «...») de un
    prompt. Son lo ÚNICO que cuenta como palabras habladas."""
    if not isinstance(texto, str):
        return []
    return [m.group(1) or m.group(2) or m.group(3) or ""
            for m in _RE_DIALOGO.finditer(texto)]


def contar_palabras_habladas(texto: str) -> int:
    """Cuenta palabras habladas según la definición determinista de la
    spec: suma de tokens alfanuméricos en todos los fragmentos entre
    comillas del prompt."""
    return sum(len(_RE_PALABRA.findall(frag)) for frag in extraer_dialogo(texto))


def _texto_que_excede(texto: str, limite: int) -> str | None:
    """Palabras habladas desde la límite+1 en adelante (el texto que
    excede el límite), o None si no excede."""
    restantes = limite
    for frag in extraer_dialogo(texto):
        tokens = _RE_PALABRA.findall(frag)
        if restantes - len(tokens) < 0:
            return " ".join(tokens[restantes:])
        restantes -= len(tokens)
    return None


def _nombres_casting(casting: Any) -> list[str]:
    """Nombres de personaje desde `casting`: lista de str o de dicts con
    clave name/nombre/character_id (formatos que ya circulan en el repo).
    Otro tipo → lista vacía (la regla de campos obligatorios ya lo
    reporta; aquí no se duplica el fallo)."""
    if isinstance(casting, str):
        return [casting] if casting.strip() else []
    if not isinstance(casting, (list, tuple)):
        return []
    nombres: list[str] = []
    for item in casting:
        if isinstance(item, str):
            nombres.append(item.strip())
        elif isinstance(item, dict):
            for clave in ("name", "nombre", "character_id", "id"):
                valor = item.get(clave)
                if isinstance(valor, str) and valor.strip():
                    nombres.append(valor.strip())
                    break
    return [n for n in nombres if n]


def _fallo(campo: str, regla: str, detalle: str) -> dict[str, str]:
    return {"campo": campo, "regla": regla, "detalle": detalle}


def validar_clip(
    clip: dict,
    *,
    duracion_objetivo: float = 10.0,
    max_palabras: int = 12,
    campos_obligatorios: tuple[str, ...] = CAMPOS_OBLIGATORIOS,
) -> dict:
    """Valida UNA ficha de clip (dict) contra las reglas editoriales de la
    Fase E. Devuelve un dict PURO (sin red, sin efectos):

        {
          "ok": bool,
          "clip_id": str|None,
          "fallos": [{"campo", "regla", "detalle"}, ...],
          "palabras_habladas": int,
          "max_palabras": int,
          "exceso": str|None,   # el TEXTO que excede el límite, o None
          "dialogo": [str],     # fragmentos entre comillas encontrados
        }
    """
    fallos: list[dict[str, str]] = []
    if not isinstance(clip, dict):
        return {"ok": False, "clip_id": None,
                "fallos": [_fallo("clip", "TIPO", "la ficha debe ser un dict")],
                "palabras_habladas": 0, "max_palabras": max_palabras,
                "exceso": None, "dialogo": []}

    clip_id = clip.get("clip_id") if isinstance(clip.get("clip_id"), str) else None

    # 1 · Campos obligatorios (presentes y no vacíos)
    for campo in campos_obligatorios:
        valor = clip.get(campo)
        if valor is None or (isinstance(valor, str) and not valor.strip()) \
                or (isinstance(valor, (list, tuple, dict)) and len(valor) == 0):
            fallos.append(_fallo(
                campo, "CAMPO_OBLIGATORIO", "ausente o vacío"))

    # 2 · Un solo párrafo en video_prompt (sin saltos de línea)
    prompt = clip.get("video_prompt")
    prompt = prompt if isinstance(prompt, str) else ""
    if prompt:
        if "\n" in prompt.strip():
            fallos.append(_fallo(
                "video_prompt", "PARRAFO_UNICO",
                "contiene saltos de línea; debe ser UN párrafo continuo"))

    # 3 · Nombres de personaje en MAYÚSCULAS
    nombres = _nombres_casting(clip.get("casting"))
    for nombre in nombres:
        if nombre != nombre.upper():
            fallos.append(_fallo(
                "casting", "NOMBRE_MAYUSCULAS",
                f"'{nombre}' no está en MAYÚSCULAS"))
        if prompt:
            apariciones = re.finditer(re.escape(nombre), prompt, re.IGNORECASE)
            alguna = False
            for m in apariciones:
                alguna = True
                if m.group(0) != nombre.upper():
                    fallos.append(_fallo(
                        "video_prompt", "NOMBRE_MAYUSCULAS",
                        f"el nombre '{nombre}' aparece como '{m.group(0)}' "
                        "(debe ir en MAYÚSCULAS en el prompt)"))
            if not alguna:
                fallos.append(_fallo(
                    "video_prompt", "NOMBRE_AUSENTE",
                    f"el personaje '{nombre}' del casting no aparece "
                    "en video_prompt"))

    # 4 · Máximo de palabras habladas (conteo determinista) + texto excedente
    dialogo = extraer_dialogo(prompt) if prompt else []
    palabras = sum(len(_RE_PALABRA.findall(f)) for f in dialogo)
    exceso = _texto_que_excede(prompt, max_palabras) if prompt else None
    if palabras > max_palabras:
        fallos.append(_fallo(
            "video_prompt", "MAX_PALABRAS_HABLADAS",
            f"{palabras} palabras habladas > {max_palabras}; excede: "
            f"\"{exceso}\""))

    # 5 · Estado final presente (el campo ya se exigió arriba; aquí se
    #     valida que sea texto con contenido si vino como str)
    final_state = clip.get("final_state")
    if isinstance(final_state, str) and final_state.strip() == "":
        fallos.append(_fallo(
            "final_state", "ESTADO_FINAL_PRESENTE", "vacío"))

    # 6 · duration_target numérico > 0 e igual al objetivo
    dt = clip.get("duration_target")
    if dt is not None and not isinstance(dt, bool):
        try:
            dt_num = float(dt)
        except (TypeError, ValueError):
            dt_num = None
        if dt_num is None:
            fallos.append(_fallo(
                "duration_target", "DURACION_NUMERICA",
                f"no es numérico: {dt!r}"))
        elif dt_num <= 0:
            fallos.append(_fallo(
                "duration_target", "DURACION_POSITIVA", f"{dt_num} <= 0"))
        elif dt_num != float(duracion_objetivo):
            fallos.append(_fallo(
                "duration_target", "DURACION_OBJETIVO",
                f"{dt_num} != {float(duracion_objetivo)} (objetivo del episodio)"))

    return {
        "ok": not fallos,
        "clip_id": clip_id,
        "fallos": fallos,
        "palabras_habladas": palabras,
        "max_palabras": max_palabras,
        "exceso": exceso,
        "dialogo": dialogo,
    }


def validar_episodio(
    clips: list[dict],
    *,
    duracion_objetivo: float = 10.0,
    clips_por_episodio: int = 6,
    max_palabras: int = 12,
    campos_obligatorios: tuple[str, ...] = CAMPOS_OBLIGATORIOS,
) -> dict:
    """Valida un EPISODIO completo (lista de fichas de clip): número de
    clips, ids únicos, episode_id coherente y cada clip válido.

    Devuelve:
        {
          "ok": bool,
          "n_clips": int,
          "clips_por_episodio": int,
          "fallos_episodio": [{"regla", "detalle"}, ...],
          "clips": [resultado de validar_clip por clip, en orden],
        }
    """
    fallos_ep: list[dict[str, str]] = []
    resultados = [
        validar_clip(c, duracion_objetivo=duracion_objetivo,
                     max_palabras=max_palabras,
                     campos_obligatorios=campos_obligatorios)
        for c in (clips if isinstance(clips, (list, tuple)) else [])
    ]

    if not isinstance(clips, (list, tuple)) or not clips:
        fallos_ep.append({"regla": "EPISODIO_CON_CLIPS",
                          "detalle": "no hay fichas de clip que validar"})
    else:
        if len(clips) != clips_por_episodio:
            fallos_ep.append({
                "regla": "NUM_CLIPS",
                "detalle": f"{len(clips)} clips != {clips_por_episodio}"})
        ids = [c.get("clip_id") for c in clips
               if isinstance(c, dict) and isinstance(c.get("clip_id"), str)]
        duplicados = sorted({i for i in ids if ids.count(i) > 1})
        if duplicados:
            fallos_ep.append({
                "regla": "CLIP_ID_UNICOS",
                "detalle": f"clip_id duplicados: {duplicados}"})
        eps = {c.get("episode_id") for c in clips if isinstance(c, dict)}
        eps.discard(None)
        if len(eps) > 1:
            fallos_ep.append({
                "regla": "EPISODE_ID_COHERENTE",
                "detalle": f"episode_id distintos en el episodio: {sorted(eps)}"})

    return {
        "ok": not fallos_ep and all(r["ok"] for r in resultados),
        "n_clips": len(resultados),
        "clips_por_episodio": clips_por_episodio,
        "fallos_episodio": fallos_ep,
        "clips": resultados,
    }
