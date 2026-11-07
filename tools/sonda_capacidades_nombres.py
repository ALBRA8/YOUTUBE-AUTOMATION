#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PASO 1 · SONDA DE CAPACIDADES — nombres en Flow y NotebookLM (SOLO LECTURA).

QUÉ HACE: se conecta a los dos MCP del repo vía `services.mcp_manager`
(transporte stdio JSON-RPC ya implementado — NUNCA habla directo con Flow
ni con NotebookLM), lista las herramientas con su `inputSchema` y responde
con evidencia las 7 preguntas de la convención de nombres:

  q1_flow_proyecto_nombre   ¿flow_new_project acepta nombre o hay
                            herramienta para renombrar proyecto?
  q2_flow_personaje_nombre  ¿se puede crear un personaje con nombre?
  q3_notebook_create_titulo ¿notebook_create acepta título?
  q4_notebook_renombrar     ¿existe herramienta para renombrar cuaderno?
  q5_source_add_titulo      ¿source_add acepta título?
  q6_flow_generacion_destino  ¿flow_generate_image / flow_generate_video /
                            flow_upload_file aceptan un identificador de
                            proyecto o destino? (Q2, 2026-11-07)
  q7_flow_new_project_cambia_activo  ¿flow_new_project cambia el proyecto
                            ACTIVO sobre el que generan las demás
                            herramientas? (Q2, 2026-11-07)

VEREDICTO por pregunta: SOPORTADO (hay evidencia en el esquema) /
NO_SOPORTADO (hay catálogo y NO está) / NOT_DEMONSTRATED (sin catálogo
real: p. ej. sin la máquina del dueño). NUNCA CREA NADA: la sonda solo
lee catálogos. El flag --crear-prueba (APAGADO por defecto) es el único
que permite creaciones de prueba y exige --confirmo "SI CREAR".

USO (máquina del dueño):
  python tools/sonda_capacidades_nombres.py                 # solo lectura
  python tools/sonda_capacidades_nombres.py --salida rep.json
  python tools/sonda_capacidades_nombres.py --crear-prueba --confirmo "SI CREAR"

Documentación: CONTEXTO YOUTUBE/06_INTEGRATIONS/INT-093_SONDA_CAPACIDADES_NOMBRES.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SOPORTADO, NO_SOPORTADO, PEND = "SOPORTADO", "NO_SOPORTADO", "NOT_DEMONSTRATED"

PREGUNTAS = (
    ("q1_flow_proyecto_nombre",
     "¿flow_new_project acepta nombre o hay herramienta para renombrar proyecto?"),
    ("q2_flow_personaje_nombre",
     "¿se puede crear un personaje con nombre?"),
    ("q3_notebook_create_titulo",
     "¿notebook_create acepta título?"),
    ("q4_notebook_renombrar",
     "¿existe herramienta para renombrar cuaderno?"),
    ("q5_source_add_titulo",
     "¿source_add acepta título?"),
    ("q6_flow_generacion_destino",
     "¿flow_generate_image / flow_generate_video / flow_upload_file aceptan "
     "un identificador de proyecto o destino?"),
    ("q7_flow_new_project_cambia_activo",
     "¿flow_new_project cambia el proyecto activo sobre el que generan "
     "las demás herramientas?"),
)

CONFIRMACION_REQUERIDA = "SI CREAR"

# ── análisis PURO del catálogo (sin red: testeable con dobles) ─────────────
_RE_NOMBRE = re.compile(r"^(name|nombre|title|titulo|project_name|display_name)$",
                        re.IGNORECASE)
_RE_RENOMBRAR_PROYECTO = re.compile(
    r"(rename|renombrar|actualizar_?nombre).*(project|proyecto)"
    r"|(project|proyecto).*(rename|renombrar)", re.IGNORECASE)
_RE_CREAR_PERSONAJE = re.compile(
    r"(create|new|add|generar|crear).*(character|personaje|avatar)"
    r"|(character|personaje|avatar).*(create|new|add)", re.IGNORECASE)
_RE_RENOMBRAR_CUADERNO = re.compile(
    r"(rename|renombrar|update).*(notebook|cuaderno)"
    r"|notebook.*(rename|renombrar|update)", re.IGNORECASE)

