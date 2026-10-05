#!/usr/bin/env python3
"""Batería GOLDEN EXECUTION CONTRACT V1.0 — P1: TRANSPARENCIA DEL video_prompt.

Prueba la cadena completa que alimenta a Google Flow:

    Production JSON (Creative Engine)
      → services/production_json.py  (parse → validate → meta.production_unit)
      → pipeline/flow_export.py      (build_script_json → script.json)
      → payload final que consume la extensión / Flow Bridge

CONTRATO P1 (fuente primaria): el video_prompt del Creative Engine debe llegar
VERBATIM al campo `motion` del payload final de Flow. flow_export NUNCA lo
reemplaza por sus plantillas creativas hardcodeadas (_video_block_text,
_artesano_video_block) ni por ai_stages; esas son SOLO fallback cuando la
unidad no trae prompt propio.

Campos del contrato verificados además de video_prompt:
  image_prompt · duration_target · initial_state · action · change ·
  final_state · audio · campos extra de unidad (casting, story_function,
  niche_extra → preservados verbatim en meta.unit)

Corre SIN servidor y SIN DB real (escenas sintéticas en memoria).
Uso:  cd yt_automation_v2 && python3 tests/test_flow_contract_p1.py
      python3 -m pytest tests/test_flow_contract_p1.py -q
"""
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from services import production_json as pj  # noqa: E402
from pipeline import flow_export as fx      # noqa: E402
from services.themes import STYLES          # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


ESTILOS = sorted({s["id"] for s in STYLES})

# Sentinels ÚNICOS del Creative Engine — deben llegar intactos al payload.
S1 = ("CE_SENTINEL_V1 :: slow dolly-in on the jade mask, dust settling, "
      "hand-carved details catching golden light, 8 seconds")
S2 = ("CE_SENTINEL_V2 :: the mask floats upward in fast-motion assembly, "
      "pieces snapping together, sparks of jade dust")
S3 = ("CE_SENTINEL_V3 :: artisan lifts the finished mask toward the sun, "
      "camera holds still, wind moves the palm fronds")

PAYLOAD = {
    "project": {"title": "Golden P1", "format": "short",
                "niche": "Miniatures"},
    "sequence": [
        {"id": "beat_001", "type": "functional_shot_transformation_beat",
         "initial_state": "empty stone altar, macro",
         "action": "jade fragments rise from the altar",
         "change": "fragments assemble into a mask",
         "final_state": "finished jade mask, golden light",
         "visual_prompt": "macro jade mask on a stone altar, golden hour, "
                          "tropical grove, no text",
         "motion_prompt": S1,
         "audio": {"kind": "asmr", "sfx": ["stone", "wind"]},
         "duration": 8,
         "casting": {"artisan": "elderly hands, weathered"},
         "story_function": "revelation",
         "niche_extra": {"material": "jade"},
         "references": [{"kind": "image", "url": "https://x/ref1.png"}]},
        {"id": "beat_002", "type": "functional_shot_transformation_beat",
         "initial_state": "assembled jade mask",
         "action": "mask floats upward in fast-motion",
         "change": "mask rotates, engraving completes",
         "final_state": "engraved mask floating",
         "visual_prompt": "close-up engraved jade mask floating, rim light, "
                          "jade dust, no text",
         "motion_prompt": S2,
         "duration": 6},
        {"id": "beat_003", "type": "functional_shot_transformation_beat",
         "initial_state": "engraved mask floating",
         "action": "artisan lifts the mask toward the sun",
         "change": "sun backlights the jade",
         "final_state": "hero shot of the finished mask",
         "visual_prompt": "hero shot jade mask backlit by sun, palm grove, "
                          "photorealistic, no text"},
    ],
    "auto_start": False,
}


def _escenas_creativas():
    data = pj.parse_payload(json.loads(json.dumps(PAYLOAD)))
    g, _av, _norm = pj.validate(data, ESTILOS)
    return g["escenas"]


def _legacy_scenes(n=3):
    """Escenas legacy (modo idea, sin production_unit)."""
    return [{"title": f"Etapa {i}", "narration": f"Escena {i}.",
             "image_prompt": f"wide shot stage {i}, golden hour, grove",
             "duration": 0.0, "status": "pending", "meta": {}}
            for i in range(1, n + 1)]


TEMPLATE_MARKERS = ("SECOND-BY-SECOND", "MAIN GOAL", "BUILDER:",
                    "FAST-MOTION STYLE", "VISUAL LAYOUT")


