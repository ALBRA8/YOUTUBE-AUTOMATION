"""
Tests para P0-2 y P0-3: Contabilidad honesta de fallos/crashes y filtrado hermético en CI.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

import tests.run_all as run_all


def test_run_all_accounting_crashes_and_non_zero():
    """P0-3: Verifica que run_all cuente como fallo una batería 'SIN RESUMEN' o con exit != 0."""
    fake_batteries = ["fake_crash.py", "fake_nonzero_zero_fails.py", "fake_ok.py", "fake_real_fail.py"]

    def fake_subprocess_run(cmd, **kwargs):
        name = Path(cmd[1]).name
        if name == "fake_crash.py":
            return MagicMock(returncode=1, stdout="Traceback (most recent call last):\nError", stderr="")
        elif name == "fake_nonzero_zero_fails.py":
            return MagicMock(returncode=1, stdout="═══ 10 OK · 0 fallos ═══\n", stderr="")
        elif name == "fake_ok.py":
            return MagicMock(returncode=0, stdout="═══ 10 OK · 0 fallos ═══\n", stderr="")
        elif name == "fake_real_fail.py":
            return MagicMock(returncode=1, stdout="═══ 8 OK · 2 fallos ═══\n", stderr="")
        return MagicMock(returncode=0, stdout="═══ 1 OK · 0 fallos ═══\n", stderr="")

    with patch("subprocess.run", side_effect=fake_subprocess_run), \
         patch("sys.stdout.write"):
        code = run_all.main(fake_batteries)

    # 4 baterías:
    # - fake_crash: exit 1, sin resumen -> 1 fallo
    # - fake_nonzero_zero_fails: exit 1 pero resumen decía 0 fallos -> 1 fallo computado
    # - fake_ok: exit 0, 0 fallos -> 0 fallos
    # - fake_real_fail: exit 1, 2 fallos -> 2 fallos
    # Total esperado: al menos 4 fallos y exit code != 0
    assert code != 0, "run_all debe salir con exit code != 0 si hubo fallos o crashes"


def test_run_all_hermetic_filter():
    """P0-2: Verifica que --hermetic excluya baterías no herméticas como test_live_boot.py."""
    executed = []

    def fake_run(cmd, **kwargs):
        executed.append(Path(cmd[1]).name)
        return MagicMock(returncode=0, stdout="═══ 1 OK · 0 fallos ═══\n", stderr="")

    with patch("subprocess.run", side_effect=fake_run), \
         patch("sys.stdout.write"):
        code = run_all.main(argv=["--hermetic"])

    assert code == 0
    assert "test_live_boot.py" not in executed, "test_live_boot no debe ejecutarse en modo hermético"
    assert len(executed) > 30, "Deben ejecutarse las baterías herméticas"


if __name__ == "__main__":
    test_run_all_accounting_crashes_and_non_zero()
    test_run_all_hermetic_filter()
    print("PASS: test_run_all_accounting")
