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

## AUD-005 — Puente GoogleFlowMCP YOUTUBE-AUTOMATION
- **Estado:** IMPLEMENTACIÓN Y PRUEBAS AISLADAS REPORTADAS PASS; LIVE TEST PENDIENTE.
- **Fuente:** informe de Antigravity del 2026-10-20; no se reejecutaron aquí las pruebas ni se verificó que los cambios locales estén en el remoto.
- **Resultado reportado:** 21/21 pruebas del puente, regresión mock F5.1 PASS, harness backend 55 OK y pruebas del paquete MCP 3/3 PASS.
- **Diseño:** `FLOW_MCP_ENABLED=0` por defecto; generación condicional; validación del archivo y fallback a proveedores existentes.
- **Bloqueo LIVE:** el perfil dedicado `%LOCALAPPDATA%\\FlowImageChrome` no existía en el preflight. Debe prepararse y autenticarse de forma interactiva si Google lo exige.
- **Próximo hito:** una imagen real a través de pipeline → MCP → Google Flow → archivo validado, en carpeta aislada y con autorización explícita.
- **Límite:** no equivale a evidencia de Start Frame; no modifica el estado del AUD-002.
