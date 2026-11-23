"""[D7] Guardia de red HERMÉTICA — sitecustomize real.

`tests/run_all.py --hermetica/--hermetic` antepone ESTE directorio al
PYTHONPATH de cada hijo; Python lo autoimporta al arrancar (módulo
`sitecustomize` del `site`) y parchea `socket.socket.connect` para QUEMAR
toda CONEXIÓN a hosts NO loopback. Loopback (127.0.0.0/8, ::1,
"localhost") sigue funcionando: las baterías de seguridad usan servidores
HTTP reales en 127.0.0.1 y deben seguir verdes bajo --hermetica.

DECISIÓN DE DISEÑO (medida, no cosmética): `socket.getaddrinfo` NO se
bloquea — el validador anti-SSRF del producto (`security.validar_url`)
resuelve el host para INSPECCIONAR la IP y decidir (es la unidad bajo
test; bloquearle el DNS cambiaría su semántica bajo guardia). La
protección real está en `connect()`: sin conexión TCP externa no hay
descarga ni llamada externa — una descarga HTTP real falla SIEMPRE con
«[h[hermética D7] red externa BLOQUEADA» en el connect.

Aceptación literal del cierre: con la guardia, una descarga HTTP real
(p. ej. http://example.com) DEBE fallar; sin la guardia, funciona.
"""
from __future__ import annotations

import ipaddress
import socket

_orig_getaddrinfo = socket.getaddrinfo
_orig_connect = socket.socket.connect

_HOSTS_LOCALES = {"localhost", ""}


def _es_local(host) -> bool:
    """True para loopback explícito (literal IP de loopback o 'localhost')."""
    if host is None:
        return False
    if isinstance(host, str):
        h = host.strip("[]").lower()
        if h in _HOSTS_LOCALES:
            return True
        try:
            return ipaddress.ip_address(h).is_loopback
        except ValueError:
            return False
    # connect también acepta bytes o enteros
    try:
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def _connect_guardado(self, address):
    host = address[0] if isinstance(address, tuple) and address else None
    if isinstance(host, str) and not _es_local(host):
        raise OSError(
            13, f"[h[hermética D7] red externa BLOQUEADA: connect({host!r}) "
                f"(corrida --hermetica; solo loopback está permitido)")
    return _orig_connect(self, address)


socket.socket.connect = _connect_guardado
