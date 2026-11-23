"""
Test P2-6: Verificación de estado NOT_DEMONSTRATED y checklist para GAP-002 / FAIL-005.
"""
from __future__ import annotations

from pathlib import Path


def test_gap002_startframe_is_not_demonstrated_and_checklist_exists():
    """P2-6: GAP-002 (Start Frame) y FAIL-005 no deben declararse implementados sin
    captura real; deben tener el checklist de captura y estado NOT_DEMONSTRATED."""
    doc_path = Path("CONTEXTO YOUTUBE/00_MASTER/PROJECT_STATE.md")
    assert doc_path.is_file(), f"{doc_path} no existe"

    content = doc_path.read_text(encoding="utf-8")
    assert "NOT_DEMONSTRATED" in content, "Debe registrar explícitamente el estado NOT_DEMONSTRATED"
    assert "GAP-002" in content or "Start Frame" in content
    assert "Checklist" in content or "Plan inmediato" in content
    assert "Preserve log" in content


if __name__ == "__main__":
    test_gap002_startframe_is_not_demonstrated_and_checklist_exists()
    print("PASS: test_p2_6_startframe_status")
