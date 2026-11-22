# -*- coding: utf-8 -*-
"""Batería BH (2026-11): rutas Flow con espacios/unidad Windows + escape
ffmpeg de la etapa 4.

BH1 (pipeline_orchestrator · _last_path / _path_from_line / respaldo outDir):
  · _last_path acepta la ÚLTIMA línea no vacía con una ruta completa de
    imagen/video (.png .jpg .jpeg .webp .mp4 .mov, case-insensitive) con
    letra de unidad de Windows (X:\\ o X:/) o barra inicial POSIX, CON
    espacios y tildes. El patrón antiguo cortaba en el primer espacio.
  · Respaldo: si el texto no trae ruta, se usa el archivo MÁS RECIENTE de
    outDir con extensión válida y fecha posterior al inicio de la llamada;
    si tampoco hay, falla con el mensaje de siempre.
  · Misma lógica en ancla (_ensure_reference), start-frame y video.

BH2 (etapa 4 y ayudantes · rutas con espacios y unidad en comandos ffmpeg):
  · ffmpeg_filter_path(): valor de opción de filtro (ass=/subtitles=/
    fontsdir=…) entre comillas simples y con escape a NIVEL OPCIÓN
    ('\\' → '\\\\', ':' → '\\:', "'" → cierre+literal+apertura). Probado con
    un parser réplica de av_get_token a DOS niveles: el esquema antiguo (sin
    comillas, solo '\\:') se TRUNCABA en el ':' de la unidad.
  · concat demuxer (video_assembler + pipeline/video): apóstrofes escapados
    '\\'' — los espacios ya iban seguros entre comillas.
  · build_burn_cmd sigue inmune por diseño (cwd=run_dir + nombre relativo).
  · build_ecommerce_ffmpeg_filter sin ruta en el filtro (variable muerta
    'badge_escaped' eliminada).

Hermética: cero red, cero Chrome, cero LLM real (doubles + mock.patch).
"""
import asyncio
import json
import os
import sys
import tempfile
import time
import unittest.mock as mock
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import mcp_manager as mcpm
from services import pipeline_orchestrator as po

# NOTA conftest (FIX-A): los módulos backend que arrastran `database`
# (pipeline.video → services.avatar_motion, video_assembler →
# asset_harvester, ecommerce_overlays) NO se importan a nivel de módulo:
# al correr la batería como script, ese import ocurre ANTES de que conftest
# instale el parche de aislamiento (pytest_configure) y el hook meta-path no
# repunta database.DB_PATH → INTERNALERROR. Se importan DENTRO de cada test
# (mismo patrón que el hook aplica al primer import bajo pytest).


# ═══════════════ parser réplica de av_get_token (ffmpeg) ══════════════════
_BS = chr(92)


def _scan_token(raw: str, i: int, term: str) -> tuple[str, int]:
    """Réplica de libavutil/avstring.c av_get_token: el '\\' escapa al carácter
    siguiente FUERA de comillas; una sección entre comillas simples se copia
    VERBATIM (los escapes se preservan para el nivel siguiente). Devuelve
    (token, posición RAW tras consumir)."""
    out: list[str] = []
    n = len(raw)
    while i < n and raw[i] not in term:
        c = raw[i]
        if c == _BS and i + 1 < n:
            out.append(raw[i + 1])
            i += 2
            continue
        if c == "'":
            i += 1
            while i < n and raw[i] != "'":
                out.append(raw[i])
                i += 1
            if i < n:
                i += 1  # cierra la comilla
            continue
        out.append(c)
        i += 1
    return "".join(out).strip(), i


def _filter_option_values(vf_value: str) -> tuple[str, list[str]]:
    """Valor completo de -vf → (nombre_filtro, valores de opción decodificados)
    según los DOS niveles de parser de ffmpeg: grafo (avfilter) y opción
    (av_opt). Para 'ass=<v1>[:fontsdir=<v2>]' devuelve (ass, [v1, v2])."""
    name, i = _scan_token(vf_value, 0, "=,;[")        # nivel grafo: nombre
    assert i < len(vf_value) and vf_value[i] == "=", vf_value
    opts, _ = _scan_token(vf_value, i + 1, "[],;")    # nivel grafo: argumentos
    # NOTA: el término del nivel grafo es solo [],; — el '=' de 'fontsdir='
    # NO es separador del grafo (los args pueden contener key=value).
    vals: list[str] = []
    j = 0
    first = True
    while j < len(opts):
        if not first:
            # 'clave=' — la clave es texto plano; se salta hasta el '='
            k, j2 = _scan_token(opts, j, ":=")
            if j2 < len(opts) and opts[j2] == "=":
                j = j2 + 1
        v, j2 = _scan_token(opts, j, ":")             # nivel opción: valor
        vals.append(v)
        first = False
        j = j2
        if j < len(opts) and opts[j] == ":":
            j += 1
    return name, vals


