# -*- coding: utf-8 -*-
"""Batería BI1 (2026-11): startFrame = nombre REAL del asset en Flow.

Problema (BI1): la etapa 3 de pipeline_orchestrator derivaba el startFrame de
_asset_name_from_file(frame) — el STEM del archivo local descargado — pero
Flow nombra sus assets por el CONTENIDO del prompt (p. ej. "Red apple
character peeking"), así que flow_generate_video fallaba con "Start frame
asset … not found in Flow project assets". Además la copia descargada es una
previsualización reducida (286x512): no hay que volver a subirla cuando el
asset ya está en Flow.

Solución verificada aquí:
  · _parse_asset_listing: parsea flow_list_assets (viñetas "- Nombre",
    líneas planas, "has no images yet", "[]"/"{}", JSON con name/id, id
    inline "- Nombre (id: xyz)") → [(nombre, id|None), …] sin inventar.
  · _unique_new_asset: diff ANTES/DESPUÉS de cada flow_generate_image;
    exactamente UN asset nuevo → ese nombre (tal cual lo lista Flow); ids
    desempatan si el listado los trae; cero/varios/duplicado → ambiguo.
  · Respaldo HONESTO ante ambigüedad: flow_upload_file con nombre explícito
    único f"{run_id}-{scene_id}" + log.warning (copia local reducida); si la
    subida también falla → error claro, sin adivinar.
  · Retry-scenes: si la escena ya tiene start-frame y Flow aún lista el
    asset, NO se regenera la imagen (ahorra créditos): solo el video. Si el
    asset ya no está o el listado cae, se regenera la imagen (vía diff).
  · El ancla de personaje NO se toca (se sube con nombre explícito y funciona).

Hermética: cero red, cero Chrome, cero LLM real (doble de manager con
proyecto Flow controlable + blueprint externo BG2 — Gemini no se llama).
"""
import json
import logging
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import mcp_manager as mcpm  # noqa: E402
from services import pipeline_orchestrator as po  # noqa: E402

# NOTA conftest (FIX-A): po arrastra config (no database a nivel de módulo) —
# mismo patrón de import que las baterías INT-023 y BH.


# ═══════════════════════ doble del manager (proyecto Flow controlable) ════
_RAISE = object()   # marcador: la siguiente llamada a flow_list_assets falla


