# -*- coding: utf-8 -*-
"""Batería BG (2026-11): BG1 resiliencia de Gemini + BG2 blueprint externo.

BG1 (gemini_client / script_gen / pipeline_orchestrator):
  · 429 RESOURCE_EXHAUSTED NO se reintenta sobre el mismo modelo (cuota
    diaria): pasa al siguiente de GEMINI_TEXT_MODEL_FALLBACKS; agotada la
    cadena, falla con el motivo real.
  · 503 UNAVAILABLE se reintenta con esperas LITERALES de 5 y 15 s antes de
    pasar al siguiente modelo.
  · 404 NOT_FOUND sigue pasando al siguiente modelo SIN esperas (BD 2C).
  · script_gen registra el último error de Gemini (código y tipo, SIN
    claves) y el orquestador lo surface en BLUEPRINT_DEMO:
    "Gemini falló: <429 cuota | 503 alta demanda | timeout | clave
    inválida>" — la sugerencia fija "¿GEMINI_API_KEY inválida?" desaparece.

BG2 (blueprint externo — puerta declarada, nunca oculta):
  · POST /api/pipeline/run acepta "blueprint" {label, title, scenes}.
  · Validación EXTRICTA → INVALID_BLUEPRINT ante cualquier caso inválido
    (esquema, >12 escenas, >max_scenes, símbolos en label, límites por
    campo, payload >20 KB); los caracteres de control se QUITAN.
  · Con blueprint válido la etapa 2 NO llama a Gemini: engine
    "external:<label>", gemini_model "", blueprint_source "external"
    visible en /api/pipeline/status, log.warning claro y la etapa 3 recibe
    las escenas. Sin "blueprint", la ruta normal queda intacta.

Hermética: cero red, cero Chrome, cero LLM real (doubles + mock.patch).
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

import config
from pipeline import script_gen
from services import gemini_client
from services import pipeline_orchestrator as po


# ═══════════════════════════════ helpers herméticos ═══════════════════════

def _err(status: int, text: str) -> Exception:
    """Error estilo SDK google-genai: excepción con .code numérico."""
    e = Exception(text)
    e.code = status
    return e


class _FakeOKResponse:
    def __init__(self, text='{"title": "T", "scenes": []}'):
        self.text = text


class MockManagerBG:
    """Mock hermético del MCP manager: preflight OK en ambos servicios,
    contexto notebook_query JSON, Flow genera archivos reales en /tmp."""

    def __init__(self):
        self.exec_calls = []
        self._img_n = 0

    async def test_pipeline(self, service, notebook_id=None):
        return {"service": service, "ok": True, "state": "connected",
                "auth": "ok", "detail": "", "browser_up": True}

    async def tools_catalog(self, service, auto_connect=True):
        return {"tools": [{"name": "notebook_query"}]}

    async def execute(self, service, tool, arguments=None, timeout=None, **kw):
        args = dict(arguments or {})
        self.exec_calls.append((service, tool, args))
        if tool == "notebook_query":
            return {"ok": True, "text": json.dumps(
                {"status": "success", "answer": "CONTEXTO FALSO del notebook"})}
        if tool == "flow_upload_file":
            n = args.get("name", "ref")
            return {"ok": True, "text": f'Uploaded "{n}". Reference as @{{{n}}}.'}
        if tool == "flow_generate_image":
            self._img_n += 1
            p = f"/tmp/bg_fake/gen_img_{self._img_n}.png"
            Path(p).parent.mkdir(parents=True, exist_ok=True)
            Path(p).write_bytes(b"fake png")
            return {"ok": True, "text": f"Generated 1 image(s):\n{p}"}
        if tool == "flow_generate_video":
            out = args.get("outFile") or "/tmp/bg_fake/v.mp4"
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"fake mp4")
            return {"ok": True, "text": f"Generated video:\n{out}"}
        return {"ok": True, "text": "ok"}


def _valid_bp(n=3, label="frutinovela"):
    return {
        "label": label,
        "title": "La manzana y la pera",
        "scenes": [
            {"title": f"Escena {i + 1}",
             "narration": f"Narración de la escena {i + 1}.",
             "image_prompt": f"cinematic shot {i + 1}"}
            for i in range(n)
        ],
    }


def _chain_cfg():
    """Parches de config para la cadena de modelos: m-prim → m-fb."""
    return (
        mock.patch.object(config, "GEMINI_API_KEY", "test_key"),
        mock.patch.object(config, "GEMINI_TEXT_MODEL", "m-prim"),
        mock.patch.object(config, "GEMINI_TEXT_MODEL_FALLBACKS", ["m-fb"]),
    )


# ═══════════════════════════════ BG1 · gemini_client ══════════════════════

@pytest.mark.asyncio
async def test_bg1_429_no_retry_same_model_moves_to_fallback():
    """BG1: 429 RESOURCE_EXHAUSTED no se reintenta sobre el mismo modelo —
    pasa al siguiente de GEMINI_TEXT_MODEL_FALLBACKS sin ninguna espera."""
    gemini_client.set_remembered_text_model(None)
    attempted, waits = [], []

    def fake_generate_content(*args, **kwargs):
        model = kwargs.get("model")
        attempted.append(model)
        if model == "m-prim":
            raise _err(429, "429 RESOURCE_EXHAUSTED. You exceeded your current quota.")
        return _FakeOKResponse()

    async def _record_sleep(_):
        waits.append(_)

    cl = mock.MagicMock()
    cl.models.generate_content.side_effect = fake_generate_content
    patches = _chain_cfg()
    with patches[0], patches[1], patches[2], \
         mock.patch.object(gemini_client, "client", return_value=cl), \
         mock.patch.object(gemini_client.asyncio, "sleep", _record_sleep):
        res = await gemini_client.generate_json("prompt de prueba")

    assert attempted == ["m-prim", "m-fb"], attempted      # siguiente modelo, 1 intento exacto
    assert waits == [], waits                              # cero esperas: 429 no se reintenta
    assert res.get("title") == "T"
    assert gemini_client.get_active_text_model() == "m-fb"


@pytest.mark.asyncio
async def test_bg1_429_exhausted_chain_fails_with_real_reason():
    """BG1: si no queda ningún modelo en la cadena, falla con el motivo real
    (la excepción 429 literal, no un mensaje genérico)."""
    gemini_client.set_remembered_text_model(None)
    attempted = []

    def fake_generate_content(*args, **kwargs):
        attempted.append(kwargs.get("model"))
        raise _err(429, "429 RESOURCE_EXHAUSTED. You exceeded your current quota.")

    cl = mock.MagicMock()
    cl.models.generate_content.side_effect = fake_generate_content
    patches = _chain_cfg()
    with patches[0], patches[1], patches[2], \
         mock.patch.object(gemini_client, "client", return_value=cl):
        with pytest.raises(Exception) as ei:
            await gemini_client.generate_json("p")
    assert attempted == ["m-prim", "m-fb"], attempted      # cada modelo UNA vez
    assert "RESOURCE_EXHAUSTED" in str(ei.value)           # motivo real literal


@pytest.mark.asyncio
async def test_bg1_503_retries_with_5_and_15s_then_next_model():
    """BG1: 503 UNAVAILABLE se reintenta con esperas LITERALES de 5 y 15 s
    antes de pasar al siguiente modelo."""
    gemini_client.set_remembered_text_model(None)
    attempted, waits = [], []

    def fake_generate_content(*args, **kwargs):
        model = kwargs.get("model")
        attempted.append(model)
        if model == "m-prim":
            raise _err(503, "503 UNAVAILABLE. The model is overloaded. Try again later.")
        return _FakeOKResponse()

    async def _record_sleep(_):
        waits.append(_)

    cl = mock.MagicMock()
    cl.models.generate_content.side_effect = fake_generate_content
    patches = _chain_cfg()
    with patches[0], patches[1], patches[2], \
         mock.patch.object(gemini_client, "client", return_value=cl), \
         mock.patch.object(gemini_client.asyncio, "sleep", _record_sleep):
        res = await gemini_client.generate_json("p")

    # 503: 2 reintentos sobre m-prim (con esperas 5 y 15 s) ANTES de pasar a m-fb
    assert attempted == ["m-prim", "m-prim", "m-prim", "m-fb"], attempted
    assert waits == [5.0, 15.0], waits                     # LITERAL: 5 s y 15 s
    assert res.get("title") == "T"


@pytest.mark.asyncio
async def test_bg1_503_second_attempt_succeeds_stays_on_model():
    """BG1: si el segundo intento supera el 503, la corrida continúa sobre el
    MISMO modelo (una sola espera de 5 s, sin saltar de modelo)."""
    gemini_client.set_remembered_text_model(None)
    attempted, waits = [], []

    def fake_generate_content(*args, **kwargs):
        model = kwargs.get("model")
        attempted.append(model)
        if model == "m-prim" and attempted.count("m-prim") == 1:
            raise _err(503, "503 UNAVAILABLE. The model is overloaded.")
        return _FakeOKResponse()

    async def _record_sleep(_):
        waits.append(_)

    cl = mock.MagicMock()
    cl.models.generate_content.side_effect = fake_generate_content
    patches = _chain_cfg()
    with patches[0], patches[1], patches[2], \
         mock.patch.object(gemini_client, "client", return_value=cl), \
         mock.patch.object(gemini_client.asyncio, "sleep", _record_sleep):
        res = await gemini_client.generate_json("p")

    assert attempted == ["m-prim", "m-prim"], attempted
    assert waits == [5.0], waits
    assert res.get("title") == "T"
    assert gemini_client.get_active_text_model() == "m-prim"


@pytest.mark.asyncio
async def test_bg1_404_moves_to_next_model_without_waits():
    """BG1: 404 NOT_FOUND pasa al siguiente modelo SIN esperas (comportamiento
    BD 2C preservado)."""
    gemini_client.set_remembered_text_model(None)
    attempted, waits = [], []

    def fake_generate_content(*args, **kwargs):
        model = kwargs.get("model")
        attempted.append(model)
        if model == "m-prim":
            raise _err(404, "404 NOT_FOUND. Model models/m-prim is no longer available.")
        return _FakeOKResponse()

    async def _record_sleep(_):
        waits.append(_)

    cl = mock.MagicMock()
    cl.models.generate_content.side_effect = fake_generate_content
    patches = _chain_cfg()
    with patches[0], patches[1], patches[2], \
         mock.patch.object(gemini_client, "client", return_value=cl), \
         mock.patch.object(gemini_client.asyncio, "sleep", _record_sleep):
        res = await gemini_client.generate_json("p")

    assert attempted == ["m-prim", "m-fb"], attempted
    assert waits == [], waits
    assert res.get("title") == "T"


@pytest.mark.asyncio
async def test_bg1_generate_text_429_also_skips_to_fallback():
    """BG1: la cadena de generate_text aplica la misma política 429 (un
    intento por modelo, sin esperas)."""
    gemini_client.set_remembered_text_model(None)
    attempted, waits = [], []

    def fake_generate_content(*args, **kwargs):
        model = kwargs.get("model")
        attempted.append(model)
        if model == "m-prim":
            raise _err(429, "429 RESOURCE_EXHAUSTED quota.")
        return _FakeOKResponse(text="texto simple")

    async def _record_sleep(_):
        waits.append(_)

    cl = mock.MagicMock()
    cl.models.generate_content.side_effect = fake_generate_content
    patches = _chain_cfg()
    with patches[0], patches[1], patches[2], \
         mock.patch.object(gemini_client, "client", return_value=cl), \
         mock.patch.object(gemini_client.asyncio, "sleep", _record_sleep):
        out = await gemini_client.generate_text("p")

    assert attempted == ["m-prim", "m-fb"], attempted
    assert waits == [], waits
    assert out == "texto simple"


# ═══════════════════════════════ BG1 · script_gen ═════════════════════════

def test_bg1_script_gen_records_and_classifies_last_error():
    """BG1: script_gen guarda el último error de Gemini y el motivo legible
    es exactamente uno de los cuatro declarados."""
    script_gen.clear_gemini_error()
    assert script_gen.describe_gemini_error() == ""
    assert script_gen.last_gemini_error() is None

    script_gen.record_gemini_error(_err(429, "429 RESOURCE_EXHAUSTED. quota"))
    assert script_gen.describe_gemini_error() == "429 cuota"

    script_gen.record_gemini_error(_err(503, "503 UNAVAILABLE overloaded"))
    assert script_gen.describe_gemini_error() == "503 alta demanda"

    script_gen.record_gemini_error(asyncio.TimeoutError())
    assert script_gen.describe_gemini_error() == "timeout"

    script_gen.record_gemini_error(Exception("API key not valid. Please pass a valid API key."))
    assert script_gen.describe_gemini_error() == "clave inválida"

    rec = script_gen.last_gemini_error()
    assert rec["type"] == "Exception"                       # tipo literal
    assert rec["code"] == ""                                # sin .code → vacío, no invención


def test_bg1_recorded_error_has_code_and_type_and_no_key_material():
    """BG1: el registro lleva código y tipo, y el detalle NUNCA contiene la
    API key (saneado por gemini_client._sanitize_error)."""
    fake_key = "AIzaFAKE-KEY-1234567890abcdef"
    with mock.patch.object(config, "GEMINI_API_KEY", fake_key):
        rec = script_gen.record_gemini_error(Exception(
            f"API key not valid: {fake_key} [reason: API_KEY_INVALID]"))
    assert rec["reason"] == "clave inválida"
    assert rec["type"] == "Exception"
    assert fake_key not in rec["detail"]
    assert "***REDACTADO***" in rec["detail"]


@pytest.mark.asyncio
async def test_bg1_from_idea_records_real_error_and_degrades_to_demo():
    """BG1: from_idea con Gemini cayendo (429) degrada a local-demo y deja
    registrado el motivo real; la corrida siguiente limpia el registro."""
    gemini_client.set_remembered_text_model(None)
    script_gen.clear_gemini_error()

    def fake_generate_content(*args, **kwargs):
        raise _err(429, "429 RESOURCE_EXHAUSTED. quota daily limit.")

    cl = mock.MagicMock()
    cl.models.generate_content.side_effect = fake_generate_content
    with mock.patch.object(config, "GEMINI_API_KEY", "test_key"), \
         mock.patch.object(gemini_client, "client", return_value=cl):
        res = await script_gen.from_idea("idea de prueba", "auto", "short")

    assert res.get("engine") == "local-demo"
    assert script_gen.describe_gemini_error() == "429 cuota"
    rec = script_gen.last_gemini_error()
    assert rec["code"] == 429 and rec["type"] == "Exception"

    # la corrida siguiente (error distinto) SURPISA el motivo nuevo, no el viejo
    def fake_generate_content_503(*args, **kwargs):
        raise _err(503, "503 UNAVAILABLE alta demanda")

    cl.models.generate_content.side_effect = fake_generate_content_503
    with mock.patch.object(config, "GEMINI_API_KEY", "test_key"), \
         mock.patch.object(gemini_client, "client", return_value=cl):
        await script_gen.from_idea("otra idea", "auto", "short")
    assert script_gen.describe_gemini_error() == "503 alta demanda"

    # sin key configurada: no hay error de Gemini registrado en la corrida
    script_gen.clear_gemini_error()
    with mock.patch.object(config, "GEMINI_API_KEY", ""):
        await script_gen.from_idea("tercera idea", "auto", "short")
    assert script_gen.describe_gemini_error() == ""


# ═══════════════════════ BG1 · mensaje de BLUEPRINT_DEMO ══════════════════

def _demo_run_run(message_reason_setup: str):
    """Corre _run real con from_idea degradando a local-demo; devuelve el
    status para inspección del mensaje BLUEPRINT_DEMO."""
    with tempfile.TemporaryDirectory() as td:
        orch = po.PipelineOrchestrator(manager=MockManagerBG(),
                                       runs_dir=Path(td) / "runs")

        async def fake_from_idea(*a, **k):
            if message_reason_setup == "429":
                script_gen.record_gemini_error(_err(429, "429 RESOURCE_EXHAUSTED quota"))
            else:
                script_gen.clear_gemini_error()
            return {"title": "Historia Demo", "engine": "local-demo",
                    "scenes": [{"title": "E1", "narration": "N1", "image_prompt": "P1"}]}

        with mock.patch.object(po.script_gen, "from_idea", fake_from_idea), \
             mock.patch.object(po.script_gen, "build_result", lambda raw: raw):
            os.environ.pop("PIPELINE_ALLOW_DEMO", None)
            run = orch.create_run(idea="idea demo", notebook_id="nb_mock")
            asyncio.run(orch._run(run["run_id"]))
            st = orch.get_status(run["run_id"])
    return st


def test_bg1_blueprint_demo_message_carries_real_429_reason():
    """BG1: BLUEPRINT_DEMO surface el motivo REAL registrado ('Gemini falló:
    429 cuota') y la sugerencia fija desaparece."""
    st = _demo_run_run("429")
    assert st["stage"] == "error"
    assert st["error_code"] == "BLUEPRINT_DEMO"
    assert "Gemini falló: 429 cuota" in st["error_detail"]
    assert "¿GEMINI_API_KEY inválida?" not in st["error_detail"]
    assert "el guion salió del generador demo y no se despacha a Flow" in st["error_detail"]


def test_bg1_blueprint_demo_message_without_error_is_a_fact_not_a_guess():
    """BG1: sin error registrado (no había key), el mensaje declara el hecho
    ('sin GEMINI_API_KEY configurada') — no una conjetura."""
    st = _demo_run_run("sin-error")
    assert st["error_code"] == "BLUEPRINT_DEMO"
    assert "Gemini falló: sin GEMINI_API_KEY configurada" in st["error_detail"]
    assert "¿GEMINI_API_KEY inválida?" not in st["error_detail"]


# ═══════════════════════════ BG2 · validación ═════════════════════════════

def _broken(label, fn):
    return (label, fn)


CASOS_INVALIDOS = [
    _broken("no es un objeto", lambda: "texto plano"),
    _broken("claves extra", lambda: {**_valid_bp(1), "extra": 1}),
    _broken("sin label", lambda: {"title": "t", "scenes": _valid_bp(1)["scenes"]}),
    _broken("label con símbolos", lambda: {**_valid_bp(1), "label": "fruti!"}),
    _broken("label vacío", lambda: {**_valid_bp(1), "label": ""}),
    _broken("label 31 chars", lambda: {**_valid_bp(1), "label": "a" * 31}),
    _broken("label no string", lambda: {**_valid_bp(1), "label": 7}),
    _broken("title 121 chars", lambda: {**_valid_bp(1), "title": "x" * 121}),
    _broken("title no string", lambda: {**_valid_bp(1), "title": 123}),
    _broken("scenes lista vacía", lambda: {**_valid_bp(1), "scenes": []}),
    _broken("13 escenas", lambda: _valid_bp(13)),
    _broken("scenes no lista", lambda: {**_valid_bp(1), "scenes": "no"}),
    _broken("escena no objeto", lambda: {**_valid_bp(1), "scenes": ["x"]}),
    _broken("escena sin clave", lambda: {**_valid_bp(1), "scenes": [
        {"title": "t", "narration": "n"}]}),
    _broken("escena con clave extra", lambda: {**_valid_bp(1), "scenes": [
        {"title": "t", "narration": "n", "image_prompt": "p", "meta": {}}]}),
    _broken("escena valor no string", lambda: {**_valid_bp(1), "scenes": [
        {"title": "t", "narration": 99, "image_prompt": "p"}]}),
    _broken("title escena 81 chars", lambda: {**_valid_bp(1), "scenes": [
        {"title": "x" * 81, "narration": "n", "image_prompt": "p"}]}),
    _broken("narration 301 chars", lambda: {**_valid_bp(1), "scenes": [
        {"title": "t", "narration": "x" * 301, "image_prompt": "p"}]}),
    _broken("image_prompt 1201 chars", lambda: {**_valid_bp(1), "scenes": [
        {"title": "t", "narration": "n", "image_prompt": "x" * 1201}]}),
    _broken("payload >20 KB", lambda: {
        "label": "frutinovela", "title": "á" * 120,
        "scenes": [{"title": "á" * 80, "narration": "é" * 300,
                    "image_prompt": "í" * 1200} for _ in range(12)]}),
]


@pytest.mark.parametrize("nombre,caso", CASOS_INVALIDOS, ids=[c[0] for c in CASOS_INVALIDOS])
def test_bg2_invalid_blueprint_rejected_with_invalid_blueprint(nombre, caso):
    """BG2: cualquier caso inválido → INVALID_BLUEPRINT (nunca reparación
    silenciosa ni truncado)."""
    bp = caso() if callable(caso) else caso
    with tempfile.TemporaryDirectory() as td:
        orch = po.PipelineOrchestrator(manager=MockManagerBG(),
                                       runs_dir=Path(td) / "runs")
        with pytest.raises(po.PipelineError) as ei:
            orch.create_run(idea="idea", blueprint=bp)
    assert ei.value.code == "INVALID_BLUEPRINT", ei.value


def test_bg2_more_scenes_than_max_scenes_rejected_not_trimmed():
    """BG2: más escenas que max_scenes → INVALID_BLUEPRINT (no truncar en
    silencio); con max_scenes suficiente pasa."""
    bp = _valid_bp(3)
    with tempfile.TemporaryDirectory() as td:
        orch = po.PipelineOrchestrator(manager=MockManagerBG(),
                                       runs_dir=Path(td) / "runs")
        with pytest.raises(po.PipelineError) as ei:
            orch.create_run(idea="idea", max_scenes=2, blueprint=bp)
        assert ei.value.code == "INVALID_BLUEPRINT"
        run = orch.create_run(idea="idea", max_scenes=3, blueprint=bp)
    assert run["external_blueprint"]["scenes"] == bp["scenes"]


def test_bg2_control_chars_removed_not_rejected():
    """BG2: los caracteres de control se QUITAN (normalización declarada)."""
    bp = _valid_bp(2)
    bp["scenes"][0]["narration"] = "La manzana\x07 descubre\x00 la traición."
    bp["scenes"][1]["image_prompt"] = "shot\x1f with control"
    norm = po.validate_external_blueprint(bp, None)
    assert norm["scenes"][0]["narration"] == "La manzana descubre la traición."
    assert norm["scenes"][1]["image_prompt"] == "shot with control"


def test_bg2_limits_after_control_char_removal():
    """BG2: los límites se miden sobre el string NORMALIZADO (una narración
    que rebasa solo por caracteres de control pasa)."""
    bp = _valid_bp(1)
    bp["scenes"][0]["narration"] = "x" * 290 + "\x01\x02" * 10   # 310 → 290 limpio
    norm = po.validate_external_blueprint(bp, None)
    assert len(norm["scenes"][0]["narration"]) == 290


# ═══════════════════════════ BG2 · etapa 2 externa ════════════════════════

def test_bg2_valid_external_blueprint_skips_gemini_and_reaches_stage3(caplog):
    """BG2: blueprint externo válido → la etapa 2 NO llama a Gemini (0
    llamadas a from_idea), engine "external:<label>", gemini_model "",
    blueprint_source "external" visible en status, log.warning claro y la
    etapa 3 despacha las escenas recibidas."""
    calls = {"from_idea": 0}

    async def spy_from_idea(*a, **k):
        calls["from_idea"] += 1
        return {"title": "NO DEBE PASAR", "engine": "fake",
                "scenes": [{"title": "X", "narration": "X", "image_prompt": "X"}]}

    bp = _valid_bp(3)
    bp["scenes"][0]["narration"] = "La manzana descubre\x07 la traición."
    with tempfile.TemporaryDirectory() as td:
        mgr = MockManagerBG()
        orch = po.PipelineOrchestrator(manager=mgr, runs_dir=Path(td) / "runs")
        run = orch.create_run(idea="idea", notebook_id="nb_mock", blueprint=bp)
        assert run["blueprint_source"] == ""       # antes de arrancar: vacío
        with mock.patch.object(po.script_gen, "from_idea", spy_from_idea), \
             caplog.at_level(logging.WARNING, logger="pipeline_orchestrator"):
            asyncio.run(orch._run(run["run_id"]))
        st = orch.get_status(run["run_id"])

    assert st["stage"] == "done", (st["stage"], st["error_detail"])
    assert calls["from_idea"] == 0, calls          # etapa 2 NO llama a Gemini
    assert st["engine"] == "external:frutinovela", st["engine"]
    assert st["gemini_model"] == "", st["gemini_model"]
    assert st["blueprint_source"] == "external"
    assert [s["scene_id"] for s in st["scenes"]] == ["s1", "s2", "s3"]
    assert st["scenes"][0]["narration"] == "La manzana descubre la traición."
    assert any("Blueprint EXTERNO frutinovela: no generado por Gemini"
               in r.getMessage() for r in caplog.records), caplog.text


def test_bg2_external_blueprint_json_and_stage3_handoff():
    """BG2: blueprint.json persistido con engine/blueprint_source externos y
    la etapa 3 recibe CADA escena (la narración llega al prompt del video)."""
    bp = _valid_bp(3)
    with tempfile.TemporaryDirectory() as td:
        mgr = MockManagerBG()
        orch = po.PipelineOrchestrator(manager=mgr, runs_dir=Path(td) / "runs")
        run = orch.create_run(idea="idea", notebook_id="nb_mock", blueprint=bp)
        asyncio.run(orch._run(run["run_id"]))
        st = orch.get_status(run["run_id"])

        bp_disk = json.loads(
            (orch.runs_dir / run["run_id"] / "blueprint.json").read_text(encoding="utf-8"))
        assert bp_disk["engine"] == "external:frutinovela"
        assert bp_disk["blueprint_source"] == "external"
        assert bp_disk["gemini_model"] == ""

        vids = [c for c in mgr.exec_calls if c[1] == "flow_generate_video"]
        assert len(vids) == 3, len(vids)          # etapa 3 despachó las 3 escenas
        assert "Narración de la escena 2." in vids[1][2]["prompt"]


def test_bg2_normal_route_unchanged_without_blueprint():
    """BG2: sin 'blueprint', todo igual que hoy — from_idea se llama una vez,
    engine del generador intacto y blueprint_source queda vacío."""
    calls = {"n": 0}

    async def fake_from_idea(*a, **k):
        calls["n"] += 1
        return {"title": "Normal", "hook": "h", "cta": "c",
                "engine": "gemini (fake-model)",
                "scenes": [{"title": "E1", "narration": "N1", "image_prompt": "P1"},
                           {"title": "E2", "narration": "N2", "image_prompt": "P2"}]}

    with tempfile.TemporaryDirectory() as td:
        mgr = MockManagerBG()
        orch = po.PipelineOrchestrator(manager=mgr, runs_dir=Path(td) / "runs")
        run = orch.create_run(idea="idea", notebook_id="nb_mock")
        assert run["external_blueprint"] is None and run["blueprint_source"] == ""
        with mock.patch.object(po.script_gen, "from_idea", fake_from_idea), \
             mock.patch.object(po.script_gen, "build_result", lambda raw: raw):
            asyncio.run(orch._run(run["run_id"]))
        st = orch.get_status(run["run_id"])

    assert st["stage"] == "done", st["error_detail"]
    assert calls["n"] == 1, calls                  # ruta normal intacta
    assert st["engine"] == "gemini (fake-model)"
    assert st["blueprint_source"] == ""


# ═══════════════════════════ BG2 · endpoint HTTP ══════════════════════════

@pytest.mark.asyncio
async def test_bg2_endpoint_run_invalid_blueprint_400():
    """BG2: POST /api/pipeline/run con blueprint inválido → 400
    [INVALID_BLUEPRINT]."""
    import httpx
    import main as _main

    mgr = MockManagerBG()
    orig = (po.orchestrator.manager, po.orchestrator.runs_dir,
            po.orchestrator._busy)
    po.orchestrator.manager = mgr
    po.orchestrator.runs_dir = Path(tempfile.mkdtemp(prefix="bg_ep_")) / "runs"
    po.orchestrator._busy = None
    try:
        async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_main.app),
                base_url="http://testserver") as c:
            r = await c.post("/api/pipeline/run",
                             json={"idea": "idea", "blueprint": {"label": "malo!"}},
                             headers={"Origin": "http://testserver"})
            assert r.status_code == 400, r.text[:200]
            assert "INVALID_BLUEPRINT" in r.text
            r = await c.post("/api/pipeline/run",
                             json={"idea": "idea", "blueprint": _valid_bp(13)},
                             headers={"Origin": "http://testserver"})
            assert r.status_code == 400 and "INVALID_BLUEPRINT" in r.text
    finally:
        po.orchestrator.manager, po.orchestrator.runs_dir, po.orchestrator._busy = orig


