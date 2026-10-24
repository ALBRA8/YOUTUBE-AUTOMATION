#!/usr/bin/env python3
"""
BATERÍA DE TESTS — INT-040 · Galería de Voces con Preescucha Interactiva

Valida el catálogo de voces, filtrado avanzado, síntesis de preescucha con caché,
streaming de audio y selección de voz a nivel global y por proyecto:
1. GET /api/voices devuelve catálogo enriquecido y soporta filtros (país, género, provider, q).
2. POST /api/voices/preview sintetiza y cachea muestras de audio.
3. GET /api/voices/audio/{filename} sirve el archivo de audio con cabeceras correctas.
4. POST /api/voices/select aplica la voz a nivel global o por proyecto.
"""
import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
import database as db  # noqa: E402
from services import voices_catalog  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
import main  # noqa: E402

OK, FAIL = 0, 0


def check(nombre: str, cond: bool, extra: str = ""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


def test_catalog_and_filtering():
    client = TestClient(main.app)

    # 1. Catálogo completo
    res = client.get("/api/voices")
    check("GET /api/voices responde 200", res.status_code == 200, str(res.status_code))
    data = res.json()
    voices = data.get("voices", [])
    check("Catálogo contiene al menos 15 voces", len(voices) >= 15, f"Total: {len(voices)}")
    check("Catálogo incluye Salomé", any(v["id"] == "es-CO-SalomeNeural" for v in voices))
    check("Catálogo incluye Fenrir", any(v["id"] == "Fenrir" for v in voices))

    # 2. Filtrado por país
    res_co = client.get("/api/voices?country=Colombia")
    co_voices = res_co.json().get("voices", [])
    check("Filtro por país Colombia devuelve al menos 2 voces", len(co_voices) >= 2, str(len(co_voices)))
    check("Todas las voces devueltas son de Colombia", all(v["country"] == "Colombia" for v in co_voices))

    # 3. Filtrado por género
    res_fem = client.get("/api/voices?gender=Femenina")
    fem_voices = res_fem.json().get("voices", [])
    check("Filtro por género Femenina devuelve solo voces femeninas", all(v["gender"] == "Femenina" for v in fem_voices))

    # 4. Filtrado por proveedor
    res_edge = client.get("/api/voices?provider=edge")
    edge_voices = res_edge.json().get("voices", [])
    check("Filtro por provider edge devuelve solo edge", all(v["provider"] == "edge" for v in edge_voices))

    # 5. Búsqueda por texto (query q)
    res_q = client.get("/api/voices?q=misterio")
    q_voices = res_q.json().get("voices", [])
    check("Búsqueda por 'misterio' encuentra Álvaro o Fenrir", len(q_voices) >= 1)


def test_preview_and_audio_serving():
    client = TestClient(main.app)

    with tempfile.TemporaryDirectory() as td:
        prev_dir = Path(td)
        with patch("services.voices_catalog.PREVIEWS_DIR", prev_dir):
            # 1. Preescucha válida (Mocking edge_tts / gemini synthesis)
            fake_audio_path = prev_dir / "preview_fake_sample.mp3"
            fake_audio_path.write_bytes(b"FAKE_MP3_AUDIO_DATA_FOR_TESTING_PURPOSES")

            async def fake_synth(vid, text=None, provider=None):
                return fake_audio_path, 3.2, "audio/mpeg"

            with patch("services.voices_catalog.synthesize_preview", side_effect=fake_synth):
                res = client.post("/api/voices/preview", json={"voice_id": "es-CO-SalomeNeural"})
                check("POST /api/voices/preview responde 200", res.status_code == 200, str(res.status_code))
                body = res.json()
                check("Preescucha devuelve audio_url", "audio_url" in body and body["audio_url"].startswith("/api/voices/audio/"))
                check("Preescucha devuelve voice_id correcto", body.get("voice_id") == "es-CO-SalomeNeural")

                # 2. Servir el archivo de audio generado
                audio_res = client.get(body["audio_url"])
                check("GET audio_url responde 200", audio_res.status_code == 200, str(audio_res.status_code))
                check("Audio MIME type es audio/mpeg", "audio/mpeg" in audio_res.headers.get("content-type", ""))
                check("Contenido del audio coincide", audio_res.content == b"FAKE_MP3_AUDIO_DATA_FOR_TESTING_PURPOSES")

            # 3. Audio inexistente responde 404
            audio_404 = client.get("/api/voices/audio/nonexistent_voice.mp3")
            check("GET audio inexistente responde 404", audio_404.status_code == 404, str(audio_404.status_code))

            # 4. Preview sin voice_id responde 400
            res_bad = client.post("/api/voices/preview", json={})
            check("POST preview sin voice_id responde 400", res_bad.status_code == 400, str(res_bad.status_code))


def test_voice_selection():
    client = TestClient(main.app)

    # 1. Selección Global
    res_global = client.post("/api/voices/select", json={"voice_id": "es-MX-JorgeNeural"})
    check("POST /api/voices/select global responde 200", res_global.status_code == 200, str(res_global.status_code))
    body_g = res_global.json()
    check("Scope global devuelto", body_g.get("scope") == "global")
    check("Config global de voz actualizada", config.EDGE_TTS_VOICE == "es-MX-JorgeNeural")

    # 2. Selección para Proyecto
    pid = db.new_id()
    db.create_project(id=pid, title="Test Voice Project", style="cinematic", format="short")

    res_proj = client.post("/api/voices/select", json={"voice_id": "es-ES-AlvaroNeural", "project_id": pid})
    check("POST /api/voices/select por proyecto responde 200", res_proj.status_code == 200, str(res_proj.status_code))
    body_p = res_proj.json()
    check("Scope project devuelto", body_p.get("scope") == "project")

    # Verificar actualización en SQLite
    proj = db.get_project(pid)
    check("DB proyecto tiene la voz actualizada", proj["voice"] == "es-ES-AlvaroNeural")
    check("DB proyecto tiene el provider actualizado", proj["tts_provider"] == "edge")

    # 3. Selección de voz inexistente responde 404
    res_not_found = client.post("/api/voices/select", json={"voice_id": "nonexistent_voice_xyz"})
    check("POST /api/voices/select con voz inexistente responde 404", res_not_found.status_code == 404, str(res_not_found.status_code))


def main_test():
    print("=" * 60)
    print("BATERÍA INT-040 · Galería de Voces con Preescucha Interactiva")
    print("=" * 60)

    print("\n── S1 · Catálogo y Filtrado Avanzado de Voces ──")
    test_catalog_and_filtering()

    print("\n── S2 · Síntesis de Preescucha y Streaming de Audio ──")
    test_preview_and_audio_serving()

    print("\n── S3 · Selección de Voz (Global y por Proyecto) ──")
    test_voice_selection()

    print("\n" + "=" * 60)
    print(f"RESULTADO: {OK} OK · {FAIL} fallos")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main_test())
