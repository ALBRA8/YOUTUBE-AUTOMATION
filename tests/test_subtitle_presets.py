#!/usr/bin/env python3
"""
BATERÍA DE TESTS — INT-041 · Presets Visuales de Subtítulos (Shorts Style Switcher)

Valida el catálogo de estilos de subtítulos, la generación ASS de cada preset,
la persistencia por proyecto y global, y las guardias de seguridad:
1. GET /api/subtitles/presets devuelve al menos 8 presets completos.
2. build_ass genera correctamente las cabeceras ASS y respeta los contratos
   legacy de 'hormozi' y 'shorts', así como las nuevas variantes (mrbeast, neon, boxed, minimal).
3. POST /api/subtitles/apply aplica el estilo a nivel global o por proyecto.
4. Validaciones y errores limpios (400 en estilo inválido, 404 en proyecto no encontrado).
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
import database as db  # noqa: E402
from pipeline import subtitles  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
import main  # noqa: E402

OK, FAIL = 0, 0


def check(nombre: str, cond: bool, extra: str = ""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


def test_presets_catalog():
    client = TestClient(main.app)

    res = client.get("/api/subtitles/presets")
    check("GET /api/subtitles/presets responde 200", res.status_code == 200, str(res.status_code))
    data = res.json()
    presets = data.get("presets", [])
    check("Contiene al menos 8 presets", len(presets) >= 8, f"Total: {len(presets)}")

    expected_ids = {"shorts", "hormozi", "mrbeast", "neon", "tiktok", "boxed", "minimal", "karaoke"}
    actual_ids = {p["id"] for p in presets}
    check("Todos los estilos esperados están presentes", expected_ids.issubset(actual_ids), str(actual_ids))

    for p in presets:
        check(f"Preset '{p['id']}' tiene preview_css y sample_text", bool(p.get("preview_css") and p.get("sample_text")))


def test_ass_generation_all_presets():
    words = [
        {"word": "esto", "start": 0.0, "end": 0.4},
        {"word": "cambia", "start": 0.4, "end": 0.8},
        {"word": "todo", "start": 0.8, "end": 1.2},
    ]

    # 1. Hormozi: Contrato legacy intacto
    ass_h = subtitles.build_ass(words, 1080, 1920, style="hormozi")
    LEGACY = "Style: Hormozi,Impact,119,&H0033FFFF,&H00FFFFFF,&H00000000,&H7F000000,-1,0,0,0,100,100,1,0,1,9,4,5,60,60,576,1"
    check("Hormozi respeta contrato legacy byte-idéntico", LEGACY in ass_h)

    # 2. Shorts: Contrato de INT-021
    ass_s = subtitles.build_ass(words, 1080, 1920, style="shorts")
    check("Shorts contiene Style: Shorts,Montserrat ExtraBold", "Style: Shorts,Montserrat ExtraBold" in ass_s)

    # 3. MrBeast: Mayúsculas y escala pop aumentada
    ass_mb = subtitles.build_ass(words, 1080, 1920, style="mrbeast")
    check("MrBeast tiene Style: Mrbeast", "Style: Mrbeast" in ass_mb)
    check("MrBeast convierte texto a mayúsculas", "ESTO CAMBIA" in ass_mb)
    check("MrBeast incluye pop de escala 125%", r"\fscx125\fscy125" in ass_mb)

    # 4. Boxed: BorderStyle=3 (caja rectangular de fondo)
    ass_bx = subtitles.build_ass(words, 1080, 1920, style="boxed")
    check("Boxed tiene Style: Boxed", "Style: Boxed" in ass_bx)
    check("Boxed usa BorderStyle=3", ",3,4,0,5," in ass_bx)

    # 5. Minimal: Alignment=2 (inferior) y marginv=80
    ass_min = subtitles.build_ass(words, 1080, 1920, style="minimal")
    check("Minimal tiene Style: Minimal", "Style: Minimal" in ass_min)
    check("Minimal usa Alignment=2 (inferior)", ",2,60,60,80,1" in ass_min)

    # 6. Neon: Verde/Cian eléctrico
    ass_neo = subtitles.build_ass(words, 1080, 1920, style="neon")
    check("Neon tiene Style: Neon", "Style: Neon" in ass_neo)
    check("Neon tiene color primario verde &H0000FF7F", "&H0000FF7F" in ass_neo)


def test_api_apply():
    client = TestClient(main.app)

    # 1. Aplicar a nivel global
    res_g = client.post("/api/subtitles/apply", json={"style_id": "mrbeast"})
    check("POST /api/subtitles/apply global responde 200", res_g.status_code == 200, str(res_g.status_code))
    check("Scope global retornado", res_g.json().get("scope") == "global")
    check("Config global actualizada", config.DEFAULT_SUBTITLE_STYLE == "mrbeast")

    # 2. Aplicar a un proyecto
    pid = db.new_id()
    db.create_project(id=pid, title="Test Subtitles Project", style="cinematic", format="short")

    res_p = client.post("/api/subtitles/apply", json={"style_id": "neon", "project_id": pid})
    check("POST /api/subtitles/apply proyecto responde 200", res_p.status_code == 200, str(res_p.status_code))
    check("Scope project retornado", res_p.json().get("scope") == "project")

    # Verificar en SQLite
    proj = db.get_project(pid)
    check("Meta del proyecto tiene subtitle_style = neon", (proj.get("meta") or {}).get("subtitle_style") == "neon")

    # 3. Error en estilo inválido
    res_err = client.post("/api/subtitles/apply", json={"style_id": "estilo_fantasma_xyz"})
    check("Estilo inválido responde 400", res_err.status_code == 400, str(res_err.status_code))

    # 4. Error en proyecto inexistente
    res_404 = client.post("/api/subtitles/apply", json={"style_id": "boxed", "project_id": db.new_id()})
    check("Proyecto inexistente responde 404", res_404.status_code == 404, str(res_404.status_code))


def main_test():
    print("=" * 60)
    print("BATERÍA INT-041 · Presets Visuales de Subtítulos (Shorts Switcher)")
    print("=" * 60)

    print("\n── S1 · Catálogo y Metadatos de Presets ──")
    test_presets_catalog()

    print("\n── S2 · Generación ASS de Todos los Presets ──")
    test_ass_generation_all_presets()

    print("\n── S3 · Endpoint REST de Aplicación Global y Proyecto ──")
    test_api_apply()

    print("\n" + "=" * 60)
    print(f"RESULTADO: {OK} OK · {FAIL} fallos")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main_test())
