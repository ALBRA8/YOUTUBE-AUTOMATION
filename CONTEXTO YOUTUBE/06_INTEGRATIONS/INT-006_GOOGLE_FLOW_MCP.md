# INT-006 — INTEGRACIÓN GoogleFlowMCP

**Última actualización:** 2026-10-21  
**Estado actual:** PUENTE LIVE VALIDADO · `FLOW_MCP_ENABLED=0` POR DEFECTO  
**Ubicación:** `D:\PROYECTOS\YOUTUBE AUTOMATION\tools\GoogleFlowMCP`  
**Servidor:** `srz-google-flow-mcp` v1.0.1  
**Protocolo:** MCP Stdio / JSON-RPC 2.0  
**Transporte navegador:** Chrome DevTools Protocol (CDP), puerto 9333

> **IMPORTANTE:** Este documento reemplaza el estado histórico que indicaba que no se había ejecutado generación real. Desde el 2026-10-21 el puente básico fue probado LIVE con Google Flow y posteriormente se implementó el Scene Asset Resolver. El detalle de Reference / Asset Lineage está documentado en `INT-007_GATE_B_REFERENCE_ASSET_LINEAGE.md`.

---

## 1. FRONTERA ARQUITECTÓNICA

`GoogleFlowMCP` es un **puente técnico**, no un agente ni un orquestador.

`YOUTUBE-AUTOMATION` mantiene la responsabilidad de orquestación audiovisual. Google Flow es un proveedor/capacidad de generación.

No se crea un nuevo agente, Production Studio, VIDEO EDITOR AGENT, QA paralelo ni MCP adicional para esta integración.

La extensión Chrome y GoogleFlowMCP son mecanismos diferentes:

```text
GoogleFlowMCP
   ↓ MCP / stdio
Node.js
   ↓ CDP :9333
Chrome dedicado
   ↓
Google Flow
```

GoogleFlowMCP no depende de la extensión para transportar la generación.

---

## 2. COMPONENTES PRINCIPALES

- `backend/services/flow_mcp_client.py` — cliente Python asíncrono MCP.
- `backend/config.py` — `FLOW_MCP_ENABLED`, `FLOW_MCP_DIR`, `FLOW_MCP_MODEL`, `FLOW_MCP_TIMEOUT`.
- `backend/pipeline/images.py` — Plan 0 condicional `flow_mcp` y fallback existente.
- `tools/GoogleFlowMCP/src/mcp.js` — servidor MCP.
- `tools/GoogleFlowMCP/src/flow.js` — interacción con Google Flow, prompts, assets y uploads.
- `tools/GoogleFlowMCP/src/chrome.js` — Chrome/CDP.
- `tools/GoogleFlowMCP/src/lock.js` — exclusión mutua.

Herramientas MCP expuestas:

1. `flow_generate_image`
2. `flow_upload_file`
3. `flow_list_assets`
4. `flow_new_project`

---

## 3. CONFIGURACIÓN Y SEGURIDAD

- `FLOW_MCP_ENABLED=0` continúa como valor por defecto.
- El perfil Chrome dedicado permanece fuera del repositorio.
- No se almacenan cookies, tokens ni credenciales en Git.
- `.flow.lock`, `state.json`, `config.json`, `output/*`, `inputs/*` y `node_modules/` permanecen excluidos según `.gitignore`.
- La activación permanente del MCP en la configuración de Antigravity no forma parte de este documento ni de los Gates actuales.

---

## 4. VALIDACIÓN PREVIA DEL PUENTE

GoogleFlowMCP fue instalado y probado localmente.

- `npm ci`: PASS.
- 95 paquetes instalados, 0 vulnerabilidades reportadas.
- `npm test`: 3/3 PASS para concurrencia/locks.
- Handshake MCP: PASS.
- `tools/list`: PASS.
- Cliente Python: 21/21 tests PASS en la batería original del bridge.

---

## 5. LIVE TEST 1 — GENERACIÓN BÁSICA

Proyecto aislado:

`_live_mcp_test_01`

Prompt:

`A glowing crystal artifact floating in an ancient stone temple, cinematic lighting, ultra detailed`

Resultado:

