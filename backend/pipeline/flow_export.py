"""
Flow Export v2 — MÉTODO COMPLETO (imágenes base + videos en cadena).

Replica el flujo de trabajo real del usuario (PASOS.txt + PROMPT GUIA.txt):
  PASO 1 → banco de ideas (metodo_chatgpt.txt, prompt verbatim para ChatGPT)
  PASO 2 → PROMPT MÁSTER con N imágenes base + N-1 videos en cadena
           (Video i = Imagen i → Imagen i+1, con acción segundo a segundo)
  + script.json con el contrato exacto de la extensión "Flow Script Processor".

Estructura del ZIP:
  <SLUG>/out/ideas/idea_NNNNNN/script.json          → ScriptData (contrato types.ts)
  <SLUG>/out/ideas/idea_NNNNNN/prompts_maestro.txt  → PROMPT MÁSTER completo
  <SLUG>/out/ideas/idea_NNNNNN/guion.txt            → narración (voz en off)
  <SLUG>/out/ideas/idea_NNNNNN/metodo_chatgpt.txt   → PASO 1 + PASO 2 para iterar en ChatGPT
  README.txt                                        → instrucciones + diagnóstico

Modos (parámetro fmt):
  transformacion → construcción/remodelación con constructor fijo (estilo MINA ABANDONADA)
  generic        → evolución cinematográfica sin constructor (cualquier nicho)

Enriquecimiento IA (use_ai=True): Gemini 2.5 Flash free tier escribe los bloques
en inglés con calidad editorial; si falla o no hay key → fallback determinista
(plantillas) para que el export NUNCA se rompa. Costo marginal: $0.
"""
from __future__ import annotations

import asyncio
import io
import json
import re
import unicodedata
import zipfile
from datetime import datetime, timezone

from services.themes import get_style

# --------------------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------------------

DEFAULT_BRAND = "Johan Monetizo"   # cartel físico de madera que aparece en todas las imágenes
VIDEO_SECONDS = 15                  # duración fija de cada video del método


def slugify(text: str) -> str:
    """'Retos Acuaticos' -> RETOS_ACUATICOS (slug de carpeta, ≤48 chars)."""
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").upper()
    return t[:48] or "PROYECTO"


_LIGHT_KEYS = ("light", "luz", "ilumin", "golden hour", "chiaroscuro", "sombra", "shadow",
               "backlight", "volumetric", "neon", "sunset", "sunrise", "daylight", "glow")
_SHOT_KEYS = ("shot", "close-up", "closeup", "wide", "portrait", "angle", "zoom", "plano",
              "macro", "aerial", "establishing", "pov", "drone", "tracking", "overhead",
              "composition", "front-facing", "eye-level")
_ENV_KEYS = ("environment", "entorno", "concept about", "background", "fondo", "escenario",
             "setting", "escena de", "interior", "exterior", "mountain", "room", "space")


def _split_prompt(flat: str) -> dict:
    """Descompone el image_prompt plano (texto con comas) en campos heurísticos."""
    segs = [s.strip() for s in (flat or "").split(",") if s.strip()]
    lighting, environment, composition, rest = [], [], [], []
    for i, s in enumerate(segs):
        low = s.lower()
        if any(k in low for k in _LIGHT_KEYS):
            lighting.append(s)
        elif any(k in low for k in _ENV_KEYS):
            environment.append(s)
        elif i == 0 or any(k in low for k in _SHOT_KEYS):
            composition.append(s)
        else:
            rest.append(s)
    return {
        "composition": composition or ["front-facing eye-level composition"],
        "lighting": lighting or ["natural cinematic lighting"],
        "environment": environment or ["the project location"],
        "style": rest,
    }


_CAM_MOVE_MAP = [
    (("close-up", "closeup", "macro", "primer plano"), "slow cinematic push-in"),
    (("wide", "establishing", "aerial", "drone"), "slow aerial pull-back revealing the scene"),
    (("overhead", "top"), "smooth overhead descent"),
    (("pov", "primera persona", "first-person"), "first-person walking movement, no flying camera"),
    (("tracking", "seguimiento"), "dynamic tracking shot following the subject"),
]
_DEFAULT_CAM = "vertical smartphone video, eye-level, realistic handheld stability, no camera spin"


def _cam_move(composition: str) -> str:
    low = (composition or "").lower()
    for keys, move in _CAM_MOVE_MAP:
        if any(k in low for k in keys):
            return move
    return _DEFAULT_CAM


def _first_sentence(text: str, maxlen: int = 160) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    m = re.match(r"(.+?[.!?¡¿])(\s|$)", t)
    s = (m.group(1) if m else t).strip()
    return s[:maxlen].rsplit(" ", 1)[0] + "…" if len(s) > maxlen else s


# --------------------------------------------------------------------------------------
# Bloques fijos del método (tomados verbatim de PASOS.txt / PROMPT GUIA.txt)
# --------------------------------------------------------------------------------------

BUILDER_PROMPT = (
    "One single adult male builder appears and works alone. He is 35 to 40 years old, "
    "strong working body, short dark hair, light beard, focused serious expression. He wears "
    "a dark green work hoodie, brown carpenter pants, black work boots, black gloves, and a "
    "black tool belt. He works in realistic fast-motion, around 4x to 6x speed. His actions "
    "are quick, efficient, and slightly motion-blurred, but every action remains physically "
    "believable."
)

BUILDER_ACTIONS = (
    "measuring, cleaning, breaking stone, drilling, using a pickaxe, using hammer and chisel, "
    "shoveling dirt or debris, pushing a wheelbarrow, carrying wood, installing beams, pouring "
    "cement, leveling the floor, compacting gravel, installing metal, installing glass, "
    "installing a door, installing lights, installing flooring, placing panels, assembling "
    "furniture, decorating, cleaning, and adjusting final details"
)

# Frase de continuidad obligatoria desde la Imagen Base 2 (PASOS.txt / PROMPT GUIA.txt)
REFERENCE_PHRASE = (
    "Use Image A as the main reference. Preserve the same location, same camera angle, same "
    "composition, same lighting direction, same construction identity, same material "
    "continuity, and the same visual atmosphere."
)

VIDEO_OPENING = (
    "Create a {seconds}-second vertical 9:16 ultra-realistic fast-motion {kind} video.\n\n"
    "Use the uploaded image as the exact starting frame. Do not redesign the scene. Preserve "
    "the same location, same camera angle, same lens feel, same vertical composition, same "
    "lighting direction, and same realistic cinematic style."
)

NEGATIVE_IMAGES_GENERAL = (
    "No people, no workers, no human figures, no visible hands, no silhouettes, no text "
    "overlay, no watermark, no interface elements, no subtitles, no digital labels, no "
    "external logos."
)

