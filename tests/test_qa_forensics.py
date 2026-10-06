#!/usr/bin/env python3
"""Batería QA FORENSE de medios — detección de assets enfermos.

La misión de evolución (Agente C) exige que el QA NO acepte "archivo
generado" como equivalente a "video correcto". Esta batería fabrica a
PROPÓSITO los 4 tipos de asset que un proveedor/una cadena rota puede
producir y verifica que video_qa los detecta midiendo, no suponiendo:

    negro.mp4            → pantalla negra (asset vacío / fade total)
    azul.mp4             → pantalla azul (crash típico del proveedor)
    naranja.mp4          → asset SANO (sin pista de audio — normal en Flow)
    verde_silencioso.mp4 → audio completamente silencioso (TTS muerto)
    rojo_con_voz.mp4     → audio audible (max_volume ≈ 0 dB, no silencio)

Además: propagación del warn a qa_project (status "warn" sin errors) y
tolerancia (nunca lanza por assets malos).

Uso:  cd yt_automation_v2 && python3 tests/test_qa_forensics.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="qa_forensics_test_"))
import config as _cfg  # noqa: E402
_cfg.DB_PATH = _TMP / "test.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP / "data"
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.DATA_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import database as db  # noqa: E402
from services import video_qa as vqa  # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


def _enc(name: str, video_src: str, audio_src: str | None = None) -> Path:
    """Codifica un MP4 de prueba con ffmpeg (256x256, h264, 1.0s).
    Todas las entradas primero; opciones de salida después (regla ffmpeg)."""
    out = _TMP / name
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "lavfi", "-i", f"{video_src}:s=256x256:d=1.0"]
    if audio_src:
        cmd += ["-f", "lavfi", "-i", audio_src]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio_src:
        cmd += ["-shortest", "-c:a", "aac"]
    cmd.append(str(out))
    proc = subprocess.run(cmd, capture_output=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg falló para {name}: "
                           f"{proc.stderr.decode('utf-8', 'replace')[-400:]}")
    return out


def _worst_is(flags: list[dict], sev: str) -> bool:
    return any(f["sev"] == sev for f in flags)


def main() -> int:
    print("── 1. fabricar assets enfermos y sanos con ffmpeg")
    negro = _enc("negro.mp4", "color=c=black")
    azul = _enc("azul.mp4", "color=c=0x0000FF")
    naranja = _enc("naranja.mp4", "color=c=0xFF8C00")
    verde_sil = _enc("verde_sil.mp4", "color=c=0x228B22",
                     "anullsrc=r=44100:cl=mono")
    rojo_voz = _enc("rojo_voz.mp4", "color=c=0xC41E3A",
                    "sine=frequency=440:sample_rate=44100")
    for f in (negro, azul, naranja, verde_sil, rojo_voz):
        check(f"fixture generado: {f.name}", f.exists() and f.stat().st_size > 1000)

    print("── 2. pantalla negra detectada (warn, no error)")
    r = vqa.qa_video(negro)
    check("pantalla_negra=True", r.get("pantalla_negra") is True, str(r.get("flags")))
    check("pantalla_azul=False (no confunde)", r.get("pantalla_azul") is False)
    check("flag warn presente", _worst_is(r["flags"], "warn"))
    check("NO hay error (fade legítimo → revisar, no bloquear)",
          not _worst_is(r["flags"], "error"))
    check("frames_muestreados==3", r.get("frames_muestreados") == 3)
    check("peor severidad = warn", vqa._worst(r["flags"]) == "warn")

    print("── 3. pantalla azul detectada (warn)")
    r = vqa.qa_video(azul)
    check("pantalla_azul=True", r.get("pantalla_azul") is True, str(r.get("flags")))
    check("pantalla_negra=False (azul no es negro: luma≈29>24)",
          r.get("pantalla_negra") is False)
    check("peor severidad = warn", vqa._worst(r["flags"]) == "warn")

    print("── 4. asset sano sin pista de audio → cero warns de forense")
    r = vqa.qa_video(naranja)
    check("pantalla_negra=False", r.get("pantalla_negra") is False)
    check("pantalla_azul=False", r.get("pantalla_azul") is False)
    check("audio_silencioso=False", r.get("audio_silencioso") is False)
    check("sin pista de audio → 'sin audio (normal)' ok",
          not r.get("has_audio") and _worst_is(r["flags"], "ok"))
    check("status global ok", vqa._worst(r["flags"]) == "ok",
          str(r["flags"]))

    print("── 5. audio completamente silencioso detectado (warn)")
    r = vqa.qa_video(verde_sil)
    check("audio_silencioso=True", r.get("audio_silencioso") is True,
          str(r.get("flags")))
    check("max_volume_db ≤ -60",
          r.get("max_volume_db") is None or r["max_volume_db"] <= -60,
          str(r.get("max_volume_db")))
    check("pantalla_negra/azul False (verde es color sano)",
          not r.get("pantalla_negra") and not r.get("pantalla_azul"))

    print("── 6. audio audible → NO silencioso")
    r = vqa.qa_video(rojo_voz)
    check("audio_silencioso=False", r.get("audio_silencioso") is False)
    check("max_volume_db > -60 (tono 440Hz audible)",
          (r.get("max_volume_db") or -99) > -60, str(r.get("max_volume_db")))
    check("status global ok", vqa._worst(r["flags"]) == "ok", str(r["flags"]))

    print("── 7. propagación: clip negro en proyecto → qa_project status warn")
    pid = "proj_forensics"
    db.create_project(id=pid, title="Forensics", status="draft",
                      mode="production_json", style="graphic-novel",
                      format="short")
    db.replace_scenes(pid, [
        {"title": "Escena 1", "narration": "Narración.",
         "image_prompt": "wide shot, golden hour, no text",
         "duration": 0.0, "status": "pending",
         "meta": {"production_unit": {
             "id": "u1", "index": 0, "type": "scene",
             "video_prompt": "CE_FORE_V1 :: slow push"}}}])
    flow_dir = _cfg.OUTPUT_DIR / pid / "flow"
    flow_dir.mkdir(parents=True, exist_ok=True)
    (flow_dir / "Escena_01_video_1.mp4").write_bytes(negro.read_bytes())
    (flow_dir / "Escena_01_flow.png").write_bytes(_png_ok())
    qa = vqa.qa_project(pid)
    check("qa corre sin lanzar", qa["ok"] is True)
    check("status == 'warn' (warn del clip negro propaga)",
          qa["status"] == "warn", qa["status"])
    check("0 errores (warn no bloquea)",
          qa["summary"]["image_errors"] == 0
          and qa["summary"]["clip_errors"] == 0)
    clip_flags = qa["scenes"][0]["clips"][0]["flags"]
    check("el flag 'pantalla negra' visible en el reporte por escena",
          any("pantalla negra" in f["msg"] for f in clip_flags), str(clip_flags))

    print("── 8. tolerancia: bytes basura → error, no crash")
    basura = _TMP / "basura.mp4"
    basura.write_bytes(b"<html>Gateway Timeout</html>" * 40)
    r = vqa.qa_video(basura)
    check("HTML disfrazado de MP4 → error (no lanza)",
          vqa._worst(r["flags"]) == "error")

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


def _png_ok(w=320, h=320, color=(200, 120, 40)) -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


if __name__ == "__main__":
    sys.exit(main())
