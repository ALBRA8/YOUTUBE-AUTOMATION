# AUDIT INDEX

## AUD-001 — Integración AGENTE-GENERAL + YOUTUBE-AUTOMATION
- **Estado:** VERIFIED para la frontera arquitectónica.
- **Resultado:** no introducir lógica específica de Flow en AGENTE-GENERAL.

## AUD-002 — Start Frame / End Frame de Google Flow
- **Estado:** STATIC AUDIT COMPLETE; LIVE UI CAPTURE PARTIAL; REAL PROTOCOL CORRELATION PENDING.
- **Alcance:** Execution Contract, exportación, extensión, interceptor, jobs y estado real.
- **Resultado estático:** referencias transportadas, pero no se demostró binding de imagen de entrada al request; Start/End Frame no son controles verificables en el contrato auditado.
- **Resultado live:** la UI real de Flow expone `Fotogramas` separado de `Ingredientes`, con slots `Iniciar` y `Finalizar`. Una imagen conocida fue colocada en `Iniciar` y la generación produjo vídeo.
- **Observabilidad:** la extensión v2.5.0 capturó observaciones `WuwhI` reales; se observaron 4 registros después de la generación.
- **Pendiente:** identificar el registro `MEDIA_GENERATION` y demostrar el `mediaId` de Start Frame en el payload real.
- **No concluye:** que una ejecución real actual haya fallado ni que un campo específico sea universal.

## AUD-003 — Actualización Git / memoria de continuidad
- **Estado:** COMPLETED para la comparación realizada.
- **Baseline histórico:** comparación inicial de YOUTUBE-AUTOMATION `main` contra `f23ce558...` encontró 4 commits posteriores que solo cambiaban documentación bajo `CONTEXTO YOUTUBE/`.
- **Después:** se agregaron/actualizaron documentos de memoria. La comparación final contra el mismo baseline informó 18 commits por delante; todos los archivos listados eran documentos de `CONTEXTO YOUTUBE/`, sin código funcional modificado en esa comparación.
- **AGENTE-GENERAL:** `main` idéntico al baseline `9b28990...` en la comparación realizada.
- **Precaución:** refrescar hashes en la siguiente sesión.

## AUD-004 — Instrumentación pasiva batchexecute / Start Frame
- **Estado:** PASS CONDITIONAL / LIVE OBSERVABILITY CONFIRMED.
- **Referencia:** commit `2d0a99b85fa8c7f224b5c8660708411b1617e32a`.
- **Resultado:** la extensión puede observar `batchexecute` y registrar `WuwhI`, `eb1hJf`, `jwpduf` y `as29s` sin alterar el tráfico; harness reportado 15/15 y F1 64/64.
- **Límite:** el harness no sustituye la correlación con el proveedor real.

## AUD-005 — Auditoría técnica y cierre F5 del fix de ingestión polimórfica (Flow Script Processor 2.6.0)
- **Estado:** CLOSED / APROBADO CON RIESGOS DOCUMENTADOS.
- **Alcance:** Modificaciones en `extension/injector.js`, `tests/flow_batchexecute_eb1hjf_mock.js`, y `tests/test_flow_startframe_eb1hjf.py`.
- **Objetivo:** Auditar la semántica de `fetch(Request)`, clonación con `input.clone().text()`, duck-typing de cuerpos, protección de streams y orden causal determinista de telemetría.
- **Intervención F5 complementaria:** Corrección de precedencia de `init.body` explícito (`body: ""` y `body: null` ya no inspeccionan el Request anterior) y coordinación causal de `captureResponse` detrás de `reqObsPromise`.
- **Resultados de pruebas locales consolidados:** 244/244 PASS acumulados (F1: 64, F2: 67, eb1hJf Dual+F5: 58, Harness: 55).
- **Puertas de control:** NO COMMIT, NO LIVE, NO MERGE, NO CONSTRUCTOR. Listo para solicitud de autorización de LIVE Gate.

## AUD-006 — Auditoría de preparación e instalación de GoogleFlowMCP (tools/GoogleFlowMCP)
- **Estado:** CLOSED / PASS (Fase de Preparación Completada y Verificada).
- **Referencia detallada:** [`AUD-006_GOOGLE_FLOW_MCP_PREPARATION.md`](./AUD-006_GOOGLE_FLOW_MCP_PREPARATION.md).
- **Alcance:** Ubicación definitiva en `tools/GoogleFlowMCP`, verificación de integridad de 15 archivos, pruebas de instalación `npm ci` (0 vulnerabilidades), pruebas de concurrencia `npm test` (3/3 pass), handshake Stdio MCP e introspección de 4 herramientas (`tools/list`).
- **Aislamiento:** Perfil Chrome independiente en `%LOCALAPPDATA%\FlowImageChrome`, puerto CDP 9333 sin conflicto con ALBRA (8000), exclusiones de Git verificadas mediante `git check-ignore`.
- **Puertas de control:** Desacoplado de producción, sin conexión a Antigravity activa, sin navegación real en Chrome. Listo para revisión de cierre de fase.
