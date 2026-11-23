#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PASO 1 · SONDA DE CAPACIDADES — nombres en Flow y NotebookLM (SOLO LECTURA).

QUÉ HACE: lee el catálogo de herramientas con su `inputSchema` de los dos
MCP del repo y responde con evidencia las 10 preguntas de la convención
de nombres (q1-q7) y de dirigibilidad de Flow (q8-q10, Y2):

  q1_flow_proyecto_nombre   ¿flow_new_project acepta nombre o hay
                            herramienta para renombrar proyecto?
  q2_flow_personaje_nombre  ¿se puede crear un personaje con nombre?
  q3_notebook_create_titulo ¿notebook_create acepta título?
  q4_notebook_renombrar     ¿existe herramienta para renombrar cuaderno?
  q5_source_add_titulo      ¿la herramienta de añadir texto
                            (notebook_add_text en el paquete real v0.1.15;
                            source_add era el nombre legacy) acepta título
                            — incluso OPCIONAL — en su esquema? (Y2)
  q6_flow_generacion_destino  ¿flow_generate_image / flow_generate_video /
                            flow_upload_file aceptan un identificador de
                            proyecto o destino? (Q2, 2026-11-07)
  q7_flow_new_project_cambia_activo  ¿flow_new_project cambia el proyecto
                            ACTIVO sobre el que generan las demás
                            herramientas? (Q2, 2026-11-07)
  q8_flow_new_project_nombre  ¿flow_new_project acepta un nombre, SOLO por
                            esquema sin recurrir a renombrar? (Y2)
  q9_flow_new_project_devuelve  ¿qué devuelve flow_new_project (id, URL o
                            nada)? — outputSchema o descripción (Y2)
  q10_flow_generacion_identificador_proyecto  ¿generate/upload aceptan un
                            IDENTIFICADOR DE PROYECTO (no un destino
                            genérico)? (Y2)

VEREDICTO por pregunta: SOPORTADO (hay evidencia en el esquema/outputSchema/
descripción) / NO_SOPORTADO (hay catálogo y NO está) / NOT_DEMONSTRATED
(sin catálogo real: p. ej. sin la máquina del dueño). NUNCA CREA NADA: la
sonda solo lee catálogos. El flag --crear-prueba (APAGADO por defecto) es
el único que permite creaciones de prueba y exige --confirmo "SI CREAR".

DÓNDE LEE EL CATÁLOGO (Y2):
  · DEFAULT — HTTP: GET /api/mcp/catalogo/{service} contra el backend YA en
    marcha (127.0.0.1:PORT de backend/.env; X-API-Key si hay
    MASTER_API_KEY). Solo lectura pura: NO lanza procesos de servidores
    MCP — evita el «timeout de 30 s en initialize» y los procesos
    duplicados que daban problemas en la máquina del dueño.
  · --modo-local — vía antigua: importa services.mcp_manager en ESTE
    proceso y puede lanzar servidores MCP DUPLICADOS (advertencia
    explícita). Solo para cuando el backend no está en marcha.

USO (máquina del dueño):
  python tools/sonda_capacidades_nombres.py                 # HTTP al backend en marcha
  python tools/sonda_capacidades_nombres.py --salida rep.json
  python tools/sonda_capacidades_nombres.py --modo-local    # proceso propio (aviso)
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
     "¿la herramienta de añadir texto (notebook_add_text / source_add) "
     "acepta título — incluso opcional — en su esquema?"),
    ("q6_flow_generacion_destino",
     "¿flow_generate_image / flow_generate_video / flow_upload_file aceptan "
     "un identificador de proyecto o destino?"),
    ("q7_flow_new_project_cambia_activo",
     "¿flow_new_project cambia el proyecto activo sobre el que generan "
     "las demás herramientas?"),
    ("q8_flow_new_project_nombre",
     "¿flow_new_project acepta un nombre (solo por esquema, sin recurrir "
     "a renombrar)?"),
    ("q9_flow_new_project_devuelve",
     "¿qué devuelve flow_new_project (id, URL o nada)?"),
    ("q10_flow_generacion_identificador_proyecto",
     "¿flow_generate_image / flow_generate_video / flow_upload_file "
     "aceptan un IDENTIFICADOR DE PROYECTO (no un destino genérico)?"),
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
# q10 (Y2): IDENTIFICADOR DE PROYECTO explícito — más estricto que el
# destino genérico de q6 (un folder/workspace no es un id de proyecto).
_RE_ID_PROYECTO = re.compile(
    r"^(project_id|project|project_name|proyecto|proyecto_id|"
    r"target_project|destination_project|destination_project_id)$",
    re.IGNORECASE)
