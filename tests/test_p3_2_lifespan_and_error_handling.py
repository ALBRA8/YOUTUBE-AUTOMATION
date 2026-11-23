"""
Test P3-2: Migración a lifespan y hardening de manejo de excepciones en pipeline/publicación.
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from backend.main import app, lifespan
from backend.pipeline.images import _save_style_method


@pytest.mark.asyncio
async def test_lifespan_context_manager_executes_safely():
    """P3-2: lifespan debe ejecutar las tareas de arranque limpiamente sin on_event."""
    assert app.router.lifespan_context is not None

    # Probar que el contexto lifespan arranca y finaliza
    with patch("backend.main.backup_svc.create_backup", return_value={"name": "test", "size": 1024}), \
         patch("backend.main.backup_svc.start_scheduler") as mock_sched:
        async with lifespan(app):
            pass
        assert mock_sched.called


@pytest.mark.asyncio
async def test_lifespan_fails_closed_on_open_lan():
    """P3-2: El guardia de seguridad en lifespan debe fallar cerrado si el HOST no es loopback
    y no hay MASTER_API_KEY ni ALLOW_OPEN_LAN."""
    with patch.dict("os.environ", {"HOST": "192.168.1.100", "ALLOW_OPEN_LAN": ""}), \
         patch("backend.security.enabled", return_value=False):
        with pytest.raises(RuntimeError, match="HOST no-loopback sin MASTER_API_KEY"):
            async with lifespan(app):
                pass


def test_save_style_method_logs_warning_on_exception(caplog):
    """P3-2: _save_style_method no debe tragar errores silenciosamente con pass."""
    with caplog.at_level(logging.WARNING):
        # Pasar ruta inválida para forzar excepción de IO
        _save_style_method("/invalid_dir_xyz_123/img.png", "gemini")
        assert any("no se pudo guardar style sidecar" in rec.message for rec in caplog.records)


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_lifespan_context_manager_executes_safely())
    asyncio.run(test_lifespan_fails_closed_on_open_lan())
    print("PASS: test_p3_2_lifespan_and_error_handling")
