"""Router del registro de producciones (PASO 3.2 + Q4).

GET /api/registro — lista las producciones registradas (minidramas) con
nicho, nombre (convención), flow_project_id y notebook_id del nicho.
Sin cambios visuales en el panel todavía: es la superficie de datos para
verificar el registro. La clave es el ID estable; los nombres son
etiquetas (ver services/registro_produccion.py).

Q4 · Cuaderno del nicho (UN cuaderno por nicho, NUNCA por historia):
POST /api/registro/nicho  {nicho_id, notebook_id, nombre_cuaderno} —
asigna el cuaderno del nicho y lo propaga a sus producciones.
GET  /api/registro/nicho/{nicho_id} — lee el cuaderno asignado.
Los IDs se validan con las MISMAS reglas que registro_path
(validar_production_id: [A-Za-z0-9._-], ≤80, sin separadores/'..'/absolutas).
Auth: heredada del middleware auth_guard (todo /api/* exige MASTER_API_KEY
si está definida; en local sin clave no bloquea — igual que el resto).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from services import registro_produccion

router = APIRouter(prefix="/api", tags=["registro"])


@router.get("/registro")
def listar_registro():
    """SOLO LECTURA · producciones con su nicho, nombre, flow_project_id
    y notebook_id (del nicho). Nunca crea ni modifica nada."""
    return {"producciones": registro_produccion.listar_producciones()}


@router.post("/registro/nicho")
def asignar_cuaderno_nicho(body: dict):
    """Q4 · Asigna el cuaderno del nicho (UN cuaderno por nicho, nunca por
    historia) y lo propaga a todas las producciones del nicho. Si el nicho
    ya tenía cuaderno distinto, se REEMPLAZA (queda la fecha del cambio)."""
    nicho = str((body or {}).get("nicho_id") or "").strip()
    notebook = str((body or {}).get("notebook_id") or "").strip()
    nombre = str((body or {}).get("nombre_cuaderno") or "").strip()
    if not nombre:
        raise HTTPException(400, "falta nombre_cuaderno (texto no vacío)")
    try:
        # mismas reglas de ID que registro_path (R2)
        registro_produccion.validar_production_id(nicho)
        registro_produccion.validar_production_id(notebook)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    entrada = registro_produccion.registrar_nicho(nicho, notebook, nombre)
    propagacion = registro_produccion.propagar_nicho(nicho)
    return {"ok": True, "nicho_id": nicho, "nicho": entrada,
            "propagacion": propagacion}


@router.get("/registro/nicho/{nicho_id}")
def leer_cuaderno_nicho(nicho_id: str):
    """Q4 · Lee el cuaderno asignado al nicho (o 404 si no tiene)."""
    try:
        registro_produccion.validar_production_id(nicho_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    entrada = registro_produccion.registro_nicho(nicho_id)
    if not entrada:
        raise HTTPException(404,
                            f"el nicho {nicho_id!r} no tiene cuaderno asignado")
    return {"nicho_id": nicho_id, **entrada}