class FlowProjectDouble:
    """Doble hermético del MCPClientManager con PROYECTO Flow controlable.
    Imita el contrato real: test_pipeline / discover_notebook_id / execute.
    · flow_generate_image registra (o no) el asset con nombre POR CONTENIDO
      del prompt — el archivo local que devuelve es una previsualización
      reducida con ESPACIOS en el nombre (su stem NO es el nombre del asset).
    · flow_list_assets responde la siguiente entrada de list_script si hay
      una (texto de entradas o _RAISE), y si no, el estado del proyecto.
    · flow_upload_file registra el nombre explícito y puede fallar."""

    def __init__(self, *, gen_registers=True,
                 gen_asset="Manzana roja asomándose",
                 seed_assets=None, list_script=None, upload_fails=False,
                 use_ids=False, extra_after_gen=None):
        self.calls = []                       # (tool, args) de execute
        self.flow_assets = list(seed_assets or [])   # [(nombre, id|None)]
        self.gen_registers = gen_registers
        self.gen_asset = gen_asset
        self.list_script = list(list_script or [])
        self.upload_fails = upload_fails
        self.use_ids = use_ids
        self.extra_after_gen = list(extra_after_gen or [])
        self._id_n = 0
        self.img_ancla_n = 0
        self.img_scene_n = 0
        self.vid_n = 0
        self.upload_names = []
        self.video_startframes = []

    # ── registro de assets con id opcional (modo use_ids) ──
    def _reg(self, name):
        if not self.use_ids:
            self.flow_assets.append((name, None))
            return
        self._id_n += 1
        self.flow_assets.append((name, f"a{self._id_n}"))

    def _listing(self, entries):
        if not entries:
            return "(the project has no images yet)"
        if self.use_ids:
            return "\n".join(f"- {n} (id: {i})" if i else f"- {n}"
                             for n, i in entries)
        return "\n".join(f"- {n}" for n, _ in entries)

    async def test_pipeline(self, service, notebook_id=None):
        return {"service": service, "ok": True, "state": "connected",
                "auth": "ok", "detail": "", "browser_up": True}

    async def discover_notebook_id(self):
        return "bi1nid"

    async def execute(self, service, tool, arguments=None, timeout=None,
                      notebook_id=None, auto_connect=True):
        args = dict(arguments or {})
        self.calls.append((tool, args))
        if service == "notebooklm":
            return {"ok": True, "text": "BIBLIA FALSA BI1: personaje manzana "
                                        "roja, arco en 3 actos."}
        if tool == "flow_list_assets":
            if self.list_script:
                nxt = self.list_script.pop(0)
                if nxt is _RAISE:
                    raise mcpm.MCPManagerError("listado caído (script)",
                                               "TOOL_ERROR")
                return {"ok": True, "text": self._listing(nxt)}
            return {"ok": True, "text": self._listing(self.flow_assets)}
        if tool == "flow_generate_image":
            is_ancla = "Personaje principal CONSISTENTE" in args.get("prompt", "")
            local = (Path(args.get("outDir", ".")) /
                     (f"ancla reducida {self.img_ancla_n + 1:03d}.png"
                      if is_ancla else
                      f"preview reducida {self.img_scene_n + 1:03d}.png"))
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(b"PNG previsualizacion reducida 286x512")
            if is_ancla:
                self.img_ancla_n += 1
                self._reg("Retrato del personaje principal")
            else:
                self.img_scene_n += 1
                if self.gen_registers:
                    # {n} = nº de escena generada → nombres distinguibles
                    self._reg(self.gen_asset.format(n=self.img_scene_n)
                              if "{n}" in self.gen_asset else self.gen_asset)
                for extra in self.extra_after_gen:
                    self.flow_assets.append(tuple(extra))
            return {"ok": True, "text": f"Generated 1 image(s) with 2:\n{local}"}
        if tool == "flow_upload_file":
            name = str(args.get("name", ""))
            self.upload_names.append(name)
            if self.upload_fails and name != "personaje":
                # BI1: el ancla se sube BIEN (no se toca); solo falla el
                # respaldo de la escena (nombre f"{run_id}-{scene_id}")
                raise mcpm.MCPManagerError("upload boom", "TOOL_ERROR")
            self._reg(name)
            return {"ok": True, "text": f'Uploaded and named "{name}".'}
        if tool == "flow_generate_video":
            self.vid_n += 1
            self.video_startframes.append(args.get("startFrame"))
            out = args.get("outFile") or "/tmp/fake_bi1_video.mp4"
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"MP4 fake")
            return {"ok": True, "text": f'Generated video with startFrame '
                                        f'"{args.get("startFrame")}":\n{out}'}
        return {"ok": True, "text": "ok"}


def _bp(n=1):
    """Blueprint EXTERNO (puerta BG2) — la etapa 2 no llama a Gemini."""
    return {"label": "bi1", "title": "Corrida BI1",
            "scenes": [{"title": f"Escena {i + 1}",
                        "narration": f"Narración de la escena {i + 1}.",
                        "image_prompt": f"Plano {i + 1} de la manzana roja."}
                       for i in range(n)]}


class _Cap(logging.Handler):
    """Captura de logs del orquestador (stdlib, sin pytest.caplog): WARNING
    y también INFO (p. ej. "reutiliza start-frame")."""

    def __init__(self):
        super().__init__(level=logging.INFO)
        self.msgs = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


async def _corrida(mgr, n_scenes=1):
    """Corrida hermética completa con el doble: devuelve (orch, run_id)."""
    orch = po.PipelineOrchestrator(
        manager=mgr, runs_dir=Path(tempfile.mkdtemp(prefix="bi1_")) / "runs")
    run = orch.create_run("idea BI1 manzana roja", notebook_id="bi1nid",
                          fmt="short", blueprint=_bp(n_scenes))
    await orch.start_run(run["run_id"])
    await orch.wait(run["run_id"], timeout=60.0)
    return orch, run["run_id"]


def _flow_tools(mgr):
    """Secuencia de tools Flow (sin la consulta de NotebookLM de Stage 1)."""
    return [t for t, _ in mgr.calls if t.startswith("flow_")]


def _snap(orch, rid):
    return orch.get_status(rid)