# Q2 · q6: herramientas de generación/subida de Flow y su identificador de
# destino; q7: indicios de «proyecto activo» en la DESCRIPCIÓN de
# flow_new_project (es conducta, no esquema: sin evidencia explícita el
# veredicto honesto es NOT_DEMONSTRATED).
_RE_GENERACION = re.compile(
    r"^flow_(generate_image|generate_video|upload_file)$", re.IGNORECASE)
_RE_DESTINO = re.compile(
    r"^(project_id|project|project_name|proyecto|proyecto_id|destino|"
    r"destination|target|target_project|folder|folder_id|workspace|"
    r"workspace_id|parent|parent_id)$", re.IGNORECASE)
_RE_ACTIVO_SI = re.compile(
    r"(cambia|activa|selecciona|fija|establece|switch|activat|sets?|select)"
    r"[\w\s]*(proyecto activo|active project|current project|proyecto actual)",
    re.IGNORECASE)
_RE_ACTIVO_NO = re.compile(
    r"(no cambia|sin cambiar|does not change|doesn't change|leaves the|"
    r"conserva el)[\w\s]*(proyecto activo|active project|current project|"
    r"proyecto actual)", re.IGNORECASE)


def _props(schema: dict) -> set[str]:
    """Nombres de propiedades de un inputSchema (top-level + un nivel en
    anyOf/oneOf). Esquema ausente → conjunto vacío (NO inventa)."""
    props: set[str] = set()
    if not isinstance(schema, dict):
        return props
    for p in (schema.get("properties") or {}):
        props.add(str(p))
    for clave in ("anyOf", "oneOf"):
        for sub in (schema.get(clave) or []):
            if isinstance(sub, dict):
                props |= {str(p) for p in (sub.get("properties") or {})}
    return props


def _tool(tools: list[dict], patron: re.Pattern) -> dict | None:
    for t in tools:
        if patron.search(str(t.get("name") or "")):
            return t
    return None


def _toma_nombre(props: set[str]) -> str | None:
    return next((p for p in sorted(props) if _RE_NOMBRE.match(p)), None)


def _veredicto(tool: dict | None, hay_catalogo: bool,
               acepta_nombre: bool, detalle_si_soporta: str) -> tuple[str, str]:
    """(veredicto, detalle) uniforme para las preguntas de creación."""
    if not hay_catalogo:
        return PEND, "sin catálogo real del MCP (NOT_DEMONSTRATED)"
    if tool is None:
        return NO_SOPORTADO, "no hay herramienta que encaje en el catálogo"
    if acepta_nombre:
        return SOPORTADO, detalle_si_soporta
    return NO_SOPORTADO, (f"la herramienta '{tool.get('name')}' existe pero "
                          "su esquema no expone nombre")


