# -*- coding: utf-8 -*-
"""Batería BM (2026-11): Extensión del blueprint externo con video_prompt y subtitle_text.

BM1:
  · Escenas del blueprint externo aceptan dos campos opcionales:
    "video_prompt" (<=600 caracteres) y "subtitle_text" (<=200).
  · Misma validación que los demás strings: solo str, control chars (Cc)
    removidos en normalización, rechazo INVALID_BLUEPRINT si no es str o supera el límite.

BM2:
  · Etapa 3: si hay video_prompt, es el prompt de flow_generate_video tal cual;
    si no, se mantiene la composición actual (movimiento + narration[:300]).

BM3:
  · Etapa 4: la entrada de la escena en el plan de render lleva subtitle_text
    cuando existe (karaoke_subtitles ya lo prefiere sobre narration).
    Si no existe, comportamiento actual.
  · Subtítulos quemados (.srt y .ass) usan subtitle_text y NO la narración con
    direcciones de voz.

BM4:
  · /api/pipeline/status (y orchestrator.get_status) expone ambos campos por escena.

Hermético: cero red, cero Chrome, cero llamadas a Flow/Gemini reales (doubles + mock).
"""
import asyncio
import json
import logging
import os
import sys
import tempfile
import unittest.mock as mock
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import asset_harvester as harv
from services import karaoke_subtitles
from services import pipeline_orchestrator as po
from services import video_assembler as vasm


# ═══════════════════════════════ Mock Manager ═══════════════════════════════

class MockManagerBM:
    """Mock hermético de MCPManager para pruebas de orquestador."""

    def __init__(self, tmp_dir: Path):
        self.tmp_dir = tmp_dir
        self.exec_calls: list[tuple[str, str, dict]] = []
        self._img_count = 0

    async def test_pipeline(self, service, notebook_id=None):
        return {"service": service, "ok": True, "state": "connected",
                "auth": "ok", "detail": "", "browser_up": True}

    async def tools_catalog(self, service, auto_connect=True):
        return {"tools": [{"name": "notebook_query"}]}

    async def execute(self, service, tool, arguments=None, timeout=None, **kw):
        args = dict(arguments or {})
        self.exec_calls.append((service, tool, args))
        if tool == "flow_list_assets":
            return {"ok": True, "text": "Assets:\n- ref [id:media_ref_1]\n"}
        if tool == "flow_upload_file":
            n = args.get("name", "ref")
            return {"ok": True, "text": f'Uploaded "{n}". Reference as @{{{n}}}.'}
        if tool == "flow_generate_image":
            self._img_count += 1
            p = self.tmp_dir / f"mock_img_{self._img_count}.png"
            p.write_bytes(b"\x89PNG\r\n\x1a\nfake_image")
            return {"ok": True, "text": f"Asset: Escena_{self._img_count} [id:mid_{self._img_count}]\n{p}"}
        if tool == "flow_generate_video":
            out = args.get("outFile") or str(self.tmp_dir / "mock_video.mp4")
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"\x00\x00\x00 ftypisomfake_video")
            return {"ok": True, "text": f"Generated video:\n{out}"}
        return {"ok": True, "text": "ok"}


def _bp_base(scenes: list[dict], label="frutinovela") -> dict:
    return {
        "label": label,
        "title": "La traición de la pera",
        "scenes": scenes,
    }


# ═══════════════════════════ BM1: Validación Blueprint ═════════════════════

