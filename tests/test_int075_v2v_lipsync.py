"""
Tests INT-075: lip-sync VIDEO-to-VIDEO del video base de Google Flow.
- _to_wav_mono16k: FFmpeg real → WAV mono 16 kHz (evita 'RIFF id')
- lipsync_video_to_video: cadena AVATAR_V2V_SPACES con failover, timeout por
  intento (asyncio.wait_for + to_thread) y FAIL-OPEN (copia el video original,
  el render nunca se rompe)
- Integración pipeline: render_scenes (pipeline/video.py) encadena el v2v en la
  rama de videos de Flow ANTES del retime/masterizado 9:16; respetado el
  interruptor AVATAR_V2V_ENABLED y el fail-open
- video_assembler.py: INTOCABLE (invariante del proyecto)

Hermeticidad: cero red, cero HF, cero Chrome. FFmpeg real solo en la prueba
de conversión de audio (rápida); el retime del pipeline se mockea.
"""
import asyncio
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
import config
from services import avatar_motion as am

ffmpeg = pytest.importorskip("shutil")  # garantiza pytest saneo; ffmpeg se asume


# ── helpers de fixtures ─────────────────────────────────────────────────
def _make_wav_stereo(path: Path, dur: float = 1.0) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                        f"sine=frequency=440:duration={dur}:sample_rate=44100",
                        "-ac", "2", str(path)], capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr[-200:]


def _make_mp3(path: Path, dur: float = 1.0) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                        f"sine=frequency=330:duration={dur}",
                        "-c:a", "libmp3lame", "-b:a", "64k", str(path)],
                       capture_output=True, timeout=60)
    if r.returncode != 0:  # sandbox sin libmp3lame → fallback WAV (mismo flujo)
        _make_wav_stereo(path, dur)


def _make_video(path: Path, dur: float = 1.0) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                        f"testsrc=duration={dur}:size=320x240:rate=10",
                        "-pix_fmt", "yuv420p", str(path)],
                       capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr[-200:]


# ── 1 · _to_wav_mono16k (FFmpeg real) ───────────────────────────────────
def test_to_wav_mono16k_from_stereo_44100(tmp_path):
    src = tmp_path / "voice_stereo.wav"
    _make_wav_stereo(src)
    out = tmp_path / "voice16k.wav"
    am._to_wav_mono16k(src, out)
    assert out.is_file() and out.stat().st_size > 44
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate,channels", "-of", "csv=p=0",
         str(out)], capture_output=True, text=True, timeout=30)
    assert probe.stdout.strip().startswith("16000,1")


def test_to_wav_mono16k_from_mp3_tts(tmp_path):
    """El audio TTS llega en mp3/webm → la conversión evita el error RIFF."""
    src = tmp_path / "tts.mp3"
    _make_mp3(src)
    out = am._to_wav_mono16k(src, tmp_path / "tts16k.wav")
    assert out.is_file() and out.stat().st_size > 44


def test_to_wav_mono16k_bad_source_raises(tmp_path):
    bad = tmp_path / "garbage.mp3"
    bad.write_bytes(b"no-es-audio\r\n" * 20)
    with pytest.raises(RuntimeError, match="wav16k"):
        am._to_wav_mono16k(bad, tmp_path / "x.wav")


# ── 2 · lipsync_video_to_video: cadena, failover, fail-open, timeout ────
def test_spaces_default_chain_order():
    assert am.v2v_space_list() == ["ByteDance/LatentSync", "akhaliq/Wav2Lip",
                                   "fffiloni/video-retalking"]


def test_v2v_requires_existing_inputs(tmp_path):
    v = tmp_path / "base.mp4"
    _make_video(v)
    with pytest.raises(FileNotFoundError, match="Audio"):
        asyncio.run(am.lipsync_video_to_video(v, tmp_path / "no.wav",
                                              tmp_path / "out.mp4"))
    a = tmp_path / "a.wav"
    _make_wav_stereo(a)
    with pytest.raises(FileNotFoundError, match="Video"):
        asyncio.run(am.lipsync_video_to_video(tmp_path / "no.mp4", a,
                                              tmp_path / "out.mp4"))