# ═══════════════════════ unidad: parser del listado ═══════════════════════
def test_bi1_parser_formatos():
    """BI1: _parse_asset_listing acepta viñetas, líneas planas, vacíos y JSON."""
    assert po._parse_asset_listing("- A\n- B, con espacios") == \
        [("A", None), ("B, con espacios", None)]
    assert po._parse_asset_listing("A plana\nB plana") == \
        [("A plana", None), ("B plana", None)]
    assert po._parse_asset_listing("") == []
    assert po._parse_asset_listing(None) == []
    assert po._parse_asset_listing("(the project has no images yet)") == []
    assert po._parse_asset_listing("[]") == []
    assert po._parse_asset_listing("{}") == []
    # JSON con name+id
    assert po._parse_asset_listing(
        '[{"name": "Rojo", "id": "x1"}, {"name": "Verde"}]') == \
        [("Rojo", "x1"), ("Verde", None)]
    # JSON dict con clave assets
    assert po._parse_asset_listing(
        '{"assets": [{"name": "Uno", "id": "u9"}]}') == [("Uno", "u9")]
    # id inline en viñeta
    assert po._parse_asset_listing("- Manzana (id: a9)") == \
        [("Manzana", "a9")]
    assert po._parse_asset_listing("- Manzana [id: b2]") == \
        [("Manzana", "b2")]
    # no inventa: líneas vacías y viñeta sin texto se descartan
    assert po._parse_asset_listing("\n   \n- \n- Nombre") == [("Nombre", None)]


def test_bi1_diff_decisiones():
    """BI1: _unique_new_asset — 1 nuevo seguro, 0/varios/duplicado → ambiguo."""
    # exactamente UN asset nuevo con nombre fresco → usarlo
    n, mot = po._unique_new_asset([("A", None)], [("A", None), ("B", None)])
    assert (n, mot) == ("B", "")
    # cero nuevos → ambiguo
    n, mot = po._unique_new_asset([("A", None)], [("A", None)])
    assert n is None and "0" in mot
    # varios nuevos → ambiguo
    n, mot = po._unique_new_asset([], [("B", None), ("C", None)])
    assert n is None and "2" in mot
    # duplicado: el excedente con nombre YA existente es ambiguo (@{nombre}
    # podría apuntar al asset viejo)
    n, mot = po._unique_new_asset([("A", None)], [("A", None), ("A", None)])
    assert n is None and "ambiguo" in mot
    # el ancla y escenas previas quedan fuera del diff de forma natural
    n, _ = po._unique_new_asset(
        [("Retrato", None), ("personaje", None)],
        [("Retrato", None), ("personaje", None), ("Nuevo", None)])
    assert n == "Nuevo"


def test_bi1_diff_ids_desempatan():
    """BI1: si el listado trae ids, la diferencia de ids manda."""
    # mismo NOMBRE, id nuevo → por nombre sería ambiguo; por id hay UNO nuevo
    n, mot = po._unique_new_asset([("M", "a0")], [("M", "a0"), ("M", "a1")])
    assert (n, mot) == ("M", "")
    # dos ids nuevos → ambiguo
    n, mot = po._unique_new_asset([("M", "a0")],
                                  [("M", "a0"), ("X", "a1"), ("Y", "a2")])
    assert n is None and "2" in mot
    # ids en todas las entradas y ninguno nuevo → 0 nuevos
    n, mot = po._unique_new_asset([("M", "a0")], [("M", "a0")])
    assert n is None and "0" in mot
    # ids PARCIALES → cae al multiconjunto de nombres (comportamiento declarado)
    n, _ = po._unique_new_asset([("A", "a0")], [("A", "a0"), ("B", None)])
    assert n == "B"


