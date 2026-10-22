# INT-020 — Corrección INT-012: `burn_subtitles` resiliente (preset veryfast + timeout degradado honestamente)

- **Fecha:** 2026-10-23
- **Clasificación:** corrección de alcance acotado (orden de trabajo "Cierre técnico", Fase 4 — arreglo ordinario documentado; NO es cambio de arquitectura ni de contrato público).
- **Incidente que corrige:** INT-012 HARD E2E `_hard_e2e_c2_01` — 4/4 escenas generadas realmente en Google Flow, ensamblado y mezcla OK, y el run completo declarado `failed` por `subprocess.TimeoutExpired` a los 900 s en el quemado de subtítulos (`libass` + `libx264 -preset medium` sobre 2160x3840).

## 1. Causa raíz (verificada en código)

`backend/pipeline/video.py::burn_subtitles` tenía dos defectos compuestos:

1. **Inconsistencia de preset:** quemaba con `-preset medium` mientras TODO el resto del módulo (Ken Burns, crossfades) usa `-preset veryfast` (`video.py:91,108,235`). En 4K vertical con libass, `medium` es varias veces más lento y rebasó el presupuesto de 900 s.
2. **Timeout no capturado:** `_run_ffmpeg` usa `subprocess.run(..., timeout=900)` que **lanza** `TimeoutExpired`; `burn_subtitles` solo manejaba `p.returncode != 0`. La excepción subió por `asyncio.to_thread` y tumbó el pipeline completo, aunque el resto del render era válido. (Un fallo ffmpeg ordinario SÍ tenía degradación honesta registrada en `subs_status.json`; el timeout era el único camino que crasheaba.)

## 2. Cambio (quirúrgico, 1 función)

En `backend/pipeline/video.py::burn_subtitles`:

- `-preset medium` → `-preset veryfast` (CRF 20 intacto; típicamente 3-5× más rápido en 4K con coste de calidad marginal; consistente con el resto del módulo).
- `subprocess.TimeoutExpired` capturado y enrutado por el **mismo camino honesto** de degradación que ya existía para `rc != 0`: copia del raw sin subtítulos + `subs_status.json {"burned": false, "reason": "ffmpeg timeout 900s — copiado sin subtítulos"}` + log de error. El archivo final queda **siempre válido** (la copia sobreescribe un posible MP4 parcial del proceso muerto).
- **No se debilita ninguna protección:** la degradación es visible — el QA final la reporta como warn (`orchestrator.py:488-494` lee `subs_status.json`), igual que hoy con cualquier otro fallo de ffmpeg. Jamás un ready/publish silencioso con degradación invisible. El timeout se mantiene en 900 s.

## 3. Por qué esto es una corrección ordinaria y no un cambio protegido

- La protección vigente ("`backend/pipeline/video.py` y su timeout de 900 s protegidos para esta migración", INDEX.md) protegía el archivo **durante la migración del arnés AGENTE-GENERAL**, hoy cerrada y publicada (P3-B COMPLETADA).
- La nueva orden de trabajo exige "ejecutar las correcciones de alcance acotado que sean necesarias para completar YOUTUBE-AUTOMATION, sin detenerte a pedir autorización para cada arreglo rutinario". No hay cambio de contrato público, ni de API, ni de estados, ni de permisos; no se desactiva protección alguna; no se habilita Flow en producción. El fix alinea el timeout con la semántica de degradación ya documentada y testada del propio módulo.
- La auditoría cruzada de Agnes (INT-019 §2.6) confirma que "cada comando ffmpeg con timeout acotado y degradación registrada" es práctica estándar del sector.

## 4. Pruebas y verificación

- **Batería nueva** `tests/test_burn_subtitles_resilience.py` (hermética, `_run_ffmpeg` simulado, sin ffmpeg real, sin red): **16/16 OK** — preset veryfast en el comando, timeout 900 intacto, éxito `burned=true`, `rc!=0` degrada con razón `rc=1`, **timeout degrada sin excepción** con razón `timeout` y sobreescribe el MP4 parcial corrupto, words vacío copia sin quemar, audio `-c:a copy`.
- **Registrada** en `tests/run_all.py` (runner canónico).
- **Suites relacionadas re-ejecutadas en verde:** test_autopublish_generate (45), test_flow_mcp_video, test_gobernanza (28), test_qa_forensics (30).
- **Suite canónica completa** `tests/run_all.py` re-ejecutada al cierre de la misión (ver §6).
- Baseline previo (main `30535f2`): 620/620 checks P3-B; sin fallos conocidos en main.

## 5. Qué queda pendiente (honesto)

- **Re-run real del HARD E2E INT-012** (proyecto completo en Google Flow real + render 4K): requiere Chrome + sesión de Google del usuario → **validación de Antigravity** (D-007). Con `veryfast` el presupuesto esperado del quemado baja de >900 s a un rango cómodo, pero la demostración real solo cuenta en la máquina del usuario. Idempotencia "Run 2" de INT-012 sigue sin ejecutarse por lo mismo.
- **R1/R2/R3** (INT-019 §3.1): extensiones propuestas de QA/preflight, pendientes de decisión separada.

## 6. Estado de publicación

- Rama local: `fix/int-012-burn-timeout` (commit de código + commit de documentación).
- **Publicación GitHub: BLOCKED BY AUTH** en el momento de esta misión (sin credencial de escritura disponible; los PAT que circularon por chat están prohibidos y deben considerarse comprometidos). No se fingió ningún push. Al recibir credencial segura de mínimo privilegio: push de la rama + merge según convención del repo.
