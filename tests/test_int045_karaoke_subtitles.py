"""Batería de pruebas unitarias para INT-045: Word-Level Animated Karaoke Subtitles.

Metodología ClonaKit: Fase 5 (Probar y Validar)
- Valida los presets visuales (Hormozi, MrBeast, Cyberpunk, Minimal)
- Formato de tiempo ASS H:MM:SS.cs
- Generación de diálogos con resaltado activo palabra a palabra y rebote fscx/fscy
- Generación atómica en disco vía write_ass
- Integración no regresiva con Video Assembler y Viral Clipper
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import karaoke_subtitles
from services import video_assembler


def test_presets_exist_and_fallbacks():
    """Valida la disponibilidad de los presets y fallback seguro."""
    for style in ("hormozi", "mrbeast", "cyberpunk", "minimal"):
        preset = karaoke_subtitles.get_preset(style)
        assert preset["name"].lower() == style
        assert "primary_color" in preset
        assert "highlight_color" in preset
        assert "font" in preset
        assert preset["fontsize_v"] > 0
        assert preset["pop_scale"] >= 100

    # Fallback desconocido va a Hormozi
    unknown = karaoke_subtitles.get_preset("desconocido_xyz")
    assert unknown["name"].lower() == "hormozi"


def test_format_ass_time():
    """Valida la conversión exacta de segundos float a H:MM:SS.cs (centésimas)."""
    assert karaoke_subtitles.format_ass_time(0.0) == "0:00:00.00"
    assert karaoke_subtitles.format_ass_time(12.34) == "0:00:12.34"
    assert karaoke_subtitles.format_ass_time(65.5) == "0:01:05.50"
    assert karaoke_subtitles.format_ass_time(3665.25) == "1:01:05.25"


def test_build_ass_header():
    """Valida la estructura obligatoria de cabeceras ASS v4+ con estilo del preset."""
    preset = karaoke_subtitles.get_preset("mrbeast")
    header = karaoke_subtitles.build_ass_header(preset, resolution="1080x1920")

    assert "[Script Info]" in header
    assert "PlayResX: 1080" in header
    assert "PlayResY: 1920" in header
    assert "[V4+ Styles]" in header
    assert "Format: Name, Fontname, Fontsize" in header
    assert f"Style: {preset['name']}" in header
    assert preset["primary_color"] in header
    assert "[Events]" in header
    assert "Format: Layer, Start, End, Style" in header


def test_build_karaoke_dialogues_word_highlight():
    """Valida que cada palabra activa reciba el color de realce y tags de rebote."""
    preset = karaoke_subtitles.get_preset("hormozi")
    words = [
        {"word": "EL", "start": 0.0, "end": 0.5},
        {"word": "SECRETO", "start": 0.5, "end": 1.2},
        {"word": "DEL", "start": 1.2, "end": 1.6},
        {"word": "ÉXITO", "start": 1.6, "end": 2.2},
    ]

    dialogues = karaoke_subtitles.build_karaoke_dialogues(words, preset)
    assert len(dialogues) == 4

    # Primera línea: activa "EL" con estilo Hormozi
    assert f"Dialogue: 0,0:00:00.00,0:00:00.50,{preset['name']}" in dialogues[0]
    assert r"{\c&H0000D7FF&\fscx115\fscy115}EL{\r}" in dialogues[0]
    assert "SECRETO" in dialogues[0]

    # Segunda línea: activa "SECRETO"
    assert f"Dialogue: 0,0:00:00.50,0:00:01.20,{preset['name']}" in dialogues[1]
    assert r"{\c&H0000D7FF&\fscx115\fscy115}SECRETO" in dialogues[1]


def test_write_ass_file_generation():
    """Valida la escritura atómica de un archivo .ass con múltiples escenas."""
    with tempfile.TemporaryDirectory() as td:
        run_dir = Path(td)
        scenes = [
            {"duration_sec": 3.0, "subtitle_text": "Aprende a programar ahora"},
            {"duration_sec": 2.5, "subtitle_text": "Construye tu propio futuro"},
        ]

        ass_path = karaoke_subtitles.write_ass(run_dir, scenes, style_name="cyberpunk")
        assert ass_path.is_file()
        assert ass_path.name == "final_captions.ass"

        content = ass_path.read_text(encoding="utf-8")
        assert "[Script Info]" in content
        assert "Style: Cyberpunk" in content
        assert "APRENDE" in content
        assert "CONSTRUYE" in content
        # Magenta cyberpunk
        assert "&H00FF00FF&" in content


def test_assembler_karaoke_integration():
    """Valida que video_assembler aplique karaoke .ass si el manifest lo solicita."""
    with tempfile.TemporaryDirectory() as td:
        run_dir = Path(td)
        manifest = {
            "run_id": "test_karaoke_run",
            "format": "short",
            "resolution": "1080x1920",
            "fps": 30,
            "subtitle_style": "mrbeast",
            "scenes": [
                {
                    "scene_id": "sc1",
                    "status": "ready",
                    "duration_sec": 3.0,
                    "has_video": False,
                    "has_audio": False,
                    "image_path": "scene_001.png",
                    "subtitle_text": "Video con subtítulos virales"
                }
            ]
        }

        # Mock de has_filter para simular ffmpeg con libass
        with patch.object(video_assembler, "has_filter", return_value=True):
            plan = video_assembler.plan_render(manifest, run_dir, subtitles="burn")
            sub_step = [s for s in plan["steps"] if s["stage"] == "subtitles"]
            assert len(sub_step) == 1
            cmd_str = " ".join(sub_step[0]["cmd"])
            # Debe quemar final_captions.ass
            assert "final_captions.ass" in cmd_str
            assert (run_dir / "final_captions.ass").is_file()