# ═══════════════════════ manager hermético configurable ═══════════════════
class MockManagerBH:
    """Mock del MCP manager: respuestas en cola para flow_generate_image/video
    y side-effect opcional (p. ej. escribir el archivo en outDir).
    BI1: mantiene un proyecto Flow MÍNIMO — flow_generate_image registra el
    asset con nombre POR CONTENIDO (no el stem del archivo local) y
    flow_list_assets lo lista, para que el startFrame detectado sea el
    nombre de Flow."""

    def __init__(self, image_texts=None, video_text="Generated video:", 
                 on_execute=None):
        self.exec_calls: list[tuple[str, dict]] = []
        self._img_texts = list(image_texts or [])
        self._video_text = video_text
        self._on_execute = on_execute
        self.flow_assets: list[str] = []   # BI1: proyecto Flow simulado
        self._img_n = 0

    async def test_pipeline(self, service, notebook_id=None):
        return {"service": service, "ok": True, "state": "connected",
                "auth": "ok", "detail": "", "browser_up": True}

    async def tools_catalog(self, service, auto_connect=True):
        return {"tools": [{"name": "flow_generate_image"}]}

    async def execute(self, service, tool, arguments=None, timeout=None, **kw):
        args = dict(arguments or {})
        self.exec_calls.append((tool, args))
        if self._on_execute:
            self._on_execute(tool, args)
        if tool == "notebook_query":
            return {"ok": True, "text": json.dumps(
                {"status": "success", "answer": "CONTEXTO FALSO del notebook"})}
        if tool == "flow_list_assets":    # BI1: listado del proyecto simulado
            if not self.flow_assets:
                return {"ok": True, "text": "(the project has no images yet)"}
            return {"ok": True,
                    "text": "\n".join(f"- {n}" for n in self.flow_assets)}
        if tool == "flow_generate_image":
            self._img_n += 1
            self.flow_assets.append(f"Recurso de Flow {self._img_n:02d}")
            t = self._img_texts.pop(0) if self._img_texts else \
                "Generated 1 image(s):"
            return {"ok": True, "text": t}
        if tool == "flow_generate_video":
            return {"ok": True, "text": self._video_text}
        if tool == "flow_upload_file":
            n = args.get("name", "ref")
            self.flow_assets.append(n)
            return {"ok": True, "text": f'Uploaded "{n}". Reference as @{{{n}}}.'}
        return {"ok": True, "text": "ok"}


def _valid_bp(n=1):
    return {
        "label": "frutinovela",
        "title": "La manzana y la pera",
        "scenes": [
            {"title": f"Escena {i + 1}",
             "narration": f"Narración de la escena {i + 1}.",
             "image_prompt": f"cinematic shot {i + 1}"}
            for i in range(n)
        ],
    }


# ═════════════════════════ BH1 · _last_path ═══════════════════════════════
def test_bh1_windows_espacios():
    """BH1: ruta Windows con espacios y unidad — la ruta COMPLETA, no cortada
    en el primer espacio (D:\\PROYECTOS\\YOUTUBE AUTOMATION\\…)."""
    p = r"D:\PROYECTOS\YOUTUBE AUTOMATION\runs\r1\ancla.jpg"
    t = "Generated 1 image(s) in 3.2s with 2 (1:1):\n" + p
    assert po._last_path(t) == p


def test_bh1_tildes():
    """BH1: tildes y eñes en la ruta se conservan."""
    p = r"D:\PROYECTOS\YOUTUBE AUTOMATION\señal áé íóúñ\img.png"
    assert po._last_path("Saved:\n" + p) == p


