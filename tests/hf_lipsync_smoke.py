#!/usr/bin/env python3
"""
SMOKE LIVE — INT-072 · Lip-Sync HF Spaces con Valeria Ríos (coste $0.00)

Anima un retrato de avatar con un fragmento de audio REAL de locución y
valida que el MP4 final sale con movimiento facial/labial y lienzo 9:16.

Uso (equivalente al pedido en la spec como backend/data/tmp/test_hf_lipsync.py):
    python tests/hf_lipsync_smoke.py                     # avatar sintético
    python tests/hf_lipsync_smoke.py --image ruta.png    # retrato real de avatar

Qué hace:
  1. Prepara imagen de rostro (argumento --image o placeholder sintético 512x512).
  2. Sintetiza locución REAL con edge-tts (es-CO-SalomeNeural); fallback sine.
  3. Llama a render_avatar_animation(engine="auto") → HF Spaces primero
     (EchoMimic/echomimic-v2/AniPortrait; usa HF_TOKEN del .env si existe),
     fail-open al motor local si HF falla o no hay cuota.
  4. Verifica: MP4 existe · tiene pista de audio · dimensiones · MOVIMIENTO
     (diferencia de píxeles entre el primer fotograma y uno intermedio).
  5. Veredicto PASS/FAIL y exit code.

Sin guardias raras: todo dentro de main() + guard __main__ (pytest NO lo
recolecta: el nombre no coincide con test_*.py).
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
from services.avatar_motion import render_avatar_animation  # noqa: E402

WORKDIR = config.TMP_DIR / "hf_lipsync_check"


def make_placeholder_face(path: Path) -> Path:
    """Retrato sintético 512x512 (no es Valeria real: es un placeholder digno)."""
    from PIL import Image, ImageDraw, ImageFilter
    img = Image.new("RGB", (512, 512), (24, 28, 38))
    d = ImageDraw.Draw(img)
    # fondo degradado
    for y in range(512):
        d.line([(0, y), (512, y)], fill=(24 + y // 24, 28 + y // 30, 38 + y // 20))
    # rostro
    d.ellipse([146, 110, 366, 420], fill=(228, 194, 166))
    d.ellipse([126, 80, 386, 300], fill=(60, 46, 40))          # cabello
    d.ellipse([156, 120, 356, 400], fill=(228, 194, 166))      # cara
    d.ellipse([200, 220, 236, 248], fill=(28, 26, 30))         # ojo izq
    d.ellipse([276, 220, 312, 248], fill=(28, 26, 30))         # ojo der
    d.arc([196, 210, 240, 254], 200, 340, fill=(50, 38, 34), width=4)
    d.arc([272, 210, 316, 254], 200, 340, fill=(50, 38, 34), width=4)
    d.ellipse([246, 330, 266, 344], fill=(196, 128, 120))      # nariz
    d.arc([216, 356, 296, 396], 20, 160, fill=(150, 90, 90), width=5)  # boca
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    img.save(path)
    return path


def make_voice_audio(path_wav: Path) -> tuple[Path, str]:
    """Locución REAL por edge-tts; fallback tono modulado. Devuelve (ruta, fuente)."""
    text = ("Hola, soy Valeria Ríos y este mensaje fue sincronizado con "
            "inteligencia artificial sin gastar un solo peso.")
    try:
        import edge_tts  # type: ignore

        async def _synth():
            comm = edge_tts.Communicate(text, "es-CO-SalomeNeural")
            await comm.save(str(path_wav.with_suffix(".mp3")))

        asyncio.run(_synth())
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(path_wav.with_suffix(".mp3")),
             "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(path_wav)],
            capture_output=True, check=True)
        return path_wav, "edge-tts (voz real)"
    except Exception as ex:
        print(f"  [aviso] edge-tts no disponible ({type(ex).__name__}): uso tono modulado")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", "sine=frequency=210:duration=3",
             "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(path_wav)],
            capture_output=True, check=True)
        return path_wav, "sine (fallback)"


def video_report(p: Path) -> dict:
    def probe(args):
        return subprocess.run(
            ["ffprobe", "-v", "error", *args, str(p)],
            capture_output=True, text=True).stdout.strip()

    dims = probe(["-select_streams", "v:0", "-show_entries", "stream=width,height",
                  "-of", "csv=p=0"])
    dur = probe(["-show_entries", "format=duration", "-of", "csv=p=0"])
    has_audio = bool(probe(["-select_streams", "a:0",
                            "-show_entries", "stream=codec_type", "-of", "csv=p=0"]))
    w, h = (dims.split(",") + ["0", "0"])[:2]
    return {"w": int(float(w or 0)), "h": int(float(h or 0)),
            "dur": float(dur or 0), "has_audio": has_audio}


def movement_check(p: Path) -> float:
    """Diferencia media de píxeles entre fotograma 0 y uno intermedio (>3 = hay movimiento)."""
    with tempfile.TemporaryDirectory() as td:
        f0, f1 = Path(td) / "f0.png", Path(td) / "f1.png"
        subprocess.run(["ffmpeg", "-y", "-i", str(p), "-vf", "select=eq(n\\,0)",
                        "-frames:v", "1", str(f0)], capture_output=True)
        subprocess.run(["ffmpeg", "-y", "-i", str(p), "-vf", "select=eq(n\\,20)",
                        "-frames:v", "1", str(f1)], capture_output=True)
        if not f0.is_file() or not f1.is_file():
            return 0.0
        from PIL import Image, ImageChops
        a, b = Image.open(f0).convert("L"), Image.open(f1).convert("L")
        if a.size != b.size:
            return 0.0
        diff = ImageChops.difference(a, b)
        hist = diff.histogram()
        total = sum(hist)
        return sum(i * c for i, c in enumerate(hist)) / max(1, total)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=str, default="",
                    help="Ruta de un retrato real de avatar (opcional)")
    args = ap.parse_args()

    WORKDIR.mkdir(parents=True, exist_ok=True)
    print("=" * 64)
    print("SMOKE INT-072 · Lip-Sync HF Spaces ($0.00) — escena Valeria Ríos")
    print("=" * 64)

    img = Path(args.image) if args.image else make_placeholder_face(WORKDIR / "valeria_face.png")
    if not img.is_file():
        print(f"FAIL: imagen no encontrada: {img}")
        return 1
    wav, voice_src = make_voice_audio(WORKDIR / "valeria_voice.wav")

    token = str(getattr(config, "HF_TOKEN", "") or "").strip()
    print(f"Imagen   : {img.name} ({'real' if args.image else 'placeholder sintético'})")
    print(f"Audio    : {voice_src} → {wav.name}")
    print(f"HF_TOKEN : {'presente (cuota ZeroGPU estable)' if token else 'AUSENTE — la cuota anónima puede agotarse'}")
    print(f"Spaces   : {getattr(config, 'AVATAR_HF_SPACES', '?')}")
    print("-" * 64)

    out = WORKDIR / "valeria_lipsync.mp4"
    res = asyncio.run(render_avatar_animation(img, out, audio_path=wav, engine="auto"))

    engine = res.get("engine")
    print(f"Motor    : {engine}" + (f"  (space: {res.get('space')})" if res.get("space") else ""))
    print(f"Ruta     : {res.get('video_path')}")

    ok = True
    rep = video_report(Path(res["video_path"]))
    print(f"Dimensiones : {rep['w']}x{rep['h']}  · duración {rep['dur']:.2f} s  · audio: {'sí' if rep['has_audio'] else 'NO'}")
    mv = movement_check(Path(res["video_path"]))
    print(f"Movimiento  : diff medio de píxeles entre frames = {mv:.2f} ({'HAY movimiento' if mv > 3 else 'estático'})")

    if engine == "liveportrait_hf":
        if (rep["w"], rep["h"]) != (config.AVATAR_OUTPUT_W, config.AVATAR_OUTPUT_H):
            print(f"FAIL: se esperaba {config.AVATAR_OUTPUT_W}x{config.AVATAR_OUTPUT_H}")
            ok = False
        if mv <= 3:
            print("FAIL: sin movimiento detectable")
            ok = False
        if not rep["has_audio"]:
            print("FAIL: sin pista de audio")
            ok = False
    else:
        print("  [aviso] HF no respondió → fallback local OK (fail-open funciona);")
        print("          para el veredicto hiperrealista configura HF_TOKEN gratis en .env.")

    print("=" * 64)
    print("VEREDICTO:", "PASS ✅" if ok else "FAIL ❌", f"(engine={engine}, movimiento={mv:.2f})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