NEGATIVE_VIDEOS_GENERAL = (
    "No music, no captions, no subtitles, no digital text, no text overlay, no interface "
    "elements, no watermark, no external logos, no newly generated readable words, no extra "
    "workers, no machinery, no morphing, no floating objects, no sudden transformation, no "
    "changing location, no changing camera angle."
)

# Frases de corrección (PROMPT GUIA.txt, sección final) — verbatim
CORRECTION_PHRASES = [
    ("Si el modelo deja al constructor en pantalla",
     "The final second must be a clean static final frame with no builder, no hands, no "
     "moving tools, and no motion blur, so this final frame can be used as the next starting image."),
    ("Si el modelo cambia el ángulo",
     "Do not change the camera angle, do not rotate the camera, do not switch to a side view, "
     "do not create a new location. Keep the same visual continuity from the uploaded starting frame."),
    ("Si hace morphing raro",
     "Every change must happen through visible physical work. Materials must be carried into "
     "frame, placed by hand, drilled, hammered, poured, aligned, cleaned, or installed. Nothing appears by magic."),
    ("Si mete texto digital",
     "No captions, no subtitles, no digital text, no text overlay, no interface elements, no "
     "watermark, no logos, no readable labels, no generated words on screen."),
    ("Si mete más personas",
     "Only one single adult male builder appears in the clips. No extra workers, no background "
     "people, no silhouettes, no crowd, no random characters."),
]

CONTINUITY_TIPS = [
    "Genera SIEMPRE las imágenes base en orden (1 → N) y usa la imagen anterior como referencia visual de la siguiente.",
    "Método imágenes base: cada video usa Imagen N como Start Frame e Imagen N+1 como End Frame (Frames to Video en Flow).",
    "Método último frame: si la continuidad se rompe, sube el último frame limpio del video anterior como nuevo Start Frame.",
    "El último segundo de cada video debe quedar limpio, estático y sin constructor: ese frame sirve de siguiente Start Frame.",
    "Si un video sale con magia o morphing, agrega una frase de la sección FRASES EXTRA y vuelve a generar.",
    "Nunca cambies de ángulo de cámara entre etapas: la continuidad es la columna vertebral del video viral.",
]

# Herramientas y acciones por etapa de la transformación (pool determinista)
_STAGE_POOLS = [
    {   # temprano: demolición y limpieza
        "tools": "a shovel, a stiff broom, measuring tape, and wooden stakes",
        "beats": [
            "He removes loose stones and debris from the working area and organizes them into piles.",
            "He scrapes the compacted ground with the shovel, pushing dirt to the side.",
            "He sweeps the whole zone with the stiff broom until the base is readable.",
            "He places wooden stakes and stretches measuring string to mark the work zone.",
        ],
        "progress": [
            "Dust rises naturally while the ground becomes cleaner and more organized.",
            "The debris piles grow neatly on both sides, leaving the center path clear.",
            "The base surface starts to look leveled, compact, and ready for construction.",
            "The marked work zone becomes clearly visible against the raw terrain.",
        ],
        "sound": ("shovel scraping dirt, broom sweeping dust, small rocks sliding, wood pieces "
                  "dropping, hammer hitting stakes, measuring tape snapping, boots crunching gravel"),
    },
    {   # medio: estructura y refuerzo
        "tools": "a pickaxe, a hammer, a chisel, a compact drill, and heavy wooden beams",
        "beats": [
            "He breaks and removes the obstructing material piece by piece with controlled strikes.",
            "He carries and positions heavy structural beams against the structure.",
            "He drills metal brackets to secure every beam firmly in place.",
            "He pours and levels the base material, then compacts it with a manual tamper.",
        ],
        "progress": [
            "Fragments fall naturally and are cleared away immediately.",
            "The structural frame stands straight, solid, and weight-bearing.",
            "Each fastener bites into place with visible torque and dust.",
            "The base becomes flat, stable, and professionally finished.",
        ],
        "sound": ("pickaxe striking stone, hammer and chisel impacts, drill fastening, material "
                  "cracking, wheelbarrow rolling, wood beam dragging, boots on gravel"),
    },
    {   # tarde: acabados premium
        "tools": "floor panels, wall panels, a drill, pendant lights, and finishing materials",
        "beats": [
            "He installs the main finishing panels with precise alignment.",
            "He mounts the light fixtures and turns them on one by one.",
            "He places the furniture and decorative components in their final positions.",
            "He cleans every surface, brushes away dust, and adjusts the last details.",
        ],
        "progress": [
            "The surfaces click into place with clean, tight joints.",
            "A warm glow spreads across the space, transforming the atmosphere.",
            "The space starts to look premium, styled, and aspirational.",
            "Everything looks clean, aligned, and ready for the final reveal.",
        ],
        "sound": ("panels sliding into place, drill screws, brush on surfaces, ladder steps, "
                  "lights clicking on, furniture dragging softly, interior echo"),
    },
]

_GENERIC_BEATS = [
    "The scene evolves naturally: the main elements of this stage become the focus.",
    "Light and atmosphere shift subtly while the composition stays exactly the same.",
    "The transformation of this stage completes through continuous, believable motion.",
    "A final detail settles into place, closing the stage visually.",
]


def _pool_for(stage_idx: int, total: int) -> dict:
    """Pool según progreso 0..1 de la etapa (determinista)."""
    p = 0.0 if total <= 1 else stage_idx / (total - 1)
    if p < 0.34:
        return _STAGE_POOLS[0]
    if p < 0.67:
        return _STAGE_POOLS[1]
    return _STAGE_POOLS[2]

# --------------------------------------------------------------------------------------
# Generadores de bloques (plantilla determinista, inglés — calidad editorial con IA)
# --------------------------------------------------------------------------------------

def _sign_line(brand: str) -> str:
    if not brand:
        return ""
    return (f'\n\nA rustic wooden sign planted naturally in the scene, clearly readable, with '
            f'hand-painted text that says "{brand}". The sign must look like a physical real '
            f'object made of wood, not digital text.')


