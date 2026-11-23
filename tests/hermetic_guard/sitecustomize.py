"""[D7] Guardia de red HERMÉTICA — sitecustomize real.

`tests/run_all.py --hermetica` antepone ESTE directorio al PYTHONPATH de cada
hijo; Python lo autoimporta al arrancar (módulo `sitecustomize` del `site`)
y parchea socket.getaddrinfo y socket.socket.connect para QUEMAR toda
conexión a hosts NO loopback. Loopback (127.0.0.0/8, ::1, "localhost")
sigue funcionando: las baterías de seguridad usan servidores HTTP reales en
127.0.0.1 y deben seguir verdes bajo --hermetica.

Aceptación literal del cierre: con la guardia, una descarga HTTP real
(p. ej. http://example.com) DEBE fallar con un error "[hermética]"; sin la
guardia, funciona.
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
    # getaddrinfo también acepta bytes o enteros
    try:
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def _getaddrinfo_guardado(host, *args, **kwargs):
    if not _es_local(host):
        raise OSError(
            13, f"[hermética D7] red externa BLOQUEADA: getaddrinfo({host!r}) "
                f"(corrida --hermetica; solo loopback está permitido)")
    return _orig_getaddrinfo(host, *args, **kwargs)


def _connect_guardado(self, address):
    host = address[0] if isinstance(address, tuple) and address else None
    if isinstance(host, str) and not _es_local(host):
        raise OSError(
            13, f"[hermética D7] red externa BLOQUEADA: connect({host!r}) "
                f"(corrida --hermetica; solo loopback está permitido)")
    return _orig_connect(self, address)


socket.getaddrinfo = _getaddrinfo_guardado
socket.socket.connect = _connect_guardado
