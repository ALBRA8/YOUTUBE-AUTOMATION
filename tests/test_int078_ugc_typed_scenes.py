#!/usr/bin/env python3
"""
Tests INT-078: tipado automático de escenas UGC (avatar + B-roll).

Completa el ciclo INT-077: los generadores EMITEN el tipo de render y el
pipeline lo CONSUME. Valida:
1. generate_ugc_script emite la estructura ganadora 3-beat:
   avatar (hook) → product_broll (beneficios) → avatar (cierre/CTA),
   con la semántica narrativa conservada en 'role'.
2. script_gen.build_result preserva el tipo en scenes.meta.type (únicos
   campos que db.replace_scenes persiste) y NO lo inventa si no viene
   (compatibilidad: otros nichos → legacy intacto).
3. db.replace_scenes/get_scenes: roundtrip de meta.type en SQLite real
   (tmp) y consumo por pipeline.video.scene_render_mode → secuencia de
   render flow_lipsync / broll_zoompan / broll_zoompan / flow_lipsync.
4. production_json: unidad_tipo del vocabulario del pipeline se expone
   PLANO en meta.type (avatar/product_broll) sin degradar el unit type
   verbatim de meta.production_unit.type; valores ajenos NO se tipan.
5. Contratos: vocabulario sincronizado con pipeline/video.py y mapeo
   role→title en el orquestador (source-based).

Hermeticidad: cero red, cero LLM, cero ffmpeg — SQLite en tmp_path.
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import config as _cfg  # noqa: E402
_TMP = Path(tempfile.mkdtemp(prefix="p1work-int078-"))
_cfg.DB_PATH = _TMP / "test.db"
_cfg.OUTPUT_DIR = _TMP / "output"

import database as db  # noqa: E402  (lee config.DB_PATH ya parcheado)
from pipeline import script_gen  # noqa: E402
from pipeline.video import scene_render_mode, BROLL_TYPES  # noqa: E402
from services import production_json as pj  # noqa: E402
from services import ugc_ad_generator  # noqa: E402


# ── 1 · generate_ugc_script: estructura ganadora avatar→broll→avatar ────
def test_ugc_script_tipado_estructura_ganadora():
    for angle in ("3_reasons", "before_after", "problema_solucion"):
        ugc = ugc_ad_generator.generate_ugc_script(
            {"name": "Mochila Anti-robo", "description": "impermeable y con USB",
             "price": "$29"}, angle=angle, duration_sec=36)
        scenes = ugc["scenes"]
        assert len(scenes) == 4
        types = [sc["type"] for sc in scenes]
        # hook y cierre/avatar; beneficios intermedios = B-roll de producto
        assert types == ["avatar", "product_broll", "product_broll", "avatar"], \
            f"{angle}: {types}"
        # semántica narrativa conservada en role (antes vivía en type)
        assert [sc["role"] for sc in scenes] == \
            ["hook", "benefit_1", "benefit_2", "cta"]
        # nada se degrada: narración y prompt siguen íntegros
        assert all(sc["narration"] and sc["visual_prompt"] for sc in scenes)


def test_ugc_script_roles_tipos_nunca_se_confunden():
    ugc = ugc_ad_generator.generate_ugc_script({"name": "X"})
    for sc in ugc["scenes"]:
        assert sc["type"] in {"avatar", "product_broll"}   # vocabulario render
        assert sc["role"] in {"hook", "benefit_1", "benefit_2", "cta"}


# ── 2 · build_result: preservación en scenes.meta.type ──────────────────
def test_build_result_preserva_meta_type():
    raw = {"title": "UGC X", "engine": "v4v-ugc", "scenes": [
        {"title": "hook", "narration": "a", "image_prompt": "p", "type": "avatar"},
        {"title": "benefit_1", "narration": "b", "image_prompt": "q",
         "type": "product_broll"},
    ]}
    result = script_gen.build_result(raw)
    assert [sc.get("meta", {}).get("type") for sc in result["scenes"]] == \
        ["avatar", "product_broll"]
    # sanitize no borra el campo extra ni el meta
    assert all("meta" in sc for sc in result["scenes"])
    # title/narration/image_prompt intactos
    assert result["scenes"][0]["title"] == "hook"
    assert result["scenes"][0]["narration"] == "a"


def test_build_result_sin_type_meta_legacy_intacto():
    result = script_gen.build_result({"title": "t", "scenes": [
        {"title": "a", "narration": "n", "image_prompt": "p"},
        {"title": "b", "narration": "m", "image_prompt": "r", "meta": {"camara": "receta_x"}},
    ]})
    assert "meta" not in result["scenes"][0]          # sin type → sin meta
    s1 = result["scenes"][1]["meta"]
    assert "type" not in s1 and s1["camara"] == "receta_x"  # meta ajeno intacto
    # un type ajeno al vocabulario se conserva pero NO activa B-roll
    r3 = script_gen.build_result({"title": "t", "scenes": [
        {"title": "a", "narration": "n", "image_prompt": "p", "type": "curiosidad"}]})
    assert r3["scenes"][0]["meta"]["type"] == "curiosidad"
    assert scene_render_mode(r3["scenes"][0], True) == "flow_lipsync"


# ── 3 · roundtrip DB + consumo por el pipeline de render ────────────────
def test_roundtrip_db_y_modos_de_render(tmp_path):
    pid = "a1b2c3d4e5f6"
    db.create_project(id=pid, title="UGC Roundtrip", mode="product",
                      status="draft", format="short", style="cinematic")
    try:
        ugc = ugc_ad_generator.generate_ugc_script({"name": "Reloj Híbrido"})
        raw = [{"title": sc.get("role") or sc.get("type", "Scene"),
                "narration": sc["narration"],
                "image_prompt": sc["visual_prompt"],
                "type": sc.get("type")} for sc in ugc["scenes"]]
        result = script_gen.build_result(
            {"title": ugc["title"], "scenes": raw, "engine": "v4v-ugc"})
        db.replace_scenes(pid, result["scenes"])
        scenes = db.get_scenes(pid)
        assert len(scenes) == 4
        assert [sc.get("meta", {}).get("type") for sc in scenes] == \
            ["avatar", "product_broll", "product_broll", "avatar"]
        # el pipeline de render (INT-077) recibe el tipo sin degradarse
        modes = [scene_render_mode(sc, True) for sc in scenes]
        assert modes == ["flow_lipsync", "broll_zoompan",
                         "broll_zoompan", "flow_lipsync"]
        # y con Flow ausente el avatar cae a Ken Burns (fail-open) mientras
        # el B-roll NO cambia de modo
        modes_nofv = [scene_render_mode(sc, False) for sc in scenes]
        assert modes_nofv == ["kenburns", "broll_zoompan",
                              "broll_zoompan", "kenburns"]
    finally:
        with db.connect() as con:
            con.execute("DELETE FROM scenes WHERE project_id=?", (pid,))
            con.execute("DELETE FROM projects WHERE id=?", (pid,))


# ── 4 · production_json: unidad_tipo → meta.type plano ──────────────────
def _validate_min(payload_seq):
    data = {"project": {"title": "Tipado UGC PJ", "style": "cinematic"},
            "sequence": payload_seq, "auto_start": False}
    g, avisos, norm = pj.validate(data, {"cinematic"})
    return g["escenas"], avisos, norm


def test_production_json_expone_meta_type_plano():
    # contrato del Creative Engine: las unidades traen 'type' (alias de
    # unidad_tipo: type/unit_type/kind/role — ver _ALIASES)
    escenas, _, _ = _validate_min([
        {"id": "u1", "type": "avatar", "image_prompt": "p1",
         "narration": "hook", "duration": 3},
        {"id": "u2", "type": "product_broll", "image_prompt": "p2",
         "narration": "broll", "duration": 4},
        {"id": "u3", "type": "BROLL", "image_prompt": "p3",
         "narration": "alias", "duration": 2},
        {"id": "u4", "type": "escena_magica", "image_prompt": "p4",
         "narration": "nicho ajeno", "duration": 2},
    ])
    mtypes = [e["meta"].get("type") for e in escenas]
    assert mtypes == ["avatar", "product_broll", "product_broll", None]
    # el unit type verbatim NUNCA se degrada (vive en production_unit)
    assert [e["meta"]["production_unit"]["type"] for e in escenas] == \
        ["avatar", "product_broll", "BROLL", "escena_magica"]
    # consumo por el pipeline con el type plano
    modes = [scene_render_mode(e, True) for e in escenas]
    assert modes == ["flow_lipsync", "broll_zoompan", "broll_zoompan",
                     "flow_lipsync"]


def test_production_json_sin_unidad_tipo_legacy():
    escenas, _, _ = _validate_min([
        {"image_prompt": "x", "narration": "n", "duration": 3},
    ])
    assert "type" not in escenas[0]["meta"]            # sin tipo → sin meta.type
    assert escenas[0]["meta"]["production_unit"]["type"] == "scene"  # default


# ── 5 · contratos de sincronía (anti-desincronización) ──────────────────
def test_contratos_vocabulario_y_orquestador():
    # vocabulario production_json sincronizado con el consumidor real
    assert pj._RENDER_BROLL_TYPES == BROLL_TYPES
    assert pj._render_type_of("avatar") == "avatar"
    assert pj._render_type_of("") is None and pj._render_type_of(None) is None
    # el orquestador mapea role→title y pasa type a build_result (source)
    src = (BACKEND / "pipeline" / "orchestrator.py").read_text(encoding="utf-8")
    assert '"title": sc.get("role") or sc.get("type", "Scene")' in src
    assert '"type": sc.get("type"),' in src
    # el generador emite 4 escenas con role+type (source)
    src_ugc = (BACKEND / "services" / "ugc_ad_generator.py").read_text(
        encoding="utf-8")
    assert '"role": "hook"' in src_ugc and '"type": "avatar"' in src_ugc
    assert '"type": "product_broll"' in src_ugc
