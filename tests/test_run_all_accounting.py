from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import run_all


def test_run_all_accounting_crashes_and_non_zero():
    """P0-3: Verifica que run_all cuente como fallo una batería 'SIN RESUMEN' o con exit != 0."""
    fake_batteries = ["fake_crash.py", "fake_nonzero_zero_fails.py", "fake_ok.py", "fake_real_fail.py"]

    def fake_subprocess_run(cmd, cwd=None, capture_output=True, text=True):
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

    # 4 baterías: 3 fallaron (fake_crash: 1 fallo, fake_nonzero_zero_fails: 1 fallo, fake_real_fail: 2 fallos)
    assert code == 1, "Debe retornar 1 si alguna batería falla"


def test_run_all_hermetic_filter():
    """P0-2: Verifica que --hermetic excluya baterías no herméticas como test_live_boot.py."""
    executed = []

    def fake_run(cmd, cwd=None, capture_output=True, text=True):
        executed.append(Path(cmd[1]).name)
        return MagicMock(returncode=0, stdout="═══ 1 OK · 0 fallos ═══\n", stderr="")

    with patch("subprocess.run", side_effect=fake_run), \
         patch("sys.stdout.write"):
        code = run_all.main(argv=["--hermetic"])

    assert code == 0
    assert "test_live_boot.py" not in executed, "test_live_boot.py no debe ejecutarse con --hermetic"
    assert "test_flow_contract_p1.py" in executed, "Baterías herméticas deben ejecutarse"


if __name__ == "__main__":
    test_run_all_accounting_crashes_and_non_zero()
    test_run_all_hermetic_filter()
    print("PASS: test_run_all_accounting + test_run_all_hermetic_filter")