def test_bh1_prefijo_saved():
    """BH1: prefijo tipo 'Saved: ' delante de la ruta con espacios."""
    p = r"D:\PROYECTOS\YOUTUBE AUTOMATION\frames\mi frame uno.PNG"
    assert po._last_path(f"Saved: {p}") == p


def test_bh1_varias_lineas_ultima_valida():
    """BH1: la ÚLTIMA línea no vacía con ruta válida gana; las líneas de
    texto suelto entre medias no la invalidan."""
    t = ("Generated 2 image(s):\n"
         r"D:\a b\one.png" "\n"
         "texto suelto sin ruta\n"
         "\n"
         r"D:\c d\two.jpg")
    assert po._last_path(t) == r"D:\c d\two.jpg"


def test_bh1_video_exts_case_insensitive():
    """BH1: .mp4/.mov/.webp y extensiones en MAYÚSCULAS aceptadas."""
    for p in (r"D:\x y\v.mp4", r"D:\x y\v.MOV", r"D:\x y\v.webp",
              r"D:\x y\v.PNG", r"D:\x y\v.JPG", r"D:\x y\v.JPEG"):
        assert po._last_path("ok:\n" + p) == p, p


def test_bh1_unidad_con_barra():
    """BH1: unidad de Windows con barra 'D:/' también aceptada (Node.js la
    emite a veces con separador forward)."""
    assert po._last_path("D:/dir con espacio/img.webp") == \
        "D:/dir con espacio/img.webp"


def test_bh1_unix_con_espacios():
    """BH1: ruta POSIX con espacios y prefijo."""
    assert po._last_path("Output: /home/u/My Videos/img.png") == \
        "/home/u/My Videos/img.png"


def test_bh1_descarta_url_y_relacion():
    """BH1: URLs y rutas relativas NO son rutas completas."""
    assert po._last_path("Saved: https://x.com/a/b.png") == ""
    assert po._last_path("Saved: //cdn.example/a/b.png") == ""
    assert po._last_path("ver assets/locales/img.png") == ""


def test_bh1_sin_ruta():
    """BH1: texto sin ninguna ruta → '' (el caller usa el respaldo)."""
    assert po._last_path("Generated 1 image(s) in 2s\n(sin ruta)") == ""
    assert po._last_path("") == ""
    assert po._last_path(None) == ""


def test_bh1_comillas_y_guion():
    """BH1: marcador '- ' y comillas alrededor de la ruta se limpian."""
    assert po._path_from_line('- "D:\\dir con espacio\\video final.mov"') == \
        r"D:\dir con espacio\video final.mov"


def test_bh1_asset_name_de_ruta_espacios():
    """BH1: el stem de una ruta con espacios se convierte en asset name
    (rutas con separador nativo; el nombre resultante jamás tiene espacios)."""
    assert po._asset_name_from_file("/PROYECTOS dir/frames/mi frame uno.PNG") \
        == "mi_frame_uno"
    import re as _re
    out = po._asset_name_from_file(
        r"D:\PROYECTOS\YOUTUBE AUTOMATION\frames\mi frame uno.PNG")
    assert _re.fullmatch(r"[A-Za-z0-9_\-]+", out), out   # sin espacios ni '\\'


# ═══════════════════ BH1 · respaldo por outDir ════════════════════════════
def test_bh1_respaldo_reciente_posterior_t0():
    """BH1: el respaldo devuelve el archivo más reciente de outDir con fecha
    posterior al inicio de la llamada; los ANTERIORES a t0 no cuentan."""
    with tempfile.TemporaryDirectory() as td:
        rd = Path(td)
        viejo = rd / "vieja.png"
        viejo.write_bytes(b"x")
        os.utime(viejo, (time.time() - 3600, time.time() - 3600))  # 1 h antes
        t0 = time.time()
        assert po._recent_media_in_dir(rd, t0) == ""     # solo el viejo: nada
        nuevo = rd / "nueva con espacios.jpg"
        nuevo.write_bytes(b"x")
        mejor = po._recent_media_in_dir(rd, t0)
        assert mejor == str(nuevo), mejor


