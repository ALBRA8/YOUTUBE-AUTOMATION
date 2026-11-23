"""
Test Z3: pipeline/video.py no debe tener una definición duplicada de _probe_nvenc
ni referencias huérfanas a ENABLE_NVENC sin definir. Debe importar la función
canónica desde video_encode.
"""
import ast
import sys
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_no_duplicate_probe_nvenc_or_orphan_enable_nvenc_in_video_py():
    video_path = BACKEND_DIR / "pipeline" / "video.py"
    assert video_path.exists(), "backend/pipeline/video.py no existe"
    content = video_path.read_text(encoding="utf-8")
    tree = ast.parse(content)

    func_defs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert "_probe_nvenc" not in func_defs, "backend/pipeline/video.py no debe definir _probe_nvenc localmente"
    assert "ENABLE_NVENC" not in content, "backend/pipeline/video.py no debe contener ENABLE_NVENC huérfano"


def test_probe_nvenc_imported_from_video_encode():
    from pipeline import video
    import video_encode

    assert hasattr(video, "_probe_nvenc"), "pipeline.video debe re-exportar _probe_nvenc"
    assert video._probe_nvenc is video_encode._probe_nvenc

    with patch("video_encode.ENABLE_NVENC", False):
        assert video._probe_nvenc() is False
