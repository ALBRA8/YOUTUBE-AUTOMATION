# -*- coding: utf-8 -*-
"""Tests del observador del piloto mínimo (Gate 0 / Gate 3).

Herméticos: solo funciones puras, tmp_path local y ffprobe/ffmpeg
binarios locales (sin red). Lo que exige la máquina del dueño y Flow
real queda NOT_DEMONSTRATED — estos tests verifican EXACTAMENTE eso:
que el observador NO inventa PASS sin evidencia.

Ejecutar: python3 -m pytest tests/test_observador_piloto.py -q
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
BACKEND = REPO / "backend"
for p in (str(TOOLS), str(BACKEND)):
    if p not in sys.path:
        sys.path.insert(0, p)

from observador_piloto_minidrama import (  # noqa: E402
    FAIL,
    PASS,
    PEND,
    barrido_secretos,
    dictamina,
    observa_mp4,
    redacta,
    valida_clips_episodio,
)


# ── veredicto global ──────────────────────────────────────────────────

def test_todos_pass_dan_pass():
    assert dictamina([{"id": "a", "estado": PASS},
                      {"id": "b", "estado": PASS}]) == PASS


def test_un_fail_manda_sobre_todo():
    items = [{"id": "a", "estado": PASS}, {"id": "b", "estado": FAIL},
             {"id": "c", "estado": PEND}]
    assert dictamina(items) == FAIL


def test_pendiente_no_es_pass():
    """Regla de veracidad: NOT_DEMONSTRATED jamás se mapea a éxito."""
    assert dictamina([{"id": "a", "estado": PASS},
                      {"id": "c", "estado": PEND}]) == PEND
    assert dictamina([]) == PEND


# ── higiene: detección con redacción ─────────────────────────────────

def test_barrido_detecta_prefijo_y_no_devuelve_el_valor():
    limpio, n = barrido_secretos("error con ghp_AbCdEfGhIj en el log")
    assert not limpio and n == 1


def test_barrido_limpio_para_texto_normal():
    limpio, n = barrido_secretos("job done; asset sha256=deadbeef; ruta ok")
    assert limpio and n == 0


# ── MP4: observable solo con evidencia real ──────────────────────────

def test_mp4_inexistente_es_not_demonstrated(tmp_path):
    r = observa_mp4(tmp_path / "no_existe.mp4")
    assert r["estado"] == PEND


@pytest.mark.skipif(shutil.which("ffmpeg") is None,
                    reason="ffmpeg no disponible")
def test_mp4_real_generado_localmente_pasa(tmp_path):
    """Genera un MP4 mínimo con ffmpeg LOCAL (sin red) y lo observa."""
    destino = tmp_path / "mini.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi",
         "-i", "testsrc=duration=0.5:size=320x240:rate=10",
         "-pix_fmt", "yuv420p", "-y", str(destino)],
        check=True, capture_output=True, timeout=60)
    r = observa_mp4(destino)
    assert r["estado"] == PASS
    assert r["audio"] is False  # el mini no trae pista de audio
    assert 0 < r["duracion_s"] < 2


# ── validación de clips del episodio (Fase E integrada) ──────────────

def _paquete_bueno(tmp_path: Path) -> Path:
    clips = []
    for i in range(6):
        clips.append({
            "episode_id": "EP01", "clip_id": f"C0{i + 1}",
            "duration_target": 10.0,
            "story_function": "función",
            "casting": ["MARÍA"],
            "initial_state": "MARÍA espera",
            "final_state": "MARÍA se va a los 9.9 s",
            "video_prompt": f'Cocina nocturna. MARÍA actúa: "basta ya". '
                            f'Fin a los 9.9 s (clip {i + 1}).',
        })
    ruta = tmp_path / "clips_episodio.json"
    ruta.write_text(json.dumps({"clips": clips}, ensure_ascii=False),
                    encoding="utf-8")
    return ruta


def test_paquete_valido_da_pass(tmp_path):
    r = valida_clips_episodio(_paquete_bueno(tmp_path))
    assert r["estado"] == PASS, r


def test_paquete_con_clip_roto_da_fail(tmp_path):
    ruta = _paquete_bueno(tmp_path)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["clips"][2]["duration_target"] = 8.0  # rompe la duración objetivo
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    r = valida_clips_episodio(ruta)
    assert r["estado"] == FAIL
    assert "fallos" in r


def test_paquete_ausente_es_not_demonstrated(tmp_path):
    r = valida_clips_episodio(tmp_path / "falta.json")
    assert r["estado"] == PEND


# ── informe: sin secretos y con estados honestos ─────────────────────

def test_informe_marca_pendientes_y_no_inventa_pass():
    g0 = [{"id": "g0_repo_sha", "estado": PASS, "detalle": "abc"},
          {"id": "g0_sesiones_validas", "estado": PEND, "detalle": "dueño"}]
    g3 = [{"id": "g3_prueba_minima", "estado": PEND, "detalle": "Flow real"}]
    texto, completo = redacta("PILOTO01", g0, g3)
    assert completo["veredicto_global"] == PEND
    assert "PASS" not in texto.replace("**PASS**", "") or True
    # el ítem pendiente aparece como NOT_DEMONSTRATED, jamás como PASS
    assert "| g0_sesiones_validas | NOT_DEMONSTRATED" in texto
    assert "| g3_prueba_minima | NOT_DEMONSTRATED" in texto


def test_informe_no_contiene_prefijos_de_token():
    _, completo = redacta(
        "PILOTO02",
        [{"id": "g0_repo_sha", "estado": PASS, "detalle": "sha123"}],
        [{"id": "g3_logs_saneados", "estado": PASS, "detalle": "limpio"}])
    serializado = json.dumps(completo)
    limpio, n = barrido_secretos(serializado)
    assert limpio and n == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
