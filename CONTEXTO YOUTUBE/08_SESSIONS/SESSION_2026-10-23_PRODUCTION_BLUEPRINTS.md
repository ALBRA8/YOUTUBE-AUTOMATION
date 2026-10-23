# Sesión de continuidad — Production Framework y Blueprints

**Fecha:** 2026-10-23  
**Repositorio:** `ALBRA8/YOUTUBE-AUTOMATION`  
**Área canónica:** `CONTEXTO YOUTUBE/00_MASTER/PRODUCTION_FRAMEWORK_BLUEPRINTS.md`  
**Estado:** DISEÑO CONCEPTUAL DOCUMENTADO; IMPLEMENTACIÓN PENDIENTE DE VERIFICACIÓN.

## Decisión confirmada
La producción audiovisual de YOUTUBE-AUTOMATION se organiza mediante un Production Framework común y Blueprints especializados por línea. No se crea un Blueprint universal ni un motor independiente para cada línea.

## Registro de líneas
- `microdrama` → `microdrama_vertical_series_5x60`
- `short` → `short_vertical_v1`
- `short_form` → `short_form_production_v1`
- `ugc` → `ugc_creator_content_v1`

## Fronteras
- Production Framework: contrato común.
- Blueprint: gramática, unidades, variables, invariantes y QC de la línea.
- Creative Engine: interpreta idea, requisitos, conocimiento y Blueprint; produce Creative Specification + Production JSON.
- Reverse Engineering Engine: herramienta independiente/transversal para estudiar referencias y extraer gramática candidata.
- NotebookLM/fuentes: conocimiento, canon, documentación y evidencia; no sustituyen el criterio del usuario ni el Blueprint.
- YOUTUBE-AUTOMATION: ejecución, generación, edición, QA y entrega.

## Regla crítica de continuidad
El diseño conversacional y la documentación versionada no prueban por sí mismos que el runtime esté implementado. No declarar selector, schemas, validador ni integración como implementados hasta verificar el código y ejecutar pruebas apropiadas.

## Próximo trabajo
1. Definir schemas o validador equivalente para Framework y cada Blueprint.
2. Registrar y seleccionar líneas sin duplicar Creative Engine.
3. Crear pruebas de contrato positivas y negativas.
4. Integrar de forma segura con el pipeline existente.
5. Documentar resultados reales, archivos y commits.

Ver detalle completo de gramáticas y contratos en [PRODUCTION_FRAMEWORK_BLUEPRINTS.md](../00_MASTER/PRODUCTION_FRAMEWORK_BLUEPRINTS.md).
