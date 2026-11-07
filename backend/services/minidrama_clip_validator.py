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
     regla 4). FUENTE DE VERDAD, en orden de prioridad:
     a) Campo estructurado `dialogue` (lista de {personaje, texto}, como
        pide la ficha de la Fase E; «dialogue» es el nombre que ya usa el
        Production JSON — no se inventan alias). Cuenta SOLO el texto de
        sus entradas; el prompt NO se escanea; sin avisos.
     b) Si `dialogue` falta (o no contiene texto extraíble), heurística
        sobre `video_prompt` (DOCUMENTADA, determinista):
        - comillas ("...", “…” o «...») → hablado;
        - segmentos entre RAYAS (—…—) sin comillas dentro → hablado SOLO
          si la raya de apertura cumple la REGLA DE LA RAYA: abre diálogo
          si va (i) al inicio de línea (o del texto), (ii) tras verbo de
          habla (dice, grita, susurra, responde, pregunta) o (iii) tras
          «:». Un par de rayas usado como ACOTACIÓN dentro de una frase
          narrativa (p. ej. «El sol —que ya caía— quemaba el camino»)
          NO cuenta: es el falso positivo corregido (R6).
        - texto tras VERBO DE HABLA + ":" (dice, grita, susurra, responde,
          pregunta) hasta fin de oración (punto o salto) → hablado, SOLO
          si ese resto no empieza por comilla o raya (no se duplica lo ya
          contado).
        Cada fragmento hallado por (rayas/verbo) genera el AVISO
        DIALOGO_SIN_COMILLAS: el clip sigue validando si no excede el
        límite, pero el aviso pide mover el diálogo a comillas o al campo
        `dialogue`.
     - Token = secuencia alfanumérica (acentos y ñ incluidas); números en
       cifra = 1 palabra, escritos en letras = sus tokens; compuesto con
       guion = 2 palabras; la raya de apertura no añade tokens; muletillas
       cuentan.
     - Si el límite se excede, el resultado DEVUELVE EL TEXTO QUE EXCEDE
       (`exceso`: las palabras a partir de la límite+1) junto a
       `dialogo` (fragmentos contados) y el total.
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

# Fragmentos de diálogo hablado entre comillas: rectas, curvas o angulares.
_RE_DIALOGO = re.compile(r'«([^»]*?)»|"([^"]*?)"|“([^”]*?)”')

# Heurística (fuente b, ver docstring): rayas —…— y verbo de habla + «:».
# REGLA DE LA RAYA (R6): un par —…— solo abre diálogo si la raya de
# apertura va tras verbo de habla, tras «:» o al inicio de línea; un par
# usado como acotación narrativa («El sol —que ya caía— quemaba…») NO
# cuenta. La condición se aplica en _raya_abre_dialogo.
_RE_RAYA = re.compile(r"—([^—\n]+?)—")
_VERBOS_HABLA = ("dice", "grita", "susurra", "responde", "pregunta")
_RE_VERBO_HABLA = re.compile(
    r"\b(?:" + "|".join(_VERBOS_HABLA) + r")\s*:\s*([^.«»“\"\n]*)",
    re.IGNORECASE)
_RE_ULTIMA_PALABRA = re.compile(r"([0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)$")

# Claves aceptadas en el campo estructurado `dialogue` (Production JSON).
_CLAVES_PERSONAJE = ("personaje", "speaker", "name", "nombre")
_CLAVES_TEXTO = ("texto", "text", "line")


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


def _dialogue_estructurado(dialogue: Any) -> tuple[list[str], list[str], bool]:
    """Fragmentos hablados desde el campo estructurado `dialogue`
    (lista de {personaje, texto}). Devuelve (fragmentos, avisos, util).
    `util` es False si el campo no sirve como fuente de verdad (no es
    lista o sus entradas no traen texto) — el llamador cae entonces a la
    heurística del prompt."""
    if not isinstance(dialogue, (list, tuple)):
        avisos = ["DIALOGUE_MALFORMADO"] if dialogue not in (None, "") else []
        return [], avisos, False
    if not dialogue:
        return [], [], True  # lista vacía explícita = sin diálogo
    frags: list[str] = []
    avisos: list[str] = []
    malformados = 0
    for item in dialogue:
        if isinstance(item, str):
            if item.strip():
                frags.append(item)
            continue
        if not isinstance(item, dict):
            malformados += 1
            continue
        texto = next((item.get(c) for c in _CLAVES_TEXTO
                      if isinstance(item.get(c), str) and item.get(c).strip()),
                     None)
        if texto is None:
            malformados += 1
            continue
        frags.append(texto)
    if malformados:
        avisos.append("DIALOGUE_MALFORMADO")
    return frags, avisos, bool(frags)


