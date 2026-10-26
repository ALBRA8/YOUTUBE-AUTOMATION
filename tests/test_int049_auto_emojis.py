"""
Unit tests for INT-049: Auto Emojis in Subtitles (CapCut / OpusClip Style)
"""
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.karaoke_subtitles import (
    detect_emoji,
    build_karaoke_dialogues,
    build_ass_from_scenes,
    get_preset,
    EMOJI_KEYWORDS
)

def test_detect_emoji_semantic_categories():
    """Verify detect_emoji matches viral keywords across multiple categories."""
    assert detect_emoji("dinero") == "💰"
    assert detect_emoji("¡DINERO!") == "💰"
    assert detect_emoji("fuego...") == "🔥"
    assert detect_emoji("secreto") == "🤫"
    assert detect_emoji("millones") == "💸"
    assert detect_emoji("peligro") == "⚠️"
    assert detect_emoji("cerebro") == "🧠"
    assert detect_emoji("podcast") == "🎙️"
    assert detect_emoji("palabra_desconocida_xyz") is None

def test_build_karaoke_dialogues_includes_emojis_when_enabled():
    """Verify build_karaoke_dialogues attaches emojis to matched words when auto_emojis=True."""
    preset = get_preset("hormozi")
    words = [
        {"word": "El", "start": 0.0, "end": 0.3},
        {"word": "secreto", "start": 0.3, "end": 0.8},
        {"word": "del", "start": 0.8, "end": 1.0},
        {"word": "dinero", "start": 1.0, "end": 1.5},
    ]

    dialogues = build_karaoke_dialogues(words, preset, auto_emojis=True)
    assert len(dialogues) == 4
    full_text = " ".join(dialogues)
    assert "SECRETO 🤫" in full_text
    assert "DINERO 💰" in full_text

def test_build_karaoke_dialogues_skips_emojis_when_disabled():
    """Verify build_karaoke_dialogues outputs clean text when auto_emojis=False."""
    preset = get_preset("hormozi")
    words = [
        {"word": "secreto", "start": 0.0, "end": 0.5},
        {"word": "dinero", "start": 0.5, "end": 1.0},
    ]

    dialogues = build_karaoke_dialogues(words, preset, auto_emojis=False)
    full_text = " ".join(dialogues)
    assert "🤫" not in full_text
    assert "💰" not in full_text
    assert "SECRETO" in full_text
    assert "DINERO" in full_text

def test_build_ass_from_scenes_with_auto_emojis():
    """Verify build_ass_from_scenes injects emojis and contains Segoe UI Emoji in header."""
    scenes = [
        {"duration_sec": 3.0, "subtitle_text": "Este es el truco para ganar en la vida"}
    ]
    ass_content = build_ass_from_scenes(scenes, style_name="mrbeast", resolution="1080x1920", auto_emojis=True)
    assert "Segoe UI Emoji" in ass_content
    # 'truco' -> ✨, 'ganar' -> 🏆
    assert "✨" in ass_content or "🏆" in ass_content