def analizar_tools(service: str, tools: list[dict]) -> list[dict]:
    """PURO · responde las 5 preguntas a partir de un catálogo de tools
    ([{name, description, inputSchema}]). Sin red, sin efectos."""
    hay = bool(tools)
    props = {t.get("name"): _props(t.get("inputSchema")) for t in tools}

    # q1 · flow_new_project con nombre / renombrar proyecto
    if service == "google-flow":
        fnp = _tool(tools, re.compile(r"^flow_new_project$", re.I))
        renom = _tool(tools, _RE_RENOMBRAR_PROYECTO)
        if not hay:
            v1, d1 = PEND, "sin catálogo real del MCP (NOT_DEMONSTRATED)"
        elif fnp is not None and _toma_nombre(props.get(fnp.get("name"), set())):
            v1 = SOPORTADO
            d1 = (f"flow_new_project acepta "
                  f"'{_toma_nombre(props.get(fnp.get('name'), set()))}' en su esquema")
        elif renom is not None:
            v1 = SOPORTADO
            d1 = f"renombrar vía tool '{renom.get('name')}'"
        elif fnp is not None:
            v1 = NO_SOPORTADO
            d1 = "flow_new_project existe pero su esquema no expone nombre " \
                 "ni hay tool de renombrar"
        else:
            v1, d1 = PEND, "flow_new_project no está en el catálogo observado"
        # q2 · crear personaje con nombre
        cp = _tool(tools, _RE_CREAR_PERSONAJE)
        acepta = cp is not None and _toma_nombre(props.get(cp.get("name"), set()))
        v2, d2 = _veredicto(cp, hay, bool(acepta),
                            f"tool '{cp.get('name')}' acepta "
                            f"'{_toma_nombre(props.get(cp.get('name'), set()))}'"
                            if acepta else "")
        # q6 (Q2) · ¿la generación acepta identificador de proyecto/destino?
        gen = [(t, {p for p in props.get(t.get("name"), set())
                    if _RE_DESTINO.match(p)})
               for t in tools if _RE_GENERACION.match(str(t.get("name") or ""))]
        if not hay:
            v6, d6 = PEND, "sin catálogo real del MCP (NOT_DEMONSTRATED)"
        elif not gen:
            v6, d6 = PEND, ("no hay herramientas flow_generate_image/"
                            "flow_generate_video/flow_upload_file en el "
                            "catálogo observado")
        elif all(con for _, con in gen):
            v6 = SOPORTADO
            d6 = "aceptan destino: " + "; ".join(
                f"{t.get('name')} acepta '{sorted(con)[0]}'"
                for t, con in gen if con)
        else:
            v6 = NO_SOPORTADO
            d6 = ("generación sin destino uniforme: " + "; ".join(
                f"{t.get('name')} "
                + (f"acepta '{sorted(con)[0]}'" if con
                   else "sin propiedad de destino")
                for t, con in gen))
        # q7 (Q2) · ¿flow_new_project cambia el proyecto ACTIVO? Es CONDUCTA,
        # no esquema: solo hay veredicto con evidencia explícita.
        if not hay or fnp is None:
            v7, d7 = PEND, ("sin catálogo real del MCP (NOT_DEMONSTRATED)"
                            if not hay else
                            "flow_new_project no está en el catálogo observado")
        else:
            desc = str(fnp.get("description") or "")
            if _RE_ACTIVO_NO.search(desc):
                v7 = NO_SOPORTADO
                d7 = "la descripción de flow_new_project declara que NO cambia "\
                     "el proyecto activo"
            elif _RE_ACTIVO_SI.search(desc):
                v7 = SOPORTADO
                d7 = "la descripción de flow_new_project declara que cambia el " \
                     "proyecto activo: «" + _RE_ACTIVO_SI.search(desc).group(0) + "»"
            else:
                v7, d7 = PEND, ("la descripción de flow_new_project no demuestra "
                                "el comportamiento (conducta, no esquema); "
                                "requiere demostración en la máquina del dueño")
    else:
        if hay:
            v1 = v2 = v6 = v7 = PEND
            d1 = d2 = d6 = d7 = "pregunta de Flow; el catálogo es de " + service
        else:
            v1 = v2 = v6 = v7 = PEND
            d1 = d2 = d6 = d7 = "sin catálogo real del MCP (NOT_DEMONSTRATED)"

    if service == "notebooklm":
        # q3 · notebook_create con título — v0.8.5 nombra el parámetro
        # título «notebook» (nlm_studio.py: notebook_create(notebook=título))
        nc = _tool(tools, re.compile(r"^notebook_create$", re.I))
        acepta = nc is not None and any(
            p == "notebook" or _RE_NOMBRE.match(p)
            for p in props.get(nc.get("name"), set()))
        v3, d3 = _veredicto(nc, hay, bool(acepta),
                            "notebook_create acepta título en su esquema"
                            if acepta else "")
        # q4 · renombrar cuaderno
        rn = _tool(tools, _RE_RENOMBRAR_CUADERNO)
        v4, d4 = _veredicto(rn, hay, rn is not None,
                            f"tool '{rn.get('name')}'" if rn else "")
        # q5 · source_add con título
        sa = _tool(tools, re.compile(r"^source_add$", re.I))
        acepta = sa is not None and "title" in props.get(sa.get("name"), set())
        v5, d5 = _veredicto(sa, hay, bool(acepta),
                            "source_add acepta 'title' en su esquema"
                            if acepta else "")
    else:
        if not hay:
            v3 = v4 = v5 = PEND
            d3 = d4 = d5 = "sin catálogo real del MCP (NOT_DEMONSTRATED)"
        else:
            v3 = v4 = v5 = PEND
            d3 = d4 = d5 = "pregunta de NotebookLM; el catálogo es de " + service

    salidas = {"q1_flow_proyecto_nombre": (v1, d1),
               "q2_flow_personaje_nombre": (v2, d2),
               "q3_notebook_create_titulo": (v3, d3),
               "q4_notebook_renombrar": (v4, d4),
               "q5_source_add_titulo": (v5, d5),
               "q6_flow_generacion_destino": (v6, d6),
               "q7_flow_new_project_cambia_activo": (v7, d7)}
    return [{"id": pid, "pregunta": texto, "veredicto": salidas[pid][0],
             "detalle": salidas[pid][1]}
            for pid, texto in PREGUNTAS]


