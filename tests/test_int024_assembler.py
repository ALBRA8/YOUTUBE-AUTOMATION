#!/usr/bin/env python3
"""
BATERÍA DE TESTS — INT-024 · Asset Harvester & FFmpeg Video Assembler
(Stage 3.5 harvest + manifest estricto · Stage 4 ensamblaje determinista)

Cubre el post-producción completa con hermeticidad total (cero red, cero
MCP, cero LLM):
  S1 · Harvester: assets dispersos de Stage 3 → rutas deterministas
      scenes/scene_{idx:03d}.mp4|.png, manifest.json con el esquema
      estricto (run_id/notebook_id/character_ref/scenes[]), validación que
      RECHAZA manifests rotos (claves ausentes, duración <= 0, status
      inválido) y fallback imagen (Ken Burns) cuando el video no llegó.
  S2 · Duration math: estimación por caracteres/seg (hermética sin TTS),
      plan_scene trim vs loop vs kenburns vs placeholder (con y sin
      ffprobe), suelos de duración mínima.
  S3 · Captions: .srt por escena con ventanas acumuladas EXACTAS
      (HH:MM:SS,mmm), numeración que omite escenas sin texto, sin drift.
  S4 · Construcción FFmpeg (dry-run puro, sin binario): cadena -vf
      scale/crop/fps exactos, -stream_loop, zoompan Ken Burns con frames
      = target*fps, apad a duración exacta, concat demuxer, amix con
      cama musical volume=-20dB, burn subtitles (libass) vs soft
      (mov_text), libx264/aac 1080p30, render_plan.json persistido.
  S5 · Orquestador: gatekeeper del render (RENDER_BLOCKED_PARTIAL_FAILURES
      sin flag / RENDER_BUSY / RENDER_NOTHING_READY), dry-run completo vía
      render_final (hilo → estado run['render'] done), retry-scenes
      bloqueado mientras renderiza, re-render permitido al terminar.
  S6 · Endpoints REST del panel (/api/pipeline/harvest|render|
      render/status|manifest|render/file) vía ASGI in-process con códigos
      estables 200/400/404.
  S7 · Render REAL de humo (solo si ffmpeg está presente): 2 escenas reales
      diminutas + placeholder + locución WAV → final_render.mp4 existe,
      duración ≈ suma del manifest, .srt generado. Sin ffmpeg la batería
      lo reporta honestamente y NO falla (degrada, nunca miente).

Convención del repo: script stdlib (sin pytest), 0 dependencias externas.
"""
import asyncio
import json
import math
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
from services import asset_harvester as harv  # noqa: E402
from services import pipeline_orchestrator as po  # noqa: E402
from services import video_assembler as vasm  # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


HAS_FFMPEG = shutil.which("ffmpeg") is not None


# ─────────────────────────── fixtures herméticos ──────────────────────────
def _tiny_video(path: Path, dur: float, size="320x180", color="0x336699") -> bool:
    """MP4 H.264 diminuto y REAL (solo si ffmpeg existe)."""
    if not HAS_FFMPEG:
        return False
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", f"color=c={color}:s={size}:r=30",
             "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "ultrafast",
             "-pix_fmt", "yuv420p", str(path)],
            check=True, capture_output=True, timeout=60)
        return path.is_file()
    except (subprocess.SubprocessError, OSError):
        return False


def _tiny_png(path: Path) -> bool:
    if not HAS_FFMPEG:
        return False
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=c=0xAA5522:s=180x320",
             "-frames:v", "1", str(path)],
            check=True, capture_output=True, timeout=60)
        return path.is_file()
    except (subprocess.SubprocessError, OSError):
        return False


