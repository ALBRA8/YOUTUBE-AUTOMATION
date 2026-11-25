# -*- coding: utf-8 -*-
"""Batería BN (2026-11): BN1 claves desconocidas en /api/pipeline/run + BN2
alias Gemini «-latest» por v1beta.

BN1 (main.py · POST /api/pipeline/run):
  · Una clave de primer nivel DESCONOCIDA (p. ej. "external_blueprint" en
    vez de "blueprint") antes se ignoraba EN SILENCIO: el blueprint no
    llegaba a create_run y la etapa 2 caía en Gemini gastando la corrida.
    Ahora el endpoint responde 422 con la clave culpable y una sugerencia
    difflib: «¿quisiste decir 'blueprint'?».
  · Varias claves desconocidas → las lista todas + el catálogo de claves
    válidas; una clave sin pariente cercano NO produce falsa sugerencia.
  · Las 7 claves conocidas siguen aceptándose igual (corrida externa 200).

BN2 (services/gemini_client.py · cadena de modelos de texto):
  · El SDK google-genai 3.6.1 rutea TODO por v1 (GOOGLE_AI_API_DEFAULT_
    VERSION='v1'), pero los alias de familia «-latest» solo están
    publicados en v1beta: por v1 dan 404 NOT_FOUND y la cadena quemaba el
    candidato sano (en vivo 2026-11-19: gemini-flash-latest 404 por v1,
    gemini-3.8-flash 200).
  · Política: alias «-latest» → PRIMERO v1beta (HttpOptions POR REQUEST,
    cliente global intacto); solo ante 404 se agota también v1 (prueba
    ambas versiones antes de descartarlo). 429/503 no prueban la otra
    versión (misma cuota/backend) → siguiente candidato como en BG1.
  · Resto de modelos: BD 2C intacto — UN intento por candidato con la
    versión por defecto (el guardia BD cuenta intentos literales).

Hermética: cero red, cero Chrome, cero LLM real (doubles + mock.patch).
"""
import asyncio
import json
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


class _Registro:
    """Graba (modelo, versión API) de cada llamada al SDK doble."""

    def __init__(self):
        self.llamadas: list[tuple[str, str | None]] = []

    def fake_generate_content(self, *args, **kwargs):
        cfg = kwargs.get("config")
        version = getattr(getattr(cfg, "http_options", None), "api_version", None)
        self.llamadas.append((kwargs.get("model"), version))
        return _FakeOKResponse()

    def fake_que_falla_en(self, regla):
        """regla(model, version) → excepción o None (éxito)."""

        def _impl(*args, **kwargs):
            cfg = kwargs.get("config")
            version = getattr(getattr(cfg, "http_options", None), "api_version", None)
            self.llamadas.append((kwargs.get("model"), version))
            exc = regla(kwargs.get("model"), version)
            if exc is not None:
                raise exc
            return _FakeOKResponse()

        return _impl


def _cliente_con(impl):
    cl = mock.MagicMock()
    cl.models.generate_content.side_effect = impl
    return cl


def _cfg_cadena(primario: str, fallbacks: list[str]):
    return (
        mock.patch.object(config, "GEMINI_API_KEY", "test_key"),
        mock.patch.object(config, "GEMINI_TEXT_MODEL", primario),
        mock.patch.object(config, "GEMINI_TEXT_MODEL_FALLBACKS", fallbacks),
    )


def _valid_bp(n=2, label="frutinovela"):
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


class MockManagerBN:
    """Mock hermético del MCP manager (preflight OK; Flow genera archivos
    reales en /tmp) — mismo patrón que la batería BG."""

    def __init__(self):
        self._img_n = 0

    async def test_pipeline(self, service, notebook_id=None):
        return {"service": service, "ok": True, "state": "connected",
                "auth": "ok", "detail": "", "browser_up": True}

    async def tools_catalog(self, service, auto_connect=True):
        return {"tools": [{"name": "notebook_query"}]}

    async def execute(self, service, tool, arguments=None, timeout=None, **kw):
        args = dict(arguments or {})
        if tool == "notebook_query":
            return {"ok": True, "text": json.dumps(
                {"status": "success", "answer": "CONTEXTO FALSO del notebook"})}
        if tool == "flow_upload_file":
            n = args.get("name", "ref")
            return {"ok": True, "text": f'Uploaded "{n}". Reference as @{{{n}}}.'}
        if tool == "flow_generate_image":
            self._img_n += 1
            p = f"/tmp/bn_fake/gen_img_{self._img_n}.png"
            Path(p).parent.mkdir(parents=True, exist_ok=True)
            Path(p).write_bytes(b"fake png")
            return {"ok": True, "text": f"Generated 1 image(s):\n{p}"}
        if tool == "flow_generate_video":
            out = args.get("outFile") or "/tmp/bn_fake/v.mp4"
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"fake mp4")
            return {"ok": True, "text": f"Generated video:\n{out}"}
        return {"ok": True, "text": "ok"}


