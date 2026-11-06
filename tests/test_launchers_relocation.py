# -*- coding: utf-8 -*-
"""P0-1 — regresión dura de la reubicación de lanzadores a launchers/.

Lección de 654d1cb: el test anterior solo buscaba SUBCADENAS y dejó pasar
un SyntaxError (paréntesis de más) en lanzador_albra.py. Ahora:
  1. Cada .py de launchers/ se compila de verdad (py_compile + ast.parse).
  2. BASE de lanzador_albra.py se resuelve EJECUTANDO su propia línea
     BASE=..., no buscando el texto.
  3. Los .bat/.sh/.vbs conservan sus anclajes de ruta (subcadena, aquí
     sí es lo correcto: son texto, no código Python).
  4. Los 7 lanzadores viven en launchers/ y ya NO en la raíz.

Ejecutar: python3 -m pytest tests/test_launchers_relocation.py -q
"""
import ast
import pathlib
import py_compile
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LAUNCH = REPO / "launchers"
LANZADORES = (
    "INICIAR-ALBRA.vbs", "DETENER-ALBRA.vbs", "DETENER-con-ventana.bat",
    "lanzador_albra.py", "start.bat", "start.sh", "LANZADORES-LEEME.txt",
)
PY_LAUNCHERS = ("lanzador_albra.py",)


def _leer(nombre):
    return (LAUNCH / nombre).read_text(encoding="utf-8")


def test_los_siete_lanzadores_viven_en_launchers():
    for nombre in LANZADORES:
        assert (LAUNCH / nombre).is_file(), f"falta launchers/{nombre}"
        assert not (REPO / nombre).exists(), (
            f"{nombre} sigue en la raíz; debe vivir solo en launchers/"
        )


def test_todos_los_python_de_launchers_compilan():
    """P0-1: py_compile REAL — un SyntaxError aquí hace fallar el test."""
    for nombre in PY_LAUNCHERS:
        ruta = LAUNCH / nombre
        py_compile.compile(str(ruta), doraise=True)  # levanta en error
        ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))


def test_base_de_lanzador_resuelve_la_raiz_de_verdad():
    """Resuelve BASE ejecutando la asignación real del archivo (no subcadena)."""
    arbol = ast.parse(_leer("lanzador_albra.py"), filename="lanzador_albra.py")
    asignaciones = [
        n for n in arbol.body
        if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "BASE" for t in n.targets
        )
    ]
    assert len(asignaciones) == 1, "BASE debe asignarse exactamente una vez"
    entorno = {"os": __import__("os"), "__file__": str(LAUNCH / "lanzador_albra.py")}
    base = eval(  # noqa: S307 — código propio del repo, entorno controlado
        ast.unparse(asignaciones[0].value), {"__builtins__": {}}, entorno
    )
    assert pathlib.Path(base).resolve() == REPO, (
        f"BASE={base!r} debe ser la raíz del repo (abuelo de launchers/)"
    )


def test_start_sh_resuelve_backend_un_nivel_arriba():
    sh = _leer("start.sh")
    assert 'cd "$(dirname "$0")/../backend"' in sh
    destino = LAUNCH.resolve().parent / "backend"
    assert (destino / "main.py").is_file()


def test_start_bat_resuelve_backend_un_nivel_arriba():
    bat = _leer("start.bat")
    assert 'cd /d "%~dp0..\\backend"' in bat


def test_iniciar_albra_vbs_toma_raiz_como_abuelo():
    vbs = _leer("INICIAR-ALBRA.vbs")
    doble = "GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))"
    assert doble in vbs
    assert "launchers\\lanzador_albra.py" in vbs
    assert "launchers\\start.bat" in vbs
    assert 'carpeta & "\\backend\\.venv\\Scripts\\python.exe"' in vbs


def test_readme_documenta_launchers():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "launchers/start.bat" in readme
    assert "launchers/start.sh" in readme
    assert "launchers/INICIAR-ALBRA.vbs" in readme


def test_leeme_lanzadores_declara_ubicacion():
    leeme = _leer("LANZADORES-LEEME.txt")
    assert "launchers/" in leeme


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
