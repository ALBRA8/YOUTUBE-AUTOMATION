# GLOSSARY — YOUTUBE-AUTOMATION

- **AGENTE-GENERAL:** cuerpo central ALBRA; infraestructura transversal y coordinación.
- **YOUTUBE-AUTOMATION:** especialización audiovisual ALBRA.
- **P1 Golden Contract:** prompt creativo `video_prompt` preservado verbatim.
- **P2:** adaptación operacional separada, usada bajo las condiciones/evidencia de `flow_adaptation`; no reemplaza P1.
- **Production JSON:** especificación estructurada de escenas y producción.
- **Execution spec / Execution Contract:** contrato de ejecución por job para controles, gate y validación.
- **Flow Bridge:** backend + extensión que conectan jobs con la UI de Google Flow.
- **flow_jobs:** cola persistente con claim, lease, heartbeat y reintentos.
- **HANDS:** capa aislada de ejecución física/mecánica con permisos, verificación y evidencia.
- **MemoryDV:** memoria operativa implementada en servicios, con episodios/observaciones/patrones y promoción controlada.
- **CONTEXTO YOUTUBE:** memoria documental Markdown versionada; no asumir que es un vector DB.
- **Start Frame / End Frame:** imagen inicial/final de referencia para generación de vídeo.
- **mediaId:** ID de un recurso en el protocolo de Flow; su significado depende de request/response.
- **mediaIdToScene:** asociación de medios detectados en respuestas con escenas; no prueba binding de input.
- **HAR:** captura HTTP del navegador; puede contener secretos y debe sanearse.
- **E2E real:** prueba con proveedor/UI reales, no solo mocks, DOM simulado, VM o backend HTTP.
- **NOT_DEMONSTRATED:** no hay evidencia suficiente para afirmar funcionamiento real.
- **Fail-closed:** ante incertidumbre en control de seguridad/contrato, denegar en vez de asumir éxito.