def test_v2v_ok_first_space(tmp_path):
    v, a, out = tmp_path / "base.mp4", tmp_path / "voice.mp3", tmp_path / "out.mp4"
    _make_video(v)
    _make_mp3(a)
    with patch.object(am, "_call_hf_v2v_gradio",
                      side_effect=lambda sp, vp, ap, op: Path(shutil_copy(vp, op))):
        res = asyncio.run(am.lipsync_video_to_video(v, a, out, timeout_s=10))
    assert res["ok"] is True and res["fallback"] is False
    assert res["space"] == "ByteDance/LatentSync"
    assert res["attempted"] == ["ByteDance/LatentSync"]
    assert Path(res["video"]).is_file()
    assert not (tmp_path / "out_voice16k.wav").exists()  # temp WAV limpiado


def test_v2v_failover_to_second_space(tmp_path):
    v, a, out = tmp_path / "base.mp4", tmp_path / "voice.wav", tmp_path / "out.mp4"
    _make_video(v)
    _make_wav_stereo(a)
    calls = []

    def fake(space, vp, ap, op):
        calls.append(space)
        if space == "ByteDance/LatentSync":
            raise RuntimeError("401 gated sin token")
        return Path(shutil_copy(vp, op))

    with patch.object(am, "_call_hf_v2v_gradio", side_effect=fake):
        res = asyncio.run(am.lipsync_video_to_video(v, a, out, timeout_s=10))
    assert res["ok"] is True
    assert res["space"] == "akhaliq/Wav2Lip"
    assert res["attempted"] == ["ByteDance/LatentSync", "akhaliq/Wav2Lip"]


def test_v2v_failopen_copies_original_when_all_fail(tmp_path):
    v, a, out = tmp_path / "base.mp4", tmp_path / "voice.wav", tmp_path / "out.mp4"
    _make_video(v)
    _make_wav_stereo(a)
    original = v.read_bytes()
    with patch.object(am, "_call_hf_v2v_gradio",
                      side_effect=RuntimeError("Space caído")):
        res = asyncio.run(am.lipsync_video_to_video(v, a, out, timeout_s=5))
    assert res["ok"] is False and res["fallback"] is True
    assert res["attempted"] == ["ByteDance/LatentSync", "akhaliq/Wav2Lip",
                                "fffiloni/video-retalking"]
    assert Path(res["video"]).read_bytes() == original  # video original intacto
    assert "Space caído" in res["error"]


def test_v2v_timeout_per_attempt_does_not_block(tmp_path):
    """Cada intento respeta su timeout: 2 Spaces × 0.3 s ≈ 0.6 s, no 2×2 s."""
    v, a, out = tmp_path / "base.mp4", tmp_path / "voice.wav", tmp_path / "out.mp4"
    _make_video(v)
    _make_wav_stereo(a)

    def slow(space, vp, ap, op):
        time.sleep(2.0)
        return Path(shutil_copy(vp, op))

    t0 = time.monotonic()
    with patch.object(am, "_call_hf_v2v_gradio", side_effect=slow):
        res = asyncio.run(am.lipsync_video_to_video(v, a, out, timeout_s=0.3))
    elapsed = time.monotonic() - t0
    assert res["ok"] is False and res["fallback"] is True
    assert len(res["attempted"]) == 3
    assert elapsed < 6.0  # sin wait_for habría sido ≥ 6 s (3 × 2 s)