def _image_block_text(i: int, sc: dict, fmt: str, brand: str) -> str:
    """Bloque EN completo para la Imagen Base i (plantilla determinista)."""
    parts = _split_prompt(sc.get("image_prompt") or "")
    comp = ". ".join(parts["composition"])
    env = ", ".join(parts["environment"])
    light = ", ".join(parts["lighting"])
    style = ", ".join(parts["style"]) or "ultra-realistic, cinematic, premium, highly detailed"
    narration = _first_sentence(sc.get("narration") or "")
    no_people = ("No people, no workers, no human figures, no visible hands" if fmt == "transformacion"
                 else "No identifiable people in focus, no text overlay, no watermark, no logos")

    if i == 1:
        head = (f"Vertical 9:16, ultra-realistic cinematic {comp}, natural but dramatic "
                f"lighting, premium smartphone video aesthetic, highly detailed textures.")
        body = (f"Show {env}. {('The scene: ' + narration) if narration else ''} "
                f"The composition must clearly show the entire working area that will later evolve.")
    else:
        head = REFERENCE_PHRASE
        body = (f"Transform the previous stage into the next real stage of the same project: "
                f"{sc.get('title', '')}. {narration} Keep the same camera angle, same vertical "
                f"9:16 composition and same lighting direction; only the construction progress changes.")

    return (f"{head}\n\n{body}\n\nMaterials and textures must look believable and premium. "
            f"Lighting: {light}. Style: {style}.\n\n{no_people}, no vehicles, no text overlay, "
            f"no watermark, no interface elements, no logos." + _sign_line(brand))


def _second_by_second(i: int, sc: dict, nxt: dict | None, fmt: str, brand: str) -> list[str]:
    """15 beats (0-1s … 14-15s). Último frame limpio = siguiente Start Frame."""
    if fmt == "transformacion":
        pool = _pool_for(i, max(2, i + (2 if nxt else 1)))
        tools = pool["tools"]
        beats, progress = pool["beats"], pool["progress"]
        off = (i - 1) % len(beats)
        rows = [
            "Show the uploaded starting frame exactly as it is, untouched.",
            f"The builder enters quickly from the lower-right side of the frame carrying {tools}.",
            beats[(off) % 4], progress[(off) % 4],
            beats[(off + 1) % 4], progress[(off + 1) % 4],
            beats[(off + 2) % 4], progress[(off + 2) % 4],
            beats[(off + 3) % 4], progress[(off + 3) % 4],
            "The main transformation of this stage becomes clearly visible from the fixed camera.",
            "He makes final adjustments to every element he just installed or modified.",
            "He cleans the work area, brushes away dust and aligns the last details.",
            "He walks around the work area quickly and checks every detail.",
            ("He exits completely to the side of the frame. The final frame must be clean, static, "
             "with no builder visible, showing this stage fully completed and ready for the next one."),
        ]
        return rows

    # genérico: evolución cinematográfica sin constructor
    cam = _cam_move((sc.get("image_prompt") or ""))
    return [
        "Show the uploaded starting frame exactly as it is, untouched.",
        f"The camera holds a stable vertical frame. {cam}.",
        _GENERIC_BEATS[0], _GENERIC_BEATS[1],
        "The key visual change of this stage happens through continuous believable motion.",
        "The environment reacts naturally: dust, light and textures stay consistent.",
        _GENERIC_BEATS[2],
        "Secondary elements settle, keeping the same location and composition.",
        _GENERIC_BEATS[3],
        "The main subject reaches the state described for this stage.",
        "Small natural motion keeps the frame alive without breaking continuity.",
        "The final details of the stage complete in smooth motion.",
        "The atmosphere stabilizes; lighting matches the next planned stage.",
        "All motion slows down, preparing a clean ending frame.",
        "End on a clean static final frame showing this stage fully completed, usable as the next starting image.",
    ]


def _video_block_text(i: int, sc: dict, nxt: dict | None, fmt: str, brand: str) -> str:
    """Bloque EN completo para el Video i (Imagen i → Imagen i+1)."""
    kind = "construction" if fmt == "transformacion" else "cinematic"
    parts = _split_prompt(sc.get("image_prompt") or "")
    env = ", ".join(parts["environment"])[:180]
    goal = _first_sentence(sc.get("narration") or "") or f"complete stage {i} of the project"
    rows = _second_by_second(i, sc, nxt, fmt, brand)
    sba = "\n\n".join(f"{j}-{j+1}s:\n{row}" for j, row in enumerate(rows))
    pool = _pool_for(i, max(2, i + (2 if nxt else 1))) if fmt == "transformacion" else None

    blocks = [VIDEO_OPENING.format(seconds=VIDEO_SECONDS, kind=kind),
              f"MAIN GOAL:\nAdvance the project to stage {i + 1}: {goal}",
              f"VISUAL LAYOUT:\nLocation: {env}.\nCamera: fixed vertical 9:16, same angle as the "
              f"starting frame.\nContinuity: every element of the previous stage remains recognizable."]
    if fmt == "transformacion":
        blocks += [
            f"BUILDER:\n{BUILDER_PROMPT}",
            "FAST-MOTION STYLE:\nRealistic 4x to 6x fast-motion. Every change must happen through "
            f"physical work ({BUILDER_ACTIONS}).",
        ]
    blocks.append(f"SECOND-BY-SECOND ACTION:\n{sba}")
    blocks.append("CAMERA STYLE:\n" + _cam_move(" ".join(parts["composition"])))
    if fmt == "transformacion" and pool:
        blocks.append("SOUND DESIGN:\nConstruction sounds only: " + pool["sound"] +
                      ". No music, no voiceover, no narration.")
    else:
        blocks.append("SOUND DESIGN:\nRealistic ambient sound only. No music, no voiceover, no narration.")
    blocks.append("NEGATIVE GUIDANCE:\n" + NEGATIVE_VIDEOS_GENERAL)
    return "\n\n".join(blocks)

# --------------------------------------------------------------------------------------
# ScriptData — contrato exacto de la extensión (utils/types.ts del manual)
# --------------------------------------------------------------------------------------

def _image_prompt_obj(i: int, sc: dict, fmt: str, brand: str, block_en: str) -> dict:
    parts = _split_prompt(sc.get("image_prompt") or "")
    # subjects[0] lleva la frase de continuidad desde la imagen 2 (la clave del método cadena)
    subj = [block_en.split("\n\n")[0]] if i > 1 else [_first_sentence(sc.get("narration") or "") or sc.get("title") or "main stage of the project"]
    return {
        "subjects": subj,
        "environment": ", ".join(parts["environment"]),
        "lighting": ", ".join(parts["lighting"]),
        "composition": ", ".join(parts["composition"]) + ", vertical 9:16 framing",
        "style": (", ".join(parts["style"]) or "ultra-realistic cinematic quality, 8K")
                 + (f', physical wooden sign with text "{brand}"' if brand else ""),
    }