def test_bh1_respaldo_solo_extensiones_validas():
    """BH1: .txt/.json/.ass se ignoran; .mp4/.mov/.webp/.MP4 cuentan."""
    with tempfile.TemporaryDirectory() as td:
        rd = Path(td)
        (rd / "notas.txt").write_text("x")
        (rd / "plan.json").write_text("{}")
        (rd / "subs.ass").write_text("[Script Info]")
        (rd / "clip.mov").write_bytes(b"x")
        (rd / "clip.MP4").write_bytes(b"x")
        got = po._recent_media_in_dir(rd, time.time())
        assert got.endswith(".MP4"), got   # el más reciente de los válidos


def test_bh1_respaldo_dir_inexistente():
    """BH1: outDir inexistente → '' sin lanzar."""
    assert po._recent_media_in_dir(Path(tempfile.gettempdir()) /
                                   "bh_no_existe_xyz", time.time()) == ""


# ═══════════════ BH1 · call-sites: ancla / start-frame / video ════════════
def test_bh1_ancla_respaldo_outdir():
    """BH1 ancla: texto SIN ruta pero Flow dejó el PNG en outDir → el respaldo
    lo encuentra y flow_upload_file recibe ESA ruta."""
    with tempfile.TemporaryDirectory() as td:
        orch = po.PipelineOrchestrator(manager=MockManagerBH(),
                                       runs_dir=Path(td) / "runs")
        run = orch.create_run(idea="idea", notebook_id="nb_mock")

        def _escribe(tool, args):
            if tool == "flow_generate_image" and args.get("outDir"):
                (Path(args["outDir"]) / "ancla con espacios.png").write_bytes(b"p")

        orch.manager = MockManagerBH(
            image_texts=["Generated 1 image(s) in 1.2s:"],   # sin ruta
            on_execute=_escribe)
        asyncio.run(orch._ensure_reference(run))
        ups = [a for t, a in orch.manager.exec_calls if t == "flow_upload_file"]
        assert ups, "no se subió el ancla"
        assert ups[0]["filePath"] == str(
            orch._run_dir(run["run_id"]) / "ancla con espacios.png"), ups[0]
        assert run["reference_asset"] == "personaje"


def test_bh1_ancla_sin_ruta_ni_respaldo_falla_igual():
    """BH1 ancla: sin ruta en el texto y sin archivos nuevos → el mensaje de
    error es el MISMO de siempre (no se inventa nada)."""
    with tempfile.TemporaryDirectory() as td:
        orch = po.PipelineOrchestrator(
            manager=MockManagerBH(image_texts=["Generated 1 image(s):"]),
            runs_dir=Path(td) / "runs")
        run = orch.create_run(idea="idea", notebook_id="nb_mock")
        with pytest.raises(mcpm.MCPManagerError, match="ancla de personaje"):
            asyncio.run(orch._ensure_reference(run))


def test_bh1_stage3_rutas_espacios_de_principio_a_fin():
    """BH1 etapa 3 completa: ancla con espacios, start-frame con espacios y
    MAYÚSCULAS, video sin ruta en el texto pero respaldado por outDir (el
    scene_s1.mp4 que Flow escribió). Todo done con video_file real."""
    with tempfile.TemporaryDirectory() as td:
        orch = po.PipelineOrchestrator(manager=MockManagerBH(),
                                       runs_dir=Path(td) / "runs")
        run = orch.create_run(idea="idea", notebook_id="nb_mock",
                              blueprint=_valid_bp(1))

        def _escribe(tool, args):
            # Flow NO devuelve ruta del video en el texto, pero SÍ deja el MP4
            if tool == "flow_generate_video" and args.get("outFile"):
                Path(args["outFile"]).write_bytes(b"mp4")

        orch.manager = MockManagerBH(
            image_texts=[
                "Generated 1 image(s) in 1.0s:\n"
                r"D:\PROYECTOS\YOUTUBE AUTOMATION\ancla\mi ancla.png",
                "Saved: /PROYECTOS dir/frames/mi frame uno.PNG",
            ],
            video_text="Generated video in 8s (no path here)",
            on_execute=_escribe)
        asyncio.run(orch._run(run["run_id"]))

        vids = [a for t, a in orch.manager.exec_calls
                if t == "flow_generate_video"]
        assert vids, "no se despachó el video"
        # BI1: startFrame = nombre del asset en Flow (la 2ª imagen: la 1ª es el
        # ancla); el stem local "mi_frame_uno" ya NO se usa como asset name.
        assert vids[0]["startFrame"] == "Recurso de Flow 02", vids[0]
        # BH1 se mantiene: la ruta Windows CON ESPACIOS del ancla llegó entera
        # a flow_upload_file
        ups = [a for t, a in orch.manager.exec_calls if t == "flow_upload_file"]
        assert ups and ups[0]["filePath"].endswith("mi ancla.png"), ups
        st = orch.get_status(run["run_id"])
        assert st["scenes"][0]["status"] == "done", st["scenes"][0]
        assert st["scenes"][0]["video_file"] == str(
            orch._run_dir(run["run_id"]) / "scene_s1.mp4")


