# -*- coding: utf-8 -*-
"""Batería BJ (2026-11): startFrame = "id:<mediaId>" del asset REAL de Flow.

Problema (BI1→BJ): Flow nombra sus assets por el CONTENIDO del prompt (p. ej.
"Red apple character peeking"), no por el archivo local descargado (una
previsualización reducida 286x512). BI1 lo resolvió con diff de listados por
NOMBRE; con nombres duplicados seguía siendo ambiguo. BJ lo cierra SIN
ambigüedad:
  · BJ2: flow_generate_image emite "Asset: <name> [id:<mediaId>]" por imagen
    ANTES de las rutas (la ÚLTIMA línea sigue siendo la ruta); flow_list_assets
    lista "- <name> [id:<mediaId>]".
  · BJ3: flow_generate_video acepta startFrame "id:<mediaId>" o nombre exacto
    (case-insensitive, la primera si hay varias); el error lista hasta 8
    nombres visibles; la salida indica qué asset se usó (Node, tools/
    GoogleFlowMCP/test/assets.test.js).
  · BJ4 (esta batería): pipeline_orchestrator etapa 3 parsea la línea
    "Asset:" (_parse_generated_asset) y llama al video con
    startFrame="id:<mediaId>"; sin línea Asset: → respaldo HONESTO
    (flow_upload_file con nombre único f"{run_id}-{scene_id}" + log.warning;
    si la subida también falla → error claro, sin adivinar). Se guardan
    nombre E id en la escena; retry-scenes reutiliza el start-frame si el
    asset sigue en Flow (por id, o por nombre en estados BI1 sin id).
    Nombres DUPLICADOS: el id desambigua (no se reutiliza el asset viejo).
  · El ancla de personaje (se sube con nombre "personaje") NO se toca.

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
    """Doble hermético del MCPClientManager con PROYECTO Flow controlable
    (contrato BJ2/BJ3 real). Imita test_pipeline / discover_notebook_id /
    execute.
    · flow_generate_image REGISTRA el asset con nombre POR CONTENIDO del
      prompt y responde con línea "Asset: <nombre> [id:<mediaId>]" ANTES de
      la ruta del archivo local (previsualización reducida, stem distinto);
      con asset_line=False responde el formato antiguo SIN la línea (para
      probar el respaldo).
    · flow_list_assets responde la siguiente entrada de list_script si hay
      una (texto de entradas o _RAISE), y si no, el estado del proyecto en
      formato "- <name> [id:<mediaId>]".
    · flow_upload_file registra el nombre explícito y puede fallar.
    · flow_generate_video graba el startFrame recibido (el orquestador real
      debe enviar "id:<mediaId>" o el nombre del respaldo)."""

    def __init__(self, *, gen_registers=True,
                 gen_asset="Manzana roja asomándose",
                 seed_assets=None, list_script=None, upload_fails=False,
                 asset_line=True, extra_after_gen=None):
        self.calls = []                       # (tool, args) de execute
        self.flow_assets = list(seed_assets or [])   # [(nombre, id)]
        self.gen_registers = gen_registers
        self.gen_asset = gen_asset
        self.list_script = list(list_script or [])
        self.upload_fails = upload_fails
        self.asset_line = asset_line          # BJ4: ¿el tool emite "Asset:"?
        self.extra_after_gen = list(extra_after_gen or [])
        self._id_n = 0
        self.img_ancla_n = 0
        self.img_scene_n = 0
        self.vid_n = 0
        self.upload_names = []
        self.video_startframes = []

    # ── registro de assets: SIEMPRE con mediaId (contrato BJ2 real) ──
    def _reg(self, name):
        self._id_n += 1
        self.flow_assets.append((name, f"a{self._id_n}"))

    def _listing(self, entries):
        if not entries:
            return "(the project has no images yet)"
        return "\n".join(f"- {n} [id:{i}]" for n, i in entries)

    async def test_pipeline(self, service, notebook_id=None):
        return {"service": service, "ok": True, "state": "connected",
                "auth": "ok", "detail": "", "browser_up": True}

    async def discover_notebook_id(self):
        return "bjnid"

    async def execute(self, service, tool, arguments=None, timeout=None,
                      notebook_id=None, auto_connect=True):
        args = dict(arguments or {})
        self.calls.append((tool, args))
        if service == "notebooklm":
            return {"ok": True, "text": "BIBLIA FALSA BJ: personaje manzana "
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
            registrado = False
            if is_ancla:
                self.img_ancla_n += 1
                self._reg("Retrato del personaje principal")
                registrado = True
            else:
                self.img_scene_n += 1
                if self.gen_registers:
                    # {n} = nº de escena generada → nombres distinguibles
                    self._reg(self.gen_asset.format(n=self.img_scene_n)
                              if "{n}" in self.gen_asset else self.gen_asset)
                    registrado = True
                for extra in self.extra_after_gen:
                    self._id_n += 1
                    self.flow_assets.append((extra[0], f"a{self._id_n}"))
            # El tool REAL (BJ2) emite la línea "Asset:" solo para el asset que
            # efectivamente creó; sin registro (gen_registers=False) no hay
            # línea → el orquestador debe tirar del respaldo de subida.
            if registrado and self.asset_line:
                ultimo = self.flow_assets[-1]
                text = (f"Generated 1 image(s) with 2:\n"
                        f"Asset: {ultimo[0]} [id:{ultimo[1]}]\n{local}")
            else:
                text = f"Generated 1 image(s) with 2:\n{local}"
            return {"ok": True, "text": text}
        if tool == "flow_upload_file":
            name = str(args.get("name", ""))
            self.upload_names.append(name)
            if self.upload_fails and name != "personaje":
                # el ancla se sube BIEN (no se toca); solo falla el respaldo
                # de la escena (nombre f"{run_id}-{scene_id}")
                raise mcpm.MCPManagerError("upload boom", "TOOL_ERROR")
            self._reg(name)
            return {"ok": True, "text": f'Uploaded and named "{name}".'}
        if tool == "flow_generate_video":
            self.vid_n += 1
            self.video_startframes.append(args.get("startFrame"))
            out = args.get("outFile") or "/tmp/fake_bj_video.mp4"
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"MP4 fake")
            return {"ok": True, "text": f'Generated video with startFrame '
                                        f'"{args.get("startFrame")}":\n{out}'}
        return {"ok": True, "text": "ok"}


def _bp(n=1):
    """Blueprint EXTERNO (puerta BG2) — la etapa 2 no llama a Gemini."""
    return {"label": "bj", "title": "Corrida BJ",
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
        manager=mgr, runs_dir=Path(tempfile.mkdtemp(prefix="bj_")) / "runs")
    run = orch.create_run("idea BJ manzana roja", notebook_id="bjnid",
                          fmt="short", blueprint=_bp(n_scenes))
    await orch.start_run(run["run_id"])
    await orch.wait(run["run_id"], timeout=60.0)
    return orch, run["run_id"]


def _flow_tools(mgr):
    """Secuencia de tools Flow (sin la consulta de NotebookLM de Stage 1)."""
    return [t for t, _ in mgr.calls if t.startswith("flow_")]


def _snap(orch, rid):
    return orch.get_status(rid)


# ═══════════════ unidad: parser de la línea Asset: (BJ4) ══════════════════
def test_bj_parse_asset_line():
    """BJ4: _parse_generated_asset — línea 'Asset: <name> [id:<mediaId>]'
    presente/ausente, antes de la ruta, con uuid real; nunca inventa."""
    assert po._parse_generated_asset(
        "Generated 1 image(s) in 2s with 2 (9:16):\n"
        "Asset: Red apple character peeking [id:9f2c1111-2222-3333-4444-555566667777]\n"
        r"D:\RUN DIR\preview-1.png") == \
        ("Red apple character peeking",
         "9f2c1111-2222-3333-4444-555566667777")
    # ausente → ("", ""): el caller usa el respaldo, sin adivinar
    assert po._parse_generated_asset(
        "Generated 1 image(s) in 2s:\nD:\\a b\\img.png") == ("", "")
    assert po._parse_generated_asset("") == ("", "")
    assert po._parse_generated_asset(None) == ("", "")
    # la ÚLTIMA línea Asset: gana (count>1 hipotético; la ruta no confunde)
    assert po._parse_generated_asset(
        "Asset: Uno [id:id1]\nAsset: Dos [id:id2]\n/x/ok.png") == \
        ("Dos", "id2")
    # línea Asset SIN id → no califica como detección (respaldo)
    assert po._parse_generated_asset("Asset: Solo nombre\n/x/ok.png") == ("", "")


def test_bj_parse_listing_formato_real():
    """BJ2 (Python): _parse_asset_listing entiende el formato REAL del tool
    '- <name> [id:<mediaId>]' y conserva los formatos previos."""
    # formato REAL BJ2: id entre corchetes
    assert po._parse_asset_listing(
        "- Manzana roja asomándose [id:a1]\n"
        "- Retrato del personaje principal [id:a2]") == \
        [("Manzana roja asomándose", "a1"),
         ("Retrato del personaje principal", "a2")]
    # compatibilidad: viñeta sin id, id entre paréntesis, líneas planas
    assert po._parse_asset_listing("- A\n- B (id: b9)") == \
        [("A", None), ("B", "b9")]
    assert po._parse_asset_listing("A plana\nB plana") == \
        [("A plana", None), ("B plana", None)]
    assert po._parse_asset_listing("(the project has no images yet)") == []
    assert po._parse_asset_listing("[]") == []
    # JSON con name+id
    assert po._parse_asset_listing(
        '[{"name": "Rojo", "id": "x1"}, {"name": "Verde"}]') == \
        [("Rojo", "x1"), ("Verde", None)]


def test_bj_asset_in_listing():
    """BJ4: _asset_in_listing — el id MANDA cuando el listado trae ids y la
    escena lo tiene; sin id en la escena (respaldo) o en el listado
    (compatibilidad) → nombre exacto."""
    listing = [("M", "a1"), ("Otra", "a2")]
    assert po._asset_in_listing("M", "a1", listing) is True
    # id ausente del listado aunque el nombre esté → False (duplicados: ESE
    # asset ya no está, no se reutiliza el homónimo viejo)
    assert po._asset_in_listing("M", "zzz", listing) is False
    # respaldo de subida (sin id) → por nombre
    assert po._asset_in_listing("M", "", listing) is True
    assert po._asset_in_listing("No está", "", listing) is False
    # listado SIN ids (formato antiguo) → por nombre
    assert po._asset_in_listing("M", "aid1", [("M", None)]) is True
    assert po._asset_in_listing("M", "aid1", [("X", None)]) is False
    assert po._asset_in_listing("", "", listing) is False


# ═══════════════════════ integración: corrida con el doble ════════════════
async def test_bj_linea_asset_presente_video_por_id():
    """BJ4 · línea 'Asset:' presente: el video recibe startFrame="id:<mediaId>"
    (NO el stem local, NO el nombre); nombre e id quedan en la escena y en
    state.json; sin subida extra ni warnings de respaldo."""
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
        # ids del doble: a1=ancla, a2=persona upload "personaje", a3=escena 1
        # el video recibió el ID del asset (inequívoco), no el nombre ni el stem
        assert mgr.video_startframes == ["id:a3"], mgr.video_startframes
        assert not mgr.video_startframes[0].startswith("preview"), \
            mgr.video_startframes[0]
        # nombre E id registrados en la escena y persistidos en state.json
        assert s1["start_frame_asset"] == "Manzana roja asomándose"
        assert s1["start_frame_asset_id"] == "a3"
        state = json.loads((orch.runs_dir / rid / "state.json")
                           .read_text(encoding="utf-8"))
        assert state["scenes"][0]["start_frame_asset"] == \
            "Manzana roja asomándose"
        assert state["scenes"][0]["start_frame_asset_id"] == "a3"
        # la única subida es la del ANCLA (la copia reducida NO se re-subió)
        assert mgr.upload_names == ["personaje"], mgr.upload_names
        assert mgr.img_scene_n == 1
        # sin warnings de respaldo: la línea Asset: vino siempre
        assert not any("Asset:" in m and "copia local" in m for m in cap.msgs)
        # secuencia estructural: ancla intacta (gen→upload sin listing) y
        # el listing SOLO para el calentamiento D2 (el diff BI1 desapareció)
        assert _flow_tools(mgr) == [
            "flow_list_assets",          # calentamiento D2
            "flow_generate_image",       # ancla (intacta: sin listing alrededor)
            "flow_upload_file",          # ancla con nombre explícito
            "flow_generate_image",       # imagen de la escena
            "flow_generate_video",       # video POR ID
        ], _flow_tools(mgr)
    finally:
        po.log.removeHandler(cap)


async def test_bj_linea_asset_ausente_respaldo_subida():
    """BJ4 · SIN línea 'Asset:' (tool antiguo): respaldo con flow_upload_file
    y nombre explícito f"{run_id}-{scene_id}" + log.warning de copia
    reducida; el video usa el NOMBRE (no hay id); escena done."""
    mgr = FlowProjectDouble(gen_registers=True, asset_line=False)
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
        assert s1["start_frame_asset_id"] == ""   # respaldo: sin id, honesto
        assert any("copia local reducida" in m and esperado in m
                   for m in cap.msgs), cap.msgs
    finally:
        po.log.removeHandler(cap)


async def test_bj_nombres_duplicados_id_desambigua():
    """BJ4 · NOMBRES DUPLICADOS: el asset generado repite un nombre que ya
    existía en Flow. La línea 'Asset:' trae el id NUEVO → el video va por
    ese id (no por el homónimo viejo) y NO se sube la copia reducida."""
    mgr = FlowProjectDouble(
        gen_registers=True, gen_asset="Manzana roja asomándose",
        seed_assets=[("Manzana roja asomándose", "a0")])
    cap = _Cap()
    po.log.addHandler(cap)
    try:
        orch, rid = await _corrida(mgr)
        snap = _snap(orch, rid)
        s1 = snap["scenes"][0]
        assert snap["stage"] == po.ST_DONE and s1["status"] == "done", \
            (snap["error_detail"], s1)
        # el id del asset NUEVO registrado tras generar (a0 era el seed;
        # a1=ancla, a2=persona "personaje", a3=escena)
        assert mgr.flow_assets[-1] == ("Manzana roja asomándose", "a3")
        assert mgr.video_startframes == ["id:a3"], mgr.video_startframes
        assert mgr.upload_names == ["personaje"], mgr.upload_names
        assert s1["start_frame_asset_id"] == "a3"
        assert not any("copia local reducida" in m for m in cap.msgs), cap.msgs
    finally:
        po.log.removeHandler(cap)


async def test_bj_respaldo_subida_falla_error_claro():
    """BJ4 · sin línea 'Asset:' Y subida fallida → error CLARO en la escena,
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
        assert "sin línea 'Asset:'" in s1["detail"], s1["detail"]
        assert "upload boom" in s1["detail"] and "TOOL_ERROR" in s1["detail"]
        assert mgr.vid_n == 0                      # nunca se adivinó el asset
        assert s1["start_frame_asset"] == ""       # nada inventado
        assert s1["start_frame_asset_id"] == ""
        assert any("copia local reducida" in m for m in cap.msgs), cap.msgs
    finally:
        po.log.removeHandler(cap)


