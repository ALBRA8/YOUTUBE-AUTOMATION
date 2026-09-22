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
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

# ── Claves API (todas opcionales: el sistema degrada con gracia) ──────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# ── Modelos Gemini ────────────────────────────────────────────────────────
GEMINI_TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-3.6-flash")
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


# ── Escritura en vivo desde el dashboard (⚙️ Configuración) ──────────────
# Claves que el dashboard puede escribir en .env. SECRET_KEYS se enmascaran
# al leerlas por la API (nunca se devuelven completas).
EDITABLE_KEYS = (
    "GEMINI_API_KEY", "TTS_PROVIDER", "EDGE_TTS_VOICE", "GEMINI_TTS_VOICE",
    "TTS_RATE", "WHISPER_MODEL", "WHISPER_DEVICE", "FPS",
)
SECRET_KEYS = {"GEMINI_API_KEY"}


def reload() -> None:
    """Relee .env y actualiza las variables globales de este módulo.
    Permite cambiar claves/ajustes desde el dashboard SIN reiniciar."""
    global GEMINI_API_KEY, GEMINI_TEXT_MODEL, GEMINI_IMAGE_MODEL
    global GEMINI_TTS_MODEL, GEMINI_TTS_VOICE, TTS_PROVIDER, EDGE_TTS_VOICE
    global TTS_RATE, WHISPER_MODEL, WHISPER_DEVICE, FPS
    load_dotenv(ENV_PATH, override=True)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-3.6-flash")
    GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
    GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
    GEMINI_TTS_VOICE = os.getenv("GEMINI_TTS_VOICE", "Fenrir")
    TTS_PROVIDER = os.getenv("TTS_PROVIDER", "edge").strip().lower() or "edge"
    EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "es-CO-SalomeNeural")
    TTS_RATE = os.getenv("TTS_RATE", "+8%")
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
    WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
    try:
        FPS = int(os.getenv("FPS", "30"))
    except ValueError:
        FPS = 30


def save_env(updates: dict) -> list[str]:
    """Escribe pares clave=valor en .env (conserva comentarios y orden) y
    recarga la configuración en memoria. Devuelve la lista de claves guardadas."""
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else [
        "# YOUTUBE AUTOMATION v2.0 — configuración (generada desde el dashboard)"]
    saved = []
    for key, value in updates.items():
        if key not in EDITABLE_KEYS:
            continue
        saved.append(key)
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}=") or line.strip().startswith(f"{key} ="):
                lines[i] = f"{key}={value}"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    reload()
    return saved
