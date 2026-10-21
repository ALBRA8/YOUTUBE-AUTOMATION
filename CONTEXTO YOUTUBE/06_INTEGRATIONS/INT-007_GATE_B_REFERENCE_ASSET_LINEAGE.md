# INT-007 — GATE B / REFERENCE & ASSET LINEAGE

**Fecha:** 2026-10-21  
**Repositorio:** `ALBRA8/YOUTUBE-AUTOMATION`  
**Rama de referencia:** `main`  
**Estado:** Gate B PASS · Gate B.1 PASS · Gate B.2 IMPLEMENTACIÓN PASS · LIVE REFERENCE CONSUMPTION PENDING

---

## 1. CONTEXTO Y DECISIÓN ARQUITECTÓNICA

El puente `YOUTUBE-AUTOMATION × GoogleFlowMCP` ya fue validado mediante una generación real de imagen en Google Flow.

El LIVE TEST 1 demostró:

- `FLOW_MCP_ENABLED=True` durante la prueba.
- `flow_mcp_client.available()=True`.
- `generate_scene_image()` ejecutó efectivamente mediante `flow_mcp`.
- Google Flow produjo una imagen real.
- PNG válido de 963,905 bytes.
- Resultado persistido en `backend/data/output/_live_mcp_test_01/scene_01.png`.
- `.flow.lock` fue liberado al finalizar.
- Tiempo reportado: 30.20 s.

Conclusión del Gate A: **PASS**.

No se requiere un nuevo agente, MCP, orquestador, Production Studio ni QA paralelo. GoogleFlowMCP permanece como puente técnico; YOUTUBE-AUTOMATION conserva la orquestación audiovisual.

---

## 2. GATE B — AUDITORÍA READ-ONLY

La auditoría de lineage confirmó que las referencias creativas ya existen y se transportan parcialmente por el sistema, pero no llegaban al generador MCP.

### Cadena actual identificada

```text
Production JSON
      ↓
scene.references / production_unit.references
      ↓
DB scenes.meta
      ↓
flow_export → script.json
      ↓
flow_jobs.execution_spec.references
      ↓
execution_contract (UNVERIFIABLE; no bloquea)
      ↓
images.py
      X  ← aquí se perdían para el Plan 0 MCP
      ↓
flow_mcp_client.generate_image(prompt)
      ↓
GoogleFlowMCP
```

### Hallazgo

`images.py` no consumía `scene.meta.production_unit.references` para el Plan 0 GoogleFlowMCP. Tampoco invocaba `flow_mcp_client.upload_file()` ni construía menciones `@{asset_name}`.

El `flow_mcp_client` ya disponía de `upload_file()`, y GoogleFlowMCP ya disponía de la capacidad de convertir `@{name}` en una referencia interactiva de Google Flow.

Dictamen: **INTEGRATION GAP**.

---

## 3. GATE B.1 — DISEÑO DEL SCENE ASSET RESOLVER

Se decidió una única abstracción pequeña:

`backend/pipeline/asset_resolver.py`

Responsabilidades:

1. Extraer referencias desde `scene.meta.production_unit.references` o `scene.references`.
2. Normalizar referencias locales soportadas.
3. Validar existencia/integridad básica del archivo.
4. Generar nombres de asset deterministas.
5. Construir menciones `@{asset_name}`.

El transporte MCP permanece en `backend/services/flow_mcp_client.py`.

El punto de orquestación permanece en `backend/pipeline/images.py`.

No se modifican Production JSON, `flow_jobs`, `execution_contract`, GoogleFlowMCP ni la extensión.

La imagen ancla de escena 0 queda fuera de este mecanismo hasta que exista un contrato explícito que la defina como referencia de Google Flow.

---

## 4. GATE B.2 — IMPLEMENTACIÓN

### Archivos creados/modificados

- `backend/pipeline/asset_resolver.py` — nuevo resolver ligero.
- `backend/pipeline/images.py` — integración limitada al bloque Plan 0.
- `tests/test_scene_asset_resolver.py` — pruebas del resolver.
- `tests/test_live_execution_2.py` — prueba LIVE de referencia.

### Comportamiento implementado

- Sin referencias: comportamiento anterior preservado; no se realizan uploads ni menciones.
- Referencia local válida: se resuelve y se prepara para upload.
- URLs remotas sin descarga local: se descartan con razón `REMOTE_URL`.
- Nombres: sanitización determinista con límite de 24 caracteres y desambiguación de colisiones.
- Menciones: formato `@{asset_name}` preservado.
- Referencias opcionales con fallo de upload: warning y degradación controlada.
- Referencias requeridas: error controlado cuando el contrato actual permite identificar esa obligatoriedad.
- `FLOW_MCP_ENABLED=0`: no se ejecuta el resolver MCP y se preserva la cadena legacy.

