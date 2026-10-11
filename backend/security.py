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


def validar_url(url: str, allow_private: bool = False) -> str:
    """Valida una URL externa y la devuelve si es segura. Lanza ValueError.

    Reglas: esquema http/https exclusivamente; sin usuario/contraseña;
    el host (literal o resuelto) NUNCA puede ser loopback/privado/link-local/
    reservado/multicast/no especificado. Nota honesta: esto bloquea el SSRF
    por resolución; un atacante con DNS rebinding (cambia la IP entre la
    validación y la conexión) queda fuera del alcance de esta guardia mínima
    — el egress real de producción debería complementarlo con firewall.

    allow_private=True (solo para objetivos PROPIOS de primera parte, p.ej.
    la sonda del Doctor contra su propio backend en 127.0.0.1:PORT, cuyo
    host nace de config y no del llamador): relaja ÚNICAMENTE
    is_private/is_loopback. Link-local (169.254.x — metadatos cloud),
    reservadas, multicast y no especificadas siguen PROHIBIDAS incluso con
    allow_private=True. Nunca exponer este flag a entradas de usuario."""
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
        prohibida = (ip.is_link_local or ip.is_reserved or ip.is_multicast
                     or ip.is_unspecified)
        if not allow_private:
            prohibida = prohibida or ip.is_private or ip.is_loopback
        if prohibida:
            raise ValueError(f"dirección no permitida ({host} → {ip}): "
                             "solo hosts públicos")
    return u


def safe_url(url: str, allow_private: bool = False) -> str:
    """Alias público de validar_url (documentación en validar_url)."""
    return validar_url(url, allow_private=allow_private)


_OPENER = _urq.build_opener(_SafeRedirectHandler)


def safe_fetch_bytes(url: str, timeout: float = 30.0,
                     headers: dict | None = None,
                     max_bytes: int | None = None) -> bytes:
    """Descarga bytes de una URL validada (anti-SSRF, redirecciones
    revalidadas). Lanza ValueError si la URL no pasa la guardia o si la
    descarga excede max_bytes (anti-DoS: sin tope, un host «público» podía
    verter GBs a RAM)."""
    target = validar_url(url)
    req = _urq.Request(target, headers=headers or {"User-Agent": "Mozilla/5.0"})
    with _OPENER.open(req, timeout=timeout) as resp:
        if max_bytes:
            data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError(f"descarga demasiado grande (> {max_bytes} bytes)")
            return data
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


# ── PHASE 1 (security hardening) · política central de Project ID, ──────────
# contención de rutas, SSRF central, valores .env y política de origen.
# Helpers ÚNICOS y reutilizables: ningún endpoint duplica estas reglas.

from pathlib import Path as _Path  # noqa: E402

# Formato canónico = database.new_id() → uuid4().hex[:12]. Un ID que no
# calce NO puede existir ni en la DB ni en disco: este único regex rechaza
# de paso traversal («..», «..%2f», «..\\»), paths absolutos, slashes,
# NUL y cualquier carácter inesperado (C1/M5 — sin duplicar regex).
PROJECT_ID_RE = _re.compile(r"^[0-9a-f]{12}$")


def validate_project_id(pid: str) -> str:
    """Valida el formato canónico de project_id (12 hex). Lanza ValueError.

    Fail-closed: «..», «../..», «..\\», «%2e%2e» (ya decodificado por el
    router), paths absolutos y IDs inexistentes en formato no llegan NUNCA
    a construir una ruta de filesystem."""
    p = str(pid or "").strip()
    if not PROJECT_ID_RE.fullmatch(p):
        raise ValueError(f"project_id inválido: {str(pid)[:80]!r}")
    return p


def safe_project_output_dir(pid: str, must_exist: bool = False,
                            root=None) -> _Path:
    """Ruta de salida del proyecto VALIDADA Y CONTENIDA (fail-closed).

    1) valida el formato del ID (validate_project_id);
    2) resuelve la ruta final (OUTPUT_DIR / pid).resolve();
    3) comprueba contención ESTRICTA dentro de (OUTPUT_DIR).resolve();
    4) opcionalmente exige que el directorio exista (must_exist=True).

    Solo después de estos pasos puede el caller operar filesystem
    (rmtree/read/write). Lanza ValueError en cualquier anomalía."""
    root_path = _Path(root).resolve() if root is not None \
        else _Path(_output_root()).resolve()
    p = validate_project_id(pid)
    target = (root_path / p).resolve()
    if target == root_path or root_path not in target.parents:
        raise ValueError("ruta fuera del directorio de salida del proyecto")
    if must_exist and not target.is_dir():
        raise ValueError("el proyecto no tiene directorio de salida")
    return target


