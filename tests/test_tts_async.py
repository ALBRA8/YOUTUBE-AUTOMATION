"""
AUDITORÍA MULTI-FUENTE 2026-11 — ffmpeg/ffprobe asíncronos en TTS (regresión).

Antes, synth_gemini/synth_edge (corrutinas) llamaban subprocess.run síncrono:
CADA conversión mp3→wav y CADA probe de duración congelaba TODO el servidor
(health, dashboard, jobs) durante segundos. Ahora las rutas async van por
asyncio.create_subprocess_exec con timeout que MATA el proceso colgado
(conserva INT-080) y el pipeline (tts_step) usa probe_duration_async.

Los tests de binario falso inyectan ejecutables python en PATH (hermético,
sin ffmpeg real salvo donde se marca); en Windows se omiten (shebang).
"""
import asyncio
import os
import sys
import time
import types
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import shutil  # noqa: E402

HAS_FFPROBE = bool(shutil.which("ffprobe"))
HAS_FFMPEG = bool(shutil.which("ffmpeg"))

import services.tts_service as tts  # noqa: E402


def _mk_fakebin(tmp_path: Path, name: str, code: str) -> Path:
    """Crea un ejecutable python con shebang en un dir falso de PATH."""
    fakebin = tmp_path / f"fakebin_{name}"
    fakebin.mkdir(exist_ok=True)
    exe = fakebin / name
    exe.write_text(f"#!/usr/bin/env python3\n{code}\n", encoding="utf-8")
    exe.chmod(0o755)
    return fakebin


def _prepend_path(monkeypatch, fakebin: Path) -> None:
    monkeypatch.setenv("PATH", f"{fakebin}{os.pathsep}{os.environ.get('PATH', '')}")


# ── 1 · roundtrip REAL con ffprobe del sistema ─────────────────────────────
@pytest.mark.skipif(not HAS_FFPROBE, reason="ffprobe no disponible")
async def test_wav_duration_async_roundtrip_real(tmp_path):
    wav = tmp_path / "real.wav"
    tts.silence_wav(wav, 1.5)
    dur = await tts.wav_duration_async(wav)
    assert abs(dur - 1.5) < 0.25


@pytest.mark.skipif(not HAS_FFPROBE, reason="ffprobe no disponible")
async def test_probe_duration_async_real_y_clemencia(tmp_path):
    wav = tmp_path / "real.wav"
    tts.silence_wav(wav, 1.0)
    assert abs(await tts.probe_duration_async(wav) - 1.0) < 0.25
    assert await tts.probe_duration_async(tmp_path / "noexiste.wav") == 0.0


def test_wav_duration_sync_sigue_viva(tmp_path):
    """Compat: la variante síncrona se conserva para código no-async."""
    wav = tmp_path / "real.wav"
    tts.silence_wav(wav, 1.0)
    if HAS_FFPROBE:
        assert abs(tts.wav_duration(wav) - 1.0) < 0.25
    else:
        assert tts.probe_duration(wav) == 0.0


# ── 2 · loop vivo + timeout con ffprobe falso ──────────────────────────────
@pytest.mark.skipif(sys.platform == "win32", reason="fakes con shebang (POSIX)")
async def test_event_loop_sigue_vivo_durante_probe_lento(tmp_path, monkeypatch):
    fakebin = _mk_fakebin(tmp_path, "ffprobe",
                          "import time; time.sleep(0.3); print('2.5')")
    _prepend_path(monkeypatch, fakebin)
    wav = tmp_path / "x.wav"
    tts.silence_wav(wav, 2.5)
    ticks = 0

    async def ticker():
        nonlocal ticks
        for _ in range(50):
            await asyncio.sleep(0.02)
            ticks += 1

    task = asyncio.create_task(ticker())
    dur = await tts.wav_duration_async(wav, timeout=10)
    await task
    assert abs(dur - 2.5) < 0.01
    assert ticks >= 10  # el loop despachó latidos durante el probe (no bloqueó)