def test_bh1_video_respaldo_reciente_con_espacios():
    """BH1 video: Flow escribe el MP4 con OTRO nombre (con espacios) y no lo
    dice en el texto → el respaldo encuentra el más reciente."""
    with tempfile.TemporaryDirectory() as td:
        orch = po.PipelineOrchestrator(manager=MockManagerBH(),
                                       runs_dir=Path(td) / "runs")
        run = orch.create_run(idea="idea", notebook_id="nb_mock",
                              blueprint=_valid_bp(1))

        def _escribe(tool, args):
            if tool == "flow_generate_video" and args.get("outDir"):
                (Path(args["outDir"]) / "clip s1 (v2).mp4").write_bytes(b"mp4")

        orch.manager = MockManagerBH(
            image_texts=[
                "ok:\n" + r"D:\a b\ancla.png",
                "ok:\n/assets/frames/frame uno.png",
            ],
            video_text="Generated video (sin ruta)",
            on_execute=_escribe)
        asyncio.run(orch._run(run["run_id"]))
        st = orch.get_status(run["run_id"])
        assert st["scenes"][0]["status"] == "done", st["scenes"][0]
        assert st["scenes"][0]["video_file"].endswith("clip s1 (v2).mp4"), \
            st["scenes"][0]["video_file"]


def test_bh1_startframe_sin_ruta_ni_respaldo_marca_failed():
    """BH1 start-frame: sin ruta y sin respaldo → la escena queda failed con
    el detalle 'no devolvió ruta del start-frame' (la corrida NO aborta)."""
    with tempfile.TemporaryDirectory() as td:
        orch = po.PipelineOrchestrator(
            manager=MockManagerBH(image_texts=[
                "ok:\n" + r"D:\a b\ancla.png",   # ancla OK
                "Generated 1 image(s):",          # start-frame SIN ruta
            ]),
            runs_dir=Path(td) / "runs")
        run = orch.create_run(idea="idea", notebook_id="nb_mock",
                              blueprint=_valid_bp(1))
        asyncio.run(orch._run(run["run_id"]))
        st = orch.get_status(run["run_id"])
        assert st["scenes"][0]["status"] == "failed", st["scenes"][0]
        assert "no devolvió ruta del start-frame" in st["scenes"][0]["detail"]


# ═══════════════════ BH2 · escape de filtros ffmpeg ═══════════════════════
def test_bh2_escape_roundtrip_windows():
    """BH2: ffmpeg_filter_path sobrevive los DOS niveles del parser de ffmpeg
    (réplica av_get_token) — unidad, backslashes, espacios, tildes."""
    casos = [
        r"D:\PROYECTOS\YOUTUBE AUTOMATION\runs\r1\subs.ass",
        r"D:\PROYECTOS\YOUTUBE AUTOMATION\señal áé íóúñ\captions.ass",
        r"C:\Users\pepe\AppData\Local\Temp\tmp123\Montserrat-ExtraBold.ttf",
        "/tmp/my run dir/final subs.srt",
        r"D:\pepe's videos\subs.ass",
    ]
    for p in casos:
        from pipeline import video as video_mod
        vf = f"ass={video_mod.ffmpeg_filter_path(p)}"
        name, vals = _filter_option_values(vf)
        assert name == "ass", vf
        assert vals and vals[0] == p, (p, vals)


def test_bh2_escape_fontsdir_segunda_opcion():
    """BH2: el ':fontsdir=' tras un valor con comillas no contamina el valor
    del ass y el fontsdir también hace round-trip."""
    ass = r"D:\PROYECTOS\YOUTUBE AUTOMATION\runs\r1\subs.ass"
    fdir = r"D:\PROYECTOS\YOUTUBE AUTOMATION\data\fonts con tilde á"
    from pipeline import video as video_mod
    vf = (f"ass={video_mod.ffmpeg_filter_path(ass)}"
          f":fontsdir={video_mod.ffmpeg_filter_path(fdir)}")
    name, vals = _filter_option_values(vf)
    assert name == "ass"
    assert vals[0] == ass, vals
    assert vals[1] == fdir, vals