# q5 (Y2): capacidad «añadir texto» — notebook_add_text en el paquete real
# v0.1.15; source_add era el nombre legacy de nlm_studio.
_RE_ANADIR_TEXTO = re.compile(
    r"^(notebook_add_text|source_add)$", re.IGNORECASE)
# q9 (Y2): qué devuelve flow_new_project — outputSchema o descripción.
_RE_DEVUELVE_SI = re.compile(
    r"(devuelve|returns?|retorna|emite)[^.\n]{0,80}\b"
    r"(id|identificador|url|enlace|link|project_id|proyecto_id)\b",
    re.IGNORECASE)
_RE_DEVUELVE_NO = re.compile(
    r"(no devuelve|no retorna|returns nothing|no retorna nada|"
    r"sin valor de retorno|does not return)", re.IGNORECASE)
_RE_SCHEMA_RETORNO = re.compile(
    r"^(id|project_id|proyecto_id|url|link|enlace)$", re.IGNORECASE)
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
        # q8 (Y2) · ¿flow_new_project acepta un nombre? — SOLO esquema, sin
        # el rescate de q1 vía herramienta de renombrar.
        if not hay:
            v8, d8 = PEND, "sin catálogo real del MCP (NOT_DEMONSTRATED)"
        elif fnp is None:
            v8, d8 = PEND, "flow_new_project no está en el catálogo observado"
        elif _toma_nombre(props.get(fnp.get("name"), set())):
            v8 = SOPORTADO
            d8 = (f"flow_new_project acepta "
                  f"'{_toma_nombre(props.get(fnp.get('name'), set()))}' en su esquema")
        else:
            v8 = NO_SOPORTADO
            d8 = "flow_new_project existe pero su esquema no expone nombre"
        # q9 (Y2) · ¿qué devuelve flow_new_project (id, URL o nada)? —
        # evidencia en outputSchema o en la descripción; sin evidencia, el
        # veredicto honesto es NOT_DEMONSTRATED (jamás se inventa).
        if not hay or fnp is None:
            v9, d9 = PEND, ("sin catálogo real del MCP (NOT_DEMONSTRATED)"
                            if not hay else
                            "flow_new_project no está en el catálogo observado")
        else:
            out_props = _props(fnp.get("outputSchema"))
            ids_out = sorted(p for p in out_props if _RE_SCHEMA_RETORNO.match(p))
            desc9 = str(fnp.get("description") or "")
            m_si = _RE_DEVUELVE_SI.search(desc9)
            if ids_out:
                v9 = SOPORTADO
                d9 = ("outputSchema expone: " + ", ".join(ids_out))
            elif m_si:
                v9 = SOPORTADO
                d9 = "la descripción declara el retorno: «" + m_si.group(0) + "»"
            elif _RE_DEVUELVE_NO.search(desc9):
                v9 = NO_SOPORTADO
                d9 = "la descripción declara que NO devuelve nada"
            else:
                v9, d9 = PEND, ("ni el outputSchema ni la descripción evidencian "
                                "qué devuelve; requiere demostración en la "
                                "máquina del dueño")
        # q10 (Y2) · ¿generate/upload aceptan un IDENTIFICADOR DE PROYECTO?
        # (más estricto que q6: un folder/workspace no es un id de proyecto)
        gen10 = [(t, {p for p in props.get(t.get("name"), set())
                      if _RE_ID_PROYECTO.match(p)})
                 for t in tools if _RE_GENERACION.match(str(t.get("name") or ""))]
        if not hay:
            v10, d10 = PEND, "sin catálogo real del MCP (NOT_DEMONSTRATED)"
        elif not gen10:
            v10, d10 = PEND, ("no hay herramientas flow_generate_image/"
                              "flow_generate_video/flow_upload_file en el "
                              "catálogo observado")
        elif all(con for _, con in gen10):
            v10 = SOPORTADO
            d10 = "aceptan id de proyecto: " + "; ".join(
                f"{t.get('name')} acepta '{sorted(con)[0]}'"
                for t, con in gen10 if con)
        else:
            v10 = NO_SOPORTADO
            d10 = ("generación sin identificador de proyecto uniforme: " + "; ".join(
                f"{t.get('name')} "
                + (f"acepta '{sorted(con)[0]}'" if con
                   else "sin propiedad de id de proyecto")
                for t, con in gen10))
    else:
        if hay:
            v1 = v2 = v6 = v7 = v8 = v9 = v10 = PEND
            d1 = d2 = d6 = d7 = d8 = d9 = d10 = ("pregunta de Flow; el catálogo es de "
                                                 + service)
        else:
            v1 = v2 = v6 = v7 = v8 = v9 = v10 = PEND
            d1 = d2 = d6 = d7 = d8 = d9 = d10 = "sin catálogo real del MCP (NOT_DEMONSTRATED)"

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
        # q5 (Y2) · capacidad «añadir texto con título»: notebook_add_text
        # en el paquete real v0.1.15; source_add era el nombre legacy de
        # nlm_studio. Basta con que 'title' ESTÉ en el esquema (opcional vale:
        # la pregunta es si lo ACEPTA, no si lo exige).
        at = _tool(tools, _RE_ANADIR_TEXTO)
        acepta = at is not None and "title" in props.get(at.get("name"), set())
        v5, d5 = _veredicto(at, hay, bool(acepta),
                            f"{at.get('name')} acepta 'title' (opcional) en su esquema"
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
               "q7_flow_new_project_cambia_activo": (v7, d7),
               "q8_flow_new_project_nombre": (v8, d8),
               "q9_flow_new_project_devuelve": (v9, d9),
               "q10_flow_generacion_identificador_proyecto": (v10, d10)}
    return [{"id": pid, "pregunta": texto, "veredicto": salidas[pid][0],
             "detalle": salidas[pid][1]}
            for pid, texto in PREGUNTAS]