def main() -> int:
    proj = {"title": "Golden P1", "format": "short"}

    print("═══ P1 · CADENA COMPLETA production_json → flow_export ═══")
    escenas = _escenas_creativas()

    print("── 1. adapter preserva la unidad creativa")
    pu1 = escenas[0]["meta"]["production_unit"]
    check("video_prompt conservado en la unidad", pu1["video_prompt"] == S1,
          repr(pu1.get("video_prompt"))[:80])
    check("prompt_sources.video apunta al Creative Engine",
          pu1["prompt_sources"]["video"] in ("motion_prompt", "video_prompt"),
          str(pu1["prompt_sources"]))
    check("initial_state preservado",
          escenas[0]["meta"]["unit"]["initial_state"]
          == PAYLOAD["sequence"][0]["initial_state"])
    check("action preservado",
          escenas[0]["meta"]["unit"]["action"] == PAYLOAD["sequence"][0]["action"])
    check("change preservado",
          escenas[0]["meta"]["unit"]["change"] == PAYLOAD["sequence"][0]["change"])
    check("final_state preservado",
          escenas[0]["meta"]["unit"]["final_state"]
          == PAYLOAD["sequence"][0]["final_state"])
    check("audio preservado verbatim",
          pu1["audio"] == PAYLOAD["sequence"][0]["audio"])
    check("casting preservado (campo extra)",
          escenas[0]["meta"]["unit"]["casting"]
          == PAYLOAD["sequence"][0]["casting"])
    check("story_function preservado (campo extra)",
          escenas[0]["meta"]["unit"]["story_function"]
          == PAYLOAD["sequence"][0]["story_function"])
    check("niche_extra preservado (campo extra)",
          escenas[0]["meta"]["unit"]["niche_extra"]
          == PAYLOAD["sequence"][0]["niche_extra"])
    check("references preservadas",
          pu1["references"] == PAYLOAD["sequence"][0]["references"])
    check("duration_target preservado",
          pu1["duration_target"] == 8, str(pu1["duration_target"]))
    check("image_prompt conservado",
          "jade mask" in (pu1["image_prompt"] or ""))

    print("── 2. P1 NÚCLEO: motion del export ES el prompt del Creative Engine")
    data = fx.build_script_json(proj, escenas, fmt="transformacion")
    sc = data["scenes"]
    check("3 escenas en el export", len(sc) == 3)
    check("escena 1 motion == CE_SENTINEL_V1 verbatim",
          sc[0]["video_prompt"]["motion"] == S1,
          repr(sc[0]["video_prompt"]["motion"])[:90])
    check("escena 2 motion == CE_SENTINEL_V2 verbatim",
          sc[1]["video_prompt"]["motion"] == S2,
          repr(sc[1]["video_prompt"]["motion"])[:90])
    check("última escena SOLO imagen (sin video_prompt)",
          "video_prompt" not in sc[2] and "videoPrompt" not in sc[2])
    check("alias camelCase videoPrompt == video_prompt",
          sc[0]["videoPrompt"] == sc[0]["video_prompt"])
    check("alias camelCase imagePrompt == image_prompt",
          sc[0]["imagePrompt"] == sc[0]["image_prompt"])
    motions = [s.get("video_prompt", {}).get("motion", "") for s in sc[:2]]
    check("NINGÚN template del método dentro de los motions creativos",
          not any(m in mot for mot in motions for m in TEMPLATE_MARKERS))
    check("export serializa a JSON (payload final válido)",
          isinstance(json.dumps(data, ensure_ascii=False), str))
    check("method base-images-chain", data["method"] == "base-images-chain")
    check("total_videos = n-1", data["total_videos"] == 2)

    print("── 3. P1 PRIORIDAD: creative gana incluso CON ai_stages en conflicto")
    ai_conflictivo = {"stages": [
        {"stage_title": "AI", "image_prompt_en": "AI IMAGE BLOCK",
         "video_prompt_en": "AI_STAGES_SHOULD_LOSE_V1"},
        {"stage_title": "AI", "image_prompt_en": "AI IMAGE BLOCK 2",
         "video_prompt_en": "AI_STAGES_SHOULD_LOSE_V2"},
        {"stage_title": "AI", "image_prompt_en": "AI IMAGE BLOCK 3"},
    ]}
    data_ai = fx.build_script_json(proj, escenas, ai=ai_conflictivo,
                                   fmt="transformacion")
    sc_ai = data_ai["scenes"]
    check("escena 1 sigue siendo CE_SENTINEL_V1 (no ai_stages)",
          sc_ai[0]["video_prompt"]["motion"] == S1)
    check("escena 2 sigue siendo CE_SENTINEL_V2 (no ai_stages)",
          sc_ai[1]["video_prompt"]["motion"] == S2)
    check("ai_stages NO contamina el motion creativo",
          "AI_STAGES_SHOULD_LOSE" not in json.dumps(sc_ai[:2],
                                                    ensure_ascii=False))

    print("── 4. P1 en modo artesano")
    data_ar = fx.build_script_json(
        {**proj, "style": "artesano"}, escenas, fmt="artesano",
        character="Capitán Jade")
    sc_ar = data_ar["scenes"]
    check("artesano escena 1 (ancla) motion == CE_SENTINEL_V1 verbatim",
          sc_ar[0]["video_prompt"]["motion"] == S1,
          repr(sc_ar[0]["video_prompt"]["motion"])[:90])
    check("artesano última escena solo imagen",
          "video_prompt" not in sc_ar[2])
    check("artesano escena 2 motion == CE_SENTINEL_V2 verbatim",
          sc_ar[1]["video_prompt"]["motion"] == S2,
          repr(sc_ar[1]["video_prompt"]["motion"])[:90])
    check("artesano ai_stages también pierde ante el creative",
          fx.build_script_json({**proj, "style": "artesano"}, escenas,
                               ai=ai_conflictivo, fmt="artesano",
                               character="Capitán Jade")["scenes"][1]
          ["video_prompt"]["motion"] == S2)

    print("── 5. FALLBACK legacy intacto (no-regresión del método)")
    legacy = _legacy_scenes()
    data_leg = fx.build_script_json(proj, legacy, fmt="transformacion")
    sc_leg = data_leg["scenes"]
    check("legacy SIN creative → plantilla del método (_video_block_text)",
          all("MAIN GOAL:" in s["video_prompt"]["motion"] for s in sc_leg[:2]))
    check("legacy última escena solo imagen", "video_prompt" not in sc_leg[2])
    data_leg_ai = fx.build_script_json(
        proj, legacy, ai={"stages": [
            {"video_prompt_en": "AI_FALLBACK_V1"},
            {"video_prompt_en": "AI_FALLBACK_V2"},
            {}]}, fmt="transformacion")
    check("legacy CON ai_stages → usa ai (comportamiento previo intacto)",
          [s["video_prompt"]["motion"] for s in
           data_leg_ai["scenes"][:2]] == ["AI_FALLBACK_V1", "AI_FALLBACK_V2"])

    print("── 6. duration_target del contrato llega al export")
    check("escena 1 duration == 8 (duration_target, no 15 fijo)",
          sc[0]["duration"] == 8, str(sc[0]["duration"]))
    check("escena 2 duration == 6", sc[1]["duration"] == 6)
    check("escena 3 sin target → VIDEO_SECONDS 15",
          sc[2]["duration"] == fx.VIDEO_SECONDS, str(sc[2]["duration"]))
    check("legacy con duration en columna lo conserva",
          data_leg_ai["scenes"][0]["duration"] == 0.0
          or data_leg_ai["scenes"][0]["duration"] == fx.VIDEO_SECONDS)
    legacy_dur = [dict(_legacy_scenes(1)[0], duration=12)]
    check("legacy duration=12 → 12",
          fx.build_script_json(proj, legacy_dur)["scenes"][0]["duration"] == 12)

    print("── 7. sanitización NO muta el prompt creativo limpio")
    check("sentinel pasa verbatim pese al blindaje anti-filtros",
          sc[0]["video_prompt"]["motion"] == S1)
    check("camera_movement sigue derivado de la composición",
          isinstance(sc[0]["video_prompt"]["camera_movement"], str)
          and sc[0]["video_prompt"]["camera_movement"])

    print("── 8. helpers P1 (unidad de contrato)")
    check("_creative_video_prompt lee la unidad",
          fx._creative_video_prompt(escenas[0]) == S1)
    check("_creative_video_prompt devuelve '' sin unidad",
          fx._creative_video_prompt(_legacy_scenes(1)[0]) == "")
    check("_creative_duration_target None sin unidad",
          fx._creative_duration_target(_legacy_scenes(1)[0]) is None)
    check("_creative_duration_target ignora basura",
          fx._creative_duration_target(
              {"meta": {"production_unit": {"duration_target": "x"}}}) is None)

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 0 if FAIL == 0 else 1


def test_golden_contract_p1():
    """Entrada pytest: la batería completa como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