def test_bh2_esquema_viejo_se_truncaba():
    """BH2 (regresión documentada): el esquema antiguo (sin comillas, solo
    replace(':', '\\:')) NO sobrevive el nivel grafo: el ':' de la unidad
    parte el valor y el filtro recibe 'D'. Por eso se cambió."""
    ass = r"D:\PROYECTOS\YOUTUBE AUTOMATION\runs\r1\subs.ass"
    from pipeline import video as video_mod
    viejo = "ass=" + Path(ass).as_posix().replace(":", "\\:")
    _, vals = _filter_option_values(viejo)
    assert vals and vals[0] == "D", vals      # truncado: el bug BH2


def test_bh2_burn_subtitles_filtro_completo(tmp_path):
    """BH2: burn_subtitles (etapa 4 del render) emite ass=…:fontsdir=… con
    comillas y round-trip EXACTO contra rutas reales con espacios y tildes."""
    from pipeline import typography as typo_mod
    from pipeline import video as video_mod

    out_dir = tmp_path / "OUTPUT DIR CON ESPACIOS á"
    proj = out_dir / "bh-proj"
    proj.mkdir(parents=True)
    words_file = proj / "words.json"
    words_file.write_text(json.dumps([
        {"word": "hola", "start": 0.0, "end": 0.5},
        {"word": "mundo", "start": 0.5, "end": 1.0},
    ]), encoding="utf8")
    raw = proj / "raw.mp4"
    raw.write_bytes(b"dummy")
    fonts = tmp_path / "fonts con tilde á"
    fonts.mkdir()
    cmds: list[list[str]] = []

    def fake_ffmpeg(cmd, timeout=300):
        cmds.append(cmd)
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"rendered")
        p = mock.MagicMock()
        p.returncode = 0
        return p

    with mock.patch.object(video_mod, "OUTPUT_DIR", out_dir), \
         mock.patch.object(video_mod, "_run_ffmpeg", side_effect=fake_ffmpeg), \
         mock.patch.object(typo_mod, "FONT_DIR", fonts):
        res = asyncio.run(video_mod.burn_subtitles(
            {"id": "bh-proj", "format": "short", "meta": {}}, raw, words_file))
    assert res.is_file(), res
    vf_val = next(c[i + 1] for c in cmds
                  for i, a in enumerate(c)
                  if a == "-vf" and "ass=" in c[i + 1])
    assert vf_val.startswith("ass='"), vf_val
    name, vals = _filter_option_values(vf_val)
    assert name == "ass"
    ass_real = proj / "subs.ass"
    assert ass_real.is_file()
    assert vals[0] == str(ass_real), (vals[0], str(ass_real))
    assert vals[1] == str(fonts), vals
    assert ":fontsdir='" in vf_val, vf_val