def test_v2v_disabled_immediate_failopen(tmp_path):
    v, a, out = tmp_path / "base.mp4", tmp_path / "voice.wav", tmp_path / "out.mp4"
    _make_video(v)
    _make_wav_stereo(a)
    original = v.read_bytes()
    with patch.object(config, "AVATAR_V2V_ENABLED", False), \
         patch.object(am, "_call_hf_v2v_gradio") as never:
        res = asyncio.run(am.lipsync_video_to_video(v, a, out))
    assert res["ok"] is False and res["fallback"] is True
    assert res["attempted"] == []
    never.assert_not_called()
    assert Path(res["video"]).read_bytes() == original


# ── 3 · Integración pipeline: render_scenes encadena el v2v ────────────
def _run_render(tmp_path, v2v_result, enabled=True, with_audio=True):
    from pipeline import video as vmod

    fv = tmp_path / "flow_base.mp4"
    _make_video(fv, dur=1.0)
    scene = {"image_path": "", "title": "s1"}
    if with_audio:
        wav = tmp_path / "scene_1.wav"
        _make_wav_stereo(wav)
        scene["audio_path"] = str(wav)

    proj_dir = tmp_path / "proj"
    fake_clip = proj_dir / "clips" / "clip_00.mp4"
    fake_clip.parent.mkdir(parents=True, exist_ok=True)
    _make_video(fake_clip, dur=0.5)

    cmds = []

    def fake_ffmpeg(cmd, timeout=900):
        cmds.append(cmd)
        import subprocess as sp
        return sp.CompletedProcess(cmd, 0, "", "")

    lipsync_mock = AsyncMock(return_value=v2v_result)
    with patch.object(vmod, "OUTPUT_DIR", tmp_path), \
         patch.object(vmod, "_run_ffmpeg", side_effect=fake_ffmpeg), \
         patch.object(am, "v2v_enabled", MagicMock(return_value=enabled)), \
         patch.object(am, "lipsync_video_to_video", lipsync_mock):
        clips = asyncio.run(vmod.render_scenes(
            {"id": "proj", "format": "short"},
            [scene], [1.5], flow_videos={0: str(fv)}))
    return clips, cmds, lipsync_mock, fv


def test_render_scenes_uses_lipsynced_source(tmp_path):
    ok_video = tmp_path / "lipsync_ready.mp4"
    _make_video(ok_video, dur=1.0)
    res = {"ok": True, "video": str(ok_video), "space": "ByteDance/LatentSync",
           "fallback": False, "attempted": ["ByteDance/LatentSync"], "error": ""}
    clips, cmds, mock, fv = _run_render(tmp_path, res)
    assert clips and clips[0].is_file()
    mock.assert_awaited_once()
    args = mock.await_args[0]
    assert Path(args[0]) == fv                       # video base de Flow
    assert args[1].name.startswith("scene_1")        # audio TTS de la escena
    assert Path(args[2]).name == "lipsync_00.mp4"    # salida intermedia
    assert str(ok_video) in cmds[0]                  # el retime usa el v2v OK


def test_render_scenes_falls_back_to_original_when_v2v_fails(tmp_path):
    fv = tmp_path / "flow_base.mp4"
    res = {"ok": False, "video": str(fv), "space": "",
           "fallback": True, "attempted": ["ByteDance/LatentSync"],
           "error": "401 gated"}
    clips, cmds, mock, fv = _run_render(tmp_path, res)
    assert clips and clips[0].is_file()
    mock.assert_awaited_once()
    assert str(fv) in cmds[0]                        # retime sobre el ORIGINAL


def test_render_scenes_skips_v2v_when_disabled(tmp_path):
    clips, cmds, mock, fv = _run_render(tmp_path, None, enabled=False)
    assert clips and clips[0].is_file()
    mock.assert_not_awaited()
    assert str(fv) in cmds[0]


def test_render_scenes_skips_v2v_without_scene_audio(tmp_path):
    clips, cmds, mock, fv = _run_render(tmp_path, None, with_audio=False)
    assert clips and clips[0].is_file()
    mock.assert_not_awaited()
    assert str(fv) in cmds[0]


def shutil_copy(src, dst):
    import shutil
    shutil.copy(src, dst)
    return dst