### Tests

- `tests/test_scene_asset_resolver.py`: **22/22 PASS**.
- Suite reportada: **45/45 PASS**.
- `node tests/flow_batchexecute_eb1hjf_mock.js`: **PASS**.
- `git diff --check`: **0 errores**.

---

## 5. LIVE TEST 2 — EVIDENCIA

Referencia utilizada:

`backend/data/output/_live_mcp_test_01/scene_01.png`

Tamaño: **963,905 bytes**.

Asset name:

`crystal_orb`

### Evidencia confirmada

1. El archivo local fue subido físicamente a Google Flow.
2. Google Flow asignó el media ID real:
   `40be5550-1eb5-43c0-a940-593147159f1d`.
3. El asset fue renombrado en la UI a `crystal_orb`.
4. La UI mostró `aria-label="crystal_orb"` y `span.footer-title = "crystal_orb"` mediante diagnóstico DOM.

### Hallazgo de compatibilidad

La UI actual de Google Flow oculta visualmente `.footer-overlay` / `span.footer-title` hasta hover.

El código actual de `tools/GoogleFlowMCP/src/flow.js` verifica el rename mediante:

```javascript
const shown = (await tile.locator('span.footer-title').innerText()).trim();
```

Sin hover, Chromium/Playwright puede devolver `""` aunque el contenido exista.

Evidencia diagnóstica:

- `textContent()` → `crystal_orb`.
- `hover()` + `innerText()` → `crystal_orb`.
- `innerText()` sin hover → `""`.

Esto se clasifica como **bug de compatibilidad de verificación DOM en GoogleFlowMCP**, no como fallo del resolver ni del upload.

### Restricción aplicada

Durante Gate B.2 no se modificó `tools/GoogleFlowMCP`, porque esa modificación no estaba autorizada.

---

## 6. ESTADO EXACTO DEL GATE B.2

| Área | Estado |
|---|---|
| Resolver implementado | PASS |
| Integración en `images.py` | PASS |
| Tests del resolver | PASS |
| Regresión reportada | PASS |
| Upload físico a Google Flow | PASS |
| Asset naming / rename físico | PASS |
| Verificación automática actual del rename | PENDING / BUG DOM |
| Injection `@{asset_name}` en pipeline | IMPLEMENTADO / TESTEADO EN MOCK |
| Generación LIVE usando la referencia | **PENDING** |
| Consumo visual verificable de la referencia | **PENDING** |

Por lo tanto, **Gate B.2 no debe marcarse todavía como PASS E2E completo**.

---

## 7. PRÓXIMO PASO AUTORIZADO

Únicamente:

### Gate B.2R — Rename verification fix + LIVE reference consumption

1. Corregir de forma mínima la verificación de `renameTile` en `tools/GoogleFlowMCP/src/flow.js`, respetando el DOM actual y los contratos existentes.
2. No alterar la arquitectura ni crear nuevos componentes.
3. Ejecutar regresión completa.
4. Ejecutar LIVE TEST 2R:

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

### Criterios de evidencia

- Upload PASS.
- Asset naming PASS.
- Mention injection PASS.
- Google Flow acepta la mención: PASS si existe evidencia observable.
- Generation PASS.
- PNG válido PASS.
- Lock liberado PASS.

No se debe afirmar que Google Flow consumió visualmente la referencia solo porque el upload tuvo éxito.

Si no existe una forma determinista de observar el consumo del chip/reference:

`REFERENCE TRANSPORT PASS / REFERENCE CONSUMPTION UNVERIFIABLE`.

---

## 8. FRONTERAS QUE NO CAMBIAN

- GoogleFlowMCP no es un agente.
- Google Flow es proveedor/capacidad.
- YOUTUBE-AUTOMATION sigue siendo el orquestador audiovisual.
- No se crea un VIDEO EDITOR AGENT.
- No se crea un nuevo Production Studio.
- No se crea otro QA/orquestador.
- F5/F5.1 de la extensión no se toca.
- La extensión no es dependencia de GoogleFlowMCP para su transporte CDP.
- `FLOW_MCP_ENABLED=0` continúa siendo el default seguro.
- Las credenciales, perfiles Chrome y artefactos runtime permanecen fuera de Git.

---

## 9. REFERENCIA OPERATIVA

Este documento complementa `INT-006_GOOGLE_FLOW_MCP.md` y prevalece sobre cualquier sección histórica de INT-006 que indique que no se ha ejecutado generación real o que el puente aún no está integrado.

**Fuente de verdad funcional actual:** código de `main` + evidencia LIVE de los Gates A/B/B.1/B.2.
