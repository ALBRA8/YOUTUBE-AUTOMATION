# Plan de prueba de producción — Serie basada en NotebookLM

**Fecha:** 2026-10-28  
**Objetivo:** demostrar con evidencia que YOUTUBE-AUTOMATION puede producir un episodio piloto siguiendo una guía de investigación preparada con NotebookLM y repetir el proceso para episodios posteriores sin perder continuidad.  
**Estado inicial:** PREPARADO · ejecución real pendiente en la máquina con sesiones, claves y Google Flow del usuario.

## Regla de veracidad

Los tests automatizados y los mocks validan contratos y lógica, pero no demuestran por sí solos que NotebookLM autenticado, Google Flow, generación de medios y render funcionen juntos en el entorno real. No publicar automáticamente durante esta prueba. No marcar PASS sin evidencia guardada.

## Alcance de la prueba

1. Convertir la guía/plan de investigación de NotebookLM en una biblia editorial de la serie.
2. Crear un episodio piloto que siga esa biblia.
3. Ejecutar el pipeline real de generación de imágenes/clips, locución, subtítulos, render y QA.
4. Verificar que los materiales y decisiones editoriales quedan guardados para producir el episodio 2 con continuidad.
5. Dejar el resultado y los bloqueos documentados.

## Gate 0 — Preparación segura

- [ ] Actualizar el repositorio y anotar rama + SHA exacto.
- [ ] Confirmar backend arriba y /api/health OK.
- [ ] Confirmar claves/proveedores configurados desde el panel; nunca copiar secretos a este documento ni a logs compartidos.
- [ ] Confirmar que NotebookLM y Google Flow muestran sesión válida.
- [ ] Ejecutar Production Doctor en modo audit/report y guardar el informe.
- [ ] Ejecutar REAL FLOW PREFLIGHT para el proyecto de prueba; debe devolver REAL FLOW PREFLIGHT PASS.
- [ ] Confirmar que la extensión Chrome está instalada y que el botón «Puente Backend» está activo.
- [ ] Desactivar autopublicación y cron/fábrica durante el piloto para evitar publicaciones o gastos involuntarios.

**STOP:** si el preflight está BLOCKED, no ejecutar generación real. Registrar el error literal y el informe; corregir el bloqueo antes de continuar.

## Gate 1 — Fijar la biblia de la serie desde NotebookLM

Usar la guía y las fuentes ya aprobadas en el notebook de la serie. Exportar o copiar al proyecto únicamente el material editorial necesario, respetando derechos y procedencia.

Crear un paquete de referencia versionado con:
- premisa, audiencia, promesa y tono;
- hechos comprobados y referencias/fuentes;
- arco de temporada y objetivo de cada episodio;
- estructura narrativa por episodio (hook, desarrollo, giro/descubrimiento, cierre y puente al siguiente);
- personajes, nombres, rasgos visuales, voz y reglas de continuidad;
- lista de afirmaciones que requieren verificación;
- restricciones editoriales y elementos que no deben inventarse;
- duración objetivo, formato y criterios de aceptación.

- [ ] Guardar el paquete como SERIE_BIBLIA.md dentro de la carpeta de trabajo del proyecto, junto con el identificador del notebook y fecha de revisión (sin cookies, tokens ni datos sensibles).
- [ ] Elegir una afirmación de la biblia y rastrearla hasta una fuente de NotebookLM.
- [ ] Revisar manualmente que el resumen no invente hechos ni presente inferencias como fuentes.
- [ ] Congelar una versión para el piloto; los cambios posteriores deben quedar anotados.

**PASS:** existe una biblia revisada y versionada que puede servir como referencia estable de varios episodios. El Audio Overview de NotebookLM, si se genera, es un artefacto opcional y no sustituye la biblia ni demuestra continuidad.

## Gate 2 — Preparar el episodio piloto

- [ ] Crear un proyecto de prueba aislado con ID y carpeta propios.
- [ ] Escribir el guion del episodio 1 contra la biblia; marcar fuentes/afirmaciones verificables.
- [ ] Dividirlo en escenas con image_prompt y, para cada escena que deba producir clip, video_prompt y duration_target.
- [ ] Revisar que las decisiones visuales respeten personajes, localizaciones, época, paleta y estado de escena.
- [ ] Comprobar el contrato Production JSON, referencias y continuidad con los tests/preflight existentes.
- [ ] Exportar el paquete que consuma el flujo de generación y comprobar que los prompts creativos se conservan sin alteraciones no autorizadas.

