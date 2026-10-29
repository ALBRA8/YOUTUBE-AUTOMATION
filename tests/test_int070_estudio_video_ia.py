#!/usr/bin/env python3
"""
BATERÍA DE TESTS — INT-070 · Adopción quirúrgica de estudio-video-ia

Cubre las 4 piezas absorbidas (herméticas, cero red, cero modelos):
  S1 · whisper_realign: realineación de timestamps Whisper contra pausas reales
       (anclaje a huecos + premio de puntuación + reparto por peso de palabra),
       compat de claves ALBRA/estudio, gate WHISPER_REALIGN, fail-open, hook
       en align_scene.
  S2 · video_retimer: cadena atempo (0.5-2.0 por paso), parse/normalización de
       anclas (fail-closed RETIME_ANCHORS_INVALID), velocidades por tramo,
       filtergraph (minterpolate solo en cámara lenta) y retime_video con
       ffmpeg/ffprobe falseados.
  S3 · accent_meter: Δ espectral 4-10 kHz sobre WAV sintéticos (tonos con
       envolvente) → distinción (España) / seseo / audio inservible (None).
  S4 · mezcla opt-in: sidechaincompress (ducking dinámico) y loudnorm -14 LUFS
       en build_mix_cmd; OFF por defecto = filtergraph golden idéntico.
"""
from __future__ import annotations

import asyncio
import math
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import config  # noqa: E402
from services import accent_meter, video_retimer, whisper_realign  # noqa: E402
from services import whisper_service as ws  # noqa: E402
from services import video_assembler  # noqa: E402


# ── S1 · whisper_realign ─────────────────────────────────────────────────────
def _words_drift():
    """Palabras Whisper con el desfase típico junto a pausas (end=1.0 vs
    pausa real 1.02-1.25)."""
    return [
        {"word": "Hola", "start": 0.0, "end": 0.5},
        {"word": "mundo.", "start": 0.5, "end": 1.0},
        {"word": "Segunda", "start": 1.0, "end": 1.5},
        {"word": "frase", "start": 1.5, "end": 2.0},
    ]


def test_realign_anchors_real_pause_with_punctuation_prize():
    out = whisper_realign.realign_words(_words_drift(), [(1.02, 1.25)], 2.0)
    # la pausa real (1.02-1.25) se ancla al hueco tras "mundo." (premio de
    # puntuación vence aunque el hueco tras "Segunda" esté a la misma distancia)
    assert out[1]["end"] == pytest.approx(1.02, abs=1e-3)
    assert out[2]["start"] == pytest.approx(1.25, abs=1e-3)
    # tramo 1 repartido por peso entre 0 y la pausa; inicio anclado
    assert out[0]["start"] == pytest.approx(0.0, abs=1e-3)
    # contigüidad: el fin de cada palabra ES el inicio de la siguiente
    assert out[0]["end"] == pytest.approx(out[1]["start"], abs=1e-3)
    assert out[2]["end"] == pytest.approx(out[3]["start"], abs=1e-3)


def test_realign_weights_digits_speak_longer():
    words = [{"word": "a", "start": 0.0, "end": 0.5},
             {"word": "123456", "start": 0.5, "end": 1.0}]
    out = whisper_realign.realign_words(words, [], 1.0)
    # "a" pesa 2.5, "123456" pesa 36.5 → "a" apenas recibe tiempo del tramo
    assert out[0]["end"] == pytest.approx(1.0 * 2.5 / 39.0, abs=1e-3)
    assert out[1]["end"] == pytest.approx(1.0, abs=1e-3)


def test_realign_requires_two_words_and_normalizes_keys():
    single = [{"word": "solo", "start": 0.1, "end": 0.9}]
    assert whisper_realign.realign_words(single, [(0.2, 0.4)], 1.0) == single
    # compat estudio-video-ia: claves w/ini/fin → salida ALBRA start/end
    estudio = [{"w": "Hola", "ini": 0.0, "fin": 0.5},
               {"w": "mundo.", "ini": 0.5, "fin": 1.0}]
    out = whisper_realign.realign_words(estudio, [], 1.0)
    assert set(out[0]) >= {"word", "start", "end"}


def test_maybe_realign_gate_off_and_fail_open(monkeypatch, tmp_path):
    raw = _words_drift()
    monkeypatch.setattr(config, "WHISPER_REALIGN", "0")
    assert whisper_realign.maybe_realign(raw, tmp_path / "a.wav", 2.0) == raw
    monkeypatch.setattr(config, "WHISPER_REALIGN", "1")

    def boom(_):
        raise RuntimeError("ffmpeg desapareció")
    monkeypatch.setattr(whisper_realign, "detect_silences", boom)
    assert whisper_realign.maybe_realign(_words_drift(), tmp_path / "a.wav",
                                         2.0) == _words_drift()