def _output_root() -> str:
    """Raíz de salida (import perezoso para evitar ciclos config↔security)."""
    import config as _cfg
    return str(_cfg.OUTPUT_DIR)


def validate_env_value(key: str, value) -> str:
    """A2 · validación central de valores destinados a .env.

    Rechaza EXPLÍCITAMENTE (ValueError, sin sanitizar en silencio) cualquier
    valor con \\r, \\n o NUL: permitiría inyectar entradas nuevas en .env
    («x\\nMASTER_API_KEY=pwn»). Toda escritura de config pasa por aquí."""
    v = str(value)
    if ("\n" in v) or ("\r" in v) or ("\x00" in v):
        raise ValueError(f"valor de {key} inválido: saltos de línea/NUL "
                         "no permitidos en configuración")
    return v


# ── A1 · SSRF central: apertura con redirects revalidados ───────────────────
def safe_urlopen(url: str, timeout: float = 30.0, allow_private: bool = False,
                 headers: dict | None = None):
    """Abre una URL validada con el opener cuya _SafeRedirectHandler
    revalida CADA salto (anti-SSRF: request inicial Y cada redirect pasan
    por validar_url). Devuelve el objeto respuesta (context manager).
    Toda sonda/fetch HTTP del backend debe usar esto o safe_fetch_bytes —
    nunca urllib.request.urlopen directo."""
    target = validar_url(url, allow_private=allow_private)
    req = _urq.Request(target, headers=headers or {"User-Agent": "Mozilla/5.0"})
    return _OPENER.open(req, timeout=timeout)


# ── M2 · política de origen para mutaciones (CSRF) ──────────────────────────
_LOCAL_ORIGIN_RE = _re.compile(
    r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$", _re.IGNORECASE)
_EXT_ORIGIN_RE = _re.compile(r"^chrome-extension://[a-p]+$", _re.IGNORECASE)


def origin_allowed(origin: str, request_host: str) -> bool:
    """¿Puede ESTE origen lanzar una mutación al API?

    Permite: (1) mismo host que el request (dashboard same-origin);
    (2) clientes locales http(s)://localhost|127.0.0.1|[::1]:puerto;
    (3) la extensión Chrome (chrome-extension:// con ID válido).
    Rechaza todo lo demás (p. ej. https://evil.example). Un request SIN
    Origin/Referer (curl, workers, API clientes) se decide en el middleware:
    se PERMITE para conservar la compatibilidad de clientes no-navegador —
    el navegador jamás omite Origin en mutaciones cross-site."""
    o = (origin or "").strip()
    if not o or o.lower() == "null":
        return False
    p = _up.urlparse(o)
    if p.scheme not in ("http", "https", "chrome-extension"):
        return False
    netloc = (p.netloc or "").lower()
    origin_host = netloc.rsplit(":", 1)[0].strip("[]") if netloc else ""
    host_only = (request_host or "").rsplit(":", 1)[0].strip("[]").lower()
    if origin_host and origin_host == host_only:
        return True
    if p.scheme == "chrome-extension":
        return bool(_EXT_ORIGIN_RE.match(o))
    return bool(_LOCAL_ORIGIN_RE.match(o))


def harden_pil(max_pixels: int) -> int:
    """M10 · anti bomba de descompresión: fija el techo global de píxeles
    de Pillow. Image.open sobre una imagen que DECLARE más del doble lanza
    DecompressionBombError (→ los callers la convierten en 4xx/422).
    Idempotente; devuelve el límite aplicado (0 si PIL no está instalada)."""
    try:
        from PIL import Image as _Img
        _Img.MAX_IMAGE_PIXELS = int(max_pixels)
        return int(max_pixels)
    except Exception:  # noqa: BLE001 — PIL ausente: nada que endurecer
        return 0