# ═══════════════════════════════ BN1 · main.py ════════════════════════════

def test_bn1_sugerencia_clave_unit():
    """difflib: el caso literal del informe y cero falsas sugerencias."""
    import main as _main
    s = _main._sugerencia_clave("external_blueprint")
    assert s == " (¿quisiste decir 'blueprint'?)", s
    # parientes reales del catálogo
    assert "notebook_id" in _main._sugerencia_clave("notebook")
    assert "nicho_id" in _main._sugerencia_clave("nicho")
    assert "max_scenes" in _main._sugerencia_clave("maxscene")
    assert "format" in _main._sugerencia_clave("formato")
    assert "style" in _main._sugerencia_clave("styles")
    # sin pariente cercano → sin sugerencia (nada inventado)
    assert _main._sugerencia_clave("zzzqqq") == ""
    assert _main._sugerencia_clave("xyzzy_qwerty") == ""
    # catálogo completo y ordenado (determinista para el mensaje 422)
    assert _main._CLAVES_PIPELINE_RUN == (
        "blueprint", "format", "idea", "max_scenes", "nicho_id",
        "notebook_id", "style")


@pytest.mark.asyncio
async def test_bn1_unknown_key_422_suggests_blueprint():
    """BN1: 'external_blueprint' desconocida → 422 con sugerencia
    «¿quisiste decir 'blueprint'?» y NINGUNA corrida creada (antes: se
    ignoraba y la etapa 2 caía en Gemini)."""
    import httpx
    import main as _main

    create_run = mock.MagicMock()
    with mock.patch.object(po.orchestrator, "create_run", create_run):
        async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_main.app),
                base_url="http://testserver") as c:
            r = await c.post("/api/pipeline/run",
                             json={"idea": "idea de prueba",
                                   "external_blueprint": _valid_bp()},
                             headers={"Origin": "http://testserver"})
    assert r.status_code == 422, (r.status_code, r.text[:200])
    detalle = r.json().get("detail", "")
    assert "external_blueprint" in detalle, detalle
    assert "¿quisiste decir 'blueprint'?" in detalle, detalle
    assert "Claves válidas:" in detalle and "blueprint, format" in detalle, detalle
    create_run.assert_not_called()  # la corrida NUNCA se lanzó


@pytest.mark.asyncio
async def test_bn1_multiple_unknown_keys_listed_with_catalog():
    """BN1: varias claves desconocidas → 422 que las lista todas y añade
    el catálogo de claves válidas."""
    import httpx
    import main as _main

    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_main.app),
            base_url="http://testserver") as c:
        r = await c.post("/api/pipeline/run",
                         json={"idea": "x", "foo": 1, "bar_zzz": 2},
                         headers={"Origin": "http://testserver"})
    assert r.status_code == 422, (r.status_code, r.text[:200])
    detalle = r.json().get("detail", "")
    assert "'foo'" in detalle and "'bar_zzz'" in detalle, detalle
    for clave in ("blueprint", "format", "idea", "max_scenes",
                  "nicho_id", "notebook_id", "style"):
        assert clave in detalle, (clave, detalle)


@pytest.mark.asyncio
async def test_bn1_all_seven_known_keys_still_accepted_full_run():
    """BN1 regresión: payload con las 7 claves conocidas → 200 + corrida
    externa completa (blueprint_source external), cero 422 falsos."""
    import httpx
    import main as _main

    mgr = MockManagerBN()
    orig = (po.orchestrator.manager, po.orchestrator.runs_dir,
            po.orchestrator._busy)
    po.orchestrator.manager = mgr
    po.orchestrator.runs_dir = Path(tempfile.mkdtemp(prefix="bn_ep_")) / "runs"
    po.orchestrator._busy = None
    try:
        async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_main.app),
                base_url="http://testserver") as c:
            r = await c.post("/api/pipeline/run",
                             json={"idea": "idea", "format": "short",
                                   "style": "auto", "notebook_id": "nb_mock",
                                   "max_scenes": 3, "nicho_id": "n1",
                                   "blueprint": _valid_bp(2)},
                             headers={"Origin": "http://testserver"})
            assert r.status_code == 200, r.text[:200]
            rid = r.json().get("run_id", "")
            assert rid, r.text[:200]
            await po.orchestrator.wait(rid, timeout=30.0)
            st = await c.get("/api/pipeline/status", params={"run_id": rid})
            js = st.json()
            assert js.get("blueprint_source") == "external", js.get("blueprint_source")
            assert js.get("engine") == "external:frutinovela", js.get("engine")
    finally:
        po.orchestrator.manager, po.orchestrator.runs_dir, po.orchestrator._busy = orig


