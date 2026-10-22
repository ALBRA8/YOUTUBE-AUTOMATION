# DECISION LOG

## D-001 — Separación cuerpo central / especialización
- **Estado:** VERIFIED (decisión vigente).
- **Decisión:** AGENTE-GENERAL conserva infraestructura transversal; lógica audiovisual/Google Flow queda en YOUTUBE-AUTOMATION.
- **Motivo:** evitar duplicación y preservar arquitectura de especializaciones.

## D-002 — No implementar Start Frame antes de capturar request real
- **Estado:** IN_PROGRESS / BLOCKED por evidencia externa.
- **Decisión:** no codificar aún binding de Start Frame de Google Flow.
- **Evidencia:** contrato construye `start_frame: None` y `end_frame: None`; camino Flow auditado inyecta prompt sin mostrar selección/binding de imagen; HAR histórico mostró `inputFrames.firstFrame.mediaId`, pero otra variante observada usa `startImage.mediaId`.
- **Criterio de salida:** request real sanitizada correlaciona imagen conocida, mediaId de entrada y resultado.

## D-003 — Referencias transportadas no significan ejecución
- **Estado:** VERIFIED. `references` se considera transportada hasta demostrar que el proveedor recibe/usa el asset.

## D-004 — Separar mediaId de entrada y de resultado
- **Estado:** VERIFIED. Un ID extraído de respuesta no prueba qué imagen se envió como input.

## D-005 — No declarar E2E real desde pruebas simuladas
- **Estado:** VERIFIED. Mocks, VM, DOM, fixtures y HTTP backend validan sus propios alcances, no Google Flow real.

## D-006 — Preservar P1 y capas fuera de alcance
- **Estado:** VERIFIED. No tocar Creative Engine, P1, Production JSON, orquestador, leases/heartbeat, HANDS núcleo ni AGENTE-GENERAL sin evidencia causal.

## D-007 — Frontera operativa Constructor / Antigravity
- **Estado:** VERIFIED / VIGENTE.
- **Decisión:** el **Constructor en la nube** es el agente responsable del trabajo sobre el código real del repositorio GitHub: auditoría del repositorio, modificaciones de código, conexiones/integraciones y documentación/versionado. **Google Antigravity**, instalado en el computador del usuario, es el agente destinado principalmente a pruebas locales, validaciones, despliegues y comprobaciones que dependan del entorno físico/local.
- **Regla de operación:** no trasladar al computador una auditoría o modificación de repositorio que el Constructor pueda realizar en GitHub; no cargar al Constructor con pruebas que necesariamente dependan del entorno local. ChatGPT coordina la arquitectura, determina qué agente corresponde y valida los resultados.
- **Alcance temporal:** esta separación se adopta como regla estable del flujo de trabajo, no como una excepción de corto plazo.

## D-008 — Agnes Video Generator: referencia de solo lectura, sin importación de código
- **Estado:** VERIFIED / VIGENTE. Comparación dirigida basada en código real en `06_INTEGRATIONS/INT-019_AGNES_COMPARACION_DIRIGIDA.md` (evaluación inicial: INT-018).
- **Decisión:** no importar código, dependencias ni componentes de lcy362/agnes-video-generator (MIT). Sus capacidades valiosas ya existen en YOUTUBE-AUTOMATION (checkpoint/reanudación, QA de producto, errores) o quedan registradas como ideas adaptables R1/R2/R3 con decisión separada. Prohibido usarlo como orquestador alternativo o crear un agente editor de vídeo.
- **Evidencia:** tabla comparativa 6 áreas con anclas archivo:línea de ambos repos; licencia MIT verificada en el clon; cero líneas copiadas; suite canónica en verde tras el fix INT-020.