def build_script_json(project: dict, scenes: list[dict], ai: dict | None = None,
                      fmt: str = "transformacion", brand: str = DEFAULT_BRAND) -> dict:
    """ScriptData del contrato: escena i = Imagen Base i + Video i (imagen i → imagen i+1).
    La última escena es SOLO imagen (revelación final), igual que el método 9+8."""
    style_id = project.get("style") or "graphic-novel"
    st = get_style(style_id)
    n = len(scenes)
    ai_stages = (ai or {}).get("stages") or []

    scenes_out = []
    for k, sc in enumerate(scenes):
        i = k + 1
        title = (ai_stages[k].get("stage_title") if k < len(ai_stages) and ai_stages[k].get("stage_title")
                 else sc.get("title") or f"Etapa {i}")
        block = (ai_stages[k].get("image_prompt_en") if k < len(ai_stages) and ai_stages[k].get("image_prompt_en")
                 else _image_block_text(i, sc, fmt, brand))
        image_prompt = _image_prompt_obj(i, sc, fmt, brand, block)
        entry = {
            "scene_number": i,
            "title": title,
            "narration": sc.get("narration") or "",
            "duration": sc.get("duration") or VIDEO_SECONDS,
            "image_prompt": image_prompt,
            "imagePrompt": image_prompt,  # alias camelCase (interfaces TS)
        }
        if i < n:  # video i transforma Imagen i → Imagen i+1
            motion = (ai_stages[k].get("video_prompt_en") if k < len(ai_stages) and ai_stages[k].get("video_prompt_en")
                      else _video_block_text(i, sc, scenes[k + 1], fmt, brand))
            video_prompt = {
                "motion": motion,
                "camera_movement": _cam_move(image_prompt["composition"]),
            }
            entry["video_prompt"] = video_prompt
            entry["videoPrompt"] = video_prompt
        scenes_out.append(entry)

    return {
        "project_name": slugify(project.get("title") or "PROYECTO"),
        "title": project.get("title") or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "format": project.get("format") or "short",
        "method": "base-images-chain",
        "total_base_images": n,
        "total_videos": max(0, n - 1),
        "style": {"id": st.get("id"), "name": st.get("name"), "prompt": st.get("prompt")},
        "scenes": scenes_out,
    }


# --------------------------------------------------------------------------------------
# PROMPT MÁSTER — réplica exacta de la estructura de PROMPT GUIA.txt
# --------------------------------------------------------------------------------------

def build_prompts_maestro(project: dict, scenes: list[dict], ai: dict | None = None,
                          fmt: str = "transformacion", brand: str = DEFAULT_BRAND) -> str:
    st = get_style(project.get("style") or "graphic-novel")
    n = len(scenes)
    ai_stages = (ai or {}).get("stages") or []
    sep = "---"

    def stage_title(k: int) -> str:
        if k < len(ai_stages) and ai_stages[k].get("stage_title"):
            return ai_stages[k]["stage_title"]
        return scenes[k].get("title") or f"Etapa {k + 1}"

    def image_block(k: int) -> str:
        if k < len(ai_stages) and ai_stages[k].get("image_prompt_en"):
            return ai_stages[k]["image_prompt_en"]
        return _image_block_text(k + 1, scenes[k], fmt, brand)

    def video_block(k: int) -> str:
        if k < len(ai_stages) and ai_stages[k].get("video_prompt_en"):
            return ai_stages[k]["video_prompt_en"]
        return _video_block_text(k + 1, scenes[k], scenes[k + 1] if k + 1 < n else None, fmt, brand)

    L: list[str] = [
        "# PROMPT MÁSTER",
        f"# {(project.get('title') or slugify(project.get('title') or 'PROYECTO')).upper()}",
        "",
        "## CONCEPTO GENERAL",
        (ai or {}).get("concepto_general") or
        f"{project.get('title') or 'Proyecto'} se desarrolla en {n} etapas visuales encadenadas. "
        "La secuencia debe sentirse realista, física y cinematográfica. Nada debe parecer magia, "
        "morphing raro o transición automática.",
        "",
        "## ESTILO VISUAL",
        f"{st.get('name', '')} — {st.get('desc', '')}. {st.get('prompt', '')}",
        "",
        "## ESTRUCTURA GENERAL",
        f"- Cantidad exacta de imágenes base: {n}.",
        f"- Cantidad exacta de videos: {n - 1}.",
        f"- Cada video dura {VIDEO_SECONDS} segundos (vertical 9:16).",
        f"- Duración total estimada: {(n - 1) * VIDEO_SECONDS} segundos.",
    ]
    L += ["", "## Imágenes Base"]
    L += [f"* Imagen Base {k + 1}: {stage_title(k)}." for k in range(n)]
    L += ["", "## Videos"]
    L += [f"* Video {k + 1}: Imagen {k + 1} → Imagen {k + 2}." for k in range(n - 1)]
    if brand:
        L += ["", "## REGLA DE MARCA",
              f'En TODAS las imágenes base aparece un cartel físico real de madera, integrado al '
              f'escenario, con texto pintado a mano que dice "{brand}". Nunca texto digital.']

    L += ["", sep, "", "# REGLAS MAESTRAS PARA IMÁGENES", "```text",
          f"Keep the same location, same project identity, same terrain and material textures, "
          f"same lighting direction, same atmosphere, same vertical 9:16 composition, same "
          f"realistic lens feel" + (f', and the same rustic wooden sign that says "{brand}"' if brand else "") + ".",
          "", "Do not add people, workers, men, women, children, human figures, visible hands, or silhouettes."
          if fmt == "transformacion" else
          "Do not add text overlay, watermark, interface elements, subtitles, digital labels, or external logos.",
          "", "Every image must look like the next real stage of the same project.",
          "", "The project must feel ultra-realistic, cinematic, premium, and highly detailed, with "
          "believable materials, believable progression, and strong visual continuity.", "```"]

    L += ["", sep, "", "# REGLAS MAESTRAS PARA VIDEOS", "```text",
          "Use the uploaded image or uploaded last frame as the exact starting frame. Do not "
          "redesign the location. Do not change the camera angle, lens, composition, lighting "
          "direction, or construction progress.",
          "",
          f"Continue the work from the current frame only. The video must be a {VIDEO_SECONDS}-second "
          "vertical 9:16 ultra-realistic fast-motion video, with slight natural motion blur, but "
          "every action must remain physically believable. Nothing appears by magic.",
          "",
          "Each video must end with a clean, static final frame usable as the next Start Frame.", "```"]

    if fmt == "transformacion":
        L += ["", sep, "", "# PROMPT FIJO DEL CONSTRUCTOR", "```text", BUILDER_PROMPT,
              "", "El constructor solo aparece en los videos, nunca en las imágenes base. "
              "Acciones reales: " + BUILDER_ACTIONS + ".", "```"]

    L += ["", sep, "", "# NEGATIVE PROMPT GENERAL PARA IMÁGENES", "```text",
          NEGATIVE_IMAGES_GENERAL, "```",
          "", "# NEGATIVE PROMPT GENERAL PARA VIDEOS", "```text",
          NEGATIVE_VIDEOS_GENERAL, "```"]

    # ── Prompts de imagen base ──
    L += ["", sep, "", "# PROMPTS DE IMAGEN BASE"]
    for k in range(n):
        i = k + 1
        L += ["", f"## IMAGEN BASE {i}", "", f"## {stage_title(k).upper()}"]
        if i > 1:
            L += ["", f"**Usar Imagen Base {i - 1} como referencia.**"]
        L += ["", "```text", image_block(k), "```", "", sep]

    # ── Prompts de video ──
    L += ["", "# PROMPTS DE VIDEO"]
    for k in range(n - 1):
        L += ["", f"# VIDEO {k + 1}", "",
              f"## {stage_title(k).upper()} → {stage_title(k + 1).upper()}",
              "", "```text", video_block(k), "```", "", sep]

    # ── Orden exacto ──
    L += ["", "# ORDEN EXACTO PARA USAR", "",
          "## Método con imágenes base", "",
          "| Video | Start Frame | End Frame |", "| --- | --- | --- |"]
    L += [f"| Video {k + 1} | Imagen Base {k + 1} | Imagen Base {k + 2} |" for k in range(n - 1)]
    L += ["", "## Método con último frame", "",
          "| Paso | Qué subes al modelo | Prompt |", "| --- | --- | --- |"]
    L += [f"| {k + 1} | " + ("Tu imagen inicial del proyecto" if k == 0 else f"Último frame limpio del Video {k}") + f" | Video {k + 1} |"
          for k in range(n - 1)]

    L += ["", sep, "", "# CONSEJOS PARA EVITAR ERRORES DE CONTINUIDAD", ""]
    L += [f"- {t}" for t in CONTINUITY_TIPS]

    L += ["", sep, "", "# FRASES EXTRA PARA CORREGIR ERRORES"]
    for title_txt, phrase in CORRECTION_PHRASES:
        L += ["", f"## {title_txt}", "", "```text", phrase, "```"]

    return "\n".join(L)