# ═══════════════════════ integración: corrida con el doble ════════════════
async def test_bi1_un_asset_nuevo_nombre_flow():
    """BI1 · EXACTAMENTE 1 nuevo: startFrame = nombre tal como lo lista Flow
    (con espacios y tildes), NO el stem del archivo local; sin subida extra."""
    mgr = FlowProjectDouble()   # gen_registers=True → "Manzana roja asomándose"
    cap = _Cap()
    po.log.addHandler(cap)
    try:
        orch, rid = await _corrida(mgr)
        snap = _snap(orch, rid)
        assert snap["stage"] == po.ST_DONE and not snap["failed_scene_ids"], \
            snap["error_detail"]
        s1 = snap["scenes"][0]
        assert s1["status"] == "done"
        # el video recibió el nombre EXACTO de Flow (espacios + tilde intactos)
        assert mgr.video_startframes == ["Manzana roja asomándose"], \
            mgr.video_startframes
        # NO es el stem del archivo local ("preview reducida 001.png")
        assert not mgr.video_startframes[0].startswith("preview"), \
            mgr.video_startframes[0]
        # el nombre quedó registrado en la escena y persistido en state.json
        assert s1["start_frame_asset"] == "Manzana roja asomándose"
        state = json.loads((orch.runs_dir / rid / "state.json")
                           .read_text(encoding="utf-8"))
        assert state["scenes"][0]["start_frame_asset"] == \
            "Manzana roja asomándose"
        # la única subida es la del ANCLA (la copia reducida NO se re-subió)
        assert mgr.upload_names == ["personaje"], mgr.upload_names
        assert mgr.img_scene_n == 1
        # sin warnings de respaldo: la detección fue concluyente
        assert not any("indetectable" in m for m in cap.msgs), cap.msgs
        # secuencia estructural: ancla intacta (gen→upload sin listing) +
        # diff antes/después SOLO alrededor de la imagen de la escena
        assert _flow_tools(mgr) == [
            "flow_list_assets",          # calentamiento D2
            "flow_generate_image",       # ancla (intacta: sin listing alrededor)
            "flow_upload_file",          # ancla con nombre explícito
            "flow_list_assets",          # antes de la imagen de la escena
            "flow_generate_image",       # imagen de la escena
            "flow_list_assets",          # después de la imagen
            "flow_generate_video",       # video con el nombre de Flow
        ], _flow_tools(mgr)
    finally:
        po.log.removeHandler(cap)


async def test_bi1_cero_nuevos_respaldo_subida():
    """BI1 · CERO nuevos: respaldo con flow_upload_file y nombre explícito
    f"{run_id}-{scene_id}" + log.warning de copia reducida; escena done."""
    mgr = FlowProjectDouble(gen_registers=False)
    cap = _Cap()
    po.log.addHandler(cap)
    try:
        orch, rid = await _corrida(mgr)
        snap = _snap(orch, rid)
        s1 = snap["scenes"][0]
        assert snap["stage"] == po.ST_DONE and s1["status"] == "done", \
            (snap["error_detail"], s1)
        esperado = f"{rid}-s1"
        assert mgr.video_startframes == [esperado], mgr.video_startframes
        assert mgr.upload_names == ["personaje", esperado], mgr.upload_names
        assert s1["start_frame_asset"] == esperado
        assert any("copia local reducida" in m and esperado in m
                   for m in cap.msgs), cap.msgs
    finally:
        po.log.removeHandler(cap)


async def test_bi1_varios_nuevos_ambiguo():
    """BI1 · VARIOS nuevos (ambiguo): respaldo de subida, sin adivinar."""
    mgr = FlowProjectDouble(
        gen_registers=True, gen_asset="Manzana roja asomándose",
        extra_after_gen=[("Manzana roja variante", None)])
    cap = _Cap()
    po.log.addHandler(cap)
    try:
        orch, rid = await _corrida(mgr)
        snap = _snap(orch, rid)
        s1 = snap["scenes"][0]
        assert snap["stage"] == po.ST_DONE and s1["status"] == "done", \
            (snap["error_detail"], s1)
        esperado = f"{rid}-s1"
        assert mgr.video_startframes == [esperado], mgr.video_startframes
        assert mgr.upload_names == ["personaje", esperado], mgr.upload_names
        assert any("indetectable" in m and "2 nuevos/ambiguos" in m
                   for m in cap.msgs), cap.msgs
    finally:
        po.log.removeHandler(cap)


async def test_bi1_duplicado_ambiguo():
    """BI1 · nombre DUPLICADO: el excedente con nombre ya existente NO se
    usa (podría apuntar al asset viejo) → respaldo de subida."""
    mgr = FlowProjectDouble(
        gen_registers=True, gen_asset="Manzana roja asomándose",
        seed_assets=[("Manzana roja asomándose", None)])
    cap = _Cap()
    po.log.addHandler(cap)
    try:
        orch, rid = await _corrida(mgr)
        snap = _snap(orch, rid)
        s1 = snap["scenes"][0]
        assert snap["stage"] == po.ST_DONE and s1["status"] == "done", \
            (snap["error_detail"], s1)
        esperado = f"{rid}-s1"
        assert mgr.video_startframes == [esperado], mgr.video_startframes
        assert mgr.upload_names == ["personaje", esperado], mgr.upload_names
        assert any("indetectable" in m and "ambiguos" in m
                   for m in cap.msgs), cap.msgs
    finally:
        po.log.removeHandler(cap)