@pytest.mark.skipif(sys.platform == "win32", reason="fakes con shebang (POSIX)")
async def test_ffprobe_colgado_se_mata_con_timeout(tmp_path, monkeypatch):
    fakebin = _mk_fakebin(tmp_path, "ffprobe",
                          "import time; time.sleep(30); print('0')")
    _prepend_path(monkeypatch, fakebin)
    wav = tmp_path / "colgado.wav"
    tts.silence_wav(wav, 1.0)
    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        await tts.wav_duration_async(wav, timeout=0.4)
    assert time.monotonic() - t0 < 5  # el timeout mató al proceso (no esperó 30 s)


# ── 3 · ffmpeg asíncrono: éxito y fallo ────────────────────────────────────
@pytest.mark.skipif(sys.platform == "win32", reason="fakes con shebang (POSIX)")
async def test_mp3_to_wav_async_fallo_runtime(tmp_path, monkeypatch):
    fakebin = _mk_fakebin(tmp_path, "ffmpeg",
                          "import sys; sys.stderr.write('boom X123'); sys.exit(1)")
    _prepend_path(monkeypatch, fakebin)
    with pytest.raises(RuntimeError, match="falló"):
        await tts._mp3_to_wav_async(tmp_path / "a.mp3", tmp_path / "a.wav")


@pytest.mark.skipif(sys.platform == "win32", reason="fakes con shebang (POSIX)")
async def test_mp3_to_wav_async_exito(tmp_path, monkeypatch):
    # fake que "convierte": crea el dst (último argumento)
    fakebin = _mk_fakebin(tmp_path, "ffmpeg",
                          "import sys, pathlib; pathlib.Path(sys.argv[-1]).write_bytes(b'RIFF')")
    _prepend_path(monkeypatch, fakebin)
    dst = tmp_path / "a.wav"
    await tts._mp3_to_wav_async(tmp_path / "a.mp3", dst)
    assert dst.exists() and dst.read_bytes() == b"RIFF"


# ── 4 · guardia de regresión: las corrutinas NO tocan el subprocess síncrono ─
async def test_synth_gemini_usa_ruta_async(tmp_path, monkeypatch):
    async def fake_pcm(text, voice):
        return b"RIFFfake"

    async def fake_probe(path, timeout=30.0):
        return 3.2

    monkeypatch.setattr(tts.gemini_client, "tts_pcm", fake_pcm)
    monkeypatch.setattr(tts, "wav_duration_async", fake_probe)

    def _bloqueo(*a, **k):
        raise AssertionError("synth_gemini llamó al probe SÍNCRONO (bloquea el loop)")

    monkeypatch.setattr(tts, "wav_duration", _bloqueo)
    out = tmp_path / "s.wav"
    dur = await tts.synth_gemini("hola", out)
    assert dur == 3.2 and out.exists()


async def test_synth_edge_usa_ruta_async(tmp_path, monkeypatch):
    class _FakeCommunicate:
        def __init__(self, text, voice, rate=None):
            pass

        async def save(self, path):
            Path(path).write_bytes(b"mp3fake")

    monkeypatch.setitem(sys.modules, "edge_tts",
                        types.SimpleNamespace(Communicate=_FakeCommunicate))

    async def fake_conv(src, dst):
        return None

    async def fake_probe(path, timeout=30.0):
        return 4.4

    monkeypatch.setattr(tts, "_mp3_to_wav_async", fake_conv)
    monkeypatch.setattr(tts, "wav_duration_async", fake_probe)

    def _bloqueo(*a, **k):
        raise AssertionError("synth_edge llamó a una conversión SÍNCRONA")

    monkeypatch.setattr(tts, "_mp3_to_wav", _bloqueo)
    monkeypatch.setattr(tts, "wav_duration", _bloqueo)
    out = tmp_path / "e.wav"
    dur = await tts.synth_edge("hola", out)
    assert dur == 4.4
    assert not out.with_suffix(".mp3").exists()  # el mp3 intermedio se borra