# ── lectura del catálogo (Y2) ─────────────────────────────────────────────
def _leer_env_backend(ruta: Path | None = None) -> tuple[int, str]:
    """(PORT, MASTER_API_KEY) leídos de backend/.env SIN levantar el backend.
    Ignora comentarios y valores vacíos; default 8000 / ""."""
    ruta = ruta or (BACKEND / ".env")
    port, key = 8000, ""
    if ruta.is_file():
        for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
            s = linea.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k == "PORT" and v.isdigit():
                port = int(v)
            elif k == "MASTER_API_KEY" and v:
                key = v
    return port, key


def _catalogo_via_http(service: str) -> dict:
    """Lee GET /api/mcp/catalogo/{service} del backend YA en marcha
    (127.0.0.1:PORT de backend/.env; X-API-Key si hay MASTER_API_KEY).
    SOLO LECTURA: el backend sirve su conexión viva — aquí no se lanza
    ningún proceso de servidores MCP. Lanza RuntimeError con mensaje
    claro (y la acción siguiente) si el backend no responde."""
    import urllib.error
    import urllib.request

    port, key = _leer_env_backend()
    url = f"http://127.0.0.1:{port}/api/mcp/catalogo/{service}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if key:
        req.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalle = ""
        try:
            cuerpo = e.read().decode("utf-8")
            detalle = str(json.loads(cuerpo).get("detail") or "")
        except Exception:  # noqa: BLE001 — el detalle es best-effort
            pass
        raise RuntimeError(
            f"HTTP {e.code} del backend en {url}: {detalle or 'sin detalle'}") from e
    except Exception as exc:  # noqa: BLE001 — el mensaje ES el dato
        raise RuntimeError(
            f"el backend no respondió en {url} (¿está en marcha? arranca el "
            f"panel, o usa --modo-local sabiendo que puede lanzar procesos "
            f"duplicados): {type(exc).__name__}: {exc}") from exc