def test_bh2_concat_assembler_espacios(tmp_path):
    """BH2: build_concat_cmd con clips en carpetas con espacios — la línea
    file '…' del demuxer hace round-trip (un nivel, comillas verbatim)."""
    from services import video_assembler as vasm
    run_dir = tmp_path / "RUN CON ESPACIOS á"
    norm = run_dir / "norm"
    norm.mkdir(parents=True)
    outs = []
    for n in ("scene_001.mp4", "scene_002.mp4"):
        p = norm / n
        p.write_bytes(b"x")
        outs.append(p)
    built = vasm.build_concat_cmd(outs, run_dir)
    lines = (norm / "concat_list.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line, p in zip(lines, outs):
        assert line.startswith("file '") and line.endswith("'"), line
        assert line[6:-1] == str(p.resolve()), line
    assert built["cmd"][built["cmd"].index("-i") + 1].endswith(
        "concat_list.txt")


def test_bh2_concat_assembler_apostrofe(tmp_path):
    """BH2: un apóstrofe en la carpeta se escapa '\\'' y hace round-trip."""
    from services import video_assembler as vasm
    run_dir = tmp_path / "pepe's run"
    norm = run_dir / "norm"
    norm.mkdir(parents=True)
    p = norm / "scene_001.mp4"
    p.write_bytes(b"x")
    vasm.build_concat_cmd([p], run_dir)
    line = (norm / "concat_list.txt").read_text(encoding="utf-8").strip()
    assert "'\\''" in line, line
    ruta = line[len("file '"):-1].replace("'\\''", "'")
    assert ruta == str(p.resolve()), (ruta, str(p.resolve()))


def test_bh2_concat_video_py_espacios(tmp_path):
    """BH2: concat_clips (pipeline/video.py) con clips en carpeta con espacios
    — concat.txt quoted + round-trip; ffmpeg mockeado rc=0."""
    from pipeline import video as video_mod
    out_dir = tmp_path / "OUTPUT DIR CON ESPACIOS"
    proj = out_dir / "bh-proj"
    proj.mkdir(parents=True)
    clips = []
    for n in ("clip_00.mp4", "clip_01.mp4"):
        c = proj / n
        c.write_bytes(b"x")
        clips.append(c)
    cmds: list[list[str]] = []

    def fake_ffmpeg(cmd, timeout=300):
        cmds.append(cmd)
        Path(cmd[-1]).write_bytes(b"concat")
        p = mock.MagicMock()
        p.returncode = 0
        return p

    with mock.patch.object(video_mod, "OUTPUT_DIR", out_dir), \
         mock.patch.object(video_mod, "_run_ffmpeg", side_effect=fake_ffmpeg):
        res = asyncio.run(video_mod.concat_clips({"id": "bh-proj"}, clips))
    assert res.is_file()
    concat_txt = (proj / "concat.txt").read_text(encoding="utf8").splitlines()
    for line, c in zip(concat_txt, clips):
        assert line.startswith("file '") and line.endswith("'"), line
        assert line[6:-1] == c.as_posix(), line
    assert cmds and cmds[0][cmds[0].index("-i") + 1].endswith("concat.txt")


def test_bh2_build_burn_cmd_inmune_por_diseno(tmp_path):
    """BH2: build_burn_cmd usa cwd=run_dir + nombre RELATIVO en el filtro —
    con rutas tipo D:\\…\\YOUTUBE AUTOMATION\\… el filtro no contiene NI UNA
    barra de la ruta: el problema de escaping no existe ahí."""
    from services import video_assembler as vasm
    run_dir = tmp_path / "RUN CON ESPACIOS á"
    run_dir.mkdir()
    src = run_dir / "video_concat.mp4"
    srt = run_dir / "final_captions.srt"
    out = run_dir / "final_render.mp4"
    built = vasm.build_burn_cmd(src, srt, out)
    vf_val = built["cmd"][built["cmd"].index("-vf") + 1]
    assert vf_val == "subtitles=final_captions.srt", vf_val
    assert "RUN" not in vf_val and _BS not in vf_val and ":" not in vf_val


def test_bh2_ecommerce_filtro_sin_ruta():
    """BH2: el filtro del badge NO incrusta la ruta del PNG (va por -i con
    índices); con una ruta Windows con espacios no aparece en el filtro."""
    from services import ecommerce_overlays as eco
    f = eco.build_ecommerce_ffmpeg_filter(
        Path(r"D:\PROYECTOS\YOUTUBE AUTOMATION\badge_rating.png"),
        start_sec=0.5, duration_sec=6.0, position="top")
    assert "PROYECTOS" not in f and _BS not in f and "badge" not in f, f
    assert f.startswith("overlay=") and "enable='" in f, f


def test_bh2_probe_y_ffprobe_argv(tmp_path):
    """BH2: ffprobe recibe la ruta como ARGV (inmune a espacios) y devuelve
    None si el medio no existe — con una ruta 'Windows' literal."""
    from services import video_assembler as vasm
    p = tmp_path / "D:\\dir con espacio\\clip.mp4"   # nombre literal con '\\'
    assert vasm._probe_media(p) is None              # no existe → None
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    # con ffprobe real instalado la duración no es None; sin binario, None —
    # ambos aceptables: el contrato es NO estimar y NO lanzar.
    d = vasm._probe_media(p)
    assert d is None or d > 0, d


# ═══════════════════════════ runner de batería ════════════════════════════
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