def build_guion(project: dict, scenes: list[dict]) -> str:
    lines = [f"GUION — {project.get('title', '')}", ""]
    for k, sc in enumerate(scenes):
        lines += [f"[Etapa {k + 1}] {sc.get('title', '')}", sc.get("narration", ""), ""]
    return "\n".join(lines)

# --------------------------------------------------------------------------------------
# metodo_chatgpt.txt — PASO 1 y PASO 2 verbatim (el flujo del usuario con ChatGPT)
# --------------------------------------------------------------------------------------

_METODO_TXT = """MÉTODO DE TRABAJO — YOUTUBE AUTOMATION v2 + CHATGPT + GOOGLE FLOW
====================================================================

Este archivo contiene TUS dos prompts de ChatGPT tal como los usas.
Workflow completo:

  1) (Opcional) PASO 1 en ChatGPT → banco de 30 ideas + ranking viral.
  2) PASO 2 en ChatGPT → desarrollo completo de UNA idea (PROMPT MÁSTER).
  3) Compara con prompts_maestro.txt de este paquete (generado por v2):
     si quieres mejorar un bloque, cópialo a ChatGPT, pídele el ajuste y pega
     el resultado de vuelta en prompts_maestro.txt.
  4) Genera en Google Flow con la extensión (script.json) o a mano con el
     documento maestro (Método imágenes base o Método último frame).
  5) Importa las carpetas Escena_XX al dashboard (botón "Importar Escena_XX").

============================== PASO 1 ==============================
"""

_PASO1 = """Quiero que actúes como un experto en creación de videos virales con inteligencia artificial, especializado en contenido de construcción, transformación extrema, arquitectura secreta, remodelaciones imposibles pero realistas, videos tipo timelapse, videos con Start Frame y End Frame, y contenido para TikTok, Facebook Reels, YouTube Shorts e Instagram Reels.

Voy a trabajar con un método específico de creación:

- Primero creo una imagen base inicial.
- Después puedo trabajar con imágenes base progresivas o usando el último frame de cada video como nueva imagen de inicio.
- El video debe sentirse como una transformación real, no como magia.
- La construcción debe hacerse con acciones físicas reales.
- El proyecto debe tener continuidad visual.
- El constructor solo aparece en los videos, nunca en las imágenes base.
- Las imágenes base no deben tener personas, manos, trabajadores, siluetas ni figuras humanas.
- Los videos deben ser realistas, cinematográficos y en cámara rápida.
- No debe haber música.
- Solo debe haber sonidos reales de construcción: taladro, martillo, pico, pala, cemento, madera, vidrio, metal, grava, pasos, bisagras, eco interior, limpieza, herramientas.
- No quiero texto digital, subtítulos, captions, logos, watermark ni elementos de interfaz.
- Si hay cartel, debe ser un cartel físico real de madera integrado al escenario.

Quiero que me des ideas nuevas para videos de construcción IA con alto potencial viral.

IMPORTANTE:
No quiero ideas simples como "construir una casita normal".
Quiero ideas visualmente locas, épicas, avanzadas y adictivas, pero que sigan siendo realistas y posibles de producir con IA usando imágenes base + videos.

Las ideas deben tener este tipo de energía:

- abrir una montaña con pico y taladro para crear una suite secreta
- convertir una mina abandonada en un loft de lujo
- construir una mansión dentro de una roca gigante
- crear una base secreta bajo un árbol enorme
- abrir una puerta escondida detrás de una cascada
- construir una villa de vidrio dentro de un acantilado
- transformar una cueva destruida en una habitación premium
- construir un garaje subterráneo bajo una piedra del desierto
- convertir un tanque oxidado en una casa cápsula de lujo
- construir una habitación secreta dentro de una colina
- abrir un túnel abandonado y convertirlo en un refugio premium
- crear una piscina subterránea dentro de una cueva
- construir una casa enterrada con techo verde natural
- transformar una estructura abandonada en una suite escondida
- crear una base moderna debajo de ruinas antiguas

Quiero mínimo 30 ideas.

Las ideas deben estar pensadas para poder desarrollarse después con esta estructura:

- imágenes base encadenadas (cada video va de una imagen a la siguiente).
- videos de 15 segundos.
- Primero se trabaja la parte exterior.
- Después se crea una entrada premium o secreta.
- Luego hay un video especial en primera persona entrando desde afuera hacia adentro.
- Después se revela el interior abandonado.
- Luego empieza la remodelación interior.
- Finalmente se llega a una suite, loft, búnker, habitación, mansión, refugio o espacio premium terminado.

El orden narrativo ideal debe ser:

1. Exterior abandonado, raro, destruido o misterioso.
2. Exterior limpio y preparado.
3. Exterior abierto, reforzado o transformado.
4. Exterior final premium con entrada secreta.
5. Cámara en primera persona entrando.
6. Interior abandonado o crudo.
7. Interior limpio, reforzado y preparado.
8. Interior avanzado con piso, paredes, luces y estructura.
9. Interior final de lujo.

Para cada idea quiero que uses este formato:

1. Número de la idea.
2. Título ultra impactante y viral.
3. Concepto principal.
4. Qué se construye exactamente.
5. Dónde ocurre la construcción.
6. Cómo se ve el exterior abandonado inicial.
7. Cómo se transforma el exterior.
8. Cómo sería la entrada secreta o premium.
9. Cómo sería el video de entrada en primera persona.
10. Cómo se ve el interior abandonado.
11. Cómo se remodela el interior.
12. Cómo se ve el resultado final de lujo.
13. Cuál sería el momento visual más viral.
14. Qué acciones físicas haría el constructor en los videos.
15. Qué herramientas aparecerían.
16. Qué materiales aparecerían.
17. Qué elemento visual debe mantenerse para continuidad.
18. Qué tan difícil sería producirlo: fácil, medio o avanzado.
19. Por qué tendría alta retención en TikTok, Facebook Reels, Instagram Reels o YouTube Shorts.
20. Qué frase corta podría usarse como gancho para presentar la idea.

Quiero que las ideas sean variadas. Divídelas en categorías como:

- Cuevas y minas abandonadas.
- Rocas gigantes y montañas.
- Bosques, árboles y raíces.
- Desierto, cráteres y ruinas.
- Agua, cascadas, lagos y estructuras ocultas.
- Espacios industriales abandonados.
- Casas subterráneas o camufladas.
- Proyectos extremos premium.

No repitas ideas.
No me des ideas aburridas.
No me des ideas genéricas.
No me des ideas imposibles de producir.
No uses magia, fantasía extrema ni transformaciones irreales.
Todo debe sentirse loco, épico, cinematográfico, premium y realista.

Al final, dame un ranking con las 10 ideas más virales, ordenadas de mayor a menor potencial, explicando brevemente por qué cada una funcionaría.
"""

