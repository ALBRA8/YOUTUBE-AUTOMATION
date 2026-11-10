"""
Test Z1: backend/main.py debe importar subprocess a nivel de módulo
para evitar NameError en POST /api/avatars/{avatar_id}/lipsync-musetalk.
"""
import ast
from pathlib import Path


def test_main_imports_subprocess_at_module_level():
    main_path = Path(__file__).resolve().parent.parent / "backend" / "main.py"
    assert main_path.exists(), "backend/main.py no existe"

    tree = ast.parse(main_path.read_text(encoding="utf-8"))

    # Verifica en el AST que hay un Import(subprocess) al nivel raíz (body)
    has_top_level_subprocess = False
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    has_top_level_subprocess = True
                    break

    assert has_top_level_subprocess, "backend/main.py debe importar subprocess en el cuerpo del módulo (top-level)"


def test_main_has_subprocess_attribute():
    import sys
    backend_dir = str(Path(__file__).resolve().parent.parent / "backend")
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    import main
    import subprocess
    assert hasattr(main, "subprocess")
    assert main.subprocess is subprocess
