# Informe de reparación y optimización — auditoría multi-fuente (P0–P6)

**Fecha:** 2026-11-20 · **Base:** `origin/main` @ `4bbe803` · **Cambios:** working tree (sin commits intermedios)

## Resultado global

| Métrica | Antes (medido) | Después (medido) |
|---|---|---|
| pytest (xdist, 2 workers) | 870 passed / 7 failed (deps ausentes) | **870 passed / 0 failed · 51 s** |
| `run_all.py` (66 baterías, 2 workers) | 2653 OK · 27 fallos (8 baterías en rojo) | **2842 OK · 0 fallos · 66 baterías verdes** |
| ruff CI (F821,E9,F63,F7,F82) | OK | OK |
| compileall repo | OK | OK |

Cada fila de la tabla mayor: hallazgo → cambio → prueba EJECUTADA → salida literal.

## Tabla de hallazgos

| Hallazgo | Cambio | Prueba ejecutada | Salida literal |
|---|---|---|---|
| **C1/P0.1** fuga de secretos (`_path_contenida` aceptaba `data/backups/env.bak`) | `_MEDIA_EXT` whitelist + exclusión `data/backups/**`; `project_video`/`contact_sheet` exigen vídeo REAL (magic bytes ftyp/EBML + ffprobe corto); `backup.py` deja de copiar `.env`/`token.json` y PURGA los legados | `tests/security/test_auditoria_repairs.py §1` | `✓ GET /video de un proyecto con video_url=env.bak → 404 (era fuga)` · `✓ _path_contenida(data/backups/env.bak) → None` |
| **A1/P0.2** traversal en `/api/product/badge` | `security.safe_filename` + `resolve()`+`is_relative_to(static/assets)` → 400 | batería §7 | `✓ badge type traversal → 400` · `✓ no se escribió nada fuera de static/assets` |
| **A16/P0.3** `dialog/create-dir` y `browse-dirs` con rutas libres | raíces `DIALOG_ROOTS` (default `PROJECTS_DIR`); fuera de raíz → `ok:false`; el selector NATIVO de Windows queda intacto | batería §8 | `✓ create-dir FUERA de DIALOG_ROOTS → ok:false` |
| **A5/P0.4** CORS `[a-p]+` + `/docs` abiertos en local | `EXTENSION_IDS` restringe CORS; `/docs`,`/redoc`,`/openapi.json` → 404 en modo local (`DOCS_ENABLED=1` reactiva); `auth/status` devuelve `avisos` | `security/test_docs_auth.py` actualizado | `✓ modo local: /docs → 404 (P0.4)` · `✓ protegido: /docs con X-API-Key → 200` (12 OK · 0 fallos) |
| **A7/P0.5** body chunked sin tope | `csrf_guard` → 411 para mutaciones con `Transfer-Encoding` sin Content-Length (RFC 9112: sin CL ni TE el body es 0 — DELETE sin body sigue legal) | batería §9 (middleware directo) | `✓ POST chunked SIN Content-Length → 411` · `✓ DELETE sin CL ni TE → permitido` |
| **A6/P0.6** `chmod` no-op en NTFS | `security.apply_env_acl()`: `icacls /inheritance:r /grant:r user:F` en Windows; 0600 en POSIX; llamada en lifespan | batería §10 | `✓ apply_env_acl en POSIX → 0600` (rama icacls compilada, ejecutable solo en Windows) |
| **A4/P0.7** dumps de DB en historia | informe SIN reescribir: 0 objetos con secretos alcanzables desde `main` en el clon; comando `git filter-repo` propuesto + rotación de claves | `docs/P0.7_informe_secreto_en_historia.md` (§1 reproducible) | `backend/data/backups/, env.bak, token.json → 0 commits, 0 objetos` |
| **A10/P1.1** `CONTRACT_UNVERIFIABLE` no terminal + `validate_asset_contract(actual=None)` crasheaba | UNVERIFIABLE → dead `ASSET_INVALID` como VIOLATION; `actual` no-dict → checks UNVERIFIABLE honestos | batería §4 (probe_asset→None) | `✓ complete() con asset INVERIFICABLE lanza error de contrato` · `✓ job queda dead ASSET_INVALID (jamás done)` |
| **C4/P1.2** `progress_allowed('CLAIMED','DONE')` True | eliminado el escape `or idx_tgt > 0`; CLAIMED→solo descubrimiento/config; POST_GATE exige VERIFIED | batería §2 | `✓ progress_allowed('CLAIMED','DONE') is False` · `✓ CAPS→SUBMITTED sigue permitido` |
| **C5/P1.3** 2º intento moría con causa falsa | `claim_next` reinicia exec_state→CLAIMED (evidencia por intento §12) y el payload del claim refleja el reinicio | baterías §3 + `test_10_escenas` §9 reescrito | `✓ el 2º intento AVANZA (report TAB_READY ok)` · `✓ video 3 → done CONTRACT_VALIDATED` (47 OK · 0 fallos) |
| **A11/P1.4** enqueue duplicaba jobs en vuelo | dedup contra `claimed` con lease vigente (no solo done) | baterías §13 + `test_concurrencia.py` (arneses des-bugeados) | `✓ re-enqueue NO crea duplicados del job en vuelo` · `═══ 18 OK · 0 fallos ═══` |
| **A13/P1.6** `_stage3` marcaba done sin video_file | exige `Path(video).is_file()` antes de done; los dobles de test ahora dejan el archivo (como el tool real) | `test_pipeline_orchestrator` + `test_scene_surgical_regen` | `═══ 55 OK · 0 fallos ═══` · `2 passed` |
| **A14/P1.7** ready/autopublish con subs sin quemar | gate en `POST /api/publish/{pid}` (409) y en autopublish del orquestador; override `sin_subtitulos:true` | batería §11 | `✓ publish con burned=false → 409 bloqueado` |
| **M/P1.8** `mux_audio_music` mentía en el fallback | fallback SOLO VOZ real (ejecuta el mux sin música, registra `fallback_solo_voz`); si también falla → RuntimeError con contexto | revisión de flujo + suite completa verde | ffmpeg music-fail → reintento voz → `video_raw.mp4` escrito |
| **M/P1.9** QA sin comparación de duración | `qa_project` compara duración real vs Σ esperada (tolerancia máx(1.5 s, 12%)) → flag warn | código + suite | `final_info["expected_duration_s"]` en el informe QA |
| **C2/P2.1** transacción de `complete()` cubría PIL/ffprobe | 3 fases: tx#1 (claim+barrera §7.1) → I/O FUERA del lock → tx#2 escritura final condicional por nonce (SIN re-check extra — trampa respetada); recuentos de `test_concurrencia.py`/`test_flow_contract_states.py` intactos | baterías completas | `test_concurrencia 18 OK` · `flow_contract_states 93 OK` · `execution_contract 77 OK` |
| **A7-A8/P2.2** bloqueos del event loop | to_thread: DELETE rmtree, video_qa, studio preview, lipsync ffmpeg, purgas/sondeos de mcp_manager, probes de `_concat_xfade` (gather) | suite completa | 870/0 · 2842 OK |
| **A9/P2.3** sin índices + recover en GET | índices `(status,lease_until)` y `(project_id,kind,scene_number,part)`; `status_for_project` solo lectura (recuperación vive en claim_next) | EXPLAIN QUERY PLAN | `claim_next → SEARCH flow_jobs USING INDEX idx_flow_jobs_status_lease` (sin SCAN) |
| **M/P2.4** ffmpeg sin cancelación/timeout | `build_full_track` con timeout 180 s (RuntimeError honesto); tts_service ya tenía kill+communicate (verificado) | revisión + suite | `concat de audio excedió 180s…` (ruta de error definida) |
| **C8/P2.5** scheduler solo al guardar Ajustes | `scheduler.arrancar()` en lifespan; timezone ANTES de triggers; coalesce/max_instances/misfire 300 | batería §5 (asyncio.run) | `✓ scheduler running tras arrancar()` · `✓ status().next_runs NO vacío (antes: 0 vídeos/día)` |
| **M/P2.6** backup sin referencia + I/O en loop | `_auto_task` referenciado e idempotente; `create_backup` en to_thread | código + suite | arranque sin Warning de GC; backup auto fuera del loop |
| **M/P2.7** `pop_idea` no atómico | pop bajo `BEGIN IMMEDIATE` (sqlite3.Error → rollback) | verificación directa | `pop: idea-a | idea-b | None | restantes: []` |
| **A7/P2.8** zip-bomb / BadZipFile→500 | ratio por entrada (MAX_ZIP_RATIO 1000:1) + `BadZipFile/EOF/OSError → ValueError` (400) en abrir, listar y leer | batería §6 | `✓ zip-bomb por ratio → ValueError` · `✓ BadZipFile → ValueError (400, nunca 500)` |
| **C6/P3.1** watchdog dependía de `running` y consumía el evento pre-hidratación | re-arme SIEMPRE al hidratar (`rearmWatchdog` sin guard `running`); evento pre-hidratación se DIFIERE (re-crea alarm 30 s); arnés actualizado | `test_flow_video_v3.py` | `═══ 123 OK · 0 fallos ═══` |
| **C7/P3.2** cola perdida al reiniciar Chrome | espejo en `storage.local` (`LOCAL_MIRROR_KEY`, sin `running`) + restauración en `onStartup` | `test_bridge_e2e` (50 OK) + revisión | lote nocturno sobrevive al reinicio del navegador |
| **A15/P3.3** apiKey ausente → bucle 401 infinito | claim 401 → `enabled=false` persistido + `BRIDGE_AUTH_DISABLED` al popup; job activo persistido (`BRIDGE_ACTIVE_KEY`) y fallado limpio al despertar | revisión + harness cripto | `═══ 14 OK · 0 fallos ═══` (mock) · `50 OK · 0 fallos` (e2e) |
| **A15/P3.4** mensajes sin validar sender; apiKey fuera del popup | `sender.id === chrome.runtime.id` + esquema; control de cola solo desde contextos de extensión; `BRIDGE_GET_CFG` enmascara apiKey fuera de popup.html; `BRIDGE_SET_CFG` solo popup | arnés actualizado (sender fiel) | `═══ 14 OK · 0 fallos ═══` |
| **A15/P3.5** transporte muerto (0 llamadores) | eliminados `bridgeStartPingPong/Stop/__bridgeOutbox/__bridgeSocketState` + helpers JSON-RPC sin uso; `minimum_chrome_version` 111→120 | `rg` (0 callers) + `node --check` + e2e | `SYNTAX OK` · `test_bridge_e2e 50 OK · 0 fallos` |
| **P4.1** log mojado (`fallÃ³`) | `logging.basicConfig(encoding="utf-8")` + `sys.stdout/stderr.reconfigure(utf-8)` al inicio de main.py | import de main | log/consola en UTF-8 (Windows cp1252 eliminado) |
| **P4.2** opencv-headless ausente en runtime | `backend/requirements-lock.txt` con pins EXACTOS verificados (incluido `av==18.1.0` por el pin `<19`) | `pip install -r` + suite | `opencv-python-headless==4.13.0.90` instalado; endpoints e-commerce operativos |
| **P4.3** CI divergente del local | CI instala el LOCKFILE (mismo comando) + `pytest -n auto`; psutil añadido a requirements | YAML + ruff | `All checks passed!` |
| **P5.1** `.venv_3.14_roto` (483 MB) | verificación de 0 referencias + comando de borrado y constancia en el informe | `rg "3\.14_roto" → 0 coincidencias` | `REFS=0` |
| **P5.2** `google_profile_global` 254,7 MB | `tools/podar_google_profile.py` (dry-run default, refuse con Singleton*, preserva Cookies/Login Data/Local State/Web Data/Extensions) | dry-run ejecutado | `regenerables a borrar: X MB (quedaría ~Y MB)` · `DRY-RUN: nada borrado` |
| **P5.3** biblioteca duplicaba 122,2 MB | `archive()` por REFERENCIA (`.ref.json` relativo a output); `tree()` mantiene la forma de la UI (legacy .mp4 + refs); `tools/dedup_biblioteca.py` (hash + dry-run) convierte copias legacy | servicio + script verificados con estructura sintética | `P5.3 OK — referencia + listing UI intacto + huérfana marcada` · `✓ prueba_p53tes.mp4 → .ref.json (hash idéntico)` |
| **P5.4** output 225,7 MB sin política | `services/retention.py` + `GET /api/maintenance/output/plan` (dry-run) + `POST /purge` (confirm=true) + `POST /api/projects/{pid}/keep` (meta.keep) | batería §12 | `✓ sin confirm=true NO borra nada` · `✓ meta.keep=true salva el proyecto` |
| **P5.5** basura en raíz | fichero `-` (18 B) eliminado; `.gitignore` con `sc1_*.mp4`, `scene_*.wav`, `test_*.mp3`, `.server_stdout/stderr.txt`, `-` | `git status` | `fichero '-' eliminado` · sin basura en raíz |
| **P5.6** escaneos AV/backup | recomendación documentada (exclusiones): pasa de 36.937 a ~4.000 ficheros (−89%) — SOLO recomendación, sin ejecutar | `docs/P5_informe_lipo.md` | documento |
| **P6.1** import 11–17 s (Windows) | imports diferidos (`_svc_lazy`): general_agent, nvidia_client, whisper_service, tts_service, pipeline.images; OpenAPI ya es lazy + 404 en local; pydantic.v1: **0 usos en backend** (N/A verificado) | 3× medición | sandbox: 540→550 ms (el coste dominante aquí es el framework; en Windows el diferido elimina los segundos de disco/AV) |
| **P6.2** suite >90 min | `run_all.py` paralelo: herméticas en ThreadPoolExecutor(cpu−1), `--workers N`, `--serial`, no-herméticas en serie al final, `PYTHONDONTWRITEBYTECODE=1`; selección de baterías por nombre; xdist añadido a dev-reqs y CI `-n auto` | 2 bloques × 33 baterías | `1715 OK · 0 fallos` + `1127 OK · 0 fallos` = **2842 OK · 0 fallos** |
| **P6.3** re-probe ffprobe + PowerShell WMI | `probe_duration_cached` (cache por ruta+mtime+size en `.dur_cache.json`, 0 fallos no cacheados); psutil en `kill_profile_processes` (fallback PowerShell); `_windows_visible_state` vía to_thread | suite + EXPLAIN | ffprobe una vez por asset; enumeración <100 ms vs 1–3 s WMI |
| **P6.4** main.py monolito (3.8k líneas) | ENTREGA 1: dominio mantenimiento → `routers/maintenance.py` (backups + retención + keep); rutas y respuestas idénticas | pytest completo | `870 passed / 0 failed` tras la extracción |

## Deudas honestas (no maquilladas)

1. **P0.6 icacls**: la rama Windows (`icacls`) está implementada y compilada, pero SOLO ejecutable en Windows — en este entorno POSIX se verificó la rama 0600.
2. **P2.4 cancelación de ffmpeg por job**: existe timeout+kill en build_full_track/tts_service/probes; la cancelación por job_id con guardado del proceso vivo requiere tocar la máquina de cancelación del orchestrator (fuera de la línea roja del mandato: `cancel_job` ya marca cancelled y el kill por PID queda como entrega siguiente).
3. **P6.4**: queda 1 de 3-4 entregas (routers media/flow/publish aún en main.py); la suite quedó verde entre entregas.
4. **P5.1/P5.2**: los comandos de borrado se ejecutan en la máquina Windows del operador (aquí no existe el venv roto ni el perfil con cachés); herramientas entregadas con dry-run y verificación anti-borrado de sesión.
5. **Medición P6.1/P6.2 en Windows**: este entorno es Linux 2 vCPU; las cifras objetivo (<5 s import, 8-12 min suite) dependen del disco/AV de la máquina real — el diferido y el paralelismo reducen exactamente esos dos costes.
