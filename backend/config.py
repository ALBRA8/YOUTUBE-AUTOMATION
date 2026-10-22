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

FLOW_MCP_ENABLED = os.getenv("FLOW_MCP_ENABLED", "0").strip().lower() in ("1", "true", "yes")
FLOW_MCP_VIDEO_ENABLED = os.getenv("FLOW_MCP_VIDEO_ENABLED", "0").strip().lower() in ("1", "true", "yes")
FLOW_MCP_DIR = Path(os.getenv("FLOW_MCP_DIR", str(BASE_DIR.parent / "tools" / "GoogleFlowMCP"))).resolve()
FLOW_MCP_MODEL = os.getenv("FLOW_MCP_MODEL", "2").strip()
FLOW_MCP_TIMEOUT = float(os.getenv("FLOW_MCP_TIMEOUT", "120.0"))

# ── NVIDIA NIM (agente VÓRTICE · OpenAI-compatible) ───────────────────────
# kimi-k3: planificación del agente, entiende el proyecto y ejecuta acciones
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "").strip()
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "moonshotai/kimi-k3").strip()
NVIDIA_BASE_URL = os.getenv(
    "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").strip().rstrip("/")
NVIDIA_FALLBACK_MODELS = [
    m.strip() for m in os.getenv(
        "NVIDIA_FALLBACK_MODELS",
        "deepseek-ai/deepseek-v4.1-flash,moonshotai/kimi-k2.6").split(",") if m.strip()]

# ── Modelos Gemini ────────────────────────────────────────────────────────
# gemini-2.5-flash: modelo REAL con generosa cuota gratuita (el default
# anterior "gemini-3.6-flash" no existe en la API → HTTP 404 Model Not Found)
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

# ── PHASE 1 (security) · límites de entrada — configurables vía .env, ──────
# seguros por defecto. Un input que exceda un límite produce SIEMPRE un
# error controlado 4xx (nunca 500 ni consumo ilimitado). Se leen en el
# momento de la llamada (no por valor en import) para que tests y operator
# puedan ajustarlos en runtime.
def _lim(name: str, default: int) -> int:
    try:
        v = int(os.getenv(name, str(default)))
        return v if v > 0 else default
    except ValueError:
        return default


LIMITS = {
    "MAX_BODY_BYTES": _lim("MAX_BODY_BYTES", 64 * 1024 * 1024),          # body HTTP global
    "MAX_UPLOAD_JSON_BYTES": _lim("MAX_UPLOAD_JSON_BYTES", 2 * 1024 * 1024),   # client_secret.json
    "MAX_ZIP_COMPRESSED_BYTES": _lim("MAX_ZIP_COMPRESSED_BYTES", 150 * 1024 * 1024),  # A7
    "MAX_ZIP_UNCOMPRESSED_BYTES": _lim("MAX_ZIP_UNCOMPRESSED_BYTES", 600 * 1024 * 1024),  # A7
    "MAX_ZIP_FILES": _lim("MAX_ZIP_FILES", 300),                        # A7
    "MAX_IMAGE_PIXELS": _lim("MAX_IMAGE_PIXELS", 40_000_000),           # M10 bomba descompresión
    "MAX_PRODUCTION_UNITS": _lim("MAX_PRODUCTION_UNITS", 40),           # A9 (≈ guion_json MAX_ESCENAS)
    "FLOW_JOB_BODY_BYTES": _lim("FLOW_JOB_BODY_BYTES", 64 * 1024 * 1024),      # complete binario
    "FLOW_JOBS_RETENTION_DAYS": _lim("FLOW_JOBS_RETENTION_DAYS", 30),   # M11 done/dead
    "LEDGER_MAX_LINES": _lim("LEDGER_MAX_LINES", 5000),                 # M11 ledger adaptación
}


def ffmpeg() -> str:
    return FFMPEG_BIN


# ── Escritura en vivo desde el dashboard (⚙️ Configuración) ──────────────
# Claves que el dashboard puede escribir en .env. SECRET_KEYS se enmascaran
# al leerlas por la API (nunca se devuelven completas).
EDITABLE_KEYS = (
    "GEMINI_API_KEY", "NVIDIA_API_KEY", "NVIDIA_MODEL", "TTS_PROVIDER",
    "EDGE_TTS_VOICE", "GEMINI_TTS_VOICE", "TTS_RATE", "WHISPER_MODEL",
    "WHISPER_DEVICE", "FPS",
)
SECRET_KEYS = {"GEMINI_API_KEY", "NVIDIA_API_KEY"}


def reload() -> None:
    """Relee .env y actualiza las variables globales de este módulo.
    Permite cambiar claves/ajustes desde el dashboard SIN reiniciar."""
    global GEMINI_API_KEY, GEMINI_TEXT_MODEL, GEMINI_IMAGE_MODEL
    global GEMINI_TTS_MODEL, GEMINI_TTS_VOICE, TTS_PROVIDER, EDGE_TTS_VOICE
    global TTS_RATE, WHISPER_MODEL, WHISPER_DEVICE, FPS
    global NVIDIA_API_KEY, NVIDIA_MODEL, NVIDIA_BASE_URL
    global FLOW_MCP_ENABLED, FLOW_MCP_DIR, FLOW_MCP_MODEL, FLOW_MCP_TIMEOUT, FLOW_MCP_VIDEO_ENABLED
    load_dotenv(ENV_PATH, override=True)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

    FLOW_MCP_ENABLED = os.getenv("FLOW_MCP_ENABLED", "0").strip().lower() in ("1", "true", "yes")
    FLOW_MCP_VIDEO_ENABLED = os.getenv("FLOW_MCP_VIDEO_ENABLED", "0").strip().lower() in ("1", "true", "yes")
    FLOW_MCP_DIR = Path(os.getenv("FLOW_MCP_DIR", str(BASE_DIR.parent / "tools" / "GoogleFlowMCP"))).resolve()
    FLOW_MCP_MODEL = os.getenv("FLOW_MCP_MODEL", "2").strip()
    FLOW_MCP_TIMEOUT = float(os.getenv("FLOW_MCP_TIMEOUT", "120.0"))
    NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "").strip()
    NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "moonshotai/kimi-k3").strip()
    NVIDIA_BASE_URL = os.getenv(
        "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").strip().rstrip("/")
    globals()["NVIDIA_FALLBACK_MODELS"] = [
        m.strip() for m in os.getenv(
            "NVIDIA_FALLBACK_MODELS",
            "deepseek-ai/deepseek-v4.1-flash,moonshotai/kimi-k2.6").split(",") if m.strip()]
    GEMINI_TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
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
    recarga la configuración en memoria. Devuelve la lista de claves guardadas.

    PHASE 1 · A2: un valor con salto de línea permitiría INYECTAR variables
    nuevas en .env («x\nMASTER_API_KEY=pwn\nNVIDIA_BASE_URL=http://atacante»
    escribiría 3 entradas). La validación central vive en
    security.validate_env_value y se rechaza de forma EXPLÍCITA (ValueError)
    — nunca se sanitiza en silencio."""
    import security as _sec
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else [
        "# YOUTUBE AUTOMATION v2.0 — configuración (generada desde el dashboard)"]
    saved = []
    for key, value in updates.items():
        if key not in EDITABLE_KEYS:
            continue
        _sec.validate_env_value(key, value)  # A2: rechaza \r / \n / NUL
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