_PASO2 = """============================== PASO 2 ==============================

Quiero que desarrolles completamente esta idea que elegí:

[PEGA AQUÍ EL NOMBRE O NÚMERO DE LA IDEA ELEGIDA]

Quiero que la desarrolles siguiendo exactamente mi método de creación de videos con inteligencia artificial usando imágenes base + videos.

IMPORTANTE:
Necesito que el resultado quede profesional, realista, cinematográfico, viral, coherente y listo para copiar y pegar en mi bloc de notas.

La estructura debe funcionar obligatoriamente así:

- Prompts de imágenes base encadenadas (cada una usa la anterior como referencia).
- Un video por transición entre imágenes.
- Cada video debe durar 15 segundos.
- Los prompts de imagen deben estar en inglés.
- Los prompts de video deben estar en inglés.
- La explicación general puede estar en español.
- Las imágenes base no deben tener personas.
- No deben aparecer hombres, trabajadores, manos visibles, siluetas ni figuras humanas en las imágenes base.
- El constructor solo aparece en los videos.
- En los videos debe aparecer siempre un solo constructor adulto.
- No debe haber música.
- Solo sonidos reales de construcción.
- No quiero texto digital, subtítulos, captions, logos, watermark ni elementos de interfaz.
- Cada transformación debe sentirse real y causada por acciones físicas.
- Nada debe aparecer mágicamente.
- No quiero morphing raro.
- No quiero cambios bruscos de ubicación, ángulo o diseño.

El constructor debe ser siempre el mismo en todos los videos normales:

One single adult male builder appears and works alone. He is 35 to 40 years old, strong working body, short dark hair, light beard, focused serious expression. He wears a dark green work hoodie, brown carpenter pants, black work boots, black gloves, and a black tool belt. He works in realistic fast-motion, around 4x to 6x speed. His actions are quick, efficient, and slightly motion-blurred, but every action remains physically believable.

El constructor debe hacer acciones reales como:

- medir
- limpiar
- romper piedra
- taladrar
- usar pico
- usar martillo y cincel
- palear tierra o escombros
- empujar carretilla
- cargar madera
- instalar vigas
- verter cemento
- nivelar suelo
- compactar grava
- instalar metal
- instalar vidrio
- instalar puerta
- instalar luces
- instalar piso
- colocar paneles
- montar muebles
- decorar
- limpiar
- ajustar detalles finales

Quiero que el orden narrativo sea este:

1. Imagen Base 1: exterior abandonado, destruido, raro o misterioso.
2. Imagen Base 2: exterior limpio y preparado.
3. Imagen Base 3: exterior abierto, reforzado o estructurado.
4. Imagen Base 4: exterior final premium con entrada secreta o moderna.
5. Imagen Base 5: entrada en primera persona desde afuera hacia adentro.
6. Imagen Base 6: interior abandonado, crudo o destruido.
7. Imagen Base 7: interior limpio, reforzado y preparado.
8. Imagen Base 8: interior avanzado con piso, paredes, luces y estructura.
9. Imagen Base 9: interior final de lujo completamente terminado.

Y los videos deben seguir este orden:

- Video 1: Imagen Base 1 → Imagen Base 2.
- Video 2: Imagen Base 2 → Imagen Base 3.
- ... (cada video va de una imagen a la siguiente)

El video de primera persona debe ser obligatorio:
Debe sentirse como si el espectador estuviera caminando desde afuera hacia adentro del proyecto.
No debe aparecer el constructor completo.
No debe aparecer rostro.
No debe aparecer cuerpo completo.
Puede aparecer una mano parcial solo si abre una puerta, pero sin mostrar cuerpo ni cara.
Debe sentirse como POV realista, cámara vertical, movimiento natural, sin volar, sin girar raro, sin salto mágico.

Quiero que me organices todo en este orden:

1. Título final de la idea.
2. Concepto general.
3. Estilo visual.
4. Duración total estimada.
5. Cantidad exacta de imágenes base.
6. Cantidad exacta de videos.
7. Reglas maestras de continuidad.
8. Reglas maestras para imágenes.
9. Reglas maestras para videos.
10. Prompt fijo del constructor.
11. Prompts de las imágenes base, en inglés.
12. Prompts de los videos, en inglés.
13. Orden exacto para usar.
14. Método alternativo usando último frame.
15. Consejos para evitar errores de continuidad.
16. Negative prompt general para imágenes.
17. Negative prompt general para videos.
18. Frases extra para corregir errores.

Para los prompts de imagen quiero que sean muy detallados.

Cada prompt de imagen debe incluir:

- qué referencia usar
- qué conservar exactamente
- qué cambiar exactamente
- dónde está la cámara
- dónde está el exterior o interior
- qué hay en primer plano
- qué hay en el centro
- qué hay en el fondo
- qué materiales aparecen
- cómo debe verse la luz
- cómo debe sentirse la atmósfera
- cómo se mantiene la continuidad
- qué no debe aparecer
- cómo se integra el cartel físico si existe

La Imagen Base 1 se crea desde cero.

Desde la Imagen Base 2 en adelante, cada prompt debe empezar con una frase parecida a:

Use Image A as the main reference. Preserve the same location, same camera angle, same composition, same lighting direction, same construction identity, same material continuity, and the same visual atmosphere.

Pero debes adaptarlo a cada etapa para que tenga sentido.

Para los prompts de video quiero que sean extremadamente detallados.

Cada prompt de video debe incluir:

- duración exacta de 15 segundos
- formato vertical 9:16
- estilo ultra realista
- fast-motion 4x a 6x
- continuidad desde el frame inicial
- objetivo del video
- layout visual del espacio
- herramientas y materiales
- descripción del constructor
- acción segundo por segundo desde 0-1s hasta 14-15s
- estilo de cámara
- sonido de construcción
- negative guidance

Cada video debe terminar con el constructor saliendo completamente del frame, excepto el video de primera persona, donde no debe aparecer el constructor.

El último segundo de cada video debe ser un frame limpio, estático y usable como siguiente Start Frame.

Quiero que los prompts de video sean largos, precisos y muy claros, no genéricos.

No quiero respuestas cortas.
No quiero que resumas.
No quiero que me des solo ideas.
Quiero el desarrollo completo, profesional y listo para producción.

IMPORTANTE:
No hagas preguntas.
No pidas confirmación.
Desarrolla la idea directamente con la mejor interpretación posible.
"""