# ═══════════════════════ BN2 · gemini_client (cadena) ═════════════════════

def test_bn2_versiones_de_candidato_unit():
    """Familia «-latest» → v1beta primero y v1 de reserva; modelos normales
    → solo la versión por defecto del SDK (BD 2C intacto)."""
    assert gemini_client._versiones_de_candidato("gemini-flash-latest") == ("v1beta", "v1")
    assert gemini_client._versiones_de_candidato("gemini-flash-lite-latest") == ("v1beta", "v1")
    assert gemini_client._versiones_de_candidato("gemini-pro-latest") == ("v1beta", "v1")
    assert gemini_client._versiones_de_candidato("gemini-3.8-flash") == (None,)
    assert gemini_client._versiones_de_candidato("gemini-2.5-flash") == (None,)
    assert gemini_client._versiones_de_candidato("m-prim") == (None,)
    assert gemini_client._es_alias_latest("gemini-flash-latest") is True
    assert gemini_client._es_alias_latest("latest-gemini") is False
    assert gemini_client._es_alias_latest("gemini-3.8-flash") is False


@pytest.mark.asyncio
async def test_bn2_alias_latest_first_attempt_is_v1beta():
    """BN2: 'gemini-flash-latest' se intenta PRIMERO por v1beta (el SDK
    3.6.1 por defecto iría por v1 → 404). Un solo intento, éxito."""
    gemini_client.set_remembered_text_model(None)
    reg = _Registro()
    patches = _cfg_cadena("gemini-flash-latest", [])
    with patches[0], patches[1], patches[2], \
            mock.patch.object(gemini_client, "client",
                              return_value=_cliente_con(reg.fake_generate_content)):
        res = await gemini_client.generate_json("p")
    assert res.get("title") == "T", res
    assert reg.llamadas == [("gemini-flash-latest", "v1beta")], reg.llamadas
    assert gemini_client.get_active_text_model() == "gemini-flash-latest"


@pytest.mark.asyncio
async def test_bn2_alias_v1beta_404_then_v1_succeeds():
    """BN2: si v1beta da 404, el MISMO alias se prueba por v1 antes de
    descartarlo (prueba ambas versiones)."""
    gemini_client.set_remembered_text_model(None)
    reg = _Registro()
    impl = reg.fake_que_falla_en(
        lambda model, version: None if version == "v1"
        else _err(404, "404 NOT_FOUND. models/gemini-flash-latest not found")
        if version == "v1beta" else _err(500, "versión inesperada"))
    patches = _cfg_cadena("gemini-flash-latest", [])
    with patches[0], patches[1], patches[2], \
            mock.patch.object(gemini_client, "client",
                              return_value=_cliente_con(impl)):
        res = await gemini_client.generate_json("p")
    assert res.get("title") == "T", res
    assert reg.llamadas == [("gemini-flash-latest", "v1beta"),
                            ("gemini-flash-latest", "v1")], reg.llamadas
    assert gemini_client.get_active_text_model() == "gemini-flash-latest"


@pytest.mark.asyncio
async def test_bn2_alias_exhausted_both_versions_moves_to_next_candidate():
    """BN2: alias 404 en v1beta Y en v1 → recién ahí pasa al siguiente
    candidato de la cadena (gemini-3.8-flash, versión default)."""
    gemini_client.set_remembered_text_model(None)
    reg = _Registro()
    impl = reg.fake_que_falla_en(
        lambda model, version: _err(404, "404 NOT_FOUND")
        if model == "gemini-flash-latest" else None)
    patches = _cfg_cadena("gemini-flash-latest", ["gemini-3.8-flash"])
    with patches[0], patches[1], patches[2], \
            mock.patch.object(gemini_client, "client",
                              return_value=_cliente_con(impl)):
        res = await gemini_client.generate_json("p")
    assert res.get("title") == "T", res
    assert reg.llamadas == [("gemini-flash-latest", "v1beta"),
                            ("gemini-flash-latest", "v1"),
                            ("gemini-3.8-flash", None)], reg.llamadas
    assert gemini_client.get_active_text_model() == "gemini-3.8-flash"