async def test_bj_retry_reutiliza_startframe():
    """BJ4 · retry-scenes: la escena tiene start-frame (nombre+id) y Flow aún
    lista el asset POR ID → NO regenera la imagen (ahorra créditos):
    reintenta SOLO el video, con el MISMO id."""
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
        # el segundo video usó el MISMO id del asset
        assert mgr.video_startframes == ["id:a3", "id:a3"], \
            mgr.video_startframes
        assert s1["start_frame_asset"] == "Manzana roja asomándose"
        assert s1["start_frame_asset_id"] == "a3"
        # sin subidas nuevas (ni referencia ni respaldo)
        assert mgr.upload_names == ["personaje"], mgr.upload_names
        assert any("reutiliza start-frame" in m for m in cap.msgs), cap.msgs
    finally:
        po.log.removeHandler(cap)
        po.log.setLevel(_lvl_previo)


async def test_bj_retry_asset_desaparecido_regenera():
    """BJ4 · retry cuando el asset YA NO está en Flow (id ausente del
    listado aunque hubiera homónimos): se regenera la imagen y el
    start-frame se re-detecta por la línea 'Asset:'; sin subida."""
    mgr = FlowProjectDouble()
    orch, rid = await _corrida(mgr)
    assert _snap(orch, rid)["scenes"][0]["status"] == "done"
    # el asset del start-frame desaparece del proyecto Flow (a3: la imagen
    # de la escena; el ancla a1 y "personaje" a2 permanecen)
    mgr.flow_assets = [e for e in mgr.flow_assets
                       if e[1] != "a3"]
    imgs_1, vids_1 = mgr.img_scene_n, mgr.vid_n
    out = await orch.retry_scenes(rid, ["s1"], force=True)
    assert out["stage"] == po.ST_DONE and out["progress_pct"] == 100
    s1 = next(s for s in out["scenes"] if s["scene_id"] == "s1")
    assert s1["status"] == "done"
    assert mgr.img_scene_n == imgs_1 + 1, (imgs_1, mgr.img_scene_n)
    assert mgr.vid_n == vids_1 + 1
    # re-detectado por la línea Asset: → mismo nombre, id nuevo (a4: el
    # ancla y la 1ª imagen ya registraron a1-a3)
    assert mgr.video_startframes[-1] == "id:a4", mgr.video_startframes
    assert mgr.upload_names == ["personaje"], mgr.upload_names
    assert s1["start_frame_asset"] == "Manzana roja asomándose"
    assert s1["start_frame_asset_id"] == "a4"


