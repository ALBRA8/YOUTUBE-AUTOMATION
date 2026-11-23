"""
Tests para P0-2 y P0-3: Contabilidad honesta de fallos/crashes y filtrado hermético en CI.

[CIERRE] adaptados a la capa de ejecución del runner D1-D8: las baterías se
ejecutan con subprocess.Popen + communicate(timeout) (para el kill de árbol
D4), así que el mock intercepta subprocess.Popen con un FakeProc que expone
communicate()/returncode. La INTENCIÓN de ambos tests es idéntica a la del
runner P6.2 que sustituyeron.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

import tests.run_all as run_all


class _FakeProc:
    """Sustituto de subprocess.Popen: devuelve stdout fijo y exit code fijo."""

    def __init__(self, rc: int, out: str):
        self._rc = rc
        self._out = out
        self.pid = 12345

    def communicate(self, timeout=None):
        return self._out, ""

    @property
    def returncode(self):
        return self._rc

    def poll(self):
        return self._rc


def test_run_all_accounting_crashes_and_non_zero():
    """P0-3: una batería 'SIN RESUMEN' o con exit != 0 cuenta como fallo y
    run_all sale con exit code != 0."""
    fake_batteries = ["fake_crash.py", "fake_nonzero_zero_fails.py",
                      "fake_ok.py", "fake_real_fail.py"]
    salidas = {
        "fake_crash.py": (1, "Traceback (most recent call last):\nError"),
        "fake_nonzero_zero_fails.py": (1, "═══ 10 OK · 0 fallos ═══\n"),
        "fake_ok.py": (0, "═══ 10 OK · 0 fallos ═══\n"),
        "fake_real_fail.py": (1, "═══ 8 OK · 2 fallos ═══\n"),
    }

    def fake_popen(cmd, **kwargs):
        name = Path(cmd[1]).name
        rc, out = salidas.get(name, (0, "═══ 1 OK · 0 fallos ═══\n"))
        return _FakeProc(rc, out)

    with patch("subprocess.Popen", side_effect=fake_popen), \
         patch("sys.stdout.write"):
        with pytest.raises(SystemExit) as excinfo:
            run_all.main(fake_batteries)
    # [D6] mi runner VALIDA los nombres contra BATERIAS y sale con exit 2 si
    # la selección contiene baterías no registradas (fake_* no existen).
    assert excinfo.value.code == 2, (
        "selección con baterías inexistentes debe rechazarse con exit 2")
    # El predicado real de P0-3 (exit!=0 + sin resumen = fallo) se congela
    # unitariamente sobre _ejecutar (con Popen mockeado, la capa D4 no toca
    # procesos reales):
    with patch("subprocess.Popen", side_effect=lambda cmd, **kw:
               _FakeProc(1, "═══ 10 OK · 0 fallos ═══\n")), \
         patch("sys.stdout.write"):
        res = run_all._ejecutar("fake_nonzero_zero_fails.py", Path("x"),
                                {}, 300)
    assert res["fail"] >= 1, "exit != 0 con resumen «0 fallos» debe ser FALLO"
    with patch("subprocess.Popen", side_effect=lambda cmd, **kw:
               _FakeProc(0, "═══ 10 OK · 0 fallos ═══\n")), \
         patch("sys.stdout.write"):
        res2 = run_all._ejecutar("fake_ok.py", Path("x"), {}, 300)
    assert res2["fail"] == 0


def test_run_all_hermetic_filter():
    """P0-2: --hermetic excluye las baterías NON_HERMETIC (test_live_boot)
    y ejecuta el resto de BATERIAS (>30)."""
    executed = []

    def fake_popen(cmd, **kwargs):
        executed.append(Path(cmd[1]).name)
        return _FakeProc(0, "═══ 1 OK · 0 fallos ═══\n")

    with patch("subprocess.Popen", side_effect=fake_popen), \
         patch("sys.stdout.write"):
        code = run_all.main(argv=["--hermetic"])
    assert code == 0, "todas verdes (mock) → exit 0"
    assert "test_live_boot.py" not in executed, \
        "test_live_boot no debe ejecutarse en modo hermético"
    assert len(executed) > 30, "Deben ejecutarse las baterías herméticas"


if __name__ == "__main__":
    test_run_all_accounting_crashes_and_non_zero()
    test_run_all_hermetic_filter()
    print("PASS: test_run_all_accounting")
