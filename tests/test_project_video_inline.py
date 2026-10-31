#!/usr/bin/env python3
"""
FIX REPRODUCCIÓN VIDEO EN UI — Content-Disposition inline vs attachment

Síntoma: el reproductor <video> de la UI se quedaba en 0:00 con pantalla
negra. Causa: FileResponse(..., filename=...) fuerza por defecto
`Content-Disposition: attachment` en Starlette, y Chrome aborta la
reproducción al recibir `attachment` en vez de `inline`.

Valida el endpoint GET /api/projects/{pid}/video:
1. Por defecto sirve `inline` (el <video> reproduce).
2. Con ?download=1 sirve `attachment` (descarga explícita).
3. Cabeceras y bytes correctos (video/mp4, contenido íntegro).
4. 404 cuando el proyecto no existe o el MP4 no está en disco.
5. Contrato fuente: `content_disposition_type` presente y el botón de
   descarga de la UI apunta a ?download=1 (anti-regresión).

Dual-mode: pytest (fixtures client/tmp_path) y script directo (main_test).
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import main  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

OK, FAIL = 0, 0

PID = "a1b2c3d4e5f6"  # 12 hex canónico (security.validate_project_id)
FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42FAKE_VIDEO_PAYLOAD_FOR_TESTING"


def check(nombre: str, cond: bool, extra: str = ""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


def _proyecto_fake(video_path: Path) -> dict:
    return {
        "id": PID,
        "title": "Resumen semanal 📈 con acentos",
        "status": "ready",
        "video_url": str(video_path),
    }


def _mp4(tmp_path: Path) -> Path:
    video_path = tmp_path / "final_9x16.mp4"
    video_path.write_bytes(FAKE_MP4)
    return video_path


@pytest.fixture
def client():
    return TestClient(main.app)


# ── S1 · inline por defecto (reproductor <video>) ──────────────────────────
def test_inline_por_defecto(client, tmp_path):
    video_path = _mp4(tmp_path)
    with patch("main.db.get_project", return_value=_proyecto_fake(video_path)):
        res = client.get(f"/api/projects/{PID}/video")
        check("GET /video sin query responde 200", res.status_code == 200, str(res.status_code))
        cd = res.headers.get("content-disposition", "")
        check("Content-Disposition por defecto es inline", cd.startswith("inline"), cd)
        check("inline conserva filename del título", "filename" in cd, cd)
        check("Content-Type es video/mp4", res.headers.get("content-type", "") == "video/mp4",
              res.headers.get("content-type", ""))
        check("Los bytes del MP4 llegan íntegros", res.content == FAKE_MP4)
        check("Sin ?download no se fuerza attachment", "attachment" not in cd.lower().split(";")[0])


# ── S2 · ?download=1 → attachment (descarga explícita) ─────────────────────
def test_download_explicito(client, tmp_path):
    video_path = _mp4(tmp_path)
    with patch("main.db.get_project", return_value=_proyecto_fake(video_path)):
        res = client.get(f"/api/projects/{PID}/video?download=1")
        check("GET /video?download=1 responde 200", res.status_code == 200, str(res.status_code))
        cd = res.headers.get("content-disposition", "")
        check("?download=1 fuerza attachment", cd.startswith("attachment"), cd)
        check("attachment conserva filename", "filename" in cd, cd)

        res0 = client.get(f"/api/projects/{PID}/video?download=0")
        check("?download=0 sigue siendo inline (solo 1 activa descarga)",
              res0.headers.get("content-disposition", "").startswith("inline"),
              res0.headers.get("content-disposition", ""))

        resT = client.get(f"/api/projects/{PID}/video?download=true")
        check("?download=true también fuerza attachment",
              resT.headers.get("content-disposition", "").startswith("attachment"),
              resT.headers.get("content-disposition", ""))


# ── S3 · Errores (404 / 400) ────────────────────────────────────────────────
def test_404_y_traversal(client):
    res = client.get("/api/projects/000000000000/video")
    check("Proyecto inexistente responde 404", res.status_code == 404, str(res.status_code))
    res2 = client.get("/api/projects/..%2F..%2Fetc%2Fpasswd/video")
    check("pid no canónico muere con 400/404 (no traversal)", res2.status_code in (400, 404),
          str(res2.status_code))


def test_mp4_borrado_del_disco(client, tmp_path):
    with patch("main.db.get_project",
               return_value=_proyecto_fake(tmp_path / "borrado.mp4")):
        res = client.get(f"/api/projects/{PID}/video")
        check("MP4 inexistente en disco responde 404", res.status_code == 404, str(res.status_code))


# ── S4 · Contrato fuente (anti-regresión) ──────────────────────────────────
def test_contrato_fuente():
    src_main = (BACKEND / "main.py").read_text(encoding="utf-8")
    check("project_video usa content_disposition_type (anti-regresión)",
          "content_disposition_type=" in src_main
          and '"attachment" if download else "inline"' in src_main)
    check("El endpoint declara query param download: bool = False",
          "async def project_video(pid: str, download: bool = False)" in src_main)
    src_ui = (BACKEND / "static" / "app.js").read_text(encoding="utf-8")
    check("El botón ⬇️ Descargar MP4 apunta a ?download=1",
          "/video?download=1" in src_ui)
    check("El reproductor <video> sigue sirviendo la URL inline (sin ?download)",
          '<video controls src="/api/projects/${p.id}/video"></video>' in src_ui)


def main_test() -> int:
    global OK, FAIL
    print("FIX UI VIDEO · Content-Disposition inline vs attachment")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as td:
        cli = TestClient(main.app)
        print("\n── S1 · inline por defecto (reproductor <video>) ──")
        test_inline_por_defecto(cli, Path(td))
        print("\n── S2 · ?download=1 → attachment (descarga explícita) ──")
        test_download_explicito(cli, Path(td))
        print("\n── S3 · Errores (404 / 400) ──")
        test_404_y_traversal(cli)
        test_mp4_borrado_del_disco(cli, Path(td))
        print("\n── S4 · Contrato fuente (anti-regresión) ──")
        test_contrato_fuente()

    print("\n" + "=" * 60)
    print(f"RESULTADO: {OK} OK · {FAIL} fallos")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main_test())