@pytest.mark.asyncio
async def test_bg2_endpoint_run_valid_blueprint_full_run():
    """BG2: POST /api/pipeline/run con blueprint válido → corrida completa
    externa; GET /api/pipeline/status muestra blueprint_source external."""
    import httpx
    import main as _main

    mgr = MockManagerBG()
    orig = (po.orchestrator.manager, po.orchestrator.runs_dir,
            po.orchestrator._busy)
    po.orchestrator.manager = mgr
    po.orchestrator.runs_dir = Path(tempfile.mkdtemp(prefix="bg_ep_")) / "runs"
    po.orchestrator._busy = None
    try:
        async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_main.app),
                base_url="http://testserver") as c:
            r = await c.post("/api/pipeline/run",
                             json={"idea": "idea", "notebook_id": "nb_mock",
                                   "blueprint": _valid_bp(2)},
                             headers={"Origin": "http://testserver"})
            assert r.status_code == 200, r.text[:200]
            rid = r.json().get("run_id", "")
            await po.orchestrator.wait(rid, timeout=30.0)
            r = await c.get("/api/pipeline/status", params={"run_id": rid})
            js = r.json()
            assert r.status_code == 200
            assert js.get("engine") == "external:frutinovela", js.get("engine")
            assert js.get("gemini_model") == ""
            assert js.get("blueprint_source") == "external"
            assert [s["scene_id"] for s in js.get("scenes", [])] == ["s1", "s2"]
            assert all(s["status"] == "done" for s in js.get("scenes", []))
    finally:
        po.orchestrator.manager, po.orchestrator.runs_dir, po.orchestrator._busy = orig


if __name__ == "__main__":
    # Batería standalone (tests/run_all.py): plugin pytest para resumen parseable
    class _Resumen:
        def __init__(self) -> None:
            self.ok = self.fallos = 0

        def pytest_runtest_logreport(self, report):
            if report.when == "call":
                if report.passed:
                    self.ok += 1
                elif report.failed:
                    self.fallos += 1

    _res = _Resumen()
    _code = pytest.main([__file__, "-q"], plugins=[_res])
    print(f"\n{_res.ok} OK · {_res.fallos} fallos")
    sys.exit(int(_code))