def build_metodo_chatgpt() -> str:
    return _METODO_TXT + _PASO1 + "\n" + _PASO2


# --------------------------------------------------------------------------------------
# README del paquete
# --------------------------------------------------------------------------------------

def build_readme(fmt: str, ai_used: bool) -> str:
    modo = ("CONSTRUCTOR FIJO (transformación/construcción)" if fmt == "transformacion"
            else "EVOLUCIÓN CINEMATOGRÁFICA (genérico, sin constructor)")
    return f"""FLOW EXPORT — MÉTODO COMPLETO (YOUTUBE AUTOMATION v2)
======================================================
Modo: {modo} · IA Gemini: {"SÍ (prompts enriquecidos)" if ai_used else "NO (plantillas deterministas)"}

CONTENIDO
---------
- script.json          → contrato de la extensión Flow Script Processor
                         (escena i = Imagen Base i + Video i; la última escena es solo imagen)
- prompts_maestro.txt  → PROMPT MÁSTER completo estilo tu método:
                         concepto, estructura, reglas maestras, negative prompts,
                         imágenes base encadenadas, videos segundo a segundo,
                         orden exacto (2 métodos), consejos y frases de corrección
- metodo_chatgpt.txt   → tus PASOS 1 y 2 verbatim para iterar ideas en ChatGPT
- guion.txt            → narración en español (voz en off / referencia)

CÓMO USAR (MÉTODO CADENA)
-------------------------
1. Descomprime este ZIP: obtendrás <PROYECTO>/out/ideas/idea_NNNNNN/
2. Abre Google Flow en Chrome y vincula la extensión a la carpeta <PROYECTO>
   (la que contiene "out").
3. Genera las imágenes base 1..N con la extensión (o pegando los bloques de
   prompts_maestro.txt en ImageFX). Respetando el orden.
4. Para cada video i: Frames to Video → Start Frame = Imagen Base i,
   End Frame = Imagen Base i+1 → pega el bloque "VIDEO i" del documento maestro.
   (Alternativa: Método último frame — ver tabla en el documento.)
5. Los archivos quedan en <PROYECTO>/Escena_XX/imagen_1.png | video_1.mp4
6. Vuelve al dashboard → "Importar Escena_XX" → ensambla el MP4 final.

PARÁMETROS DE EXPORTACIÓN (URL)
-------------------------------
  ?format=transformacion   → constructor fijo (por defecto)
  ?format=generic          → evolución cinematográfica sin constructor
  ?ai=1                    → enriquece los prompts en inglés con Gemini (free tier)
  ?brand=Johan%20Monetizo  → texto del cartel físico de madera (marca del canal)
  ?idea=7                  → número de carpeta idea_000007 (si ya tienes ideas)

DIAGNÓSTICO: SI LA EXTENSIÓN NO CARGA LAS ESCENAS
-------------------------------------------------
A) ¿Vinculaste la carpeta correcta? El handle debe apuntar a la carpeta que
   contiene "out/ideas/" (ej: ...\\projects\\MI_PROYECTO).
B) Cache de la extensión:
   1. chrome://extensions → "Flow Script Processor" → botón de recarga (⟳)
   2. Cierra y reabre el popup; si persiste, re-vincula la carpeta.
C) Plan B: botón "Subir JSON" del popup → selecciona este script.json directo.
D) DevTools del popup (clic derecho → Inspeccionar) → Console: no debe haber
   errores rojos al vincular.

Nota: si ya exportaste antes, renombra idea_000001 por el siguiente número libre
(idea_000002, ...) — la extensión siempre toma el número MÁS ALTO.
"""

# --------------------------------------------------------------------------------------
# Enriquecimiento con Gemini (free tier, $0) — fallback determinista si falla
# --------------------------------------------------------------------------------------

_AI_SCHEMA = {
    "type": "object",
    "properties": {
        "concepto_general": {"type": "string"},
        "estilo_visual": {"type": "string"},
        "stages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "stage_title": {"type": "string"},
                    "image_prompt_en": {"type": "string"},
                    "video_prompt_en": {"type": "string"},
                },
                "required": ["stage_title", "image_prompt_en", "video_prompt_en"],
            },
        },
    },
    "required": ["concepto_general", "estilo_visual", "stages"],
}