**PASS:** el proyecto pasa validación de contrato y REAL FLOW PREFLIGHT. No iniciar Flow si falta video_prompt en una unidad que debe generar clip.

## Gate 3 — Ejecución real controlada

1. Ejecutar primero una prueba mínima de una escena/imágenes en Google Flow, siguiendo ANTIGRAVITY_VALIDACION_PRODUCCION.md §4.
2. Confirmar que el asset aparece en la ruta esperada, que el job termina en done, y que QA no detecta errores.
3. Solo después, producir el piloto completo (recomendación: 2–3 escenas con video para la primera pasada; ampliar al formato real una vez que el recorrido corto funcione).
4. Ejecutar locución, alineación de subtítulos y render.
5. Revisar el MP4 final con reproducción real, audio audible, sincronía, legibilidad, duración, resolución y ausencia de pantallas negras/azules.
6. Ejecutar video_qa y guardar el reporte junto al proyecto.

- [ ] Guardar logs saneados, ID del proyecto, IDs/estados de jobs, rutas de assets y resultado QA.
- [ ] No compartir HAR/capturas con cookies, tokens, credenciales ni URLs firmadas.
- [ ] No activar autopublicación; la publicación es un gate separado y requiere aprobación humana.

**PASS:** MP4 final reproducible + audio/subtítulos correctos + QA sin errores bloqueantes + trazabilidad de las escenas y assets. Un test con mocks, fixture o backend HTTP aislado no cuenta como generación real de Google Flow.

## Gate 4 — Prueba de continuidad y repetibilidad

- [ ] Guardar una ficha del episodio 1: resumen canónico, estado final de personajes, hechos ya revelados, decisiones visuales, fuentes usadas y preguntas abiertas.
- [ ] Preparar un esquema del episodio 2 usando la misma biblia y la ficha del episodio 1.
- [ ] Verificar que el episodio 2 no contradice hechos, personajes o cronología fijados en el episodio 1.
- [ ] Generar al menos un arte/escena de prueba del episodio 2 y compararlo con las reglas visuales del episodio 1.
- [ ] Comprobar que el flujo no depende de memoria conversacional efímera: los materiales de continuidad deben estar guardados en archivos del proyecto.

**PASS:** episodio 2 puede planearse desde artefactos persistentes y mantiene continuidad editorial/visual. Esto demuestra repetibilidad básica, no que una temporada completa esté libre de errores.

## Gate 5 — Cierre y veredicto

- [ ] Volver a ejecutar Production Doctor verify/report.
- [ ] Guardar métricas, QA y evidencia de los pasos completados.
- [ ] Registrar fallos con el error literal y la capa del Doctor; no reparar a ciegas.
- [ ] Actualizar ESTADO_REAL.md solo con resultados realmente observados.
- [ ] Dejar el estado como uno de estos:
  - BLOCKED: no se pudo iniciar por prerequisitos o preflight.
  - CODE_PASS / LIVE_NOT_RUN: pruebas de código verdes, proveedores reales no probados.
  - PILOT_LIVE_PASS: episodio piloto generado y validado de punta a punta.
  - SERIES_REPEATABILITY_PASS: piloto + prueba de continuidad del episodio 2 superados.
  - PUBLISH_READY: solo si además se validó la publicación en privado y se aprobó el procedimiento de publicación.

## Evidencia mínima que se debe adjuntar al informe

- SHA de repo y rama.
- Informe de Doctor/preflight.
- ID de proyecto y estado final de jobs.
- Referencia a SERIE_BIBLIA.md y guion del piloto.
- Rutas de imagen/video/audio/SRT/MP4 finales.
- Reporte de video_qa y comprobación manual de reproducción.
- Evidencia de continuidad del episodio 2.
- Incidencias y clasificación; sin secretos.

## Referencias internas

- ESTADO_REAL.md — inventario verificado y límites de evidencia.
- docs/PRODUCTION_DOCTOR.md — audit/fix/verify/preflight.
- CONTEXTO YOUTUBE/05_TESTS/ANTIGRAVITY_VALIDACION_PRODUCCION.md — ejecución real de NotebookLM, Flow y pipeline.
- CONTEXTO YOUTUBE/06_INTEGRATIONS/INT-069_NOTEBOOKLM_STUDIO_BRIDGE_AND_SESSION_HARDENING.md y INT-069B_ALINEACION_TOOLS_NOTEBOOKLM_V085.md — puente Studio y alineación NotebookLM v0.8.5.
