# -*- coding: utf-8 -*-
"""P1-5 · Regresión del gate de placeholders.

1. MAX_ALLOWED_PLACEHOLDERS se lee de UNA sola fuente (config.
   max_allowed_placeholders) — queda prohibido os.getenv("MAX_ALLOWED_
   PLACEHOLDERS") disperso (guardia AST sobre backend/).
2. _run_flow_render (entrada del render con assets Flow importados, que es
   también la ruta del orquestador MCP vía orchestrator.start_flow_render)
   LLAMA a _gate_imagenes_reales (verificación AST de la llamada, no
   subcadenas — lección P0-1).

Ejecutar: python3 -m pytest tests/test_p1_5_placeholder_gate.py -q
"""
import ast
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import config  # noqa: E402


def test_umbral_viene_de_config_y_respeta_entorno(monkeypatch):
    assert config.max_allowed_placeholders() == config.MAX_ALLOWED_PLACEHOLDERS
    monkeypatch.setenv("MAX_ALLOWED_PLACEHOLDERS", "3")
    assert config.max_allowed_placeholders() == 3
    monkeypatch.setenv("MAX_ALLOWED_PLACEHOLDERS", "0")
    assert config.max_allowed_placeholders() == 0


def test_sin_os_getenv_dispersos_del_umbral():
    """Guardia AST: ninguna llamada os.getenv('MAX_ALLOWED_PLACEHOLDERS')."""
    ofensores = []
    for path in sorted(BACKEND.rglob("*.py")):
        if path.name == "config.py":  # la definición legítima vive aquí
            continue
        arbol = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for n in ast.walk(arbol):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "getenv" and n.args
                    and isinstance(n.args[0], ast.Constant)
                    and n.args[0].value == "MAX_ALLOWED_PLACEHOLDERS"):
                ofensores.append(
                    f"{path.relative_to(REPO)}:{n.lineno}")
    assert not ofensores, (
        f"os.getenv('MAX_ALLOWED_PLACEHOLDERS') disperso (P1-5): {ofensores}. "
        "Usa config.max_allowed_placeholders()."
    )


def test_run_flow_render_aplica_el_gate_de_imagenes():
    """AST: _run_flow_render debe llamar a _gate_imagenes_reales."""
    src = (BACKEND / "pipeline" / "orchestrator.py").read_text(encoding="utf-8")
    arbol = ast.parse(src)
    cuerpo = None
    for n in ast.walk(arbol):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) \
                and n.name == "_run_flow_render":
            cuerpo = n
            break
    assert cuerpo is not None, "_run_flow_render no encontrada"
    llamadas = {ast.unparse(c.func) for c in ast.walk(cuerpo)
                if isinstance(c, ast.Call)}
    assert "_gate_imagenes_reales" in llamadas, (
        "start_flow_render/_run_flow_render no aplica el gate de placeholders "
        "(P1-5): el orquestador MCP y el render Flow entregarían placeholders")


def test_start_flow_render_es_la_ruta_del_orquestador_mcp():
    """AST: la ruta MCP (main.py) invoca orchestrator.start_flow_render."""
    src = (BACKEND / "main.py").read_text(encoding="utf-8")
    arbol = ast.parse(src)
    llama = any(isinstance(n, ast.Call)
                and ast.unparse(n.func) == "orchestrator.start_flow_render"
                for n in ast.walk(arbol))
    assert llama, "main.py debe entrar al render vía orchestrator.start_flow_render"


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