@pytest.mark.asyncio
async def test_align_scene_hook_realigns(monkeypatch):
    async def fake_transcribe(path):
        return _words_drift()
    monkeypatch.setattr(ws, "transcribe_words", fake_transcribe)
    monkeypatch.setattr(whisper_realign, "detect_silences", lambda p: [(1.02, 1.25)])
    out = await ws.align_scene("x", "audio.wav", 2.0)
    assert out[1]["end"] == pytest.approx(1.02, abs=1e-3)     # realineado
    monkeypatch.setattr(config, "WHISPER_REALIGN", "0")
    out_raw = await ws.align_scene("x", "audio.wav", 2.0)
    assert out_raw == _words_drift()                          # crudo (gate off)


# ── S2 · video_retimer ───────────────────────────────────────────────────────
def test_chain_atempo_encadena_fuera_de_rango():
    assert video_retimer.chain_atempo(4.0) == [2.0, 2.0]
    assert video_retimer.chain_atempo(0.25) == [0.5, 0.5]
    assert video_retimer.chain_atempo(1.5) == [1.5]
    with pytest.raises(ValueError):
        video_retimer.chain_atempo(0.0)


def test_parse_and_normalize_anchors():
    assert video_retimer.parse_anchors("1.5=2.0, 3=3.5") == [(1.5, 2.0), (3.0, 3.5)]
    assert video_retimer.parse_anchors([(1.0, 1.0)]) == [(1.0, 1.0)]
    anclas = video_retimer.normalize_anchors([(2.0, 2.5)], 10.0, 10.5)
    assert anclas == [(0.0, 0.0), (2.0, 2.5), (10.0, 10.5)]
    with pytest.raises(ValueError, match="RETIME_ANCHORS_INVALID"):
        video_retimer.normalize_anchors([(2.0, 12.0)], 10.0, 10.0)  # dest retrocede al final


def test_velocities_and_filtergraph():
    anclas = video_retimer.normalize_anchors([(2.0, 4.0)], 10.0, 10.0)
    segs = video_retimer.segment_velocities(anclas)
    assert segs[0] == (0.0, 2.0, 0.5)          # cámara lenta ×0.5
    assert segs[1][2] == pytest.approx(8.0 / 6.0, abs=1e-5)   # aceleración suave
    fc = video_retimer.build_retime_graph(anclas, has_audio=True)
    assert "trim=start=0.00000:end=2.00000" in fc
    assert "setpts=(PTS-STARTPTS)/0.50000" in fc
    assert "minterpolate=fps=24:mi_mode=mci:mc_mode=aobmc:vsbmc=1" in fc
    assert "atempo=0.50000" in fc
    assert "atrim=start=2.00000:end=10.00000" in fc
    # concat consume por SEGMENTO (v,a intercalados) — regresión del smoke real
    assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]" in fc
    assert fc.endswith("[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]")
    fc_sin_audio = video_retimer.build_retime_graph(anclas, has_audio=False)
    assert "[0:a]" not in fc_sin_audio and "atrim" not in fc_sin_audio \
        and "atempo" not in fc_sin_audio                    # sin rama de audio
    assert fc_sin_audio.endswith("concat=n=2:v=1:a=0[v]")


