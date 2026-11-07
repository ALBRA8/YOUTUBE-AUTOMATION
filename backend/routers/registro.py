"""Router de SOLO LECTURA del registro de producciones (PASO 3.2).

GET /api/registro — lista las producciones registradas (minidramas) con
nicho, nombre (convención), flow_project_id y notebook_id del nicho.
Sin cambios visuales en el panel todavía: es la superficie de datos para
verificar el registro. La clave es el ID estable; los nombres son
etiquetas (ver services/registro_produccion.py).
"""
from __future__ import annotations

from fastapi import APIRouter

from services import registro_produccion

router = APIRouter(prefix="/api", tags=["registro"])


@router.get("/registro")
def listar_registro():
    """SOLO LECTURA · producciones con su nicho, nombre, flow_project_id
    y notebook_id (del nicho). Nunca crea ni modifica nada."""
    return {"producciones": registro_produccion.listar_producciones()}