def test_bm1_validation_with_and_without_optional_fields():
    """BM1: escenas aceptan video_prompt y subtitle_text opcionales.

    Sin ellos se mantienen las 3 claves estándar.
    """
    # 1. Sin campos opcionales
    bp_no_opts = _bp_base([
        {"title": "Escena 1", "narration": "Narración 1", "image_prompt": "Prompt 1"}
    ])
    norm = po.validate_external_blueprint(bp_no_opts)
    sc0 = norm["scenes"][0]
    assert set(sc0.keys()) == {"title", "narration", "image_prompt"}
    assert sc0["title"] == "Escena 1"

    # 2. Con ambos campos opcionales
    bp_with_opts = _bp_base([
        {
            "title": "Escena 1",
            "narration": "Narración 1",
            "image_prompt": "Prompt 1",
            "video_prompt": "Cámara lenta acercándose a Manolo",
            "subtitle_text": "¿Patricia? ¿Qué haces?",
        }
    ])
    norm2 = po.validate_external_blueprint(bp_with_opts)
    sc_opt = norm2["scenes"][0]
    assert sc_opt["video_prompt"] == "Cámara lenta acercándose a Manolo"
    assert sc_opt["subtitle_text"] == "¿Patricia? ¿Qué haces?"

    # 3. Con solo uno de los campos opcionales
    bp_only_video = _bp_base([
        {"title": "E1", "narration": "N1", "image_prompt": "P1", "video_prompt": "VP1"}
    ])
    norm_v = po.validate_external_blueprint(bp_only_video)
    assert "video_prompt" in norm_v["scenes"][0]
    assert "subtitle_text" not in norm_v["scenes"][0]

    bp_only_sub = _bp_base([
        {"title": "E1", "narration": "N1", "image_prompt": "P1", "subtitle_text": "ST1"}
    ])
    norm_s = po.validate_external_blueprint(bp_only_sub)
    assert "subtitle_text" in norm_s["scenes"][0]
    assert "video_prompt" not in norm_s["scenes"][0]


def test_bm1_validation_length_limits():
    """BM1: video_prompt <= 600 chars y subtitle_text <= 200 chars."""
    # video_prompt límite 600
    bp_600 = _bp_base([
        {"title": "E1", "narration": "N1", "image_prompt": "P1", "video_prompt": "v" * 600}
    ])
    norm = po.validate_external_blueprint(bp_600)
    assert len(norm["scenes"][0]["video_prompt"]) == 600

    bp_601 = _bp_base([
        {"title": "E1", "narration": "N1", "image_prompt": "P1", "video_prompt": "v" * 601}
    ])
    with pytest.raises(po.PipelineError) as exc_v:
        po.validate_external_blueprint(bp_601)
    assert exc_v.value.code == "INVALID_BLUEPRINT"
    assert "video_prompt" in str(exc_v.value)

    # subtitle_text límite 200
    bp_200 = _bp_base([
        {"title": "E1", "narration": "N1", "image_prompt": "P1", "subtitle_text": "s" * 200}
    ])
    norm = po.validate_external_blueprint(bp_200)
    assert len(norm["scenes"][0]["subtitle_text"]) == 200

    bp_201 = _bp_base([
        {"title": "E1", "narration": "N1", "image_prompt": "P1", "subtitle_text": "s" * 201}
    ])
    with pytest.raises(po.PipelineError) as exc_s:
        po.validate_external_blueprint(bp_201)
    assert exc_s.value.code == "INVALID_BLUEPRINT"
    assert "subtitle_text" in str(exc_s.value)


def test_bm1_validation_control_characters_and_types():
    """BM1: normalización remueve caracteres de control; tipos estrictos str."""
    # Control chars eliminados antes de validar longitud
    bp_ctrl = _bp_base([
        {
            "title": "E1",
            "narration": "N1",
            "image_prompt": "P1",
            "video_prompt": "x" * 595 + "\x00\x07\x1f" * 5,  # 610 chars brutos -> 595 limpios
            "subtitle_text": "y" * 195 + "\x00\x08" * 5,     # 205 chars brutos -> 195 limpios
        }
    ])
    norm = po.validate_external_blueprint(bp_ctrl)
    assert len(norm["scenes"][0]["video_prompt"]) == 595
    assert len(norm["scenes"][0]["subtitle_text"]) == 195

    # Tipos no-string son rechazados
    bp_bad_vtype = _bp_base([
        {"title": "E1", "narration": "N1", "image_prompt": "P1", "video_prompt": 12345}
    ])
    with pytest.raises(po.PipelineError) as exc_t1:
        po.validate_external_blueprint(bp_bad_vtype)
    assert exc_t1.value.code == "INVALID_BLUEPRINT"

    bp_bad_stype = _bp_base([
        {"title": "E1", "narration": "N1", "image_prompt": "P1", "subtitle_text": ["sub"]}
    ])
    with pytest.raises(po.PipelineError) as exc_t2:
        po.validate_external_blueprint(bp_bad_stype)
    assert exc_t2.value.code == "INVALID_BLUEPRINT"

    # Claves extra en escena rechazadas
    bp_extra = _bp_base([
        {"title": "E1", "narration": "N1", "image_prompt": "P1", "invalido": "foo"}
    ])
    with pytest.raises(po.PipelineError) as exc_extra:
        po.validate_external_blueprint(bp_extra)
    assert exc_extra.value.code == "INVALID_BLUEPRINT"


