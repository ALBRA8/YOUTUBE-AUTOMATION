# -*- coding: utf-8 -*-
"""P0-2c — guardia AST anti-SSRF "hermanos".

Recorre TODO backend/**/*.py con ast y FALLA si aparece una llamada de
red cruda hacia URL no constante fuera de security.py:

  · urllib.request.urlopen(...) (directa, por alias, o sobre una variable
    asignada a urllib.request / Request / opener)
  · requests.<verbo>(...) o import requests
  · httpx.<verbo>(...) / httpx.Client(...) / import httpx

Lista blanca DOCUMENTADA (cada entrada con su motivo, longitud mínima):
  · backend/security.py             — la propia guardia central (validar_url,
                                      safe_fetch_bytes, _SafeRedirectHandler).
  · backend/services/mcp_manager.py — sondeo CDP al Chrome local 127.0.0.1
                                      (loopback por diseño; MCP de Google Flow).
  · backend/services/hands/flow_operator.py — transporte HTTP genérico
                                      INYECTABLE de HANDS (_UrllibHttp; HANDS
                                      está DORMIDO, D-010; URLs de config local).
  · backend/_dev_wait_open.py       — health check del lanzador dev a la
                                      constante http://127.0.0.1:8000.

Ejecutar: python3 -m pytest tests/test_p0_2_ssrf_guard.py -q
"""
import ast
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"

WHITELIST = {
    "security.py": "guardia central SSRF (validar_url/safe_fetch_bytes)",
    "services/mcp_manager.py": "sondeo CDP a 127.0.0.1 (Chrome local, Google Flow)",
    "services/hands/flow_operator.py": (
        "transporte HTTP genérico inyectable de HANDS (_UrllibHttp; HANDS "
        "DORMIDO según D-010)"),
    "_dev_wait_open.py": (
        "health check del lanzador dev a la constante http://127.0.0.1:8000"),
    "services/nvidia_client.py": (
        "cliente API NVIDIA con host fijo por config del dueño "
        "(config.NVIDIA_BASE_URL, https://integrate.api.nvidia.com/v1); "
        "SSE async; el host NO proviene de la petición del usuario"),
    "services/broll_overlay.py": (
        "búsqueda en API Pexels con host fijo api.pexels.com; el link de "
        "descarga que devuelve el JSON externo SÍ se valida con "
        "security.validar_url antes del httpx.get (test_p0_2_ssrf_siblings)"),
}

HTTPX_VERBS = {"get", "post", "put", "delete", "head", "patch", "options",
               "stream", "request", "Client", "AsyncClient"}
REQUESTS_VERBS = HTTPX_VERBS - {"Client", "AsyncClient"}
LIBS = {"urllib.request", "requests", "httpx", "urllib"}


def _dotted(node):
    """Convierte Attribute/Name anidados a 'a.b.c' (None si no cabe)."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _resolutor(arbol):
    """Devuelve resuelve(nombre) → dotted real, con aliases y variables."""
    aliases = {}   # "urllib_request" → "urllib.request"
    nombres = {}   # "urlopen" → "urllib.request.urlopen" (from X import Y)
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name in LIBS:
                    aliases[a.asname or a.name.split(".")[0]] = a.name
        elif isinstance(n, ast.ImportFrom) and n.module in LIBS:
            for a in n.names:
                nombres[a.asname or a.name] = f"{n.module}.{a.name}"

    var_dotted = {}  # variables asignadas a un dotted conocido
    for n in ast.walk(arbol):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)):
            d = _dotted(n.value)
            if d:
                var_dotted[n.targets[0].id] = d

    def resuelve(nombre):
        if nombre in nombres:
            return nombres[nombre]
        if nombre in aliases:
            return aliases[nombre]
        if nombre in var_dotted:
            return var_dotted[nombre]
        return nombre

    return resuelve


def _violaciones(path):
    """[(línea, descripción)] de llamadas de red crudas del archivo."""
    arbol = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    resuelve = _resolutor(arbol)
    hallazgos = []

    for n in ast.walk(arbol):
        if isinstance(n, ast.Import) and any(
                a.name in ("requests", "httpx") for a in n.names):
            hallazgos.append((n.lineno, "import directo de requests/httpx"))
            continue
        if not isinstance(n, ast.Call):
            continue
        d = _dotted(n.func)
        if not d:
            continue
        cabeza, _, cola = d.rpartition(".")
        full = f"{resuelve(cabeza)}.{cola}" if cola else resuelve(d)
        resuelto = None
        if full == "urllib.request.urlopen" or full == "urllib.urlopen":
            resuelto = "urllib.urlopen"
        elif full.startswith("requests.") and cola in REQUESTS_VERBS:
            resuelto = full
        elif full.startswith("httpx.") and cola in HTTPX_VERBS:
            resuelto = full
        if resuelto:
            hallazgos.append((n.lineno, resuelto))
    return hallazgos


def test_guardia_sin_red_cruda_fuera_de_la_lista_blanca():
    ofensores = []
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        if rel in WHITELIST:
            continue
        try:
            hallazgos = _violaciones(path)
        except SyntaxError as e:  # un SyntaxError también es hallazgo
            ofensores.append(f"{rel}:SYNTAXERROR:{e}")
            continue
        for linea, que in hallazgos:
            ofensores.append(f"{rel}:{linea}: {que}")
    assert not ofensores, (
        "Llamadas de red crudas fuera de security.py y de la lista blanca "
        f"(P0-2c): {ofensores}. Usa security.validar_url + "
        "security.safe_fetch_bytes, o documenta el motivo en WHITELIST."
    )


def test_lista_blanca_sigue_existiendo_y_motivada():
    """La lista blanca no puede crecer en silencio: cada entrada con motivo."""
    assert len(WHITELIST) == 6, (
        "Nueva entrada en WHITELIST sin auditoría: documenta el motivo y "
        "justifícala en la revisión (P0-2c)"
    )
    for ruta, motivo in WHITELIST.items():
        assert motivo and len(motivo) > 15, f"motivo vacío para {ruta}"
        assert (BACKEND / ruta).is_file(), f"whitelist apunta a {ruta} inexistente"


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
