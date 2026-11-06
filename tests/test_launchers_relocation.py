# -*- coding: utf-8 -*-
"""PASO 3 — regresión de la reubicación de lanzadores a launchers/.

Verifica (hermético, sin ejecutar nada):
  1. Los 7 lanzadores viven en launchers/ y ya NO en la raíz.
  2. start.sh y start.bat resuelven el backend un nivel arriba.
  3. INICIAR-ALBRA.vbs toma la raíz como ABUELO y llama a los
     compañeros dentro de launchers/.
  4. lanzador_albra.py ancla BASE en la raíz (doble dirname).
  5. README.md documenta la nueva ubicación.

Ejecutar: python3 -m pytest tests/test_launchers_relocation.py -q
"""
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LANZADORES = (
    "INICIAR-ALBRA.vbs", "DETENER-ALBRA.vbs", "DETENER-con-ventana.bat",
    "lanzador_albra.py", "start.bat", "start.sh", "LANZADORES-LEEME.txt",
)


def _leer(nombre):
    return (REPO / "launchers" / nombre).read_text(encoding="utf-8")


def test_los_siete_lanzadores_viven_en_launchers():
    for nombre in LANZADORES:
        assert (REPO / "launchers" / nombre).is_file(), f"falta launchers/{nombre}"
        assert not (REPO / nombre).exists(), (
            f"{nombre} sigue en la raíz; debe vivir solo en launchers/"
        )


def test_start_sh_resuelve_backend_un_nivel_arriba():
    sh = _leer("start.sh")
    assert 'cd "$(dirname "$0")/../backend"' in sh, (
        "start.sh debe hacer cd al backend del PADRE de launchers/"
    )
    # y la ruta resuelta existe de verdad
    destino = (REPO / "launchers").resolve().parent / "backend"
    assert (destino / "main.py").is_file()


def test_start_bat_resuelve_backend_un_nivel_arriba():
    bat = _leer("start.bat")
    assert 'cd /d "%~dp0..\\backend"' in bat, (
        'start.bat debe hacer cd /d "%~dp0..\\backend" (padre de launchers/)'
    )


def test_iniciar_albra_vbs_toma_raiz_como_abuelo():
    vbs = _leer("INICIAR-ALBRA.vbs")
    # doble GetParentFolderName: launchers/ -> raíz
    doble = "GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))"
    assert doble in vbs, "el .vbs debe subir DOS niveles (launchers -> raíz)"
    assert "launchers\\lanzador_albra.py" in vbs
    assert "launchers\\start.bat" in vbs
    assert 'carpeta & "\\backend\\.venv\\Scripts\\python.exe"' in vbs


def test_lanzador_albra_py_ancla_base_en_raiz():
    py = _leer("lanzador_albra.py")
    assert "os.path.dirname(os.path.dirname(os.path.abspath(__file__)))" in py, (
        "BASE debe ser el abuelo del script (el script vive en launchers/)"
    )
    assert 'os.path.join(BASE, "launchers", "start.bat")' in py
    # comprobación viva del ancla: doble dirname == raíz del repo
    base = (REPO / "launchers" / "lanzador_albra.py").resolve().parent.parent
    assert base == REPO


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
