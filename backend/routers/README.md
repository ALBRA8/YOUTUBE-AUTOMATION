# Plan de Modularización por Fases — Desacoplamiento de `backend/main.py`

## Diagnóstico Inicial
- **Líneas:** 3.754 líneas
- **Endpoints:** 167 endpoints en un único archivo monolítico
- **Objetivo (P3-1):** Desacoplar gradualmente en routers `APIRouter` independientes, organizados por dominio funcional, garantizando cero roturas de compatibilidad con la SPA y la extensión.

---

## Fases de Migración

### Fase 1 — Piloto (Ejecutada)
- **Dominio:** Nichos y Plantillas (`/api/niches`)
- **Endpoints:** 4
  - `GET /api/niches`
  - `GET /api/niches/templates`
  - `POST /api/niches/templates`
  - `DELETE /api/niches/templates/{tid}`
- **Router:** `backend/routers/niches.py`
- **Estado:** PASS (verificado con suite de regresión `tests/test_p3_1_routers_phase1.py`).

### Fase 2 — Configuración y Utilidades
- **Dominios:**
  - `/api/voices` (4 endpoints)
  - `/api/config` (4 endpoints)
  - `/api/backups` (3 endpoints)
  - `/api/dialog` (4 endpoints)
- **Routers previstos:** `routers/voices.py`, `routers/config.py`, `routers/backups.py`, `routers/dialog.py`.

### Fase 3 — Avatares, Marcas y E-Commerce
- **Dominios:**
  - `/api/avatars` (13 endpoints)
  - `/api/brand-profiles` (9 endpoints)
  - `/api/product` (4 endpoints)
  - `/api/clipper` (4 endpoints)
- **Routers previstos:** `routers/avatars.py`, `routers/brands.py`, `routers/product.py`, `routers/clipper.py`.

### Fase 4 — Integraciones Externas y Extensión Chrome
- **Dominios:**
  - `/api/extension` (11 endpoints)
  - `/api/mcp` (17 endpoints)
  - `/api/nlm` (3 endpoints)
- **Routers previstos:** `routers/extension.py`, `routers/mcp.py`, `routers/nlm.py`.

### Fase 5 — Núcleo del Pipeline, Proyectos y Publicación
- **Dominios:**
  - `/api/projects` (19 endpoints)
  - `/api/pipeline` (9 endpoints)
  - `/api/scenes` (5 endpoints)
  - `/api/publish` (5 endpoints)
  - `/api/production_doctor` (5 endpoints)
- **Routers previstos:** `routers/projects.py`, `routers/pipeline.py`, `routers/publish.py`, `routers/doctor.py`.