def _raya_abre_dialogo(texto: str, inicio: int) -> bool:
    """REGLA DE LA RAYA (R6, determinista): la raya que abre en `inicio`
    solo abre diálogo si (i) va al inicio de línea (o del texto), (ii) va
    tras verbo de habla (dice, grita, susurra, responde, pregunta) o
    (iii) va tras «:». Pares de rayas como acotación dentro de una frase
    narrativa («El sol —que ya caía— quemaba el camino») NO cuentan."""
    linea_previa = texto[:inicio].rsplit("\n", 1)[-1]
    if not linea_previa.strip():            # (i) inicio de línea / del texto
        return True
    previo = linea_previa.rstrip()
    if previo.endswith(":"):                # (iii) tras dos puntos
        return True
    m = _RE_ULTIMA_PALABRA.search(previo)   # (ii) tras verbo de habla
    return bool(m and m.group(1).lower() in _VERBOS_HABLA)


def _fragmentos_heuristicos(texto: str) -> tuple[list[str], int]:
    """Fuente (b), ver docstring: comillas + rayas —…— (REGLA DE LA RAYA:
    solo tras verbo de habla, «:» o inicio de línea) + verbo de habla.
    Devuelve (fragmentos, nº de fragmentos hallados FUERA de comillas).
    El texto tras verbo no se cuenta si empieza por comilla/raya (ya se
    cuenta por otra vía — nunca se duplica)."""
    if not isinstance(texto, str):
        return [], 0
    frags: list[str] = []
    fuera = 0
    for m in _RE_DIALOGO.finditer(texto):
        frags.append(m.group(1) or m.group(2) or m.group(3) or "")
    residuo = _RE_DIALOGO.sub("«»", texto)   # comillas ya contadas («» bloquea)
    for m in _RE_RAYA.finditer(residuo):
        frag = (m.group(1) or "").strip()
        if not frag:
            continue
        if not _raya_abre_dialogo(residuo, m.start()):
            continue                         # acotación narrativa (R6)
        frags.append(frag)
        fuera += 1
    residuo = _RE_RAYA.sub("«»", residuo)    # rayas ya contadas («» bloquea)
    for m in _RE_VERBO_HABLA.finditer(residuo):
        frag = (m.group(1) or "").strip()
        if frag and frag[:1] not in ('"', "“", "«", "—"):
            frags.append(frag)
            fuera += 1
    return frags, fuera


def _texto_que_excede(fragmentos: list[str], limite: int) -> str | None:
    """Palabras habladas desde la límite+1 en adelante (el texto que
    excede el límite), o None si no excede."""
    restantes = limite
    for frag in fragmentos:
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
          "avisos": [{"campo", "regla", "detalle"}, ...],  # no afectan ok
          "fuente_conteo": "dialogue"|"video_prompt"|"ninguna",
          "palabras_habladas": int,
          "max_palabras": int,
          "exceso": str|None,   # el TEXTO que excede el límite, o None
          "dialogo": [str],     # fragmentos contados (fuente de verdad)
        }
    """
    fallos: list[dict[str, str]] = []
    if not isinstance(clip, dict):
        return {"ok": False, "clip_id": None,
                "fallos": [_fallo("clip", "TIPO", "la ficha debe ser un dict")],
                "avisos": [], "fuente_conteo": "ninguna",
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

    # 4 · Máximo de palabras habladas — fuente de verdad: campo
    #     estructurado `dialogue`; si no sirve, heurística del prompt
    #     (ver docstring). Los avisos NO afectan `ok`.
    avisos: list[dict[str, str]] = []
    frag_struct, avisos_dial, util = _dialogue_estructurado(
        clip.get("dialogue"))
    if util:
        dialogo = frag_struct
        fuente = "dialogue"
    else:
        dialogo, fuera = _fragmentos_heuristicos(prompt)
        fuente = "video_prompt" if dialogo else "ninguna"
        if fuera:
            avisos.append(_fallo(
                "video_prompt", "DIALOGO_SIN_COMILLAS",
                f"{fuera} fragmento(s) hablado(s) fuera de comillas "
                "(rayas o verbo de habla); muévelos a comillas o al "
                "campo `dialogue`"))
    for codigo in avisos_dial:
        avisos.append(_fallo(
            "dialogue", codigo,
            "el campo `dialogue` no aporta texto utilizable; se contó "
            "con la heurística del prompt"))
    palabras = sum(len(_RE_PALABRA.findall(f)) for f in dialogo)
    exceso = _texto_que_excede(dialogo, max_palabras)
    if palabras > max_palabras:
        fallos.append(_fallo(
            "dialogue" if fuente == "dialogue" else "video_prompt",
            "MAX_PALABRAS_HABLADAS",
            f"{palabras} palabras habladas > {max_palabras}; excede: "
            f"\"{exceso}\""))

    # 4b · Personaje del campo `dialogue` en MAYÚSCULAS (misma regla 3)
    if isinstance(clip.get("dialogue"), (list, tuple)):
        for item in clip["dialogue"]:
            if not isinstance(item, dict):
                continue
            per = next((item.get(c) for c in _CLAVES_PERSONAJE
                        if isinstance(item.get(c), str)
                        and item.get(c).strip()), None)
            if per and per != per.upper():
                fallos.append(_fallo(
                    "dialogue", "NOMBRE_MAYUSCULAS",
                    f"'{per}' no está en MAYÚSCULAS"))

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
        "avisos": avisos,
        "fuente_conteo": fuente,
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
