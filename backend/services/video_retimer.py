"""
YOUTUBE AUTOMATION v2.26 — Retimer de video por anclas palabra↔escena (INT-070)

Adaptado de estudio-video-ia (scripts/retimar.py, material aportado por el
usuario; sin fichero LICENSE — se porta el ALGORITMO, no el fichero).

PROBLEMA que resuelve: los generadores de video IA (Kling, Flow) reparten las
imágenes clave casi a intervalos iguales y NO respetan los segundos del prompt
(desvíos de hasta ~4 s). El contrato de ejecución (§13) hoy RECHAZA el clip
(CONTRACT_VIOLATION → ASSET_INVALID terminal). El retimer ofrece la vía
ALTERNATIVA: aceptar el clip y ESTIRAR/ENCOGER tramos entre anclas
origen=destino para que cada cambio de escena caiga exactamente en su palabra
de la narración. Es la diferencia entre regenerar (créditos + espera) y arreglar.

Mecánica por tramo [s0,s1)→[d0,d1):
  - video: trim + setpts=(PTS-STARTPTS)/vel con vel=(s1-s0)/(d1-d0);
    si vel < 1-0.02 (cámara lenta) interpola movimiento (minterpolate mci/aobmc).
  - audio: atrim + atempo encadenado (el filtro solo admite 0.5–2.0 por paso).
USO PREVISTO: herramienta de rescate (llamada por operador/doctor/orquestador
cuando la validación contractual reporta desvío de duración). NO se engancha
automáticamente al pipeline en INT-070 — decisión documentada en la ficha.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger("video_retimer")

FPS = 24
IGUAL = 0.02   # tramos a menos de un 2 % de 1x se dejan a 1x exacta


def chain_atempo(v: float) -> list[float]:
    """atempo solo admite 0.5–2.0 por filtro: se encadena para salirse del rango."""
    if v <= 0:
        raise ValueError(f"velocidad no positiva: {v}")
    pasos = []
    w = float(v)
    while w > 2.0:
        pasos.append(2.0)
        w /= 2.0
    while w < 0.5:
        pasos.append(0.5)
        w /= 0.5
    pasos.append(w)
    return pasos


def parse_anchors(spec: str | list[tuple[float, float]]) -> list[tuple[float, float]]:
    """'19.0=19.0,24.3=25.6' → [(19.0, 19.0), (24.3, 25.6)] (o lista directa)."""
    if not isinstance(spec, str):
        return [(float(s), float(d)) for s, d in spec]
    out = []
    for par in filter(None, (p.strip() for p in spec.split(","))):
        s, d = (float(x) for x in par.split("="))
        out.append((s, d))
    return out


def normalize_anchors(anchors: list[tuple[float, float]],
                      fin_src: float, fin_dst: float) -> list[tuple[float, float]]:
    """Añade 0=0 y fin_original=fin_destino, ordena y valida estrictamente
    creciente. Lanza ValueError con código si las anclas no crecen."""
    anclas = [(0.0, 0.0)] + [(float(s), float(d)) for s, d in anchors] + \
             [(float(fin_src), float(fin_dst))]
    anclas.sort()
    for (s0, d0), (s1, d1) in zip(anclas, anclas[1:]):
        if s1 <= s0 or d1 <= d0:
            raise ValueError(
                f"RETIME_ANCHORS_INVALID: anclas no crecientes {s0}={d0} → {s1}={d1}")
    return anclas


def segment_velocities(anclas: list[tuple[float, float]]) -> list[tuple[float, float, float]]:
    """[(s0, s1, vel), ...] por tramo: vel = span_origen / span_destino."""
    return [(s0, s1, (s1 - s0) / (d1 - d0))
            for (s0, d0), (s1, d1) in zip(anclas, anclas[1:])]


def build_retime_graph(anclas: list[tuple[float, float]], *, fps: int = FPS,
                       has_audio: bool = True) -> str:
    """filter_complex completo (puro, sin ffmpeg) — testeable sin binario.

    NOTA de orden: el filtro concat consume las entradas SEGMENTO a SEGMENTO
    (v,a por tramo), no todo el video primero — por eso las salidas se
    intercalan [v0][a0][v1][a1]…"""
    grafo, salidas = [], []
    for i, (s0, s1, vel) in enumerate(segment_velocities(anclas)):
        v = f"[0:v]trim=start={s0:.5f}:end={s1:.5f},setpts=(PTS-STARTPTS)/{vel:.5f}"
        if vel < 1 - IGUAL:
            v += f",minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:vsbmc=1"
        grafo.append(f"{v},fps={fps}[v{i}]")
        salidas.append(f"[v{i}]")
        if has_audio:
            atempo = ",".join(f"atempo={p:.5f}" for p in chain_atempo(vel))
            grafo.append(f"[0:a]atrim=start={s0:.5f}:end={s1:.5f},"
                         f"asetpts=PTS-STARTPTS,{atempo}[a{i}]")
            salidas.append(f"[a{i}]")
    n = len(anclas) - 1
    grafo.append("".join(salidas) + f"concat=n={n}:v=1:a={1 if has_audio else 0}"
                 + ("[v][a]" if has_audio else "[v]"))
    return ";".join(grafo)


def probe_duration(path: str | Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise ValueError(f"RETIME_PROBE_FAILED: {r.stderr[-300:]}")
    return float(json.loads(r.stdout)["format"]["duration"])


def has_audio_stream(path: str | Path) -> bool:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return False
    return any(s.get("codec_type") == "audio"
               for s in json.loads(r.stdout).get("streams", []))


def _run_ffmpeg(src: Path, dst: Path, anclas: list[tuple[float, float]],
                *, fps: int, crf: int, preset: str, has_audio: bool) -> None:
    fc = build_retime_graph(anclas, fps=fps, has_audio=has_audio)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
           "-filter_complex", fc, "-map", "[v]"]
    if has_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-crf", str(crf), "-preset", preset,
            "-pix_fmt", "yuv420p", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise ValueError(f"RETIME_FFMPEG_FAILED: {r.stderr[-400:]}")


async def retime_video(src: str | Path, dst: str | Path,
                       anchors: str | list[tuple[float, float]], *,
                       fps: int = FPS, crf: int = 14, preset: str = "slow",
                       fin_dst: float | None = None) -> dict:
    """Rejunta `src` a `dst` según anclas origen=destino (segundos). Devuelve
    resumen de tramos.Valida TODO antes de invocar ffmpeg (fail-closed)."""
    src, dst = Path(src), Path(dst)
    if not src.is_file():
        raise ValueError(f"RETIME_SRC_MISSING: {src}")
    fin_src = await asyncio.to_thread(probe_duration, src)
    destino = float(fin_dst) if fin_dst is not None else fin_src  # sin voz: misma duración total
    anclas = normalize_anchors(parse_anchors(anchors), fin_src, destino)
    has_audio = await asyncio.to_thread(has_audio_stream, src)
    segs = segment_velocities(anclas)
    await asyncio.to_thread(_run_ffmpeg, src, dst, anclas, fps=fps, crf=crf,
                            preset=preset, has_audio=has_audio)
    dur = await asyncio.to_thread(probe_duration, dst)
    log.info("[video_retimer] %s → %s: %d tramos, %.2f s (antes %.2f s)",
             src.name, dst.name, len(segs), dur, fin_src)
    return {"out": str(dst), "segments": [
        {"src": [round(s0, 3), round(s1, 3)], "velocity": round(vel, 5)}
        for s0, s1, vel in segs], "duration": round(dur, 3), "duration_before": round(fin_src, 3)}