- `FLOW_MCP_ENABLED=True` en memoria.
- `flow_mcp_client.available()=True`.
- Método efectivo: `flow_mcp`.
- Duración: 30.20 s.
- PNG: `backend/data/output/_live_mcp_test_01/scene_01.png`.
- Tamaño: 963,905 bytes.
- Validación binaria: PASS.
- `.flow.lock` tras ejecución: ausente.

**Gate A: PASS.**

---

## 6. REFERENCE / ASSET LINEAGE

Gate B detectó un integration gap: `Production JSON` ya conserva `references`, pero el Plan 0 MCP no las convertía en assets de Google Flow.

La capacidad del MCP ya existía:

```text
flow_upload_file()
      ↓
asset name
      ↓
@{asset_name}
      ↓
flow_generate_image()
```

El detalle completo de la auditoría, diseño e implementación está en:

`CONTEXTO YOUTUBE/06_INTEGRATIONS/INT-007_GATE_B_REFERENCE_ASSET_LINEAGE.md`

---

## 7. SCENE ASSET RESOLVER — GATE B.2

Se autorizó una única abstracción nueva:

`backend/pipeline/asset_resolver.py`

Responsabilidades:

- extracción de referencias;
- validación local;
- nombres deterministas;
- manejo de colisiones;
- construcción de `@{asset_name}`.

Integración:

`backend/pipeline/images.py`

No se modificaron `production_json.py`, `flow_jobs.py`, `execution_contract.py` ni la extensión.

Tests del resolver: **22/22 PASS**.

Suite reportada de regresión: **45/45 PASS**.

Mock F5.1: **PASS**.

`git diff --check`: **0 errores**.

---

## 8. LIVE TEST 2 — UPLOAD DE REFERENCIA

Referencia:

`backend/data/output/_live_mcp_test_01/scene_01.png`

Asset name:

`crystal_orb`

Evidencia confirmada:

- upload físico a Google Flow: PASS;
- media ID real: `40be5550-1eb5-43c0-a940-593147159f1d`;
- rename físico en UI: PASS;
- `aria-label="crystal_orb"`: confirmado;
- `span.footer-title` contiene `crystal_orb`: confirmado mediante diagnóstico DOM.

### Limitación detectada

La UI actual oculta el título hasta hover. `renameTile()` utiliza actualmente `innerText()` sin hover, por lo que Chromium/Playwright puede devolver cadena vacía aunque el rename haya ocurrido.

Evidencia:

- `textContent()` → `crystal_orb`.
- `hover()` + `innerText()` → `crystal_orb`.
- `innerText()` sin hover → vacío.

Esto es un **bug de verificación DOM en GoogleFlowMCP**, no un fallo del upload ni del Scene Asset Resolver.

Durante B.2 no se modificó `tools/GoogleFlowMCP` porque esa corrección no estaba autorizada en esa fase.

---

## 9. ESTADO ACTUAL DE LOS GATES

| Gate | Estado |
|---|---|
| Gate A — generación básica LIVE | **PASS** |
| Gate B — Reference / Asset Lineage audit | **PASS — INTEGRATION GAP identificado** |
| Gate B.1 — diseño Scene Asset Resolver | **PASS** |
| Gate B.2 — implementación | **PASS** |
| Gate B.2 — tests | **PASS** |
| Gate B.2 — upload/reference transport LIVE | **PASS** |
| Gate B.2 — rename verification | **PENDING — DOM compatibility fix** |
| Gate B.2 — generación LIVE consumiendo referencia | **PENDING** |
| Gate B.2 — consumo visual determinista de referencia | **PENDING / depende de evidencia** |

**No declarar todavía PASS E2E completo para referencias.**

---

## 10. PRÓXIMO PASO

El único siguiente paso autorizado es:

**Gate B.2R — corrección mínima de la verificación de `renameTile` + LIVE TEST 2R completo.**

Secuencia:

```text
archivo local
   ↓
upload_file()
   ↓
asset_name
   ↓
@{asset_name}
   ↓
flow_generate_image()
   ↓
PNG válido
```

Criterio de evidencia:

- Upload PASS.
- Naming PASS.
- Mention injection PASS.
- Generation PASS.
- PNG válido PASS.
- Lock liberado PASS.
- Si no existe observación determinista del consumo del chip: `REFERENCE TRANSPORT PASS / REFERENCE CONSUMPTION UNVERIFIABLE`.

No tocar Start Frame, imagen ancla de escena 0 ni otros mecanismos avanzados hasta cerrar este gate.
