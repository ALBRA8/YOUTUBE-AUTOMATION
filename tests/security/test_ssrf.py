"""
PHASE 1 · A1/A8 — REGRESIÓN RUNTIME de la política SSRF central.

La guardia (validar_url + _SafeRedirectHandler + safe_urlopen) resuelve
DNS y bloquea loopback/privada/link-local/metadatos/IPv6-equivalente ANTES
del request inicial Y en CADA redirect; yt-dlp (url_mode) pasa por la
misma política. Incluye sonda HTTP REAL contra servidor loopback vivo.
Windows-safe.
"""
import asyncio
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="p1sec_ssrf_"))
import config as _cfg  # noqa: E402

_cfg.DB_PATH = _TMP / "t.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import security as _sec  # noqa: E402
from services.production_doctor import layers as _layers  # noqa: E402
from services import url_mode  # noqa: E402

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


def _rechaza(url, allow_private=False):
    try:
        _sec.validar_url(url, allow_private=allow_private)
        return False
    except ValueError:
        return True


# ── matriz A1: destinos prohibidos (resolución DNS real incluida) ──
for nombre, url in [
    ("loopback IPv4", "http://127.0.0.1/x"),
    ("localhost (resuelve a loopback)", "http://localhost/x"),
    ("rango 127/8", "http://127.8.8.8/x"),
    ("privada 192.168", "http://192.168.1.5/x"),
    ("privada 10/8", "http://10.0.0.1/x"),
    ("privada 172.16/12", "http://172.16.0.9/x"),
    ("link-local / metadatos 169.254", "http://169.254.169.254/latest/meta-data/"),
    ("0.0.0.0 (unspecified)", "http://0.0.0.0/x"),
    ("IPv6 loopback ::1", "http://[::1]/x"),
    ("IPv4-mapped-IPv6 ::ffff:127.0.0.1", "http://[::ffff:127.0.0.1]/x"),
    ("IPv6 privada fc00", "http://[fc00::1]/x"),
    ("credenciales embebidas", "http://user:pass@example.com/x"),
    ("esquema file://", "file:///etc/passwd"),
    ("esquema ftp", "ftp://example.com/x"),
]:
    check(f"validar_url rechaza {nombre}", _rechaza(url))

# allow_private solo relaja privada/loopback — JAMÁS link-local/metadatos
check("allow_private=True permite 127.0.0.1 (sonda del backend propio)",
      not _rechaza("http://127.0.0.1:8000/api/health", allow_private=True))
check("allow_private=True SIGUE bloqueando 169.254 (metadatos)",
      _rechaza("http://169.254.169.254/x", allow_private=True))
check("allow_private=True SIGUE bloqueando 0.0.0.0",
      _rechaza("http://0.0.0.0/x", allow_private=True))

# hostname público: allow solo si este entorno tiene DNS (honesto)
try:
    socket.getaddrinfo("example.com", None)
    dns_ok = True
except OSError:
    dns_ok = False
if dns_ok:
    check("validar_url permite host público con DNS real",
          not _rechaza("https://example.com/"))
else:
    print("· (sin DNS en este entorno: caso allow-público omitido)")

# ── redirect revalidado (unit): cada salto pasa por la guardia ──
class _FakeReq:
    timeout = None


_handler = _sec._SafeRedirectHandler()
for nombre, newurl in [("redirect → 192.168.x.x", "http://192.168.0.44/x"),
                       ("redirect → 127.0.0.1", "http://127.0.0.1:9000/x"),
                       ("redirect → 169.254 metadatos", "http://169.254.169.254/x")]:
    try:
        _handler.redirect_request(_FakeReq(), None, 302, "Found", {}, newurl)
        check(f"_SafeRedirectHandler bloquea {nombre}", False)
    except ValueError:
        check(f"_SafeRedirectHandler bloquea {nombre}", True)

# ── sonda HTTP REAL: servidor loopback que redirige a metadatos ──
class _Redir(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
        self.end_headers()

    def log_message(self, *a):  # silencio
        pass


_srv = HTTPServer(("127.0.0.1", 0), _Redir)
_port = _srv.server_address[1]
threading.Thread(target=_srv.serve_forever, daemon=True).start()
try:
    ok, detail = _layers._http_probe(f"http://127.0.0.1:{_port}/redir",
                                     timeout=3.0, trusted_private=True)
    check("sonda REAL: redirect público/propio → metadatos 169.254 BLOQUEADO",
          ok is False and ("ValueError" in detail or "dirección" in detail
                           or "rechazada" in detail or "no permitida" in detail),
          detail[:100])
    # sin trusted_private, la URL loopback inicial ni siquiera pasa la guardia
    ok2, detail2 = _layers._http_probe(f"http://127.0.0.1:{_port}/redir",
                                       timeout=3.0, trusted_private=False)
    check("sonda REAL: loopback con guardia estricta → rechazo inicial",
          ok2 is False and "guardia" in detail2.lower(), detail2[:100])
finally:
    _srv.shutdown()

# ── A8: yt-dlp (url_mode) pasa por la MISMA política ──
for nombre, url in [("file://", "file:///etc/passwd"),
                    ("metadatos", "http://169.254.169.254/x"),
                    ("LAN privada", "http://192.168.1.50/video")]:
    try:
        url_mode._guard_ssrf(url)
        check(f"url_mode._guard_ssrf rechaza {nombre}", False)
    except ValueError:
        check(f"url_mode._guard_ssrf rechaza {nombre}", True)

try:
    asyncio.run(url_mode.transcript_from_url("file:///etc/passwd", "p1t"))
    check("transcript_from_url(file://) NO ejecuta yt-dlp (rechaza antes)", False)
except Exception as e:  # noqa: BLE001 — ValueError/UrlModeError aceptables
    check("transcript_from_url(file://) NO ejecuta yt-dlp (rechaza antes)",
          type(e).__name__ in ("ValueError", "UrlModeError"),
          type(e).__name__)

print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