# ── conexión con el MCP (la ÚNICA vía: services.mcp_manager) ──────────────
async def sondar_mcp(service: str, catalogo_fn=None) -> dict:
    """Lee el catálogo de tools de un servicio. `catalogo_fn` permite doble
    de prueba (tests). Cualquier error de conexión → NOT_DEMONSTRATED."""
    if catalogo_fn is None:
        from services.mcp_manager import manager
        catalogo_fn = manager.tools_catalog
    try:
        cat = await catalogo_fn(service)
    except Exception as exc:  # noqa: BLE001 — sin MCP real: pendiente, honesto
        return {"service": service, "server_info": {}, "tools": [],
                "error": f"{type(exc).__name__}: {exc}"}
    return {"service": service, "server_info": cat.get("server_info", {}),
            "tools": cat.get("tools", []), "error": ""}


def _resumen(service: str, sondado: dict) -> dict:
    return {"service": service, "version": sondado["server_info"],
            "error": sondado["error"],
            "preguntas": analizar_tools(service, sondado["tools"]),
            "tools": [{"name": t.get("name"),
                       "description": str(t.get("description") or "")[:140]}
                      for t in sondado["tools"]]}


# ── creaciones de prueba (APAGADAS salvo flag + confirmación) ─────────────
async def crear_pruebas(ejecutar_fn) -> list[dict]:
    """Tres creaciones mínimas de prueba vía mcp_manager.execute. SOLO se
    llama con --crear-prueba --confirmo 'SI CREAR'. `ejecutar_fn` es el
    doble de prueba en tests (nunca Flow/NotebookLM reales)."""
    pruebas = [
        ("flow_new_project_con_nombre", "google-flow", "flow_new_project",
         {"name": "SONDA · prueba · borrar"}),
        ("crear_personaje_con_nombre", "google-flow", "flow_new_character",
         {"name": "SONDA · prueba · borrar"}),
        ("notebook_create_con_titulo", "notebooklm", "notebook_create",
         {"notebook": "SONDA · prueba · borrar"}),
    ]
    out = []
    for etiqueta, service, tool, args in pruebas:
        try:
            res = await ejecutar_fn(service, tool, args)
            out.append({"prueba": etiqueta, "resultado": "EJECUTADA",
                        "detalle": str(res)[:200]})
        except Exception as exc:  # noqa: BLE001 — el fallo ES el dato
            out.append({"prueba": etiqueta, "resultado": "FALLO",
                        "detalle": f"{type(exc).__name__}: {exc}"[:200]})
    return out


async def _correr(args) -> int:
    servicios = (["google-flow", "notebooklm"] if args.servicio == "ambos"
                 else [args.servicio])
    bloque = {}
    for svc in servicios:
        sondado = await sondar_mcp(svc)
        bloque[svc] = _resumen(svc, sondado)

    informe = {
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "regla": "solo lectura; NADA se crea salvo --crear-prueba + confirmación",
        "servicios": bloque,
    }
    if args.crear_prueba:
        if (args.confirmo or "").strip().upper() != CONFIRMACION_REQUERIDA:
            print("REFUSADO: --crear-prueba exige --confirmo \"SI CREAR\" "
                  "(nada se creó).", file=sys.stderr)
            return 2
        from services.mcp_manager import manager
        informe["creaciones_de_prueba"] = await crear_pruebas(manager.execute)

    texto = json.dumps(informe, ensure_ascii=False, indent=2)
    print(texto)
    if args.salida:
        Path(args.salida).write_text(texto + "\n", encoding="utf-8")
        print(f"informe guardado en {args.salida}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Sonda de capacidades MCP para la convención de nombres "
                    "(solo lectura; nunca crea nada salvo flag+confirmación)")
    ap.add_argument("--servicio", choices=("ambos", "google-flow", "notebooklm"),
                    default="ambos")
    ap.add_argument("--salida", default=None,
                    help="ruta JSON donde guardar el informe")
    ap.add_argument("--crear-prueba", action="store_true",
                    help="APAGADO por defecto: permite creaciones de prueba")
    ap.add_argument("--confirmo", default=None,
                    help="exigir el texto exacto \"SI CREAR\"")
    return asyncio.run(_correr(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
