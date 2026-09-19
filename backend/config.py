"""
YOUTUBE AUTOMATION v2.0 — Configuración central
Carga .env y define rutas de trabajo. Coste objetivo por video: $0.00
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = DATA_DIR / "output"
TMP_DIR = DATA_DIR / "tmp"
for d in (DATA_DIR, OUTPUT_DIR, TMP_DIR):
    d.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "yt_automation.db"
load_dotenv(BASE_DIR / ".env")

# ── Claves API (todas opcionales: el sistema degrada con gracia) ──────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# ── Modelos Gemini ────────────────────────────────────────────────────────
GEMINI_TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")

# ── TTS ───────────────────────────────────────────────────────────────────
# Proveedor: "gemini" (voz premium Fenrir) o "edge" (gratuito ilimitado)
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "edge")  # edge | gemini
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "es-CO-SalomeNeural")
GEMINI_TTS_VOICE = os.getenv("GEMINI_TTS_VOICE", "Fenrir")
TTS_RATE = os.getenv("TTS_RATE", "+8%")

# ── Whisper (alineación palabra a palabra) ────────────────────────────────
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")  # tiny|base|small|medium
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")  # cpu | cuda

# ── Video ─────────────────────────────────────────────────────────────────
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
FPS = int(os.getenv("FPS", "30"))
SHORT_W, SHORT_H = 1080, 1920     # 9:16
LONG_W, LONG_H = 1920, 1080       # 16:9
MUSIC_VOLUME = 0.18
MUSIC_DIR = DATA_DIR / "music"
MUSIC_DIR.mkdir(exist_ok=True)

# ── Modo fábrica ──────────────────────────────────────────────────────────
FACTORY_TIMES = [t.strip() for t in os.getenv(
    "FACTORY_TIMES", "07:00,12:30,19:00").split(",") if t.strip()]
FACTORY_TIMEZONE = os.getenv("FACTORY_TIMEZONE", "America/Bogota")
FACTORY_NICHE = os.getenv("FACTORY_NICHE", "historias reales impactantes")
FACTORY_AUTOPUBLISH = os.getenv("FACTORY_AUTOPUBLISH", "false").lower() == "true"

# ── YouTube (autopublish opcional) ────────────────────────────────────────
YT_CLIENT_SECRET = str(DATA_DIR / "client_secret.json")
YT_TOKEN_FILE = str(DATA_DIR / "token.json")

# ── Servidor ──────────────────────────────────────────────────────────────
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))


def ffmpeg() -> str:
    return FFMPEG_BIN