async def test_bi1_ids_desempatan_en_corrida():
    """BI1 · ids en el listado: mismo nombre con id nuevo = UN asset nuevo →
    se usa el nombre de Flow y NO se sube la copia reducida."""
    mgr = FlowProjectDouble(
        gen_registers=True, gen_asset="Manzana roja asomándose",
        use_ids=True, seed_assets=[("Manzana roja asomándose", "a0")])
    cap = _Cap()
    po.log.addHandler(cap)
    try:
        orch, rid = await _corrida(mgr)
        snap = _snap(orch, rid)
        s1 = snap["scenes"][0]
        assert snap["stage"] == po.ST_DONE and s1["status"] == "done", \
            (snap["error_detail"], s1)
        assert mgr.video_startframes == ["Manzana roja asomándose"], \
            mgr.video_startframes
        assert mgr.upload_names == ["personaje"], mgr.upload_names
        assert not any("indetectable" in m for m in cap.msgs), cap.msgs
    finally:
        po.log.removeHandler(cap)


async def test_bi1_respaldo_subida_falla_error_claro():
    """BI1 · detección ambigua Y subida fallida → error CLARO en la escena,
    sin video y sin adivinar el asset."""
    mgr = FlowProjectDouble(gen_registers=False, upload_fails=True)
    cap = _Cap()
    po.log.addHandler(cap)
    try:
        orch, rid = await _corrida(mgr)
        snap = _snap(orch, rid)
        s1 = snap["scenes"][0]
        assert snap["stage"] == po.ST_DONE
        assert snap["error_code"] == "PARTIAL_FAILURES", snap["error_code"]
        assert s1["status"] == "failed"
        assert "indetectable" in s1["detail"] and "upload boom" in s1["detail"], \
            s1["detail"]
        assert "TOOL_ERROR" in s1["detail"]
        assert mgr.vid_n == 0                      # nunca se adivinó el asset
        assert s1["start_frame_asset"] == ""       # nada inventado
        assert any("copia local reducida" in m for m in cap.msgs), cap.msgs
    finally:
        po.log.removeHandler(cap)


async def test_bi1_retry_reutiliza_startframe():
    """BI1 · retry-scenes: si Flow aún lista el start-frame, NO regenera la
    imagen (ahorra créditos): reintenta SOLO el video."""
    mgr = FlowProjectDouble()
    orch, rid = await _corrida(mgr)
    snap = _snap(orch, rid)
    assert snap["scenes"][0]["status"] == "done"
    imgs_1, vids_1 = mgr.img_scene_n, mgr.vid_n
    cap = _Cap()
    po.log.addHandler(cap)
    _lvl_previo = po.log.level   # el INFO del reuso solo sale con nivel INFO
    po.log.setLevel(logging.INFO)
    try:
        out = await orch.retry_scenes(rid, ["s1"], force=True)
        assert out["stage"] == po.ST_DONE and out["progress_pct"] == 100
        s1 = next(s for s in out["scenes"] if s["scene_id"] == "s1")
        assert s1["status"] == "done"
        # NO se regeneró la imagen; el video sí se re-despachó
        assert mgr.img_scene_n == imgs_1, (imgs_1, mgr.img_scene_n)
        assert mgr.vid_n == vids_1 + 1, (vids_1, mgr.vid_n)
        # el segundo video usó el MISMO nombre de Flow
        assert mgr.video_startframes == ["Manzana roja asomándose",
                                         "Manzana roja asomándose"], \
            mgr.video_startframes
        assert s1["start_frame_asset"] == "Manzana roja asomándose"
        # sin subidas nuevas (ni referencia ni respaldo)
        assert mgr.upload_names == ["personaje"], mgr.upload_names
        assert any("reutiliza start-frame" in m for m in cap.msgs), cap.msgs
    finally:
        po.log.removeHandler(cap)
        po.log.setLevel(_lvl_previo)


