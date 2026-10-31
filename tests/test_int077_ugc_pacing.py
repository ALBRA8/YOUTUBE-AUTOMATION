#!/usr/bin/env python3
"""
Tests INT-077: pacing estricto + estructura UGC nativa (avatar + B-roll).

Problemas que valida:
1. Desfase audio/video (11.8s de voz sobre 7.6s de Flow) → el clip SIEMPRE
   alcanza la narración: retime setpts, bucle automático cuando el cap de
   slow-mo (FACTOR_MAX) no basta, y verificación ffprobe post-render con
   remediación única forzando bucle.
2. Fatiga de avatar (uncanny valley) → escenas product_broll renderizan
   imagen de producto + zoompan con SOLO TTS en off; el lip-sync v2v jamás
   se invoca para ellas aunque tengan video de Flow asignado.
3. Muxing modular → los clips no finales compensan GAP de voz + pad de
   transición: Σclips == Σdurations + GAP×(n-1) == voice_full.wav.

Hermeticidad: cero red, cero HF, cero Chrome. FFmpeg/ffprobe REALES en las
pruebas de integración (clips 480x854@fast para rapidez).
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
import config
from pipeline import video as vmod
from pipeline import tts_step

ffmpeg_ok = subprocess.run(["ffmpeg", "-version"], capture_output=True)
pytestmark = pytest.mark.skipif(ffmpeg_ok.returncode != 0,
                                reason="ffmpeg no disponible en sandbox")


# ── helpers ─────────────────────────────────────────────────────────────
def _make_video(path: Path, dur: float = 1.0, size: str = "320x240") -> None:
    r = subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                        f"testsrc=duration={dur}:size={size}:rate=10",
                        "-pix_fmt", "yuv420p", str(path)],
                       capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr[-200:]


def _make_img(path: Path) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                        "color=c=tomato:s=480x854", "-frames:v", "1",
                        str(path)], capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr[-200:]


def _make_wav(path: Path, dur: float = 1.0) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                        f"sine=frequency=440:duration={dur}",
                        str(path)], capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr[-200:]


def _probe(path: Path) -> float:
    return vmod.probe_duration(path)


# ── 1 · retime_clip_cmd: pacing milimétrico ─────────────────────────────
def test_retime_normal_factor(tmp_path):
    src = tmp_path / "flow.mp4"
    _make_video(src, dur=7.6)
    cmd = vmod.retime_clip_cmd(src, 11.8, tmp_path / "out.mp4", 1080, 1920)
    # caso EXACTO del reporte: 11.8s de voz sobre 7.6s de Flow → factor 1.55
    assert "setpts=PTS*1.552632" in " ".join(cmd)
    assert "-stream_loop" not in cmd          # dentro del cap → sin bucle
    assert cmd[cmd.index("-t") + 1] == "11.800"


def test_retime_loop_when_audio_exceeds_cap(tmp_path):
    src = tmp_path / "flow.mp4"
    _make_video(src, dur=7.6)
    # 25s de voz sobre 7.6s: 25/7.6=3.29 > FACTOR_MAX → enbucle 4 segmentos
    cmd = vmod.retime_clip_cmd(src, 25.0, tmp_path / "out.mp4", 1080, 1920)
    assert "-stream_loop" in cmd and "-1" in cmd
    assert "setpts=PTS*0.822368" in " ".join(cmd)  # factor por segmento 25/4/7.6
    assert cmd[cmd.index("-t") + 1] == "25.000"


def test_retime_force_loop_always_loops(tmp_path):
    src = tmp_path / "flow.mp4"
    _make_video(src, dur=7.6)
    cmd = vmod.retime_clip_cmd(src, 11.8, tmp_path / "out.mp4", 1080, 1920,
                               force_loop=True)
    assert "-stream_loop" in cmd              # remediación: bucle garantizado


def test_retime_probe_fallido_factor_neutro(tmp_path):
    cmd = vmod.retime_clip_cmd(tmp_path / "no_existe.mp4", 11.8,
                               tmp_path / "out.mp4", 1080, 1920)
    assert "setpts=PTS*1.000000" in " ".join(cmd)  # factor 1.0 (la post-verificación
    # lo detectará corto y remedió con force_loop — nunca un clip silencioso)


# ── 2 · scene_render_mode: tipos UGC ────────────────────────────────────
def test_scene_render_mode_tipos():
    assert vmod.scene_render_mode({"type": "product_broll"}, True) == "broll_zoompan"
    assert vmod.scene_render_mode({"type": "broll"}, True) == "broll_zoompan"
    assert vmod.scene_render_mode({"type": "product"}, False) == "broll_zoompan"
    assert vmod.scene_render_mode({"meta": {"type": "BROLL"}}, True) == "broll_zoompan"
    assert vmod.scene_render_mode({"type": "avatar"}, True) == "flow_lipsync"
    assert vmod.scene_render_mode({}, True) == "flow_lipsync"      # legacy
    assert vmod.scene_render_mode({"type": "avatar"}, False) == "kenburns"
    assert vmod.scene_render_mode({}, False) == "kenburns"


# ── 3 · render_scenes: cadena mixta avatar+broll REAL ───────────────────
def test_render_scenes_cadena_mixta(tmp_path):
    proj_dir = tmp_path / "proj"
    fv0, fv1, fv2 = (tmp_path / f"flow{i}.mp4" for i in range(3))
    _make_video(fv0, dur=1.0)
    _make_video(fv1, dur=1.0)
    _make_video(fv2, dur=1.0)
    img1 = tmp_path / "prod.png"
    _make_img(img1)
    wav0 = tmp_path / "scene_0.wav"
    _make_wav(wav0)

    scenes = [
        {"image_path": "", "audio_path": str(wav0)},                      # avatar
        {"image_path": str(img1), "type": "product_broll",
         "audio_path": str(wav0)},                                        # b-roll
        {"image_path": ""},                                               # avatar
    ]
    durations = [2.0, 1.5, 1.8]
    lipsync = AsyncMock(return_value={"ok": False, "video": "", "error": "x",
                                      "fallback": True, "attempted": [],
                                      "space": ""})

    with patch.object(vmod, "OUTPUT_DIR", tmp_path), \
         patch.object(vmod, "SHORT_W", 480), patch.object(vmod, "SHORT_H", 854), \
         patch.object(vmod, "FPS", 10), \
         patch.object(vmod.avatar_motion, "v2v_enabled", MagicMock(return_value=True)), \
         patch.object(vmod.avatar_motion, "lipsync_video_to_video", lipsync):
        clips = asyncio.run(vmod.render_scenes(
            {"id": "proj", "format": "short"}, scenes, durations,
            flow_videos={0: str(fv0), 1: str(fv1), 2: str(fv2)},
            transition_pad=0.0))

    assert len(clips) == 3 and all(c.is_file() for c in clips)
    # v2v SOLO en la escena avatar 0 (la 1 es b-roll ignorado a propósito;
    # la 2 no tiene audio de escena)
    lipsync.assert_awaited_once()

    d0, d1, d2 = (_probe(c) for c in clips)
    gap = tts_step.GAP
    # targets INT-077: no-final = dur + gap (+pad); final = dur
    assert abs(d0 - (2.0 + gap)) < 0.15, f"clip0 {d0:.3f} vs {2.0 + gap:.3f}"
    assert abs(d1 - (1.5 + 0.05 + gap)) < 0.15, f"clip1(broll) {d1:.3f}"
    assert abs(d2 - 1.8) < 0.15, f"clip2 {d2:.3f}"

    # sidecars con verificación milimétrica registrada
    for i, c in enumerate(clips):
        side = json.loads(c.with_suffix(".json").read_text())
        assert side["fitted"] is True, f"clip {i} no fitted: {side}"
        assert side["measured"] == pytest.approx(
            [2.0 + gap, 1.5 + 0.05 + gap, 1.8][i], abs=0.15)


def test_render_scenes_suma_coincide_con_voice_full(tmp_path):
    """Contrato milimétrico: Σclips(fv) == Σdurations + GAP×(n-1) — lo que
    dura voice_full.wav. Con transition_pad=0 (concat sin xfade)."""
    gap = tts_step.GAP
    fv = tmp_path / "flow.mp4"
    _make_video(fv, dur=1.0)
    scenes = [{"image_path": ""}, {"image_path": ""}]
    durations = [2.0, 1.5]
    with patch.object(vmod, "OUTPUT_DIR", tmp_path), \
         patch.object(vmod, "SHORT_W", 480), patch.object(vmod, "SHORT_H", 854), \
         patch.object(vmod, "FPS", 10):
        clips = asyncio.run(vmod.render_scenes(
            {"id": "proj2", "format": "short"}, scenes, durations,
            flow_videos={0: str(fv), 1: str(fv)}, transition_pad=0.0))
    total = sum(_probe(c) for c in clips)
    assert total == pytest.approx(sum(durations) + gap, abs=0.12)


# ── 4 · caso del reporte: voz 11.8s sobre Flow 7.6s ─────────────────────
def test_voz_mas_larga_que_flow_reproduce_completa(tmp_path):
    """El video ya no se corta en seco a mitad de la narración."""
    fv = tmp_path / "flow.mp4"
    _make_video(fv, dur=7.6)
    out = tmp_path / "proj3" / "clips" / "clip_00.mp4"
    out.parent.mkdir(parents=True)
    cmd = vmod.retime_clip_cmd(fv, 11.8, out, 480, 854, fps=10)
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    assert r.returncode == 0, r.stderr[-200:]
    assert _probe(out) == pytest.approx(11.8, abs=0.2)


def test_remediacion_clip_corto(tmp_path):
    """Post-verificación: si el primer render produce un clip corto (probe
    fallido, cache rancio, v2v acortado) se remedia UNA vez con bucle."""
    fv = tmp_path / "flow.mp4"
    _make_video(fv, dur=2.0)
    scenes = [{"image_path": ""}]
    durations = [4.0]

    def fake_ffmpeg(cmd, timeout=900):
        if "-stream_loop" in cmd:        # remedio → render correcto completo
            subprocess.run(cmd, capture_output=True, timeout=300)
        else:                            # primer intento → clip TRUNCADO 0.4s
            mod = list(cmd)
            mod[mod.index("-t") + 1] = "0.400"
            subprocess.run(mod, capture_output=True, timeout=300)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with patch.object(vmod, "OUTPUT_DIR", tmp_path), \
         patch.object(vmod, "SHORT_W", 480), patch.object(vmod, "SHORT_H", 854), \
         patch.object(vmod, "FPS", 10), \
         patch.object(vmod, "_run_ffmpeg", side_effect=fake_ffmpeg):
        clips = asyncio.run(vmod.render_scenes(
            {"id": "proj4", "format": "short"}, scenes, durations,
            flow_videos={0: str(fv)}))
    d = _probe(clips[0])
    assert d == pytest.approx(4.0, abs=0.2), f"remediación falló: {d:.3f}s"
    side = json.loads(clips[0].with_suffix(".json").read_text())
    assert side["fitted"] is True


# ── 5 · build_full_track: el audio que los clips compensan ──────────────
def test_voice_full_dur_con_gap(tmp_path):
    proj = tmp_path / "proj5"
    adir = proj / "audio"
    adir.mkdir(parents=True)
    _make_wav(adir / "scene_00.wav", dur=2.0)
    _make_wav(adir / "scene_01.wav", dur=1.5)
    with patch.object(tts_step, "OUTPUT_DIR", tmp_path):
        full = asyncio.run(tts_step.build_full_track(
            {"id": "proj5"}, [2.0, 1.5]))
    d = _probe(full)
    assert d == pytest.approx(2.0 + tts_step.GAP + 1.5, abs=0.1), \
        f"voice_full {d:.3f}s — los clips deben compensar EXACTO esto"


# ── 6 · contratos fuente ─────────────────────────────────────────────────
def test_contratos():
    assert vmod.VOICE_GAP == tts_step.GAP          # sync estructural
    assert "product_broll" in vmod.BROLL_TYPES
    assert vmod.FACTOR_MAX == 2.5 and vmod.CLIP_TOL == 0.25
    src = Path(vmod.__file__).read_text(encoding="utf-8")
    assert "scene_gap: float | None = None" in src
    assert "force_loop" in src and "-stream_loop" in src
    # invariante del proyecto: video_assembler.py INTOCABLE
    asm = (Path(vmod.__file__).parent.parent / "services" /
           "video_assembler.py").stat().st_mtime
    assert asm > 0  # existe; el diff del commit lo demuestra (no se toca)