@pytest.mark.asyncio
async def test_retime_video_happy_and_fail_closed(monkeypatch, tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\x00\x00")
    durs = {"clip.mp4": 10.0, "out.mp4": 8.0}   # probe por nombre de fichero
    monkeypatch.setattr(video_retimer, "probe_duration",
                        lambda p: durs[Path(p).name])
    monkeypatch.setattr(video_retimer, "has_audio_stream", lambda p: True)
    llamadas = []

    def fake_ffmpeg(src, dst, anclas, *, fps, crf, preset, has_audio):
        llamadas.append((dst, len(anclas), has_audio))
    monkeypatch.setattr(video_retimer, "_run_ffmpeg", fake_ffmpeg)

    res = await video_retimer.retime_video(src, tmp_path / "out.mp4",
                                           "2.0=1.0", fin_dst=8.0)
    assert res["duration"] == 8.0 and res["duration_before"] == 10.0
    assert res["segments"][0]["velocity"] == 2.0     # 2 s de origen → 1 s de destino
    assert len(llamadas) == 1 and llamadas[0][2] is True

    with pytest.raises(ValueError, match="RETIME_SRC_MISSING"):
        await video_retimer.retime_video(tmp_path / "nope.mp4", tmp_path / "x.mp4", "1=1")
    with pytest.raises(ValueError, match="RETIME_ANCHORS_INVALID"):
        await video_retimer.retime_video(src, tmp_path / "x.mp4", "2.0=12.0",
                                         fin_dst=10.0)
    assert len(llamadas) == 1                        # fail-closed: ffmpeg nunca se invocó


# ── S3 · accent_meter ────────────────────────────────────────────────────────
SR = accent_meter.SR


def _escribe_wav(ruta: Path, tonos: list[tuple[float, float, float]]):
    """WAV mono 16-bit: silencio + un tono 5 kHz con envolvente hanning por
    (inicio_s, dur_s, amplitud) — el pico espectral es único por 'palabra'."""
    total = max((int((t + d) * SR) for t, d, _ in tonos), default=SR // 4)
    x = np.zeros(int(total) + SR // 10, dtype=np.float32)
    for t0, dur, amp in tonos:
        i0 = int(t0 * SR)
        n = int(dur * SR)
        env = np.hanning(n).astype(np.float32)
        t_seg = np.arange(n) / SR
        x[i0:i0 + n] += amp * env * np.sin(2 * math.pi * 5000 * t_seg).astype(np.float32)
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def _diez_palabras(amp_z: float, amp_s: float) -> list[tuple[float, float, float]]:
    # 5 palabras con z/c (primeras) + 5 con s; 0.3 s de tono cada 0.65 s
    return [(i * 0.65, 0.30, amp_z if i < 5 else amp_s) for i in range(10)]


def test_accent_distincion_espana(tmp_path):
    wav = tmp_path / "voz_es.wav"
    _escribe_wav(wav, _diez_palabras(0.15, 0.60))   # s (últimas 5) +12 dB sobre z/c
    res = accent_meter.audit_voice(wav, "es-ES")
    assert res["valida"] is True and res["acento"] == "espana"
    assert res["delta_db"] == pytest.approx(12.04, abs=1.0)


def test_accent_seseo_latam(tmp_path):
    wav = tmp_path / "voz_latam.wav"
    _escribe_wav(wav, _diez_palabras(0.30, 0.30))   # mitades iguales → Δ≈0
    res = accent_meter.audit_voice(wav, "es-LATAM")
    assert res["valida"] is True and res["acento"] == "seseo"
    assert abs(res["delta_db"]) <= 1.5
    res_es = accent_meter.audit_voice(wav, "es-ES")
    assert res_es["valida"] is False                 # mismo audio NO vale para es-ES


def test_accent_audio_inservible_y_dudoso(tmp_path):
    corto = tmp_path / "corto.wav"
    _escribe_wav(corto, [(0.0, 0.02, 0.5)])          # más corto que la ventana FFT
    res = accent_meter.audit_voice(corto, "es-ES")
    assert res["valida"] is False and "ACCENT" in res.get("error", "")
    bandera = tmp_path / "dudosa.wav"
    _escribe_wav(bandera, [(i * 0.65, 0.30, 0.30 if i < 5 else 0.45) for i in range(10)])
    res2 = accent_meter.classify(accent_meter.measure_delta(bandera), "es-ES")
    assert res2["acento"] in ("dudoso", "espana")    # Δ≈4-6 dB: zona gris honesta


# ── S4 · mezcla opt-in en build_mix_cmd ─────────────────────────────────────
def _mix(monkeypatch, tmp_path, sidecan, loudnorm):
    monkeypatch.setattr(config, "RENDER_MUSIC_SIDECAN", "1" if sidecan else "0")
    monkeypatch.setattr(config, "RENDER_LOUDNORM", "1" if loudnorm else "0")
    concat = tmp_path / "concat.mp4"
    concat.write_bytes(b"\x00")
    music = tmp_path / "cama.mp3"
    music.write_bytes(b"\x00")
    return video_assembler.build_mix_cmd(concat, music, tmp_path / "run")


def test_mix_default_golden_sin_sidechain_ni_loudnorm(monkeypatch, tmp_path):
    res = _mix(monkeypatch, tmp_path, False, False)
    fc = res["cmd"][res["cmd"].index("-filter_complex") + 1]
    assert fc == ("[1:a]volume=-20dB[m];"
                  "[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[aout]")
    assert res["cmd"][res["cmd"].index("-map") + 3] == "[aout]"
    assert res["sidechain"] is False and res["loudnorm"] is False


def test_mix_sidechain_duck_dinamico(monkeypatch, tmp_path):
    res = _mix(monkeypatch, tmp_path, True, False)
    fc = res["cmd"][res["cmd"].index("-filter_complex") + 1]
    assert "asplit=2[voz][llave]" in fc
    assert ("[bed][llave]sidechaincompress=threshold=0.03:ratio=6:"
            "attack=20:release=350[bedd]") in fc
    assert "[voz][bedd]amix=inputs=2:duration=first:dropout_transition=0[aout]" in fc
    assert res["sidechain"] is True and "loudnorm" not in fc


def test_mix_loudnorm_youtube_14_lufs(monkeypatch, tmp_path):
    res = _mix(monkeypatch, tmp_path, False, True)
    fc = res["cmd"][res["cmd"].index("-filter_complex") + 1]
    assert "[amix]loudnorm=I=-14:TP=-1:LRA=11[aout]" in fc
    assert res["cmd"][res["cmd"].index("-map") + 3] == "[aout]"
    res2 = _mix(monkeypatch, tmp_path, True, True)   # ambas: sidechain → loudnorm
    fc2 = res2["cmd"][res2["cmd"].index("-filter_complex") + 1]
    assert "sidechaincompress" in fc2 and "loudnorm=I=-14:TP=-1:LRA=11[aout]" in fc2


def test_mix_sin_musica_es_none(tmp_path):
    assert video_assembler.build_mix_cmd(tmp_path / "c.mp4", None, tmp_path) is None
