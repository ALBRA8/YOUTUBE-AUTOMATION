# KNOWLEDGE INDEX

## K-001 — Jerarquía de evidencia
Código/tests prueban el alcance testeado; ejecución real externa demuestra comportamiento del proveedor/UI en esa ejecución. No sustituir una categoría por otra.

## K-002 — P1/P2
P1 creativo se conserva intacto. P2 solo se aplica como adaptación operacional respaldada por evidencia y límites definidos.

## K-003 — Start Frame
Una frase en prompt no es un binding de asset. Identificar recurso y comprobar el campo real de la solicitud.

## K-004 — Media IDs
Clasificar por dirección y evento: asset de entrada, resultado, batch/workflow o vídeo final. No inferir equivalencia por el nombre genérico mediaId.

## K-005 — Estados
Usar PROPOSED, PLANNED, IN_PROGRESS, EXPERIMENTAL, VERIFIED, FAILED, BLOCKED, SUPERSEDED y ARCHIVED. “No demostrado” no significa “falló en ejecución”.

## K-006 — Memoria documental y MemoryDV
`CONTEXTO YOUTUBE` es Markdown versionado. No se encontró evidencia de embeddings/vector DB en esta carpeta. El repo declara aparte `services/memorydv.py`, almacenamiento JSONL local gitignored y tests; mantener ambos conceptos separados.

## K-007 — Video base de referencia 2026-10-17
`K-007_VIDEO_BASE_REFERENCIA_2026-10-17.md` conserva el video que originó conceptualmente la línea de YOUTUBE-AUTOMATION. El conocimiento transferible es: producción basada en proyectos y escenas, separación narrativa/visual, assets identificables, generación como capacidad/proveedor intercambiable, validación de resultados y postproducción. Google Flow se interpreta como una capacidad dentro de un pipeline mayor; YOUTUBE-AUTOMATION permanece como orquestador audiovisual. El video es referencia conceptual/histórica, no evidencia técnica ni especificación de código.
