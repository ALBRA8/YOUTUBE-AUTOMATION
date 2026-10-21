# INT-007 — GATE B / REFERENCE & ASSET LINEAGE

**Fecha:** 2026-10-21  
**Repositorio:** `ALBRA8/YOUTUBE-AUTOMATION`  
**Rama de referencia:** `main`  
**Estado actualizado:** Gate A PASS · Gate B PASS (gap identificado) · Gate B.1 PASS · Gate B.2 implementación PASS · Gate B.2R LIVE reference consumption PASS según evidencia reportada.

---

## 1. CONTEXTO Y DECISIÓN ARQUITECTÓNICA

El puente `YOUTUBE-AUTOMATION × GoogleFlowMCP` fue validado mediante generación real en Google Flow. Posteriormente se implementó y probó el puente de referencias locales.

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

La auditoría de lineage confirmó que las referencias creativas ya existían y se transportaban parcialmente por el sistema, pero no llegaban al generador MCP.

### Cadena antes de B.2

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

Dictamen: **INTEGRATION GAP**, corregido en B.2 según el informe de implementación y LIVE TEST 2R.

---

## 3. GATE B.1 — DISEÑO DEL SCENE ASSET RESOLVER

Se aprobó una única abstracción pequeña:

`backend/pipeline/asset_resolver.py`

Responsabilidades:

1. Extraer referencias desde `scene.meta.production_unit.references` o `scene.references`.
2. Normalizar referencias locales soportadas.
3. Validar existencia/integridad básica del archivo.
4. Generar nombres de asset deterministas.
5. Construir menciones `@{asset_name}`.

El transporte MCP permanece en `backend/services/flow_mcp_client.py`. El punto de orquestación permanece en `backend/pipeline/images.py`.

La imagen ancla de escena 0 queda fuera de este mecanismo hasta que exista un contrato explícito que la defina como referencia de Google Flow.

---

## 4. GATE B.2 — IMPLEMENTACIÓN

### Archivos creados/modificados reportados

- `backend/pipeline/asset_resolver.py` — nuevo resolver ligero.
- `backend/pipeline/images.py` — integración limitada al bloque Plan 0.
- `tests/test_scene_asset_resolver.py` — pruebas del resolver.
- `tests/test_live_execution_2.py` — prueba LIVE de referencia.

### Comportamiento implementado reportado

- Sin referencias: comportamiento anterior preservado; no se realizan uploads ni menciones.
- Referencia local válida: se resuelve y prepara para upload.
- URLs remotas sin descarga local: se descartan con razón `REMOTE_URL`.
- Nombres: sanitización determinista con límite de 24 caracteres y desambiguación de colisiones.
- Menciones: formato `@{asset_name}` preservado.
- Referencias opcionales con fallo de upload: warning y degradación controlada.
- Referencias requeridas: error controlado cuando el contrato actual permite identificar esa obligatoriedad.
- `FLOW_MCP_ENABLED=0`: no se ejecuta el resolver MCP y se preserva la cadena legacy.

### Tests reportados

- `tests/test_scene_asset_resolver.py`: **22/22 PASS**.
- Suite combinada: **45/45 PASS**.
- `node tests/flow_batchexecute_eb1hjf_mock.js`: **PASS**.
- `git diff --check`: **0 errores**.

Estos resultados proceden del informe de ejecución proporcionado; no constituyen una ejecución independiente de las pruebas en este documento.

---

## 5. LIVE TEST 2 — UPLOAD Y RENAME

Referencia utilizada:

`backend/data/output/_live_mcp_test_01/scene_01.png`

Tamaño: **963,905 bytes**. Asset name: `crystal_orb`.

### Evidencia reportada

1. El archivo local fue subido físicamente a Google Flow.
2. Google Flow asignó el media ID `40be5550-1eb5-43c0-a940-593147159f1d`.
3. El asset fue renombrado en la UI a `crystal_orb`.
4. El diagnóstico DOM mostró `aria-label="crystal_orb"` y `span.footer-title = "crystal_orb"`.

### Bug de compatibilidad detectado

La UI actual de Google Flow oculta visualmente `.footer-overlay` / `span.footer-title` hasta hover. La verificación anterior con `innerText()` sin hover podía devolver cadena vacía aunque el contenido existiera.

Diagnóstico reportado:

- `textContent()` → `crystal_orb`.
- `hover()` + `innerText()` → `crystal_orb`.
- `innerText()` sin hover → `""`.

Esto se clasificó como bug de compatibilidad de verificación DOM en GoogleFlowMCP, no como fallo del upload ni del resolver.

---

## 6. GATE B.2R — FIX Y LIVE REFERENCE CONSUMPTION

**Estado reportado: PASS.** Este cierre se basa en el informe de ejecución de B.2R entregado el 2026-10-21; el diff local y los artefactos no se inspeccionaron de forma independiente al registrar esta actualización.

### Fix aplicado reportado

Archivo modificado:

`tools/GoogleFlowMCP/src/flow.js`

La verificación de `renameTile()` se reforzó con:

1. `tile.hover().catch(() => {})` para activar el estado de interacción de la tarjeta.
2. `textContent()` para inspeccionar el título aunque esté oculto por CSS.
3. `innerText()` como comprobación complementaria.

La validación final reportó `shown = "crystal_orb"` con coincidencia exacta.

