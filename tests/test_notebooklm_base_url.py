import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from services.mcp_manager import manager


def test_notebooklm_env_vars_respected():
    """Verifica que mcp_manager exponga y respete NOTEBOOKLM_BASE_URL y NOTEBOOKLM_BL."""
    base_url = "https://notebook.google.com"
    bl = "boq_labs-tailwind-frontend_20261112.11_p0"
    os.environ["NOTEBOOKLM_BASE_URL"] = base_url
    os.environ["NOTEBOOKLM_BL"] = bl

    from services.mcp_manager import _cfg
    assert _cfg("NOTEBOOKLM_BASE_URL", "default") == base_url
    assert _cfg("NOTEBOOKLM_BL", "default") == bl
