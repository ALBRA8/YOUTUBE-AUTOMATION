# ROADMAP
## AHORA (máximo 2)
- Fase 1 · Estabilizar: cerrar SSRF en pipeline/images.py (modo Producto); el CI
  debe correr TODAS las baterías (hoy 23 quedan fuera de pytest); arreglar orden
  de middlewares con MASTER_API_KEY (preflight CORS da 401); arreglar los 6
  tests rotos y los 4 de run_all.
## SIGUIENTE
- Fase 2 · Calidad de video: no entregar placeholders (umbral 0-1 + reintento),
  menos re-codificación en cadena, loudnorm activo, +faststart, medir zoompan.
- Fase 3 · Aceptación: 10 videos seguidos en 2 nichos; cero placeholders; cero
  "listos" con fallos de QA; el dueño revisa una muestra. Meta: 8/10 sin
  intervención manual.
## DESPUÉS
- Start Frame de Flow (solo tras captura real de red, ver PROJECT_STATE).
- Autopublicación y modo fábrica a escala.
- Partir main.py en routers, migrar a lifespan, revisar excepts amplios.
## EN RESERVA (no tocar)
- HANDS (control manual del PC): dormido.
## HECHO
- INT-091 selector de carpetas; INT-092 timeout Flow 300 s y render 4K (2026-11-06).
- Memoria del repo: LEEME_PRIMERO.md + ROADMAP.md; lanzadores → launchers/
  (rutas verificadas por test); estado unificado (ESTADO_REAL 53 baterías,
  tabla CONTRACT reparada, PROJECT_STATE un solo Estado, D-010/D-011) y
  baterías HANDS en CI (2026-11-06).