async def test_bj_retry_respaldo_sin_id_reutiliza_por_nombre():
    """BJ4 · escena creada por RESPALDO (sin id, nombre f"{rid}-sN"): el
    retry la reutiliza POR NOMBRE (compatibilidad) y no re-subir nada."""
    mgr = FlowProjectDouble(gen_registers=True, asset_line=False)
    orch, rid = await _corrida(mgr)
    s1 = _snap(orch, rid)["scenes"][0]
    assert s1["status"] == "done" and s1["start_frame_asset_id"] == ""
    esperado = f"{rid}-s1"
    assert s1["start_frame_asset"] == esperado
    imgs_1, vids_1, ups_1 = mgr.img_scene_n, mgr.vid_n, len(mgr.upload_names)
    out = await orch.retry_scenes(rid, ["s1"], force=True)
    assert out["stage"] == po.ST_DONE
    s1 = next(s for s in out["scenes"] if s["scene_id"] == "s1")
    assert s1["status"] == "done"
    assert mgr.img_scene_n == imgs_1          # sin regenerar imagen
    assert mgr.vid_n == vids_1 + 1            # solo el video
    assert len(mgr.upload_names) == ups_1     # sin re-subir el respaldo
    assert mgr.video_startframes[-1] == esperado


async def test_bj_ancla_intacta_dos_escenas():
    """BJ4 · el ANCLA de personaje no se toca: una sola generación + una sola
    subida con nombre explícito, compartida por las 2 escenas; cada escena
    recibe SU id por la línea 'Asset:' de SU generación."""
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
        assert mgr.img_scene_n == 2
        # ids: a1=ancla, a2="personaje", a3=escena 1, a4=escena 2 → video POR id
        assert mgr.video_startframes == ["id:a3", "id:a4"], \
            mgr.video_startframes
        estados = {(s["scene_id"], s["start_frame_asset"],
                    s["start_frame_asset_id"]) for s in snap["scenes"]}
        assert estados == {("s1", "Manzana roja asomándose toma 1", "a3"),
                           ("s2", "Manzana roja asomándose toma 2", "a4")}, \
            estados
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