### Regresión reportada

- `npm test` en `tools/GoogleFlowMCP`: **3/3 PASS**.
- `tests/test_scene_asset_resolver.py`: **22/22 PASS**.
- `tests/test_flow_mcp_bridge.py`: **21/21 PASS**.
- Suite combinada `tests/test_flow_bridge.py tests/test_bridge_e2e.py tests/test_flow_mcp_bridge.py tests/test_scene_asset_resolver.py`: **45/45 PASS** en 17.73 s.
- `node tests/flow_batchexecute_eb1hjf_mock.js`: **PASS**.
- `git diff --check`: **0 errores**.

### LIVE TEST 2R — evidencia reportada

| Campo | Resultado |
|---|---|
| Referencia local | `backend/data/output/_live_mcp_test_01/scene_01.png` |
| Tamaño de referencia | 963,905 bytes |
| Asset name | `crystal_orb` |
| Upload | PASS |
| Media ID de referencia | `f7057dfd-9eb5-415b-b4da-5edb16871292` |
| Rename y verificación | PASS; coincidencia exacta `crystal_orb` |
| Duración | 44.60 s |
| Prompt | `Referencing @{crystal_orb}: Transform this artifact into a radiant cosmic galaxy orb surrounded by stardust, 8k resolution, cinematic lighting, cinematic lighting, hyperdetailed, 8k resolution, photorealistic, 35mm film grain, masterpiece, no text, no letters, no watermark, no distorted anatomy, coherent facial features, natural hands` |
| Mention-chip | PASS reportado; el selector de ingredientes encontró `crystal_orb` y se verificó el incremento de `div.ProseMirror span.mention-chip` |
| Generación | PASS reportado |
| Imagen de salida | `backend/data/output/_live_mcp_test_02r/scene_01.png` |
| Copia de artefacto | `live_test_02r_scene_01.png` |
| Tamaño de salida | 890,967 bytes |
| Dimensiones/formato reportados | 768 × 1376, 9:16, PNG |
| Validación binaria | `flow_mcp_client.verify_image_file() = True` |
| Sidecar | `{"method":"flow_mcp"}` |
| Lock final | `.flow.lock` liberado; `exists = False` |

### Dictamen de referencia

**`REFERENCE CONSUMPTION PASS` — según evidencia reportada.**

La verificación de `mention-chip` prueba que la referencia fue seleccionada e insertada interactivamente en el editor de Google Flow antes de generar. Esto demuestra el consumo de la referencia por el mecanismo de entrada de Flow; no demuestra por sí solo el grado de influencia visual que tuvo en los píxeles de salida.

### Archivos de trabajo reportados al terminar B.2R

- Modificado: `backend/pipeline/images.py`
- Modificado: `tools/GoogleFlowMCP/src/flow.js`
- Nuevo: `backend/pipeline/asset_resolver.py`
- Nuevo: `tests/test_live_execution_2.py`
- Nuevo: `tests/test_scene_asset_resolver.py`

El informe indicó que no se hicieron commits ni pushes. Por tanto, este inventario es el estado de trabajo reportado, no una afirmación de que esos archivos ya estén presentes en `origin/main`.

---

## 7. ESTADO CONSOLIDADO DE GATES

| Gate | Dictamen |
|---|---|
| A — generación básica MCP LIVE | PASS |
| B — auditoría lineage | PASS; integration gap identificado |
| B.1 — diseño del resolver | PASS |
| B.2 — implementación del resolver | PASS según tests reportados |
| B.2 — upload y rename LIVE | PASS |
| B.2R — verificación de rename | PASS reportado |
| B.2R — inserción de mention-chip | PASS reportado |
| B.2R — generación y PNG válido | PASS reportado |
| B.2R — lock liberado | PASS reportado |

**Conclusión técnica:** el flujo de referencia local → upload → nombre de asset → mention-chip de Google Flow → generación de imagen se reportó como validado LIVE.

---

## 8. SIGUIENTE PASO Y CONTROL DE GIT

El informe de B.2R propuso consolidar en `main` mediante commit atómico y push. Sin embargo, el propio informe indica que siguen existiendo cambios locales sin commit y que no se han hecho pushes.

Antes de consolidar, revisar en la máquina de trabajo:

1. `git status --short`
2. `git diff --check`
3. `git diff` completo, incluyendo revisión de los archivos nuevos.
4. Confirmar que no haya archivos runtime, secretos, perfiles, imágenes de salida o datos de sesión en el conjunto a versionar.
5. Ejecutar las pruebas relevantes desde el árbol de trabajo que se pretende publicar.

**No se ha hecho commit ni push desde esta actualización documental.** La consolidación de código debe ser una operación separada y explícitamente autorizada.

---

## 9. FRONTERAS QUE NO CAMBIAN

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

## 10. REFERENCIA OPERATIVA

Este documento complementa `INT-006_GOOGLE_FLOW_MCP.md` y prevalece sobre cualquier sección histórica que indique que no se ha ejecutado generación real o que el puente no está integrado.

**Fuente de verdad funcional:** código del repositorio correspondiente y evidencia de cada Gate. Los resultados LIVE de B.2R se registran como reportados por la sesión de trabajo; deben cotejarse con el diff y los artefactos locales antes de consolidar el código en `main`.