async def sondar_mcp(service: str, catalogo_fn=None, modo: str = "http") -> dict:
    """Lee el catálogo de tools de un servicio.

    modo "http" (DEFAULT): GET /api/mcp/catalogo/{service} contra el backend
      ya en marcha — solo lectura, NO lanza procesos (Y2).
    modo "local" (--modo-local): vía antigua; importa services.mcp_manager
      en ESTE proceso y puede lanzar servidores MCP DUPLICADOS aunque el
      backend ya los tenga conectados.
    `catalogo_fn` sigue admitiéndose como doble de prueba (tests). Cualquier
    error → NOT_DEMONSTRATED (jamás un SOPORTADO inventado)."""
    if catalogo_fn is None:
        if modo == "local":
            from services.mcp_manager import manager
            catalogo_fn = manager.tools_catalog
        else:
            catalogo_fn = _catalogo_via_http
    try:
        cat = catalogo_fn(service)
        if asyncio.iscoroutine(cat):
            cat = await cat   # la vía local (manager.tools_catalog) es async
    except Exception as exc:  # noqa: BLE001 — sin catálogo real: pendiente, honesto
        return {"service": service, "server_info": {}, "tools": [],
                "error": f"{type(exc).__name__}: {exc}"}
    return {"service": service, "server_info": cat.get("server_info", {}),
            "tools": cat.get("tools", []), "error": ""}


def _resumen(service: str, sondado: dict) -> dict:
    return {"service": service, "version": sondado["server_info"],
            "error": sondado["error"],
            "preguntas": analizar_tools(service, sondado["tools"]),
            # Y2: description COMPLETA e inputSchema COMPLETO en el JSON
            # (antes se recortaba a 140 y se perdía el esquema).
            "tools": [{"name": t.get("name"),
                       "description": str(t.get("description") or ""),
                       "inputSchema": dict(t.get("inputSchema") or {})}
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
    modo = "local" if args.modo_local else "http"
    if modo == "local":
        print("AVISO: --modo-local importa el gestor MCP en ESTE proceso y puede "
              "lanzar servidores MCP DUPLICADOS aunque el backend ya los tenga "
              "conectados (en la máquina del dueño ambos dieron «timeout de 30 s "
              "en initialize»). El modo normal lee el catálogo por HTTP del "
              "backend en marcha (GET /api/mcp/catalogo).", file=sys.stderr)
    bloque = {}
    for svc in servicios:
        sondado = await sondar_mcp(svc, modo=modo)
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
    ap.add_argument("--modo-local", action="store_true",
                    help="vía antigua: importa mcp_manager en ESTE proceso y "
                         "puede lanzar servidores MCP DUPLICADOS; el default "
                         "lee el catálogo por HTTP del backend en marcha")
    ap.add_argument("--crear-prueba", action="store_true",
                    help="APAGADO por defecto: permite creaciones de prueba")
    ap.add_argument("--confirmo", default=None,
                    help="exigir el texto exacto \"SI CREAR\"")
    return asyncio.run(_correr(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
