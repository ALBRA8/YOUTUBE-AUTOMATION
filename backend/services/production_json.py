"""v2.16 · Contrato production_json — el puente entre el CREATIVE ENGINE
(generador de Production JSON por nicho) y la fábrica.

CAMBIOS v2.15 (cierre del contrato Creative Engine → Adapter → Factory):
  A. Normalización MECÁNICA ampliada (sin tocar intención creativa):
     - título de proyecto: title | name
     - duración de unidad: duration | duration_seconds
     - format: string («short», «9:16»…) U objeto ({"aspect_ratio": "9:16"});
       si el objeto trae aspect_ratio manda; si no, format.type; el resto
       del objeto viaja íntegro en production.json (nunca se descarta).
  B. DOS niveles de validación:
     1) ESTRUCTURAL (validate): ¿el envelope puede interpretarse?
     2) EJECUCIÓN (validate_execution): ¿cada unidad trae los datos
        creativos que la fábrica necesita para ejecutarse? Los faltantes se
        REPORTAN con unidad/campo/por qué/fuente esperada. El Adapter NUNCA
        inventa contenido ni convierte prompt_generation_rules en prompts.
     image_prompt es obligatorio para la EJECUCIÓN ACTUAL de generación de imágenes,
     pero NO bloquea la INGESTA ni el dry-run: si falta, se conserva la unidad
     como incompleta y la validación de ejecución la marca como bloqueante.
     El Adapter nunca inventa el prompt. La ausencia de duration se reporta
     como dato creativo faltante para timing (no bloqueante).

DIFERENCIA con guion_json (que queda INTACTO como la otra puerta):
  guion_json      = contrato rígido de guion terminado (narración obligatoria).
  production_json = envelope GENÉRICO de nichos: el Adapter traduce cada
                    unidad creativa al modelo de ejecución interno SIN
                    imponer estructura narrativa ni tocar lo específico
                    del nicho (Miniatures, Recipes, Frutinovelas y los que
                    vengan — cero ramas if/else por nicho).

PRINCIPIOS (spec aprobada — ver GET /api/production_json/contrato):
  1. NO hay esquema universal de nicho: lo desconocido se CONSERVA verbatim
     en meta.unit (nunca se interpreta, nunca se descarta).
  2. La fábrica no regenera contenido creativo: solo normalizaciones
     mecánicas seguras (alias ES/EN, ids sintéticos), todas registradas.
  3. narration es lo ÚNICO que llega a TTS. dialogue-LISTA (lipsync) se
     conserva verbatim y NUNCA se convierte en voz; dialogue-STRING es la voz
     del dialecto Creative Engine → se mapea a narration (registrado en
     avisos). Sin narración no se inventa audio (meta.tts_skip → silencio a
     la duración objetivo en tts_step).
  4. duration_target se conserva SEPARADO de la duración real; la desviación
     la registra el orquestador tras el TTS (nunca se reescribe el pedido).
  5. video_prompt (motion) se conserva pero NO es obligatorio para la
     ejecución actual; se aceptan equivalentes (motion_prompt/prompt_video…).
  6. El Production JSON original se guarda COMPLETO como production.json
     dentro de la carpeta del proyecto + referencia sha256 en meta
     (auditoría, debugging, regeneración, versionado, trazabilidad).
  7. Cero columnas SQLite nuevas: todo vive en scenes.meta / projects.meta /
     production.json. Sin cambios de carpetas, cache, backups, Flow,
     proveedores ni navegador.

Aquí NO hay LLM interno: valida, traduce a unidades ejecutables y crea el
proyecto listo para el pipeline (imágenes en adelante).
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import database as db
from config import OUTPUT_DIR
from services import camera_recipes

# ── límites y constantes del contrato ─────────────────────────────────────
ERR = "Creative Production JSON validation error"
MAX_TITULO = 60
MAX_TITULO_UNIDAD = 80
MAX_OUTFIT = 120
MAX_AMBIENTE = 200
PLATAFORMAS = ("youtube", "tiktok", "instagram", "facebook")

# alias mecánicos aceptados por campo (equivalentes se normalizan y el alias
# original queda registrado en meta.production_unit.prompt_sources)
_ALIASES = {
    "sequence": ("sequence", "units", "shots", "scenes", "beats"),
    "titulo": ("titulo", "title", "título", "name"),
    "formato": ("formato", "format", "aspect"),
    "estilo": ("estilo", "style"),
    "voz": ("voz", "voice"),
    "avatar_id": ("avatar_id", "avatar", "personaje"),
    "nicho": ("nicho", "niche", "carpeta"),
    "plataformas": ("plataformas", "platforms"),
    "auto_start": ("auto_start", "autoStart", "auto"),
    "continuity": ("continuity", "continuidad"),
    # ── por unidad ──
    "unidad_id": ("id", "unit_id", "scene_id", "shot_id", "beat_id", "slug"),
    "unidad_tipo": ("type", "unit_type", "kind", "role"),
    "titulo_unidad": ("title", "titulo", "título", "name", "label"),
    "narracion": ("narration", "narracion", "narración", "voiceover",
                  "voice_over", "voz_off", "voz"),
    "dialogue": ("dialogue", "dialogo", "diálogo", "dialogues"),
    "image_prompt": ("image_prompt", "visual_prompt", "prompt_image",
                     "prompt_imagen", "image prompt", "visual prompt"),
    "video_prompt": ("video_prompt", "motion_prompt", "prompt_video",
                     "video prompt", "motion prompt", "prompt_movimiento"),
    "camera": ("camera", "camara", "cámara", "camera_recipe"),
    "environment": ("environment", "ambiente", "setting"),
    "outfit": ("outfit", "vestuario", "wardrobe", "atuendo", "clothing"),
    "references": ("references", "referencias", "refs", "reference_images"),
    "audio": ("audio", "audio_design", "sound", "sound_design"),
    "duration": ("duration", "duration_seconds", "duration_target",
                 "target_duration", "duracion", "duración"),
}


def _first(d: dict, canonical: str):
    """Primer valor presente del campo (por alias) en d."""
    for k in _ALIASES.get(canonical, (canonical,)):
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return None


def _consume(d: dict, canonical: str, as_str: bool = False):
    """Primer valor por alias + la clave consumida. Con as_str=True salta
    valores no-string (siguen buscando su alias correcto o quedan verbatim).
    → (valor, clave_consumida | None)"""
    for k in _ALIASES.get(canonical, (canonical,)):
        if isinstance(d, dict) and k in d and d[k] is not None:
            if as_str and not isinstance(d[k], str):
                continue
            return d[k], k
    return None, None


def _limpia(s) -> str:
    return str(s or "").strip()


# normalización MECÁNICA de formato (equivalencias aceptadas, cero creatividad)
_MAP_FORMATO = {
    "short": "short", "shorts": "short", "vertical": "short",
    "reel": "short", "reels": "short", "9:16": "short", "9x16": "short",
    "long": "long", "horizontal": "long", "landscape": "long",
    "16:9": "long", "16x9": "long", "longform": "long", "largo": "long",
}


def _formato_desde_valor(v, av: list, norm: list) -> str:
    """format → "short"|"long" — SOLO equivalencias mecánicas registradas.

    Acepta string («short», «9:16», «vertical»…) u objeto (el Creative
    Engine puede mandar {"aspect_ratio": "9:16", ...} o {"type": "short"}).
    En el objeto manda aspect_ratio; si no hay, type. Las demás claves del
    objeto NO se pierden: el Production JSON original viaja íntegro a
    production.json. Devuelve short|long y registra la equivalencia usada.
    """
    if isinstance(v, dict):
        ratio = v.get("aspect_ratio") or v.get("aspectRatio") or v.get("ratio")
        tipo = v.get("type") or v.get("format")
        fuente, crudo = ("aspect_ratio", ratio) if ratio else ("type", tipo)
        crudo = crudo.strip() if isinstance(crudo, str) else None
        if not crudo:
            av.append("format objeto sin aspect_ratio/type interpretable — "
                      "uso short (9:16); el objeto completo viaja íntegro "
                      "en production.json")
            return "short"
        m = _MAP_FORMATO.get(crudo.lower())
        if m is None:
            bajo = crudo.lower()
            if "vertical" in bajo or "9:16" in bajo or "9x16" in bajo:
                m = "short"
            elif "horizontal" in bajo or "16:9" in bajo or "16x9" in bajo:
                m = "long"
            else:
                av.append(f"format.{fuente} «{crudo}» desconocido — uso "
                          "short (9:16); el objeto completo viaja íntegro "
                          "en production.json")
                return "short"
        norm.append(f"format objeto → {fuente} «{crudo}» → {m} "
                    "(normalización mecánica; objeto íntegro en "
                    "production.json)")
        return m
    s = _limpia(v).lower()
    if not s:
        return "short"
    m = _MAP_FORMATO.get(s)
    if m:
        return m
    av.append(f"formato «{s}» desconocido — uso short (9:16)")
    return "short"


def parse_payload(payload) -> dict:
    """Acepta dict, str JSON o str con fences ```json …``` → dict."""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", "replace")
    if not isinstance(payload, str) or not payload.strip():
        raise ValueError(f"{ERR}: payload vacío — envía el Creative "
                         "Production JSON (objeto o string JSON)")
    txt = payload.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", txt, re.DOTALL)
    if m:
        txt = m.group(1)
    try:
        data = json.loads(txt)
    except json.JSONDecodeError as e:
        raise ValueError(f"{ERR}: JSON inválido: {e}")
    if not isinstance(data, dict):
        raise ValueError(f"{ERR}: el JSON debe ser un objeto (envelope)")
    return data


# ── validación + adaptación (el corazón del Adapter) ──────────────────────
def validate(data: dict, estilos_validos: set[str],
             production_id: str | None = None) -> tuple[dict, list[str], list[str]]:
    """Envelope → (modelo de ejecución, avisos, normalizaciones).

    - avisos: decisiones tolerantes que NO impiden la producción.
    - normalizaciones: mecánicas seguras, todas registradas.
    Lanza ValueError con mensajes «Creative Production JSON validation error: …»
    cuando falta algo ESTRUCTURAL (identificación, sequence).
    """
    av: list[str] = []
    norm: list[str] = []

    # ── 1. envelope: project (string o dict) + sequence ──
    project = data.get("project")
    if isinstance(project, str):
        project = {"title": project}
    if not isinstance(project, dict):
        project = {}

    # Campos de envelope/proyecto que el Adapter interpreta mecánicamente.
    # Todo lo demás se conserva verbatim para que los Blueprints puedan
    # ampliar el contrato sin exigir ramas nuevas en el Builder.
    _project_consumed = set()
    for canon in ("titulo", "formato", "estilo", "voz", "avatar_id",
                  "nicho", "plataformas", "auto_start", "continuity", "camera"):
        _project_consumed.update(_ALIASES.get(canon, (canon,)))
    project_extra = {k: copy.deepcopy(v) for k, v in project.items()
                     if k not in _project_consumed and k not in _ALIASES["sequence"]}
    _root_consumed = {"project"}
    for canon in ("titulo", "formato", "estilo", "voz", "avatar_id",
                  "nicho", "plataformas", "auto_start", "continuity", "camera"):
        _root_consumed.update(_ALIASES.get(canon, (canon,)))
    _root_consumed.update(_ALIASES["sequence"])
    root_extra = {k: copy.deepcopy(v) for k, v in data.items()
                  if k not in _root_consumed}

    def _pf(canon: str):
        v = _first(project, canon)
        return _first(data, canon) if v is None else v

    titulo = _limpia(_pf("titulo"))
    if not titulo:
        raise ValueError(f"{ERR}: proyecto no identificable — añade "
                         "project.title (o title en la raíz del envelope)")
    g_titulo = titulo[:MAX_TITULO]
    if len(titulo) > MAX_TITULO:
        norm.append(f"titulo del proyecto recortado a {MAX_TITULO} caracteres "
                    "(el original vive intacto en production.json)")

    seq_raw, seq_key = None, None
    for k in _ALIASES["sequence"]:
        if isinstance(data.get(k), list):
            seq_raw, seq_key = data[k], k
            break
        if isinstance(project.get(k), list):
            seq_raw, seq_key = project[k], f"project.{k}"
            break
    if seq_raw is None:
        raise ValueError(f"{ERR}: sequence no encontrada — el envelope debe "
                         "traer una lista de unidades (sequence[])")
    if not seq_raw:
        raise ValueError(f"{ERR}: sequence vacía — se requiere al menos 1 unidad")
    if seq_key != "sequence":
        norm.append(f"sequence localizada en «{seq_key}» "
                    "(alias mecánico, contenido intacto)")

    # ── 2. campos de proyecto ──
    formato = _formato_desde_valor(_pf("formato"), av, norm)

    estilo = _limpia(_pf("estilo")).lower() or "auto"
    if estilo not in estilos_validos:
        av.append(f"estilo «{estilo}» no existe — uso auto")
        estilo = "auto"

    voz = _limpia(_pf("voz")) or None
    avatar_id = _limpia(_pf("avatar_id")) or None
    nicho = _limpia(_pf("nicho"))[:60] or None

    plats = _pf("plataformas")
    if not isinstance(plats, list):
        plats = ["youtube"]
    plats = [str(p).strip().lower() for p in plats]
    buenas = [p for p in plats if p in PLATAFORMAS]
    if len(buenas) < len(plats):
        av.append("plataformas ignoradas: "
                  + ", ".join(p for p in plats if p not in PLATAFORMAS))

    # receta de cámara por defecto del proyecto (opcional)
    cam_p = _limpia(_pf("camera")).lower()
    camara_proyecto = None
    if cam_p:
        if cam_p in camera_recipes.ids():
            camara_proyecto = cam_p
        else:
            av.append(f"cámara de proyecto «{cam_p}» no es receta de la "
                      "fábrica — no se aplica (el original vive en "
                      "production.json; cada unidad conserva la suya verbatim)")

    continuity = _first(data, "continuity")
    if continuity is None:
        continuity = project.get("continuity")

    auto = _pf("auto_start")
    auto_start = bool(auto) if auto is not None else False

    # ── 3. unidades → modelo de ejecución ──
    escenas: list[dict] = []
    for i0, u in enumerate(seq_raw):
        i = i0 + 1   # 1-based para humanos; sequence[i0] 0-based en errores
        if not isinstance(u, dict):
            raise ValueError(f"{ERR}: sequence[{i0}] debe ser un objeto, "
                             f"no {type(u).__name__}")

        consumidas: set[str] = set()  # solo las claves realmente mapeadas
        # las no-consumidas van verbatim a meta.unit (cero pérdida)

        def c(canon, as_str=False):
            v, k = _consume(u, canon, as_str)
            if k:
                consumidas.add(k)
            return v

        def ck(canon, as_str=False):
            """Como c() pero devuelve (valor, alias_consumido)."""
            v, k = _consume(u, canon, as_str)
            if k:
                consumidas.add(k)
            return v, k

        uid = _limpia(c("unidad_id", as_str=True))
        if not uid:
            tipo_guess = _limpia(_first(u, "unidad_tipo") if
                                 isinstance(_first(u, "unidad_tipo"), str) else "")
            uid = f"{tipo_guess or 'unit'}_{i0:03d}"
            norm.append(f"sequence[{i0}]: id sintético «{uid}» "
                        "(la unidad no traía id — mecánico, no creativo)")
        tipo_raw = c("unidad_tipo", as_str=True)
        utipo = _limpia(tipo_raw) or "scene"
        rut = _limpia(c("titulo_unidad", as_str=True))[:MAX_TITULO_UNIDAD] \
            or f"Unidad {i} · {uid}"

        # 3a. prompts — image opcional en INGESTA, requerido para la
        # ejecución actual de generación de imágenes; video opcional.
        # El Adapter conserva la ausencia y NO inventa el prompt ni deriva
        # uno de prompt_generation_rules. validate_execution() lo reporta
        # como bloqueante para la ejecución actual.
        img, img_alias = ck("image_prompt", as_str=True)
        img = _limpia(img) or None

        vid, vid_alias = ck("video_prompt", as_str=True)
        video_prompt = _limpia(vid) or None
        if video_prompt is None and _first(u, "video_prompt") is not None:
            # motion/video prompt no-string (dict de motion, lista…) → verbatim
            av.append(f"sequence[{i0}]: prompt de video no-string — conservado "
                      "verbatim en meta.unit (no se normaliza)")

        # 3b. narración / diálogo — dialogue-LISTA es guion de lipsync y NUNCA
        # es TTS; dialogue-STRING es la voz del dialecto Creative Engine
        # (Frutinovelas, Miniatures, Recipes…) → se mapea a narration. Fix de
        # regresión: v2.14 dejaba ese texto sin NINGÚN ejecutor y producía
        # videos mudos marcados ready (la voz quedaba varada en meta.unit).
        narr = _limpia(c("narracion", as_str=True))
        dialogo = c("dialogue")
        if not narr and isinstance(dialogo, str):
            narr = _limpia(dialogo)
            if narr:
                av.append(f"sequence[{i0}]: dialogue(string) → narration — "
                          "es la voz del dialecto Creative Engine "
                          "(conservado verbatim en meta.unit)")
        tts_skip = not narr  # sin narración no se inventa voz ni se lee el título

        # 3c. duración objetivo (se conserva SEPARADA de la real)
        # duration y duration_seconds son alias mecánicos; el alias usado
        # queda registrado (duration_source) como toda equivalencia mecánica
        target, dur_alias = ck("duration")
        duration_target = None
        if target is not None:
            try:
                duration_target = float(target)
            except (TypeError, ValueError):
                raise ValueError(
                    f"{ERR}: sequence[{i0}].duration debe ser un número "
                    f"positivo, llegó {_limpia(target)[:40]!r}")
            if duration_target <= 0:
                raise ValueError(
                    f"{ERR}: sequence[{i0}].duration debe ser un número "
                    f"positivo, llegó {duration_target}")

        # 3d. cámara: receta de fábrica si coincide; verbatim siempre
        cam_u = _limpia(c("camera", as_str=True))
        cam_receta, cam_verbatim = None, (cam_u or None)
        if cam_u and cam_u.lower() in camera_recipes.ids():
            cam_receta = cam_u.lower()
            if cam_receta != cam_u:
                norm.append(f"sequence[{i0}]: cámara «{cam_u}» → receta "
                            f"«{cam_receta}»")

        # 3e. entorno / vestuario / referencias / audio / continuidad
        amb_raw = _limpia(c("environment", as_str=True))
        ambiente = amb_raw[:MAX_AMBIENTE] or None
        if len(amb_raw) > MAX_AMBIENTE:
            av.append(f"sequence[{i0}]: environment recortado a "
                      f"{MAX_AMBIENTE} caracteres")
        out_raw = _limpia(c("outfit", as_str=True))
        outfit = out_raw[:MAX_OUTFIT] or None
        if len(out_raw) > MAX_OUTFIT:
            av.append(f"sequence[{i0}]: outfit recortado a {MAX_OUTFIT} "
                      "caracteres")
        referencias = c("references")
        audio = c("audio")
        cont_u = c("continuity")

        # 3f. TODO lo específico del nicho va verbatim (sin interpretar)
        unidad_verbatim = {k: copy.deepcopy(v) for k, v in u.items()
                           if k not in consumidas}

        # ── modelo de ejecución interno (contrato del Builder) ──
        punit = {
            "id": uid,
            "index": i0,
            "type": utipo,
            "title": rut,
            "duration_target": duration_target,
            "duration_source": dur_alias if duration_target is not None
                               else None,
            "duration_actual": None,      # lo registra el orquestador tras TTS
            "duration_deviation": None,
            "narration": narr or None,
            "dialogue": copy.deepcopy(dialogo),   # LISTA = lipsync verbatim;
                                                  # STRING ya mapeó a narration
            "image_prompt": img,                  # puede ser None en ingesta
            "video_prompt": video_prompt,         # conservado, no obligatorio
            "execution_requirements": {
                "image_generation": bool(img),
                "image_prompt_required_by_current_executor": True,
            },
            "prompt_sources": {"image": img_alias,
                               "video": vid_alias if video_prompt else None},
            "camera": {"recipe": cam_receta, "verbatim": cam_verbatim},
            "environment": ambiente,
            "outfit": outfit,
            "references": copy.deepcopy(referencias),
            "audio": copy.deepcopy(audio),        # nunca interpretado
            "continuity": copy.deepcopy(cont_u),  # nunca interpretado
            "tts_skip": tts_skip,
        }

        meta_esc: dict = {
            "production_unit": punit,
            # claves planas que consumen images.py / tts_step (convención ya
            # existente del contrato guion_json: meta.camara/outfit/ambiente)
            "tts_skip": tts_skip,
        }
        if duration_target is not None:
            meta_esc["duration_target"] = duration_target
        if cam_receta:
            meta_esc["camara"] = cam_receta
        if ambiente:
            meta_esc["ambiente"] = ambiente
        if outfit:
            meta_esc["outfit"] = outfit
        if unidad_verbatim:
            meta_esc["unit"] = unidad_verbatim

        escenas.append({
            "title": rut,
            "narration": narr,          # "" si no hay — TTS lo respeta
            "image_prompt": img or "",
            "duration": 0.0,            # columna = duración REAL (la fija el pipeline)
            "status": "pending",
            "meta": meta_esc,
        })

    g = {
        "titulo": g_titulo,
        "formato": formato,
        "estilo": estilo,
        "voz": voz,
        "avatar_id": avatar_id,
        "nicho": nicho,
        "plataformas": buenas or ["youtube"],
        "camara": camara_proyecto,
        "escenas": escenas,
        "auto_start": auto_start,
        "continuity": copy.deepcopy(continuity) if continuity is not None else None,
        "project_extra": project_extra,
        "root_extra": root_extra,
        "production": {
            "adapter": "production_json/v2.16.1",
            "production_id": production_id,
            "unidades": len(escenas),
            "sequence_key": seq_key,
            "titulos": [e["title"] for e in escenas],
            "avisos": av,
            "normalizaciones": norm,
            "ingestado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    }
    return g, av, norm


# ── validación de EJECUCIÓN (nivel 2 — qué necesita cada unidad) ──────────
_MOTIVO_IMG = ("la fábrica genera la imagen de la unidad a partir de ese "
               "prompt; sin él la unidad no puede ejecutarse")
_FUENTE_IMG = ("sequence[{i}].image_prompt (o equivalente mecánico: "
               "visual_prompt / prompt_image / prompt_imagen) — lo provee el "
               "CREATIVE ENGINE; las reglas globales (prompt_generation_"
               "rules) NO sustituyen el prompt concreto por unidad")
_MOTIVO_DUR = ("la fábrica necesita la duración pedida para respetar el "
               "timing creativo de la unidad (TTS / edición / render)")
_IMPACTO_DUR = ("no bloqueante: el pipeline usa su duración mecánica por "
                "defecto y registra la desviación tras el TTS "
                "(duration_target queda None)")
_FUENTE_DUR = ("sequence[{i}].duration (o duration_seconds) — lo provee el "
               "CREATIVE ENGINE")


def validate_execution(data: dict) -> dict:
    """Nivel 2 — VALIDACIÓN DE EJECUCIÓN (complementa la estructural).

    Comprueba unidad por unidad que existan los datos creativos que la
    fábrica realmente necesita para ejecutar:
      - image_prompt (string) → BLOQUEANTE: sin él no hay generación de imagen.
      - duration → dato creativo faltante para el timing; se REPORTA (no
        bloqueante: existe duración mecánica por defecto en el pipeline).
      - video/motion_prompt ausente → solo contador informativo (hoy el
        pipeline no lo exige).

    Los requisitos se derivan de lo que el pipeline ejecuta, NO del nicho:
    nunca se exige dialogue/narration/lipsync/cliffhanger/ingredients ni
    ningún campo creativo específico. El Adapter NO inventa ni deriva
    contenido: cada faltante se reporta con unidad, campo, por qué y fuente
    esperada para que lo provea el Creative Engine. No lanza excepciones.
    """
    seq = None
    for k in _ALIASES["sequence"]:
        if isinstance(data.get(k), list):
            seq = data[k]
            break
        proj = data.get("project")
        if isinstance(proj, dict) and isinstance(proj.get(k), list):
            seq = proj[k]
            break

    reporte: dict = {
        "nivel": "ejecucion",
        "politica": "el Adapter NO inventa contenido creativo: cada faltante "
                    "se reporta para que lo provea el Creative Engine",
        "unidades_auditadas": 0,
        "unidades_ejecutables": 0,
        "unidades_bloqueadas": 0,
        "unidades_con_faltantes_no_bloqueantes": 0,
        "unidades_sin_video_prompt": 0,
        "unidades_con_faltantes": [],
    }
    if not isinstance(seq, list):
        reporte["nota"] = ("sequence no interpretable — la validación "
                           "estructural (validate) reporta el problema")
        return reporte

    for i0, u in enumerate(seq):
        if not isinstance(u, dict):
            continue
        reporte["unidades_auditadas"] += 1
        raw_id = _first(u, "unidad_id")
        uid = str(raw_id) if raw_id is not None else f"unit_{i0:03d}"
        raw_tipo = _first(u, "unidad_tipo")
        utipo = _limpia(raw_tipo) if isinstance(raw_tipo, str) else ""
        utipo = utipo or "scene"

        faltantes: list[dict] = []

        img, _ = _consume(u, "image_prompt", as_str=True)
        if not _limpia(img):
            faltantes.append({
                "campo": "image_prompt", "bloqueante": True,
                "motivo": _MOTIVO_IMG,
                "fuente_esperada": _FUENTE_IMG.format(i=i0)})

        dur, _ = _consume(u, "duration")
        if dur is None:
            faltantes.append({
                "campo": "duration", "bloqueante": False,
                "motivo": _MOTIVO_DUR, "impacto": _IMPACTO_DUR,
                "fuente_esperada": _FUENTE_DUR.format(i=i0)})

        vid, _ = _consume(u, "video_prompt", as_str=True)
        if not _limpia(vid):
            reporte["unidades_sin_video_prompt"] += 1

        if faltantes:
            reporte["unidades_con_faltantes"].append({
                "unidad": f"sequence[{i0}]", "id": uid, "tipo": utipo,
                "faltantes": faltantes})
            if any(f["bloqueante"] for f in faltantes):
                reporte["unidades_bloqueadas"] += 1
            else:
                reporte["unidades_con_faltantes_no_bloqueantes"] += 1
        else:
            reporte["unidades_ejecutables"] += 1
    return reporte


# ── conservación del original (trazabilidad) ──────────────────────────────
def save_original(pid: str, payload) -> dict:
    """Guarda el Production JSON original COMPLETO como production.json en la
    carpeta del proyecto. Si llegó string se escribe byte-a-byte; si llegó
    dict se serializa canónico. Devuelve la referencia para meta."""
    d = OUTPUT_DIR / pid
    d.mkdir(parents=True, exist_ok=True)
    out = d / "production.json"
    if isinstance(payload, (bytes, bytearray)):
        raw = bytes(payload)
    elif isinstance(payload, str):
        raw = payload.strip().encode("utf-8")
    else:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    out.write_bytes(raw)
    return {
        "file": "production.json",
        "path": str(out),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


# ── ingesta completa (paridad con guion_json.ingest) ──────────────────────
async def ingest(payload, estilos_validos: set[str], crear_proyecto,
                 auto_start_override=None) -> dict:
    """parse → validate → crear proyecto → escenas → production.json → arrancar.

    `crear_proyecto(g)` lo pasa main.py (crea la fila con mode=production_json
    y meta.production_json). Lanza ValueError con mensajes listos para el
    Creative Engine externo.
    """
    data = parse_payload(payload)
    proj = data.get("project")
    production_id = data.get("id") or (
        proj.get("id") if isinstance(proj, dict) else None)
    g, avisos, norm = validate(data, estilos_validos, production_id=production_id)
    if auto_start_override is not None:
        g["auto_start"] = bool(auto_start_override)

    # Preflight antes de crear/lanzar: una ingesta con lanzar=false puede
    # conservar unidades incompletas; una ejecución no puede arrancar si el
    # executor actual de imágenes carece de image_prompt.
    exec_report = validate_execution(data)
    if g["auto_start"] and exec_report.get("unidades_bloqueadas"):
        faltantes = []
        for item in exec_report.get("unidades_con_faltantes", []):
            for f in item.get("faltantes", []):
                if f.get("bloqueante"):
                    faltantes.append(f"{item['unidad']} ({item['id']}): {f['campo']}")
        raise ValueError(
            f"{ERR}: no se puede lanzar el pipeline; faltan datos "
            f"creativos bloqueantes para la ejecución actual: "
            + "; ".join(faltantes)
            + ". El Adapter no inventa prompts; completa el Production "
            "JSON desde el Creative Engine y reintenta."
        )

    project = crear_proyecto(g)
    pid = project["id"]
    db.replace_scenes(pid, g["escenas"])

    ref = save_original(pid, payload)
    meta = dict(project.get("meta") or {})
    pj = dict(meta.get("production_json") or {})
    pj.update(ref)
    pj["unidades"] = len(g["escenas"])
    pj["formato"] = g["formato"]
    pj["avisos"] = avisos
    pj["normalizaciones"] = norm
    meta["production_json"] = pj
    if g.get("continuity") is not None:
        meta["continuity"] = g["continuity"]
    db.update_project(pid, meta=meta)

    job_id = None
    if g["auto_start"]:
        # import diferido: evita círculo main → production_json → main
        from pipeline import orchestrator
        job_id = await orchestrator.start_pipeline(pid, autopublish=False)

    # Guardar también el resultado del preflight permite inspeccionar desde
    # dashboard/API por qué una unidad está incompleta sin perder el original.
    meta = dict(db.get_project(pid).get("meta") or {})
    pj = dict(meta.get("production_json") or {})
    pj["validacion_ejecucion"] = exec_report
    db.update_project(pid, meta={**meta, "production_json": pj})

    return {
        "ok": True,
        "project_id": pid,
        "titulo": project.get("title"),
        "modo": "production_json",
        "formato": g["formato"],
        "estilo": g["estilo"],
        "unidades": len(g["escenas"]),
        "unit_types": sorted({e["meta"]["production_unit"]["type"]
                              for e in g["escenas"]}),
        "tts_skips": sum(1 for e in g["escenas"] if e["meta"]["tts_skip"]),
        "avisos": avisos,
        "normalizaciones": norm,
        "production_file": {"file": ref["file"], "bytes": ref["bytes"],
                            "sha256": ref["sha256"]},
        "job_id": job_id,
        "siguiente": (f"pipeline lanzado (job {job_id})" if job_id
                      else f"consulta el estado del proyecto {pid} o ábrelo "
                           "en el dashboard"),
    }


def validate_only(payload, estilos_validos: set[str]) -> dict:
    """Dry-run del Adapter (POST /api/production_json/validate): valida y
    traduce SIN crear proyecto, escenas ni archivos. Incluye el reporte de
    VALIDACIÓN DE EJECUCIÓN (nivel 2) con los datos creativos faltantes —
    reportados, jamás inventados."""
    data = parse_payload(payload)
    proj = data.get("project")
    production_id = data.get("id") or (
        proj.get("id") if isinstance(proj, dict) else None)
    g, avisos, norm = validate(data, estilos_validos, production_id=production_id)
    return {
        "ok": True,
        "dry_run": True,
        "titulo": g["titulo"],
        "formato": g["formato"],
        "estilo": g["estilo"],
        "nicho": g["nicho"],
        "unidades": len(g["escenas"]),
        "unit_types": sorted({e["meta"]["production_unit"]["type"]
                              for e in g["escenas"]}),
        "tts_skips": sum(1 for e in g["escenas"] if e["meta"]["tts_skip"]),
        "duracion_objetivo_total": round(sum(
            e["meta"]["duration_target"] for e in g["escenas"]
            if e["meta"].get("duration_target")), 2),
        "avisos": avisos,
        "normalizaciones": norm,
        "validacion_ejecucion": validate_execution(data),
        "vista_previa": [{"id": e["meta"]["production_unit"]["id"],
                          "title": e["title"],
                          "narration": e["narration"] or None,
                          "dialogue": e["meta"]["production_unit"]["dialogue"],
                          "video_prompt": bool(
                              e["meta"]["production_unit"]["video_prompt"]),
                          "duration_target": e["meta"].get("duration_target"),
                          "campos_nicho": sorted(
                              (e["meta"].get("unit") or {}).keys())}
                         for e in g["escenas"]],
    }


def spec(estilos_ids: list[str]) -> dict:
    """Spec machine-readable del contrato (para el Creative Engine y humanos)."""
    camaras = ", ".join(sorted(camera_recipes.ids()))
    return {
        "version": "2.16.1",
        "uso": 'POST /api/projects con {"mode": "production_json", '
               '"production": <envelope>} (objeto, string JSON o fences). '
               'Dry-run: POST /api/production_json/validate. guion_json sigue '
               'disponible e INTACTO para guiones terminados.',
        "campos": {
            "project": "objeto o string — identificación del proyecto "
                       "(title|name, format, style, voice, niche, "
                       "continuity…); OBLIGATORIO identificable "
                       "(project.title o project.name)",
            "sequence": "lista OBLIGATORIA de unidades creativas (1+); el "
                        "Adapter acepta sequence/units/shots/scenes/beats",
            "title|name": "str — título del proyecto (≤60; el original se "
                          "conserva). «name» es alias mecánico de «title»",
            "format": "'short' (9:16) | 'long' (16:9) — default short; "
                      "string o OBJETO ({\"aspect_ratio\": \"9:16\", …} / "
                      "{\"type\": \"short\", …}): en el objeto manda "
                      "aspect_ratio, si no type; el objeto completo se "
                      "conserva íntegro en production.json",
            "style": f"id visual (GET /api/styles) — default 'auto'. "
                     f"Válidos: {', '.join(estilos_ids)}",
            "voice": "voz edge-tts opcional",
            "avatar_id": "personaje opcional (GET /api/avatars)",
            "niche": "carpeta opcional del árbol de proyectos (≤60)",
            "platforms": "lista: youtube|tiktok|instagram|facebook — default [youtube]",
            "continuity": "se conserva VERBATIM a nivel proyecto y unidad, "
                          "sin comprensión semántica",
            "auto_start": "bool — true lanza el pipeline al ingerir",
        },
        "campos_de_unidad": {
            "id": "identificador de la unidad (si falta, id sintético "
                  "registrado como normalización mecánica)",
            "type": "tipo/dialecto de unidad (scene, "
                    "functional_shot_transformation_beat…) — el Adapter NO "
                    "ramifica por tipo: mismo tratamiento para todos",
            "title": "título de la unidad (≤80)",
            "image_prompt|visual_prompt|prompt_image": "OPCIONAL EN INGESTA (string, "
                    "inglés) — equivalente del CREATIVE ENGINE. El Adapter "
                    "NO lo inventa ni lo deriva de prompt_generation_rules. "
                    "Para el executor actual de generación de imágenes es "
                    "BLOQUEANTE en preflight/ejecución; si falta, se conserva "
                    "la unidad y se reporta exactamente qué debe aportar el "
                    "CREATIVE ENGINE",
            "video_prompt|motion_prompt|prompt_video": "OPCIONAL hoy — se "
                    "conserva sin perder motion_prompt; nunca bloquea",
            "narration": "OPCIONAL — lo ÚNICO que llega a TTS",
            "dialogue": "LISTA = guion de lipsync, se conserva verbatim y "
                        "NUNCA se convierte en TTS; STRING = la voz del "
                        "dialecto Creative Engine → se mapea a narration",
            "duration|duration_seconds": "número positivo — se conserva como "
                        "duration_target SEPARADO de la duración real; la "
                        "desviación queda registrada tras el TTS; si falta, "
                        "la validación de ejecución lo reporta como dato "
                        "creativo faltante para el timing (no bloqueante)",
            "camera": "receta de fábrica (GET /api/cameras) o descripción "
                      "libre (se conserva verbatim)",
            "environment / outfit": "opcional — consumidos por el ensamblador "
                                    "de prompts (meta.ambiente/meta.outfit)",
            "references / audio / continuity": "se conservan VERBATIM",
            "todo lo demás": "initial_state, action, change, final_state, "
                             "casting, ingredients, preparation, "
                             "story_function, information_state, cliffhanger, "
                             "dark_twist, payoff, activation, reveal… → "
                             "meta.unit SIN interpretar",
        },
        "principios": [
            "no hay esquema universal por nicho: el Adapter no ramifica por "
            "nicho y lo desconocido se conserva",
            "la fábrica jamás regenera ni inventa contenido creativo: si "
            "falta un dato creativo obligatorio, produce ERROR EXPLÍCITO "
            "(unidad · campo · por qué · quién lo debe proveer)",
            "dos niveles de validación: ESTRUCTURAL (¿el envelope se puede "
            "interpretar?) y DE EJECUCIÓN (¿cada unidad trae lo necesario "
            "para ejecutarse? — validate_execution); los requisitos se "
            "derivan del pipeline, nunca del nicho",
            "sin narración no hay TTS: silencio a duration_target "
            "(nunca se lee el título, dialogue nunca es voz)",
            "normalizaciones mecánicas seguras permitidas y SIEMPRE "
            "registradas (avisos + normalizaciones): title|name, "
            "duration|duration_seconds, format string|objeto.aspect_ratio",
            "el envelope original completo se guarda como production.json en "
            "la carpeta del proyecto + sha256 en meta",
            "cero columnas SQLite nuevas: meta y production.json bastan",
        ],
        "validaciones": [
            "nivel 1 ESTRUCTURAL: proyecto identificable (project.title|name "
            "o title|name raíz), sequence existente y no vacía (lista de "
            "objetos), duration válida si existe (número > 0)",
            "nivel 2 EJECUCIÓN (validate_execution): por unidad, "
            "image_prompt string = BLOQUEANTE; duration ausente = dato "
            "creativo faltante para el timing (reportado, no bloqueante); "
            "sin campos obligatorios por nicho",
            "cada unidad con image_prompt string",
            "errores con formato: «Creative Production JSON validation error: "
            "sequence[4] requires image_prompt» + detalle (unidad, campo, "
            "por qué, quién lo provee)",
            "NO se exigen campos por nicho (dialogue, narration, character, "
            "ingredients, initial_state, cliffhanger, motion_prompt…)",
        ],
        "cameras": f"recetas válidas: {camaras}",
        "ejemplo": {
            "project": {"title": "Mini demo", "format": "short",
                        "niche": "Miniatures"},
            "sequence": [
                {"id": "beat_001",
                 "type": "functional_shot_transformation_beat",
                 "initial_state": "empty red pan, macro",
                 "action": "batter pours from a tiny bowl",
                 "change": "batter spreads into a circle",
                 "final_state": "golden pancake with bubbles",
                 "visual_prompt": "macro miniature red pan, golden pancake "
                                  "batter spreading, pastel kitchen, no text",
                 "motion_prompt": "slow top-down push-in, batter spreading",
                 "audio": {"kind": "asmr", "sfx": ["pour", "sizzle"]},
                 "duration": 8},
            ],
            "auto_start": False,
        },
    }
