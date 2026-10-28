# Checklist de Validación en Antigravity — Gate de Producción

> **Objetivo:** pasar de "código verde" (192/192 pytest + baterías standalone) a
> **"operativo real"** con evidencia medida en la máquina del usuario. Regla de
> oro del repo (ESTADO_REAL.md): nada se declara terminado sin batería que lo
> respalde — esta sesión es la batería que solo puede correr en tu entorno
> (Chrome + sesión Google + NotebookLM + claves API + hardware real).
>
> **Fecha de creación:** 2026-10-28 · Baseline de código: `8a5ec67` (INT-069) + INT-069.1.
> **Regla:** marcar cada paso con ✅/❌ + evidencia (captura, log o path). Si un
> paso falla, anotar el error literal y parar ahí — el diagnóstico lo hace el
> Production Doctor (paso 3), no a mano.

---

## 0. Prerrequisitos (5 min)

- [ ] Repo actualizado: `git pull origin main` → HEAD ≥ `8a5ec67`.
- [ ] PAT antiguo (`ghp_IoIr...`) **revocado** en GitHub → Settings → Developer settings → Tokens. El nuevo token NO se guarda en ficheros del repo.
- [ ] `.env` del backend con claves reales (Gemini/TTS, MASTER_API_KEY). Referencia de variables: `backend/.env.example`.
- [ ] Chrome cerrado por completo antes de los pasos que lo lanzan (los lanzadores capturan sesión con CDP; un Chrome ya abierto sin puerto de debug los confunde).

## 1. Arranque del backend (2 min)

- [ ] Ejecutar `start.bat` (o `LANZADORES-LEEME.txt` según tu instalación). Verificar en el log: venv OK, sin purge de `.venv` (INT-034), backend arriba en el puerto esperado.
- [ ] Abrir el panel → badges de MCP: **GoogleFlowMCP** y **notebooklm-mcp** en verde (conectados).

## 2. Sesión NotebookLM con INT-069.1 (5 min) — *estrena los defaults v0.8.5*

- [ ] «🔑 Vincular Sesión Google (Login Único)» → login Google OK.
- [ ] «📋 Listar mis notebooks» → el dropdown «Notebook activo» se rellena. **Este paso ahora usa `notebook_list` (v0.8.5)** — si aparece AUTH_REQUIRED, el refresh automático de INT-069 debe recuperarlo solo (log: un `auth refresh` + reintento de sonda).
- [ ] Evidencia esperada: sin badges AUTH_REQUIRED tras el login; si el refresh no basta, anotar `auth_detail` del badge.

## 3. Production Doctor + REAL FLOW PREFLIGHT (5 min)

- [ ] MCP tool `production_doctor` (audit → report) o su endpoint: capas A-I sin errores bloqueantes. Guardar el reporte (`data/doctor/`).
- [ ] MCP tool `real_flow_preflight` → resultado **`REAL FLOW PREFLIGHT PASS`**. Si sale BLOCKED, los motivos listados son exactamente la lista de lo que falta — tratarlos uno a uno antes de seguir.
- [ ] `P-EXT-RUNTIME` puede salir `NOT_DEMONSTRATED` (no bloqueante por diseño): se convierte en CONNECTED con la evidencia del paso 5.

## 4. LIVE TEST 1 — generación controlada con Flow real (15 min) — *el pendiente histórico*

- [ ] Proyecto mínimo de 1 escena (imagen, sin video) desde el panel con la extensión instalada y Chrome con tu sesión de Google.
- [ ] Extensión: botón «Puente Backend» activo → la cola Flow toma el job → Flow genera → la imagen aterriza en `data/output/<pid>/flow/Escena_01_flow.png`.
- [ ] Verificar en panel: job `done` (no dead), mapeo de escena OK, QA por escena sin flags rojos.
- [ ] **Criterio de éxito:** primera generación REAL documentada (esto cierra el «E2E con Google Flow REAL: no demostrado» de ESTADO_REAL.md §3 para imágenes).

## 5. E2E de video corto con contrato de ejecución (20 min)

- [ ] Proyecto de 2-3 escenas con video. La extensión 2.4.x debe pasar por el ciclo completo: consentimiento (`generate-consent`) → gate de configuración → generación → validación contractual (ffprobe).
- [ ] **Criterio de éxito:** `exec_state` llega a `CONTRACT_VALIDATED/DONE` sin `CONFIG_*` ni `ASSET_INVALID`; auto-render disparado al completar el proyecto.
- [ ] Si Flow cambia de UI y el gate falla: anotar la clasificación A-I que produce FLOW ADAPTATION (evidencia de red/notificaciones) — es exactamente el dato que falta catalogar.

## 6. INT-069 Studio Bridge — primer Audio Overview real (10 min)

- [ ] `POST /api/nlm/studio/audio-overview` con el texto del guion (o botón del panel si ya está cableado en UI) → 202 con `job`.
- [ ] Poll `GET /api/nlm/studio/status/{notebook_id}` hasta `ready` (tarda minutos; timeout 900 s).
- [ ] `GET /api/nlm/studio/download/{notebook_id}` → `.m4a` audible en `backend/data/exports/nlm_studio/<notebook_id>/`.
- [ ] **Criterio de éxito:** primer podcast generado end-to-end por el sistema (modalidad audio nueva del pipeline).

## 7. Ola nueva INT-029..068 — humo real (15 min, opcional pero recomendado)

Con el backend arriba y claves reales, disparar por panel al menos una pasada de: viral_clipper o karaoke_subtitles o multilang_dubber (1 servicio basta como humo; los 16 comparten patrón de wiring). Anotar cualquier traceback — los tests los cubren con mocks; esta es su primera luz real.

## 8. Cierre de sesión

- [ ] `GET /api/metrics` → snapshot con las tasas §28 pobladas por la corrida real.
- [ ] Volver a correr `production_doctor` (verify) → comparar contra el del paso 3.
- [ ] Reportar resultados (✅/❌ + evidencia) para actualizar ESTADO_REAL.md §3, TEST_INDEX (LIVE TEST 1) y las fichas INT afectadas.

---

### Interpretación rápida

| Resultado | Significado |
|---|---|
| Pasos 1-4 ✅ | Pipeline de imágenes REAL demostrado — el hito E2E más antiguo pendiente queda cerrado. |
| Pasos 1-5 ✅ | Producción de video corta operativa de punta a punta. |
| Pasos 1-6 ✅ | **100% operativos**: código verde + evidencia real de las 3 vías (Flow, pipeline, Studio). |
| Cualquier ❌ | No bloquea para siempre: anota error literal + ejecuta Doctor → el diagnóstico determinista dice qué capa falló. |