# ═══════════════════════════ BM2: Etapa 3 Video Prompt ══════════════════════

def test_bm2_stage3_uses_video_prompt_verbatim():
    """BM2: Etapa 3 usa video_prompt tal cual cuando está presente;

    si no, compone image_prompt + movimiento + narration[:300].
    """
    custom_video_prompt = (
        "Slow cinematic push-in on Manolo peaking through the pantry door, "
        "dramatic lighting, soft focus on the lemon in the background."
    )
    bp = _bp_base([
        {
            "title": "Escena Con Prompt",
            "narration": "Voz dramática: Manolo espía a Patricia con el limón.",
            "image_prompt": "3D cartoon apple in dark kitchen",
            "video_prompt": custom_video_prompt,
        },
        {
            "title": "Escena Sin Prompt",
            "narration": "Voz con lágrimas: Manolo no puede creer lo que ve.",
            "image_prompt": "3D cartoon apple weeping",
        },
    ])

    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        mgr = MockManagerBM(tmp_path)
        orch = po.PipelineOrchestrator(manager=mgr, runs_dir=tmp_path / "runs")
        run = orch.create_run(idea="Prueba BM2", notebook_id="nb_mock", blueprint=bp)

        asyncio.run(orch._run(run["run_id"]))

        st = orch.get_status(run["run_id"])
        assert st["stage"] == "done"
        assert st["done_count"] == 2

        video_calls = [c for c in mgr.exec_calls if c[1] == "flow_generate_video"]
        assert len(video_calls) == 2

        # Escena 1 (s1): video_prompt tal cual
        call_s1_args = video_calls[0][2]
        assert call_s1_args["prompt"] == custom_video_prompt

        # Escena 2 (s2): composición tradicional
        call_s2_args = video_calls[1][2]
        expected_s2 = (
            "3D cartoon apple weeping\n"
            "Movimiento de cámara y acción, plano continuo coherente: "
            "Voz con lágrimas: Manolo no puede creer lo que ve."
        )
        assert call_s2_args["prompt"] == expected_s2


# ═══════════════════════════ BM3: Etapa 4 Plan & Subtítulos ═════════════════