async def test_bi1_retry_asset_desaparecido_regenera():
    """BI1 · retry cuando el asset YA NO está en Flow: se regenera la imagen
    (vía diff de listados) y el start-frame se re-detecta; sin subida."""
    mgr = FlowProjectDouble()
    orch, rid = await _corrida(mgr)
    assert _snap(orch, rid)["scenes"][0]["status"] == "done"
    # el asset del start-frame desaparece del proyecto Flow
    mgr.flow_assets = [e for e in mgr.flow_assets
                       if e[0] != "Manzana roja asomándose"]
    imgs_1, vids_1 = mgr.img_scene_n, mgr.vid_n
    out = await orch.retry_scenes(rid, ["s1"], force=True)
    assert out["stage"] == po.ST_DONE and out["progress_pct"] == 100
    s1 = next(s for s in out["scenes"] if s["scene_id"] == "s1")
    assert s1["status"] == "done"
    assert mgr.img_scene_n == imgs_1 + 1, (imgs_1, mgr.img_scene_n)
    assert mgr.vid_n == vids_1 + 1
    # re-detectado por diff: mismo nombre de Flow, sin respaldo de subida
    assert mgr.video_startframes[-1] == "Manzana roja asomándose"
    assert mgr.upload_names == ["personaje"], mgr.upload_names
    assert s1["start_frame_asset"] == "Manzana roja asomándose"


async def test_bi1_listado_cae_respaldo():
    """BI1 · flow_list_assets cae antes/después de generar (calentamiento OK):
    detección imposible → respaldo de subida con nombre explícito, done."""
    # guion: [calentamiento OK, antes RAISE, después RAISE]
    mgr = FlowProjectDouble(list_script=[[], _RAISE, _RAISE],
                           gen_registers=True)
    cap = _Cap()
    po.log.addHandler(cap)
    try:
        orch, rid = await _corrida(mgr)
        snap = _snap(orch, rid)
        s1 = snap["scenes"][0]
        assert snap["stage"] == po.ST_DONE and s1["status"] == "done", \
            (snap["error_detail"], s1)
        esperado = f"{rid}-s1"
        assert mgr.video_startframes == [esperado], mgr.video_startframes
        assert mgr.upload_names == ["personaje", esperado], mgr.upload_names
        assert any("listado Flow indisponible" in m and "indetectable" in m
                   for m in cap.msgs), cap.msgs
    finally:
        po.log.removeHandler(cap)


async def test_bi1_ancla_intacta_dos_escenas():
    """BI1 · el ANCLA de personaje no se toca: una sola generación + una sola
    subida con nombre explícito, compartida por las 2 escenas; cada escena
    detecta SU asset nuevo por diff (2 imágenes → 2 nombres distintos)."""
    mgr = FlowProjectDouble(
        gen_asset="Manzana roja asomándose toma {n}")   # nombre por escena
    cap = _Cap()
    po.log.addHandler(cap)
    try:
        orch, rid = await _corrida(mgr, n_scenes=2)
        snap = _snap(orch, rid)
        assert snap["stage"] == po.ST_DONE and not snap["failed_scene_ids"], \
            snap["error_detail"]
        # ancla: exactamente 1 generación y 1 subida con nombre explícito
        assert mgr.img_ancla_n == 1 and mgr.upload_names == ["personaje"], \
            (mgr.img_ancla_n, mgr.upload_names)
        # cada escena detectó SU asset nuevo por diff (nombres distintos,
        # sin subidas de respaldo)
        assert mgr.img_scene_n == 2
        assert mgr.video_startframes == ["Manzana roja asomándose toma 1",
                                         "Manzana roja asomándose toma 2"], \
            mgr.video_startframes
        estados = {s["scene_id"]: s["start_frame_asset"]
                   for s in snap["scenes"]}
        assert estados == {"s1": "Manzana roja asomándose toma 1",
                           "s2": "Manzana roja asomándose toma 2"}, estados
    finally:
        po.log.removeHandler(cap)


# ═══════════════════════ runner de batería ════════════════════════════════
if __name__ == "__main__":
    import pytest as _pytest

    class _Resumen:
        def __init__(self):
            self.ok = 0
            self.fallos = 0

        def pytest_runtest_logreport(self, report):
            if report.when == "call":
                if report.passed:
                    self.ok += 1
                elif report.failed:
                    self.fallos += 1

    _res = _Resumen()
    _code = _pytest.main([__file__, "-q"], plugins=[_res])
    print(f"\n{_res.ok} OK · {_res.fallos} fallos")
    sys.exit(int(_code))
