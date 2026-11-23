"""
Test Z4: Verificación de integración continua con ruff y corrección de reglas
F821, E9, F63, F7 y F82 sobre backend y tools.
"""
import ast
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def test_ci_workflow_has_ruff_step():
    ci_file = ROOT_DIR / ".github" / "workflows" / "ci.yml"
    assert ci_file.exists(), "ci.yml no existe"
    content = ci_file.read_text(encoding="utf-8")

    assert "ruff check" in content
    assert "F821" in content
    assert "backend tools" in content


def test_ruff_zero_findings_on_backend_and_tools():
    # Ejecuta ruff sobre backend y tools con las reglas exigidas
    cmd = [sys.executable, "-m", "ruff", "check", "--select", "F821,E9,F63,F7,F82", "backend", "tools"]
    proc = subprocess.run(cmd, cwd=str(ROOT_DIR), capture_output=True, text=True)
    assert proc.returncode == 0, f"ruff reportó hallazgos:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"


def test_qa_forensics_imports_any():
    qa_file = ROOT_DIR / "backend" / "services" / "qa_forensics_checker.py"
    assert qa_file.exists()
    content = qa_file.read_text(encoding="utf-8")
    assert "Any" in content, "qa_forensics_checker.py debe importar Any de typing"


def test_mcp_manager_no_redundant_sys_redefinitions():
    mcp_file = ROOT_DIR / "backend" / "services" / "mcp_manager.py"
    assert mcp_file.exists()
    tree = ast.parse(mcp_file.read_text(encoding="utf-8"))

    # Verifica que dentro de las funciones no se redefina/reimporte 'import sys'
    nested_sys_imports = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        if alias.name == "sys":
                            nested_sys_imports.append((node.name, child.lineno))

    assert len(nested_sys_imports) == 0, f"mcp_manager.py reimporta sys dentro de funciones: {nested_sys_imports}"
