"""
Test P3-3: Verificación de integridad documental (ESTADO_REAL.md, PROJECT_STATE.md, FAILURE_INDEX.md).
"""
from __future__ import annotations

from pathlib import Path


def test_estado_real_battery_count_and_table_format():
    """P3-3: ESTADO_REAL.md debe declarar 53 baterías y tener la tabla de contratos íntegra."""
    path = Path("ESTADO_REAL.md")
    assert path.is_file()
    content = path.read_text(encoding="utf-8")

    assert "53 baterías" in content, "ESTADO_REAL.md debe reportar 53 baterías canónicas"
    assert "35 baterías" not in content, "35 baterías es obsoleto"

    # Verificar que las filas de EXECUTION CONTRACT tengan formato markdown válido (inicia y termina con |)
    lines = content.splitlines()
    for l in lines:
        if "EXECUTION CONTRACT V1.0" in l or "EXECUTION CONTRACT V1.1" in l:
            stripped = l.strip()
            assert stripped.startswith("|") and stripped.endswith("|"), f"Fila de tabla rota: {stripped}"


def test_project_state_unified_status_and_pat_revocation():
    """P3-3: PROJECT_STATE.md debe tener un único Estado unificado en cabecera y la revocación del PAT marcada PENDIENTE DE CONFIRMACIÓN POR EL DUEÑO (P0-3)."""
    path = Path("CONTEXTO YOUTUBE/00_MASTER/PROJECT_STATE.md")
    assert path.is_file()
    content = path.read_text(encoding="utf-8")

    # Cabecera unificada sin bloques contradictorios
    header_section = content[:1500]
    assert "**Estado Unificado:**" in header_section, "Debe tener un bloque unificado de Estado"
    assert "IN_PROGRESS — migración AGENTE-GENERAL" not in header_section, "No debe haber bloque de Estado contradictorio en cabecera"
    # P0-3 (auditoría de verificación): NO se afirma revocación sin evidencia.
    # La redacción honesta es "PENDIENTE DE CONFIRMACIÓN POR EL DUEÑO".
    assert "PENDIENTE DE CONFIRMACIÓN POR EL DUEÑO" in content, (
        "PROJECT_STATE.md debe declarar la revocación del PAT como pendiente "
        "de confirmación del dueño, nunca como hecho sin evidencia")


def test_failure_index_records_audit_006():
    """P3-3: FAILURE_INDEX.md debe registrar los hallazgos de AUDIT-006."""
    path = Path("CONTEXTO YOUTUBE/07_FAILURES/FAILURE_INDEX.md")
    assert path.is_file()
    content = path.read_text(encoding="utf-8")

    assert "AUDIT-006" in content
    assert "SEC-001" in content
    assert "VID-001" in content


if __name__ == "__main__":
    test_estado_real_battery_count_and_table_format()
    test_project_state_unified_status_and_pat_revocation()
    test_failure_index_records_audit_006()
    print("PASS: test_p3_3_docs_integrity")
