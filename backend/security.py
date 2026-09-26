"""
YOUTUBE AUTOMATION v2.0 — Clave maestra opcional (blindaje del panel)

Por defecto el servidor escucha en 127.0.0.1 y funciona ABIERTO (modo local,
como OBS o Jupyter). Si vas a exponerlo a internet (VPS, LAN compartida),
define MASTER_API_KEY en backend/.env y TODAS las rutas /api/* exigirán la
clave. Aceptada por 4 vías para cubrir todos los clientes del sistema:

  1. Header   X-API-Key: <clave>            (dashboard, scripts, curl)
  2. Header   Authorization: Bearer <clave> (clientes estándar)
  3. Cookie   yta-master-key=<clave>        (EventSource/SSE no puede poner
                                             headers → usa cookies same-origin)
  4. Query    ?api_key=<clave>              (última opción para clientes
                                             limitados; evítala en logs)

Sin MASTER_API_KEY definida, enabled() devuelve False y el middleware no
bloquea nada (comportamiento histórico, cero ruptura para el usuario local).
La clave NUNCA se sirve por la API: /api/auth/status solo revela si hace falta.
"""
import hmac
import os

COOKIE_NAME = "yta-master-key"
# Rutas que deben responder sin clave: health (monitorización) y el propio
# descubrimiento de si hace falta login.
PUBLIC_PATHS = {"/api/health", "/api/auth/status"}

_key = ""


def reload() -> None:
    """Relee MASTER_API_KEY del entorno (config.load_dotenv ya corrió)."""
    global _key
    _key = os.getenv("MASTER_API_KEY", "").strip()


reload()


def enabled() -> bool:
    return bool(_key)


def verify(provided: str) -> bool:
    """Comparación en tiempo constante (evita oracle de timing)."""
    if not _key:
        return True
    return hmac.compare_digest((provided or "").strip(), _key)
