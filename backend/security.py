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


# ── safe_url / safe_filename — guardia de contenido externo (§seguridad) ──
# TODO contenido externo (URL de imagen de la extensión, probe HTTP del
# Doctor) se considera NO confiable: solo http/https hacia hosts públicos,
# sin credenciales en la URL y con CADA redirección revalidada (anti-SSRF:
# antes un URL `file://` o `http://127.0.0.1:8000/api/config` suministrado
# por el usuario se descargaba y servía como imagen de escena).
import ipaddress  # noqa: E402
import re as _re  # noqa: E402
import socket  # noqa: E402
import urllib.parse as _up  # noqa: E402
import urllib.request as _urq  # noqa: E402

_FILENAME_RE = _re.compile(r"^[A-Za-z0-9._-]{1,120}$")


class _SafeRedirectHandler(_urq.HTTPRedirectHandler):
    """Redirecciones revalidadas: cada salto pasa por la misma guardia."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validar_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validar_url(url: str) -> str:
    """Valida una URL externa y la devuelve si es segura. Lanza ValueError.

    Reglas: esquema http/https exclusivamente; sin usuario/contraseña;
    el host (literal o resuelto) NUNCA puede ser loopback/privado/link-local/
    reservado/multicast/no especificado. Nota honesta: esto bloquea el SSRF
    por resolución; un atacante con DNS rebinding (cambia la IP entre la
    validación y la conexión) queda fuera del alcance de esta guardia mínima
    — el egress real de producción debería complementarlo con firewall."""
    u = (url or "").strip()
    p = _up.urlparse(u)
    if p.scheme not in ("http", "https"):
        raise ValueError(f"esquema no permitido: {p.scheme or '(vacío)'} "
                         "(solo http/https)")
    if p.username or p.password:
        raise ValueError("URL con credenciales incrustadas no permitida")
    host = p.hostname
    if not host:
        raise ValueError("URL sin host")
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as e:
        raise ValueError(f"host no resoluble: {host} ({e.__class__.__name__})") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ValueError(f"dirección no permitida ({host} → {ip}): "
                             "solo hosts públicos")
    return u


def safe_url(url: str) -> str:
    """Alias público de validar_url (documentación en validar_url)."""
    return validar_url(url)


_OPENER = _urq.build_opener(_SafeRedirectHandler)


def safe_fetch_bytes(url: str, timeout: float = 30.0,
                     headers: dict | None = None) -> bytes:
    """Descarga bytes de una URL validada (anti-SSRF, redirecciones
    revalidadas). Lanza ValueError si la URL no pasa la guardia."""
    target = validar_url(url)
    req = _urq.Request(target, headers=headers or {"User-Agent": "Mozilla/5.0"})
    with _OPENER.open(req, timeout=timeout) as resp:
        return resp.read()


def safe_filename(name: str) -> str:
    """Nombre de archivo de origen NO confiable → base segura.

    Devuelve solo el basename y valida la lista blanca [A-Za-z0-9._-]
    (anti path-traversal). Los puntos iniciales se rechazan (hidden files:
    «../../.env» se reduce a «.env» y se descarta). Lanza ValueError si el
    nombre no puede sanearse. Nota honesta: con el prefijo uuid del caller
    («voice_upload_<uuid>_»), incluso un basename válido no puede escapar
    del directorio destino; la guardia de puntos es defensa en profundidad."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not base or base.startswith(".") or not _FILENAME_RE.fullmatch(base):
        raise ValueError(f"nombre de archivo inválido: {(name or '')[:80]!r} "
                         "(usa A-Z a-z 0-9 . _ - sin puntos iniciales)")
    return base