def _ai_user_prompt(project: dict, scenes: list[dict], fmt: str, brand: str) -> str:
    fmt_rules = (
        "Nicho: construcción/transformación extrema con constructor humano fijo. "
        "Las imágenes base NUNCA tienen personas. El constructor SOLO aparece en los videos: "
        + BUILDER_PROMPT +
        " Cada video termina con el constructor saliendo del frame y un último segundo limpio "
        "y estático usable como siguiente Start Frame."
        if fmt == "transformacion" else
        "Nicho genérico: evolución cinematográfica sin constructor humano. La cámara mantiene "
        "continuidad total y la escena evoluciona de forma creíble."
    )
    brand_rule = (f'En todas las imágenes base aparece un cartel físico real de madera con texto '
                  f'pintado a mano: "{brand}". Nunca texto digital.' if brand else
                  "No incluyas carteles ni texto en las imágenes.")
    esc = "\n".join(
        f"  {k + 1}. Título: {sc.get('title', '')} | Narración (ES): {sc.get('narration', '')[:220]} "
        f"| Image prompt actual (EN): {(sc.get('image_prompt') or '')[:220]}"
        for k, sc in enumerate(scenes))
    return f"""Eres un experto en videos virales de IA (imagen base + video de 15s con Start Frame y End Frame).

PROYECTO: {project.get('title', '')}
Escenas (una por etapa de la transformación):
{esc}

MÉTODO (obligatorio):
- {len(scenes)} imágenes base encadenadas. La Imagen Base 1 se crea desde cero.
- Desde la Imagen Base 2, cada prompt de imagen EMPIEZA con: "{REFERENCE_PHRASE}"
  (adaptado a la etapa).
- Video i va de Imagen i (Start Frame) a Imagen i+1 (End Frame), dura exactamente
  {VIDEO_SECONDS} segundos, vertical 9:16, ultra realista, con acción SEGUNDO A SEGUNDO
  (0-1s hasta 14-15s) y termina en frame limpio y estático.
- {fmt_rules}
- {brand_rule}
- Reglas maestras: nada de magia ni morphing; cada cambio se causa con acción física visible;
  sin música; sin texto digital; sin marcas de agua; continuidad de cámara y materiales.
- Negative guidance de video (inclúyelo en cada video_prompt_en): "{NEGATIVE_VIDEOS_GENERAL}"

DEVUELVE JSON (mismo idioma pedido):
- concepto_general: 3-5 frases EN ESPAÑOL del concepto viral del video.
- estilo_visual: 1-2 frases EN ESPAÑOL del estilo visual.
- stages: EXACTAMENTE {len(scenes)} elementos, en orden:
  - stage_title: título corto EN ESPAÑOL de la etapa (3-7 palabras, estilo "EXTERIOR ABANDONADO").
  - image_prompt_en: prompt de imagen EN INGLÉS, 90-160 palabras, ultra detallado
    (cámara, primer plano/centro/fondo, materiales, luz, atmósfera, continuidad, qué no debe aparecer).
  - video_prompt_en: prompt de video EN INGLÉS para la transición Imagen {1}→{2} del primer elemento,
    con secciones MAIN GOAL, VISUAL LAYOUT, {('BUILDER, FAST-MOTION STYLE, ' if fmt == 'transformacion' else '')}SECOND-BY-SECOND ACTION
    (15 beats), CAMERA STYLE, SOUND DESIGN y NEGATIVE GUIDANCE. Para el ÚLTIMO stage deja
    video_prompt_en como cadena vacía (""), porque la última imagen no tiene video después."""


_MODEL_CANDIDATES = (None, "gemini-3.6-flash", "gemini-flash-latest", "gemini-2.5-flash")
"""None = usar GEMINI_TEXT_MODEL configurado. Google retira modelos con el tiempo
(gemini-2.x ya devolvió 404 para keys nuevas), así que probamos en cascada."""


async def enrich_scenes_ai(project: dict, scenes: list[dict], fmt: str = "transformacion",
                           brand: str = DEFAULT_BRAND, timeout_s: float = 150.0) -> dict | None:
    """Llama a Gemini (free tier) para escribir los bloques con calidad editorial.
    Prueba modelos candidatos en cascada (por si el configurado fue retirado).
    Devuelve None si no hay key, si todos fallan o si expira el timeout → plantillas."""
    try:
        from services import gemini_client
        if not gemini_client.available():
            return None
        prompt = _ai_user_prompt(project, scenes, fmt, brand)
        raw, last_err = None, None
        for cand in _MODEL_CANDIDATES:
            try:
                raw = await asyncio.wait_for(
                    gemini_client.generate_json(prompt, schema=_AI_SCHEMA, model=cand),
                    timeout=timeout_s)
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                raw = None
        if raw is None:
            raise RuntimeError(f"todos los modelos fallaron: {last_err}")
        stages = raw.get("stages") if isinstance(raw, dict) else None
        if not isinstance(stages, list) or len(stages) < len(scenes):
            return None
        stages = stages[:len(scenes)]
        for s in stages:
            if not isinstance(s, dict):
                return None
            s["video_prompt_en"] = (s.get("video_prompt_en") or "").strip()
            s.setdefault("image_prompt_en", "")
            s.setdefault("stage_title", "")
        return {"concepto_general": (raw.get("concepto_general") or "").strip(),
                "estilo_visual": (raw.get("estilo_visual") or "").strip(),
                "stages": stages}
    except Exception as e:  # noqa: BLE001 — degradación graceful SIEMPRE
        import logging
        logging.getLogger("flow_export").warning("Enriquecimiento IA falló: %s", e)
        return None


# --------------------------------------------------------------------------------------
# Empaquetado ZIP
# --------------------------------------------------------------------------------------

async def export_zip_bytes(project: dict, scenes: list[dict], idea_number: int = 1,
                           fmt: str = "transformacion", use_ai: bool = False,
                           brand: str = DEFAULT_BRAND) -> tuple[bytes, str, bool]:
    """Devuelve (zip_bytes, slug, ai_used). Estructura: <SLUG>/out/ideas/idea_NNNNNN/..."""
    slug = slugify(project.get("title") or "PROYECTO")
    ai = await enrich_scenes_ai(project, scenes, fmt=fmt, brand=brand) if use_ai else None
    script = build_script_json(project, scenes, ai=ai, fmt=fmt, brand=brand)
    idea_dir = f"{slug}/out/ideas/idea_{max(1, min(idea_number, 999999)):06d}"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{idea_dir}/script.json",
                   json.dumps(script, ensure_ascii=False, indent=2))
        z.writestr(f"{idea_dir}/prompts_maestro.txt",
                   build_prompts_maestro(project, scenes, ai=ai, fmt=fmt, brand=brand))
        z.writestr(f"{idea_dir}/guion.txt", build_guion(project, scenes))
        z.writestr(f"{idea_dir}/metodo_chatgpt.txt", build_metodo_chatgpt())
        z.writestr("README.txt", build_readme(fmt, ai_used=ai is not None))
    return buf.getvalue(), slug, ai is not None