def test_bm3_render_plan_and_burned_subtitles():
    """BM3:

    - la entrada de la escena en el plan de render lleva subtitle_text cuando existe.
    - subtítulos quemados (.srt y .ass) usan subtitle_text y NO la narración con
      direcciones de voz.
    - sin subtitle_text, se mantiene el comportamiento actual (usa narración).
    """
    voice_direction_narration_1 = (
        'Manolo, la manzana roja, espía por la rendija del frutero. Voz grave y dramática, '
        'español latino: "¿Patricia? ¿Qué le estás entregando a ese limón a medianoche?"'
    )
    clean_sub_1 = "¿Patricia? ¿Qué le estás entregando a ese limón a medianoche?"

    voice_direction_narration_2 = (
        'Voz rota y desesperada: "¡Nunca te perdonaré esto, Patricia!"'
    )

    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        run_dir = tmp_path / "run_test_bm3"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Simulamos una corrida con 2 escenas terminadas: s1 con subtitle_text, s2 sin él
        fake_run = {
            "run_id": "run_test_bm3",
            "idea": "Frutinovela",
            "format": "short",
            "stage": "done",
            "scenes": [
                {
                    "scene_id": "s1",
                    "title": "E1",
                    "narration": voice_direction_narration_1,
                    "subtitle_text": clean_sub_1,
                    "status": "done",
                    "video_file": str(run_dir / "s1.mp4"),
                },
                {
                    "scene_id": "s2",
                    "title": "E2",
                    "narration": voice_direction_narration_2,
                    "subtitle_text": "",
                    "status": "done",
                    "video_file": str(run_dir / "s2.mp4"),
                },
            ],
        }
        # Crear los MP4s ficticios
        (run_dir / "s1.mp4").write_bytes(b"dummy video 1")
        (run_dir / "s2.mp4").write_bytes(b"dummy video 2")

        # 1. Harvest produce manifest estricto
        manifest, _ = harv.harvest_run(fake_run, run_dir, placeholders_for_failed=True)

        sc_m1 = manifest["scenes"][0]
        sc_m2 = manifest["scenes"][1]

        assert sc_m1["subtitle_text"] == clean_sub_1
        assert sc_m2["subtitle_text"] == ""
        assert sc_m2["narration"] == voice_direction_narration_2

        # 2. plan_render
        plan = vasm.plan_render(manifest, run_dir, subtitles="burn")
        scene_plans = plan["scene_plans"]
        assert len(scene_plans) == 2

        # Escena 1 en el plan de render lleva subtitle_text
        assert "subtitle_text" in scene_plans[0]
        assert scene_plans[0]["subtitle_text"] == clean_sub_1

        # Escena 2 en el plan de render NO lleva subtitle_text (comportamiento actual)
        assert "subtitle_text" not in scene_plans[1]

        # 3. Subtítulos generados (.srt)
        srt_content = (run_dir / "final_captions.srt").read_text(encoding="utf-8")

        # Escena 1: USA subtitle_text y NO la narración con direcciones de voz
        assert clean_sub_1 in srt_content
        assert "Voz grave y dramática" not in srt_content
        assert "Manolo, la manzana roja, espía" not in srt_content

        # Escena 2: sin subtitle_text, USA narración
        assert voice_direction_narration_2 in srt_content

        # 4. Subtítulos estilo karaoke (.ass)
        ass_content = karaoke_subtitles.build_ass_from_scenes(
            manifest["scenes"], style_name="hormozi", resolution="1080x1920"
        )
        assert "Voz grave y dramática" not in ass_content
        assert "PATRICIA" in ass_content.upper()


# ═══════════════════════════ BM4: Status Endpoint ═══════════════════════════

def test_bm4_status_exposes_both_fields_per_scene():
    """BM4: orchestrator.get_status expone video_prompt y subtitle_text por escena."""
    bp = _bp_base([
        {
            "title": "E1 Con Todo",
            "narration": "Narración 1",
            "image_prompt": "Prompt 1",
            "video_prompt": "VP1",
            "subtitle_text": "ST1",
        },
        {
            "title": "E2 Estándar",
            "narration": "Narración 2",
            "image_prompt": "Prompt 2",
        },
    ])

    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        mgr = MockManagerBM(tmp_path)
        orch = po.PipelineOrchestrator(manager=mgr, runs_dir=tmp_path / "runs")
        run = orch.create_run(idea="Prueba BM4", notebook_id="nb_mock", blueprint=bp)

        asyncio.run(orch._run(run["run_id"]))

        st = orch.get_status(run["run_id"])
        scenes = st["scenes"]
        assert len(scenes) == 2

        # Escena 1: expone ambos valores
        assert scenes[0]["video_prompt"] == "VP1"
        assert scenes[0]["subtitle_text"] == "ST1"

        # Escena 2: expone ambos campos como string vacío
        assert "video_prompt" in scenes[1]
        assert "subtitle_text" in scenes[1]
        assert scenes[1]["video_prompt"] == ""
        assert scenes[1]["subtitle_text"] == ""

        # Backfill de corrida vieja sin los campos
        old_run = {
            "run_id": "run_old_test",
            "stage": "done",
            "scenes": [
                {"scene_id": "s1", "title": "Old Scene", "narration": "Old Narration"}
            ],
        }
        old_dir = tmp_path / "runs" / "run_old_test"
        old_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "state.json").write_text(json.dumps(old_run), encoding="utf-8")

        st_old = orch.get_status("run_old_test")
        old_sc = st_old["scenes"][0]
        assert "video_prompt" in old_sc and old_sc["video_prompt"] == ""
        assert "subtitle_text" in old_sc and old_sc["subtitle_text"] == ""