@pytest.mark.asyncio
async def test_bn2_non_latest_model_keeps_single_default_attempt():
    """BN2 regresión BD 2C: un modelo NO-alias sigue intentándose UNA vez
    con la versión por defecto (sin duplicar intentos por versión)."""
    gemini_client.set_remembered_text_model(None)
    reg = _Registro()
    impl = reg.fake_que_falla_en(
        lambda model, version: _err(404, "404 NOT_FOUND. models/m-prim is no longer available.")
        if model == "m-prim" else None)
    patches = _cfg_cadena("m-prim", ["m-fb"])
    with patches[0], patches[1], patches[2], \
            mock.patch.object(gemini_client, "client",
                              return_value=_cliente_con(impl)):
        res = await gemini_client.generate_json("p")
    assert res.get("title") == "T", res
    assert reg.llamadas == [("m-prim", None), ("m-fb", None)], reg.llamadas


@pytest.mark.asyncio
async def test_bn2_alias_429_skips_second_version_goes_to_next_candidate():
    """BN2/BG1: 429 (cuota) en el alias NO prueba la otra versión (misma
    cuota en v1/v1beta) → siguiente candidato inmediato, cero esperas."""
    gemini_client.set_remembered_text_model(None)
    reg = _Registro()
    impl = reg.fake_que_falla_en(
        lambda model, version: _err(429, "429 RESOURCE_EXHAUSTED. You exceeded your current quota.")
        if model == "gemini-flash-latest" else None)
    waits: list[float] = []

    async def _record_sleep(_):
        waits.append(_)

    patches = _cfg_cadena("gemini-flash-latest", ["m-fb"])
    with patches[0], patches[1], patches[2], \
            mock.patch.object(gemini_client, "client",
                              return_value=_cliente_con(impl)), \
            mock.patch.object(gemini_client.asyncio, "sleep", _record_sleep):
        res = await gemini_client.generate_json("p")
    assert res.get("title") == "T", res
    assert reg.llamadas == [("gemini-flash-latest", "v1beta"),
                            ("m-fb", None)], reg.llamadas
    assert waits == [], waits


@pytest.mark.asyncio
async def test_bn2_remembered_alias_reuses_v1beta_without_wasted_attempt():
    """BN2: el alias recordado recae directamente en v1beta en la segunda
    llamada (un solo intento; ningún reintento desperdiciado por v1)."""
    gemini_client.set_remembered_text_model(None)
    reg = _Registro()
    patches = _cfg_cadena("gemini-flash-latest", [])
    with patches[0], patches[1], patches[2], \
            mock.patch.object(gemini_client, "client",
                              return_value=_cliente_con(reg.fake_generate_content)):
        await gemini_client.generate_json("primera")
        reg.llamadas.clear()
        await gemini_client.generate_json("segunda")
    assert reg.llamadas == [("gemini-flash-latest", "v1beta")], reg.llamadas


@pytest.mark.asyncio
async def test_bn2_generate_text_alias_uses_v1beta_first():
    """BN2: generate_text aplica la MISMA política (alias → v1beta primero)."""
    gemini_client.set_remembered_text_model(None)
    reg = _Registro()

    class _Txt:
        text = "hola mundo"

    def impl(*args, **kwargs):
        cfg = kwargs.get("config")
        version = getattr(getattr(cfg, "http_options", None), "api_version", None)
        reg.llamadas.append((kwargs.get("model"), version))
        r = mock.MagicMock()
        r.text = "hola mundo"
        return r

    patches = _cfg_cadena("gemini-flash-latest", [])
    with patches[0], patches[1], patches[2], \
            mock.patch.object(gemini_client, "client",
                              return_value=_cliente_con(impl)):
        out = await gemini_client.generate_text("p")
    assert out == "hola mundo", out
    assert reg.llamadas == [("gemini-flash-latest", "v1beta")], reg.llamadas


@pytest.mark.asyncio
async def test_bn2_alias_both_versions_fail_raises_real_reason():
    """BN2: alias agotado en v1beta y v1 SIN fallbacks → sube el motivo
    real (la 404 literal), no un error genérico."""
    gemini_client.set_remembered_text_model(None)
    reg = _Registro()
    impl = reg.fake_que_falla_en(
        lambda model, version: _err(404, "404 NOT_FOUND. alias inexistente"))
    patches = _cfg_cadena("gemini-flash-latest", [])
    with patches[0], patches[1], patches[2], \
            mock.patch.object(gemini_client, "client",
                              return_value=_cliente_con(impl)):
        with pytest.raises(Exception) as ei:
            await gemini_client.generate_json("p")
    assert reg.llamadas == [("gemini-flash-latest", "v1beta"),
                            ("gemini-flash-latest", "v1")], reg.llamadas
    assert "404" in str(ei.value), str(ei.value)


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