def _tiny_wav(path: Path, dur: float = 0.6, freq: int = 440) -> None:
    """WAV PCM mono 24k con seno puro (stdlib wave, sin numpy)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 24000
    n = int(rate * dur)
    frames = bytearray()
    for i in range(n):
        # seno por identidad deentera — suficiente para un medio válido
        val = int(12000 * math.sin(2 * math.pi * freq * i / rate))
        frames += int(val).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def fake_run(tmp: Path, with_files: bool = True) -> dict:
    """Estado de corrida 'completada' típico de INT-023:
    s1 done (video), s2 done (solo imagen → fallback Ken Burns),
    s3 failed (→ placeholder con flag)."""
    run = {
        "run_id": "run_int024_test",
        "created_at": "2026-10-23T12:00:00",
        "idea": "video de prueba INT-024",
        "notebook_id": "nb_test_123",
        "format": "short",
        "style": "auto",
        "stage": "done",
        "error_code": "PARTIAL_FAILURES",
        "error_detail": "1 escena(s) fallaron: s3",
        "steps": [{"stage": s, "label": l, "state": "pending", "detail": ""}
                  for s, l in po._STEPS],
        "progress_pct": 95,
        "context_chars": 1200,
        "blueprint_title": "Prueba INT-024",
        "scenes": [
            {"scene_id": "s1", "title": "Escena 1",
             "narration": "Bienvenidos a esta historia increíble que empieza ahora mismo.",
             "image_prompt": "plano abierto", "status": "done", "attempts": 1,
             "video_file": str(tmp / "scene_s1.mp4") if with_files else "",
             "detail": ""},
            {"scene_id": "s2", "title": "Escena 2",
             "narration": "El giro inesperado llegó cuando nadie lo esperaba realmente.",
             "image_prompt": "primer plano", "status": "done", "attempts": 1,
             "video_file": str(tmp / "scene_s2_inexistente.mp4"),  # reportado pero ausente
             "detail": ""},
            {"scene_id": "s3", "title": "Escena 3",
             "narration": "Y así terminó todo entre la niebla del recuerdo.",
             "image_prompt": "cierre", "status": "failed", "attempts": 2,
             "video_file": "", "detail": "[TOOL_ERROR] simulado"},
        ],
        "dispatched": 3,
        "done_count": 2,
        "failed_scene_ids": ["s3"],
        "reference_asset": "personaje",
        "render": {"status": "idle", "stage": "", "progress_pct": 0,
                   "output": "", "error_code": "", "error_detail": "",
                   "started_at": "", "finished_at": ""},
    }
    return run


def seed_assets(tmp: Path) -> None:
    """Assets 'de Flow' en el run_dir: video s1 real (o falso), imagen s2."""
    tmp.mkdir(parents=True, exist_ok=True)
    if HAS_FFMPEG:
        _tiny_video(tmp / "scene_s1.mp4", 0.8)
    else:
        (tmp / "scene_s1.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
    _tiny_png(tmp / "scene_s2.png")


# ═════════════════════════════ S1 · HARVESTER + MANIFEST ═════════════════
def s1_harvester(tmp: Path):
    print("\n── S1 · Asset Harvester + manifest estricto ──")
    seed_assets(tmp)
    run = fake_run(tmp)

    manifest, path = harv.harvest_run(run, tmp, placeholders_for_failed=False)
    check("S1 harvest_run escribe manifest.json atómico", path.is_file()
          and path.name == "manifest.json")
    check("S1 esquema: claves raíz obligatorias",
          all(k in manifest for k in ("run_id", "notebook_id", "character_ref",
                                      "format", "aspect", "fps", "resolution",
                                      "scenes")))
    check("S1 run_id/notebook_id/character_ref propagados",
          manifest["run_id"] == "run_int024_test" and
          manifest["notebook_id"] == "nb_test_123" and
          manifest["character_ref"] == "personaje")
    check("S1 formato short → 9:16 @ 1080x1920",
          manifest["aspect"] == "9:16" and manifest["resolution"] == "1080x1920")
    sc = manifest["scenes"]
    check("S1 3 escenas en orden con idx determinista",
          [s["scene_id"] for s in sc] == ["s1", "s2", "s3"] and
          [s["idx"] for s in sc] == [1, 2, 3])
    check("S1 rutas deterministas scenes/scene_001.mp4 …",
          sc[0]["asset_path"] == "scenes/scene_001.mp4" and
          (tmp / sc[0]["asset_path"]).is_file())
    check("S1 s2: video ausente → fallback imagen scene_002.png (Ken Burns)",
          sc[1]["asset_type"] == "image" and
          sc[1]["asset_path"] == "scenes/scene_002.png" and
          (tmp / "scenes/scene_002.png").is_file())
    check("S1 s3 failed SIN flag → status failed bloqueante",
          sc[2]["status"] == "failed" and sc[2]["asset_type"] == "placeholder")
    check("S1 duraciones > 0 en todas",
          all(isinstance(s["duration_sec"], (int, float)) and s["duration_sec"] > 0
              for s in sc))
    check("S1 locución narration/scene_001.wav detectada si existe",
          sc[0]["narration_audio_path"] in ("", "narration/scene_001.wav"))
    check("S1 validación pasa en manifest sano",
          harv.validate_manifest(manifest) == [])
    # validación estricta RECHAZA rotos
    broken = json.loads(json.dumps(manifest))
    del broken["character_ref"]
    check("S1 validación: falta clave raíz → error",
          any("character_ref" in e for e in harv.validate_manifest(broken)))
    broken = json.loads(json.dumps(manifest))
    broken["scenes"][0]["duration_sec"] = 0
    check("S1 validación: duration_sec <= 0 → error",
          any("duration_sec" in e for e in harv.validate_manifest(broken)))
    broken = json.loads(json.dumps(manifest))
    broken["scenes"][1]["status"] = "no_existe"
    check("S1 validación: status inválido → error",
          any("status inválido" in e for e in harv.validate_manifest(broken)))
    broken = json.loads(json.dumps(manifest))
    broken["scenes"][2]["scene_id"] = "s1"
    check("S1 validación: scene_id duplicado → error",
          any("duplicado" in e for e in harv.validate_manifest(broken)))
    try:
        harv.load_manifest(tmp / "carpeta_vacia_404")
        check("S1 load_manifest inexistente lanza código estable", False)
    except harv.HarvesterError as e:
        check("S1 load_manifest inexistente lanza código estable",
              e.code == "HARVEST_NO_MANIFEST")
    # placeholders_for_failed=True convierte s3
    manifest2, _ = harv.harvest_run(run, tmp, placeholders_for_failed=True)
    check("S1 flag force → s3 status placeholder (no bloqueante)",
          manifest2["scenes"][2]["status"] == "placeholder" and
          manifest2["scenes"][2]["duration_sec"] > 0)
    check("S1 manifest re-escrito (idempotente, path estable)",
          (tmp / "manifest.json").is_file())


# ═════════════════════════════ S2 · DURATION MATH ════════════════════════
def s2_duration_math(tmp: Path):
    print("\n── S2 · Duration math (sync trim/loop/kenburns/placeholder) ──")
    d = harv.estimate_duration("")
    check("S2 texto vacío → suelo RENDER_MIN_SCENE_SEC",
          d == float(config.RENDER_MIN_SCENE_SEC))
    d = harv.estimate_duration("a" * 145)
    check("S2 145 chars @ 14.5 cps → 10.0s", abs(d - 10.0) < 0.01)
    d = harv.estimate_duration("corta")
    check("S2 texto corto respeta suelo mínimo", d >= float(config.RENDER_MIN_SCENE_SEC))
    # plan_scene con archivo REAL (ffprobe presente en sandbox)
    vid = tmp / "probe_video.mp4"
    real = _tiny_video(vid, 1.0) if HAS_FFMPEG else False
    if real:
        p = vasm.plan_scene({"status": "ready", "asset_type": "video",
                             "asset_path": "probe_video.mp4",
                             "duration_sec": 0.5}, tmp)
        check("S2 video 1.0s vs target 0.5s → trim", p["mode"] == "trim"
              and abs(p["source_duration"] - 1.0) < 0.15)
        p = vasm.plan_scene({"status": "ready", "asset_type": "video",
                             "asset_path": "probe_video.mp4",
                             "duration_sec": 2.5}, tmp)
        check("S2 video 1.0s vs target 2.5s → loop", p["mode"] == "loop")
        p = vasm.plan_scene({"status": "ready", "asset_type": "video",
                             "asset_path": "probe_video.mp4",
                             "duration_sec": 1.0}, tmp)
        check("S2 video ≈ target → trim (tolerancia 0.05s)", p["mode"] == "trim")
    else:
        check("S2 ffprobe ausente: video 1.0s no probeable → loop seguro",
              vasm.plan_scene({"status": "ready", "asset_type": "video",
                               "asset_path": "no_existe.mp4",
                               "duration_sec": 2.0}, tmp)["mode"] == "loop")
    p = vasm.plan_scene({"status": "ready", "asset_type": "image",
                         "asset_path": "f.png", "duration_sec": 3.0}, tmp)
    check("S2 imagen → kenburns con target exacto",
          p["mode"] == "kenburns" and p["target"] == 3.0)
    p = vasm.plan_scene({"status": "placeholder", "asset_type": "placeholder",
                         "asset_path": "", "duration_sec": 2.0}, tmp)
    check("S2 placeholder → lavfi color", p["mode"] == "placeholder")
    p = vasm.plan_scene({"status": "ready", "asset_type": "video",
                         "asset_path": "fantasma.mp4", "duration_sec": 2.0}, tmp)
    check("S2 asset fantasma (probe None) → loop (nunca crashea)",
          p["mode"] == "loop" and p.get("source_duration") is None)


# ═════════════════════════════ S3 · CAPTIONS .SRT ════════════════════════
def s3_captions(tmp: Path):
    print("\n── S3 · Captions .srt (ventanas acumuladas exactas) ──")
    entries = [
        {"scene_id": "s1", "duration_sec": 8.4, "subtitle_text": "Primera línea."},
        {"scene_id": "s2", "duration_sec": 2.6, "subtitle_text": ""},  # sin texto
        {"scene_id": "s3", "duration_sec": 1.0, "subtitle_text": "Cierre."},
    ]
    srt = vasm.build_srt(entries)
    blocks = [b for b in srt.strip().split("\n\n") if b.strip()]
    check("S3 escena sin texto NO genera bloque", len(blocks) == 2)
    check("S3 numeración compacta 1..2 (sin huecos)",
          blocks[0].startswith("1\n") and blocks[1].startswith("2\n"))
    check("S3 ventana acumulada exacta [0 → 8.4]",
          "00:00:00,000 --> 00:00:08,400" in blocks[0])
    check("S3 segunda ventana arranca en 8.4+2.6=11.0 (no en 8.4)",
          "00:00:11,000 --> 00:00:12,000" in blocks[1])
    check("S3 timestamps con coma decimal SRT", "," in blocks[0].splitlines()[1])
    check("S3 texto preservado con líneas separadas",
          "Primera línea." in blocks[0] and "Cierre." in blocks[1])
    p = vasm.write_srt(tmp, entries)
    check("S3 write_srt persiste en run_dir", p.is_file() and "Cierre." in p.read_text())
    # borde: milisegundos redondeo estable
    check("S3 _ts(59.9995) no regresa 60s (llevada correcta)",
          vasm._ts(59.9995) in ("00:00:59,999", "00:01:00,000"))
    check("S3 _ts(3661.5) → 01:01:01,500",
          vasm._ts(3661.5) == "01:01:01,500")


# ═════════════════════════════ S4 · CONSTRUCCIÓN FFMPEG ══════════════════
def s4_ffmpeg_construction(tmp: Path):
    print("\n── S4 · Construcción FFmpeg (dry-run puro, sin binario) ──")
    seed_assets(tmp)
    run = fake_run(tmp)
    manifest, _ = harv.harvest_run(run, tmp, placeholders_for_failed=True)
    # locución real para escena 1 (apad path)
    _tiny_wav(tmp / "narration" / "scene_001.wav", 0.6)
    manifest["scenes"][0]["narration_audio_path"] = "narration/scene_001.wav"
    harv.write_manifest(tmp, manifest)

    plan = vasm.plan_render(manifest, tmp, music_path="", subtitles="burn")
    check("S4 plan: 5 pasos (3 escenas + concat + subtítulos/copia)",
          len(plan["steps"]) == 5, f"steps={len(plan['steps'])}")
    check("S4 plan: usa las 3 escenas con duración total = suma manifest",
          plan["scenes_used"] == 3 and
          abs(plan["duration_total"] - sum(s["duration_sec"] for s in manifest["scenes"])) < 0.01)
    sc_cmds = [st for st in plan["steps"] if st["stage"] == "scenes"]
    c1 = " ".join(sc_cmds[0]["cmd"])
    check("S4 s1 (video trim/loop): normalización 1080x1920 cover+crop",
          "scale=1080:1920:force_original_aspect_ratio=increase" in c1
          and "crop=1080:1920" in c1 and "fps=30" in c1)
    check("S4 s1: locución → apad a duración exacta + aac 48k stereo",
          "apad=whole_dur=" in c1 and "aac" in c1 and "-ar" in c1 and "48000" in c1)
    check("S4 s1: H.264 preset/CRF configurables",
          "libx264" in c1 and config.RENDER_X264_PRESET in c1
          and f"-crf {config.RENDER_CRF}" in c1)
    check("S4 s1: -t exacto = duration_sec del manifest",
          f"-t {manifest['scenes'][0]['duration_sec']:.3f}" in c1)
    check("S4 s1: salida determinista norm/scene_001.mp4",
          "norm/scene_001.mp4" in c1)
    c2 = " ".join(sc_cmds[1]["cmd"])
    check("S4 s2 imagen → zoompan Ken Burns con frames=target*fps",
          "zoompan=" in c2 and "min(zoom+0.0015,1.15)" in c2
          and f":d={int(round(manifest['scenes'][1]['duration_sec'] * 30))}:" in c2
          and "s=1080x1920" in c2)
    c3 = " ".join(sc_cmds[2]["cmd"])
    check("S4 s3 placeholder → lavfi color casi-negro",
          "color=c=0x101418" in c3 and "anullsrc=r=48000:cl=stereo" in c3)
    concat = [st for st in plan["steps"] if st["stage"] == "concat"][0]
    jc = " ".join(concat["cmd"])
    check("S4 concat demuxer -safe 0 -c copy con lista de rutas absolutas",
          "-f concat" in jc and "-safe 0" in jc and "-c copy" in jc and
          "concat_list.txt" in jc)
    lst = (tmp / "norm" / "concat_list.txt").read_text()
    check("S4 lista de concat en orden escena_001→003",
          lst.index("scene_001.mp4") < lst.index("scene_002.mp4") < lst.index("scene_003.mp4"))
    check("S4 .srt generado con las 3 escenas",
          (tmp / "final_captions.srt").is_file() and
          "Bienvenidos" in (tmp / "final_captions.srt").read_text())
    if vasm.has_filter("subtitles"):
        check("S4 burn: filtro subtitles con ruta RELATIVA (sin escaping)",
              "subtitles=final_captions.srt" in
              " ".join([st for st in plan["steps"] if st["stage"] == "subtitles"][0]["cmd"]))
        check("S4 plan.subtitles = burn", plan["subtitles"] == "burn")
    else:
        check("S4 sin libass → degrada a soft mov_text",
              "mov_text" in " ".join(
                  [st for st in plan["steps"] if st["stage"] == "subtitles"][0]["cmd"]))
    check("S4 salida final final_render.mp4", plan["final"].endswith("final_render.mp4"))

    # mezcla con cama musical ducked -20dB (comando dedicado)
    music = tmp / "bed_music.wav"
    _tiny_wav(music, 1.0, freq=220)
    mix = vasm.build_mix_cmd(tmp / "video_concat.mp4", music, tmp)
    jm = " ".join(mix["cmd"])
    check("S4 mix: música ducked a -20dB (volume) + amix duration=first",
          "volume=-20dB" in jm and "amix=inputs=2:duration=first" in jm)
    check("S4 mix: video se copia sin re-codificar (rápido)",
          "-c:v copy" in jm and mix["out"].name == "final_av.mp4")
    check("S4 mix: sin música → None (no paso de mezcla)",
          vasm.build_mix_cmd(tmp / "video_concat.mp4", None, tmp) is None)
    check("S4 música inexistente → resolve_music None (no tumba)",
          vasm.resolve_music(str(tmp / "fantasma.mp3")) is None)

    # soft mux explícito
    soft = vasm.build_soft_cmd(tmp / "video_concat.mp4",
                               tmp / "final_captions.srt",
                               tmp / "final_render.mp4")
    check("S4 soft: pista mov_text con idioma spa",
          "mov_text" in " ".join(soft["cmd"]) and "language=spa" in " ".join(soft["cmd"]))

    # assemble_run dry_run → plan persistido, NADA ejecutado
    res = vasm.assemble_run(tmp, dry_run=True, subtitles="off")
    check("S4 assemble_run dry_run → sin tocar ffmpeg",
          res["dry_run"] is True and res["steps"] == len(res["plan"]["steps"]))
    check("S4 render_plan.json persistido con los comandos exactos",
          (tmp / "render_plan.json").is_file() and
          "final_render.mp4" in (tmp / "render_plan.json").read_text())
    check("S4 dry_run no produce final_render.mp4",
          not (tmp / "final_render.mp4").exists())
    # manifest inválido → rechazo ANTES de ffmpeg
    bad = {"run_id": "x", "scenes": []}
    try:
        vasm.plan_render(bad, tmp)
        check("S4 plan_render con 0 escenas útiles → RENDER_NOTHING_READY", False)
    except vasm.AssemblerError as e:
        check("S4 plan_render con 0 escenas útiles → RENDER_NOTHING_READY",
              e.code == "RENDER_NOTHING_READY")


# ═════════════════════════════ S5 · ORQUESTADOR ══════════════════════════
async def s5_orchestrator(tmp: Path):
    print("\n── S5 · Orquestador: gatekeeper + render en hilo ──")
    runs_dir = tmp / "runs"
    orch = po.PipelineOrchestrator(manager=object(), runs_dir=runs_dir)
    rd = runs_dir / "run_int024_test"
    rd.mkdir(parents=True, exist_ok=True)
    seed_assets(rd)
    run = fake_run(rd)
    orch._save(run)

    # gate: PARTIAL_FAILURES sin flag → bloqueado
    try:
        orch.render_final("run_int024_test")
        check("S5 render sin flag con fallidas → RENDER_BLOCKED_PARTIAL_FAILURES", False)
    except po.PipelineError as e:
        check("S5 render sin flag con fallidas → RENDER_BLOCKED_PARTIAL_FAILURES",
              e.code == "RENDER_BLOCKED_PARTIAL_FAILURES")
    # gate: ya renderizando
    orch._render_busy["run_int024_test"] = True
    try:
        orch.render_final("run_int024_test", force_placeholder_on_failed=True)
        check("S5 doble render → RENDER_BUSY", False)
    except po.PipelineError as e:
        check("S5 doble render → RENDER_BUSY", e.code == "RENDER_BUSY")
    # gate: retry-scenes bloqueado mientras renderiza
    try:
        await orch.retry_scenes("run_int024_test")
        check("S5 retry-scenes durante render → RENDER_BUSY", False)
    except po.PipelineError as e:
        check("S5 retry-scenes durante render → RENDER_BUSY", e.code == "RENDER_BUSY")
    orch._render_busy.pop("run_int024_test")
    # gate: corrida inexistente
    try:
        orch.render_final("run_que_no_existe")
        check("S5 render de corrida inexistente → RUN_NOT_FOUND", False)
    except po.PipelineError as e:
        check("S5 render de corrida inexistente → RUN_NOT_FOUND", e.code == "RUN_NOT_FOUND")

    # dry-run completo vía render_final (hilo, NO bloquea el event loop)
    render = orch.render_final("run_int024_test",
                               force_placeholder_on_failed=True, dry_run=True)
    check("S5 render_final devuelve estado running inmediato",
          render["status"] == "running" and render["dry_run"] is True)
    await orch.wait("render:run_int024_test", timeout=30)
    await asyncio.sleep(0.05)
    run = orch._load("run_int024_test")
    rr = run["render"]
    check("S5 worker en hilo termina done (dry-run)", rr["status"] == "done",
          json.dumps(rr, ensure_ascii=False)[:200])
    check("S5 estado del run vuelve a ST_DONE tras el render",
          run["stage"] == po.ST_DONE)
    check("S5 step [4/4] ok con detalle del plan",
          any(st["stage"] == "stage4_render" and st["state"] == "ok"
              for st in run["steps"]))
    check("S5 render_plan.json persistido por el worker",
          (rd / "render_plan.json").is_file())
    check("S5 manifest.json persistido por el worker (Stage 3.5)",
          (rd / "manifest.json").is_file())
    check("S5 single-flight liberado tras el render",
          not orch._render_busy.get("run_int024_test"))
    check("S5 get_render_status refleja done + failed_scene_ids",
          (lambda st: st["render"]["status"] == "done"
           and st["failed_scene_ids"] == ["s3"])(orch.get_render_status("run_int024_test")))
    # re-render permitido al terminar
    orch.render_final("run_int024_test", force_placeholder_on_failed=True,
                      dry_run=True)
    await orch.wait("render:run_int024_test", timeout=30)
    await asyncio.sleep(0.05)
    check("S5 re-render permitido al terminar el anterior",
          orch._load("run_int024_test")["render"]["status"] == "done")
    # get_manifest
    m = orch.get_manifest("run_int024_test")
    check("S5 get_manifest valida y devuelve el schema estricto",
          m.get("schema") == "albra.manifest/1")
    # harvest_only standalone
    m2 = orch.harvest_only("run_int024_test", placeholders_for_failed=True)
    check("S5 harvest_only regenera manifest sin renderizar",
          m2["run_id"] == "run_int024_test" and len(m2["scenes"]) == 3)


# ═════════════════════════════ S6 · ENDPOINTS ASGI ═══════════════════════
async def s6_endpoints(tmp: Path):
    print("\n── S6 · Endpoints REST del panel (ASGI in-process) ──")
    import httpx
    import main as _main

    orig_dir = po.orchestrator.runs_dir
    orig_busy = po.orchestrator._busy
    orig_rbusy = dict(po.orchestrator._render_busy)
    po.orchestrator.runs_dir = tmp / "runs_api"
    po.orchestrator._busy = None
    po.orchestrator._render_busy = {}
    rd = tmp / "runs_api" / "run_int024_api"
    rd.mkdir(parents=True, exist_ok=True)
    seed_assets(rd)
    run = fake_run(rd)
    run["run_id"] = "run_int024_api"
    po.orchestrator._save(run)
    H = {"Origin": "http://testserver"}
    try:
        async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_main.app),
                base_url="http://testserver") as c:
            r = await c.post("/api/pipeline/harvest", json={"run_id": "run_int024_api"},
                             headers=H)
            check("S6 POST /harvest → 200 con manifest estricto",
                  r.status_code == 200 and r.json().get("schema") == "albra.manifest/1",
                  r.text[:160])
            r = await c.get("/api/pipeline/manifest?run_id=run_int024_api", headers=H)
            check("S6 GET /manifest → 200 y 3 escenas",
                  r.status_code == 200 and len(r.json().get("scenes", [])) == 3)
            r = await c.post("/api/pipeline/render",
                             json={"run_id": "run_int024_api"},
                             headers=H)
            check("S6 POST /render sin flag con fallidas → 400 RENDER_BLOCKED…",
                  r.status_code == 400 and "RENDER_BLOCKED_PARTIAL_FAILURES" in r.text,
                  r.text[:160])
            r = await c.post("/api/pipeline/render",
                             json={"run_id": "run_int024_api",
                                   "force_placeholder_on_failed": True,
                                   "dry_run": True},
                             headers=H)
            check("S6 POST /render (force + dry_run) → 200 running",
                  r.status_code == 200 and
                  r.json()["render"]["status"] in ("running", "done"),
                  r.text[:200])
            # polling hasta done (hilo del worker)
            done = False
            for _ in range(100):
                await asyncio.sleep(0.1)
                r = await c.get("/api/pipeline/render/status?run_id=run_int024_api",
                                headers=H)
                if r.json().get("render", {}).get("status") == "done":
                    done = True
                    break
            check("S6 GET /render/status → done tras polling", done)
            r = await c.get("/api/pipeline/render/file?run_id=run_int024_api",
                            headers=H)
            check("S6 GET /render/file en dry-run → 404 RENDER_NO_OUTPUT",
                  r.status_code == 404 and "RENDER_NO_OUTPUT" in r.text)
            r = await c.get("/api/pipeline/render/status?run_id=fantasma_404",
                            headers=H)
            check("S6 status de corrida fantasma → 404 RUN_NOT_FOUND",
                  r.status_code == 404 and "RUN_NOT_FOUND" in r.text)
            r = await c.post("/api/pipeline/render",
                             json={"run_id": "fantasma_404"}, headers=H)
            check("S6 render de fantasma → 404", r.status_code == 404)
            r = await c.get("/api/pipeline/manifest?run_id=fantasma_404", headers=H)
            check("S6 manifest de fantasma → 404", r.status_code == 404)
    finally:
        po.orchestrator.runs_dir = orig_dir
        po.orchestrator._busy = orig_busy
        po.orchestrator._render_busy = orig_rbusy


# ═════════════════════════════ S7 · RENDER REAL DE HUMO ══════════════════
def s7_real_render(tmp: Path):
    print("\n── S7 · Render REAL de humo (micro-escenas, ffmpeg local) ──")
    if not HAS_FFMPEG:
        check("S7 ffmpeg ausente → batería degrada honesta (dry-run cubierto en S4)",
              True)
        return
    ver = vasm.ffmpeg_version()
    check("S7 ffmpeg detectado", bool(ver), str(ver))
    # render MINÚSCULO y rápido: suelo de escena 0.7s vía config dinámica
    # (las funciones leen config en tiempo de llamada → hermético y veloz)
    orig_min = config.RENDER_MIN_SCENE_SEC
    try:
        config.RENDER_MIN_SCENE_SEC = 0.7
        rd = tmp / "smoke"
        seed_assets(rd)
        run = fake_run(rd)
        for sc in run["scenes"]:        # sin narración → duración = suelo (0.7s)
            sc["narration"] = ""
        run["scenes"][0]["narration"] = "x"  # s1 usa su WAV real de 0.5s
        manifest, _ = harv.harvest_run(run, rd, placeholders_for_failed=True)
        _tiny_wav(rd / "narration" / "scene_001.wav", 0.5)
        manifest["scenes"][0]["narration_audio_path"] = "narration/scene_001.wav"
        harv.write_manifest(rd, manifest)
        subs = "burn" if vasm.has_filter("subtitles") else "soft"
        res = vasm.assemble_run(rd, dry_run=False, subtitles=subs)
        final = Path(res["output"])
        check("S7 final_render.mp4 generado", final.is_file() and
              final.stat().st_size > 1000)
        dur = vasm._probe_media(final)
        total = sum(s["duration_sec"] for s in manifest["scenes"])
        check("S7 duración del MP4 ≈ suma del manifest (±0.6s)",
              dur is not None and abs(dur - total) < 0.6, f"{dur} vs {total}")
        check("S7 .srt generado junto al render",
              (rd / "final_captions.srt").is_file())
        check("S7 norm/ con 3 escenas normalizadas",
              len(list((rd / "norm").glob("scene_*.mp4"))) == 3)
        check("S7 subs aplicados en el modo declarado",
              res.get("subtitles") == subs)
        # sin manifest → error estable (no ffmpeg). assemble_run deja escapar
        # HarvesterError (contrato del manifest) — el worker lo surfaced igual.
        empty = tmp / "sin_manifest"
        empty.mkdir(parents=True, exist_ok=True)
        try:
            vasm.assemble_run(empty, dry_run=False)
            check("S7 assemble sin manifest → HARVEST_NO_MANIFEST", False)
        except (harv.HarvesterError, vasm.AssemblerError) as e:
            check("S7 assemble sin manifest → HARVEST_NO_MANIFEST",
                  e.code == "HARVEST_NO_MANIFEST")
    finally:
        config.RENDER_MIN_SCENE_SEC = orig_min


# ─────────────────────────────────── main ────────────────────────────────
def main() -> int:
    print("=" * 60)
    print("BATERÍA INT-024 · Asset Harvester & FFmpeg Video Assembler")
    print("=" * 60)
    with tempfile.TemporaryDirectory(prefix="int024_") as td:
        tmp = Path(td)
        s1_harvester(tmp / "s1")
        s2_duration_math(tmp / "s2")
        s3_captions(tmp / "s3")
        s4_ffmpeg_construction(tmp / "s4")
        asyncio.run(s5_orchestrator(tmp / "s5"))
        asyncio.run(s6_endpoints(tmp / "s6"))
        s7_real_render(tmp / "s7")
    print("\n" + "=" * 60)
    print(f"RESULTADO: {OK} OK · {FAIL} fallos")
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
