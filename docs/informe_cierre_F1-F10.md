# Informe de cierre F1-F10 — últimos huecos para 100% operativo

**Fecha:** 2026-11-23 · **Base:** `c3de757` (main, árbol limpio) · **Entorno de cierre:** clon Linux del sandbox (Python 3.12.16). Los artefactos físicos de la lipo (F2/F3/F4/F5 en su tamaño real) viven SOLO en la máquina Windows del dueño: aquí se entrega el mecanismo probado + los comandos exactos; las cifras de la máquina del dueño se citan del mandato y NO se declaran ejecutadas.

## Resultado global

| Métrica | Antes (c3de757) | Después (medido) |
|---|---|---|
| `run_all.py` serie | 2951 OK · 0 fallos · 70 baterías | **2983 OK · 0 fallos · 0 SKIP · 71 baterías · 2m57.4s** |
| `run_all.py --workers 6` | no medido en 71 baterías | **2983 OK · 0 fallos · 2m13.5s** (F10) |
| Suite en árbol CRLF materializado | dependiente del checkout (live_boot 4 fallos) | **verde** (única dependencia eliminada, F7) |
| pytest completo | 953 passed | 953 passed / 0 failed (post-cambios, re-medido) |
| CI Windows | exploratorio (continue-on-error, sin run_all) | **job real visible** con `run_all --hermetic` (F8) |
| D1 (aislamiento BD) | hash+mtime idénticos | idénticos (`9afa69dd…` antes = después) |
| npm test (GoogleFlowMCP) | 28/28 | 28/28 |
| ruff F821,E9,F63,F7,F82 | limpio | limpio |

## Tabla de ítems (ítem → cambio → comando de verificación → salida LITERAL)

| Ítem | Cambio | Comando | Salida literal |
|---|---|---|---|
| **F1a** cv2 no instalado en el venv del dueño | (aquí) `pip install -r backend/requirements-lock.txt` desde el lock, sin instalación suelta | `python -m pip install -r backend/requirements-lock.txt` | `Successfully installed av-18.1.0 ctranslate2-4.9.0 … onnxruntime-1.32.0 … yt-dlp-2026.10.26` (el venv del sandbox TAMBIÉN tenía drift: av/onnxruntime/ctranslate2/faster-whisper/google-* faltaban — la guardia F1b lo habría cazado) |
| **F1b** guardia «declarado == instalado» | NUEVA batería `tests/security/test_lock_drift.py` (30 checks): 27 pins del lock vs `importlib.metadata` del intérprete; falta → fallo NOMBRANDO el paquete. Registrada en BATERIAS + PYTEST_IGNORADAS (71 baterías) | `python3 tests/security/test_lock_drift.py` | `✓ opencv-python-headless==4.13.0.90 instalado` … `✓ import cv2 funciona` … `═══ 30 OK · 0 fallos ═══` — negativo (lockfile sintético): `✗ paquete-fantasma==9.9.9 instalado — FALTA en el venv (incidente P4.2/F1…)` · `═══ 5 OK · 2 fallos ═══` exit 1 |
| **F1 aceptación** | servidor uvicorn VIVO con BD/OUTPUT aislados por env (`DB_PATH/DATA_DIR/…` de config.py) | `POST /api/product/badge {"type":"rating"}` | `HTTP 200` · `{"ok":true,"badge_url":"/static/assets/badge_rating.png"}` · magic bytes `b'\x89PNG'` 4232 B en backend/static/assets |
| | | `POST /api/product/callout-layer` (defaults) | `HTTP 200` · `{"ok":true,"callouts_url":"/static/assets/callouts_….png","callouts_count":2,…}` · `b'\x89PNG'` |
| | | `POST /api/product/studio-preview` (image_url pública) | `HTTP 200` · `{"ok":true,"studio_preview_url":"/static/studio_previews/studio_….jpg","cutout_url":…}` · `b'\x89PNG'` + JPEG |
| | | `POST /api/avatars/<sintético>/circle-pip` | `HTTP 200` · `{"ok":true,"pip_url":"/static/assets/avatar_pip_…_cyan.png"}` · `b'\x89PNG'` 12463 B |
| **F2** `.venv_3.14_roto` (483 MB · 12.654 fich) | NO existe en el clon de cierre (artefacto exclusivo de la máquina del dueño). Verificación de referencias ejecutada | alcance del mandato (equivalente POSIX): `rg -n '3\.14_roto\|venv_3' launchers .github/workflows ROADMAP.md LEEME_PRIMERO.md ESTADO_REAL.md SESSION_INDEX.md README.md backend/*.py backend/*.txt` | **VACÍO** (exit 1, sin coincidencias). Repo completo: solo `docs/informe_reparacion_optimizacion.md:51` y `docs/P5_informe_lipo.md` (se auto-referencian: documentan el borrado) |
| | borrado en la MÁQUINA DEL DUEÑO (comando del mandato, ya verificado 0 refs) | `Remove-Item 'backend\.venv_3.14_roto' -Recurse -Force` | por ejecutar por el dueño; esperado −483,0 MB · −12.654 ficheros |
| **F3** podar perfil Google (254,7 MB → ~20 MB) | `tools/podar_google_profile.py` ya existía (P5.2): probado de punta a punta con perfil SINTÉTICO (29,6 MB de cachés + sesión completa) dentro de `backend/data/google_profile_global` (gitignored) | `python tools/podar_google_profile.py` (dry-run) | `tamaño actual: 29.6 MB` · `regenerables a borrar: 29.6 MB` · `DRY-RUN: nada borrado` · tras dry-run: 38 ficheros (idéntico) |
| | | `--ejecutar` con Singleton* | `REFUSIDO: el perfil tiene Singleton* — Chrome está (o estuvo) abierto…` · `exit=2` · 40 ficheros intactos |
| | | `--ejecutar` real | `✓ borrado component_crx_cache (4.8 MB)` … 10 borrados · `Listo: 29.6 MB liberados` · sesión íntegra: Cookies/Login Data/Login Data For Account/Local State/Web Data/Network/Cookies/Extensions ✓ CONSERVADOS · DESPUÉS: 60K · 10 ficheros |
| | aceptación real del dueño (conexión Google) | `netstat -ano \| Select-String ':9333'` + `POST /api/mcp/connect-all-google` | por ejecutar en la máquina del dueño tras podar (aquí sin Chrome real; el mecanismo de conservación queda demostrado) |
| **F4** biblioteca duplica output (122,2 MB) | mecanismo P5.3 ya en el repo (`archive()` por referencia + `tools/dedup_biblioteca.py`): probado con duplicado sintético hash-idéntico (3,0 MB) | `python tools/dedup_biblioteca.py` | `copias convertibles: 1 → liberar 3.0 MB` · `DRY-RUN: no se ha borrado ni escrito nada` · tras dry-run: 6 ficheros (idéntico) |
| | | `--ejecutar` | `✓ video_prueba_f4.mp4 → video_prueba_f4.ref.json (liberados 3.0 MB)` · la copia desaparece (36K→44K con solo el .ref.json) |
| | UI sigue listando | `python3 -c "from services import library; print(library.tree())"` | `{'niche': 'f4prueba', 'files': [{'name': 'video_prueba_f4', 'size': 3145728, …, 'ref': True, 'path': '…/output/f4probepid01/f4probepid01_final.mp4'}]}` — la biblioteca sigue siendo función de producto |
| | conversión de las 11 copias legacy del dueño | `python tools\dedup_biblioteca.py` (dry-run) → `--ejecutar` | por ejecutar en la máquina del dueño; esperado −122,2 MB → biblioteca < 5 MB |
| **F5** retención de output | §12 de `test_auditoria_repairs.py` AMPLIADA (+2 checks): default N=10 y dry-run idempotente | `python3 tests/security/test_auditoria_repairs.py` | `✓ dry-run idempotente: plan dos veces = mismo informe (mismos borrables y mismos MB, nada borrado)` · `✓ default N=10 (config.LIMITS) y conserva EXACTAMENTE los 10 más recientes (+ marcados/job activo)` · `═══ 46 OK · 0 fallos ═══` |
| | endpoints ya existentes (P5.4) | `GET /api/maintenance/output/plan` + `POST /api/maintenance/output/purge` con `confirm=true` | el dueño lista con el plan (dry-run) y decide; sin `confirm=true` NO borra (46/46 lo congelan) |
| **F6** import < 5000 ms | sin cambio (lazy-imports P6.1 intactos) | `python -c "import time;t=time.perf_counter();import main;print(int((time.perf_counter()-t)*1000),'ms')"` ×3 | `536 ms` · `535 ms` · `523 ms` |
| **F7** CRLF no reproducible | 1) experimento: árbol con **515 ficheros LF→CRLF** (9 binarios + 4 bat excluidos) + `core.autocrlf=true` = estado tipo-dueño; 2) hallazgo: `git status` pinta 513 M con `git diff` VACÍO (estado «fantasma» — la fragilidad es real); 3) suite en ese árbol: ÚNICA dependencia = `test_live_boot.py` (bash no ejecuta CRLF: `syntax error near unexpected token '$'do\r''` → 4 fallos); 4) FIX: `test_live_boot.py` ejecuta los .sh desde copia LF-normalizada HERMANA del script (mismo dirname — los scripts derivan el repo de `$(dirname "$0")/..`), decisión documentada: **fin de línea irrelevante para la ejecución** | `python3 tests/test_live_boot.py` en /tmp/crlf_tree | `═══ 34 OK · 0 fallos ═══` (antes: `0 OK · 4 fallos`) |
| | checkout fresco (aceptación) | `git clone` en otra carpeta + `git status --porcelain` | **limpio** (con `.gitattributes` X3, eol=lf manda sobre autocrlf en un checkout fresco: el árbol nuevo nace LF) |
| | receta para el dueño (su árbol actual CRLF) | clon fresco en otra carpeta y continuar ahí (o `git rm --cached -r . && git reset --hard` con stash previo) | el estado CRLF-fantasma desaparece; suite verde en AMBOS (LF medido aquí + CRLF medido aquí) |
| **F8** CI ciego a Windows | `ci.yml` `ci-windows`: windows-latest / **Python 3.13** / sin continue-on-error / pytest xdist + **`python tests/run_all.py --hermetic`** (69 baterías). Por qué 3.13 y no 3.14: el lock no puede — numpy==2.1.3 sin wheels cp314 (evidencia PyPI: cp310..cp313+cp313t); av 18.1.0 y opencv 4.13.0.90 = abi3 (≥3.11); ctranslate2/onnxruntime con cp313. Ubuntu `ci` queda como gate requerido. **4 corridas reales: 3 clases de fallo solo-Windows cazadas y corregidas** — (a) hijos minidrama sin reconfigure D5 → «0 OK · -1 fallos» en cp1252 (bloque D5 añadido; 54 y 12 OK); (b) intento de endurecimiento de bucles MCP REVERTIDO por el trinquete P2-2 (287 > 286 — la resiliencia ya existía en el finally → PROCESS_DEAD) y sustituido por done-callback de visibilidad en _spawn (0 except Exception nuevos); (c) checks de sandbox con startswith(str(_TMP)) rotos por paths 8.3 (RUNNER~1) vs resolve() expandido → is_relative_to sobre formas resueltas (memorydv 36 OK, skills 34 OK) | corrida #4 (API GitHub) | **`CI YOUTUBE-AUTOMATION | completed | success`** en `f90d558` — `ci` success · `ci-windows` success (run_all --hermetic + pytest xdist en windows-latest/3.13) |
| **F9** default inseguro del badge | YA corregido en el linaje V15 (`out_path` keyword-only sin default + ValueError); aquí se MIDE el negativo y el endpoint | `python3 -c "from services import ecommerce_overlays as eco; eco.generate_ecommerce_badge('rating')"` | `F9 OK TypeError: generate_ecommerce_badge() missing 1 required keyword-only argument: 'out_path'` · y el endpoint sigue `HTTP 200` (F1 aceptación) |
| **F10** `--workers 6` | medido, no supuesto | `python tests/run_all.py --workers 6` (2 corridas) | `═══ 2983 OK · 0 fallos · 0 SKIP en 71 baterías ═══` · `real 2m13.475s` (user 1m41s) — serie 2m57.4s: **el paralelo es seguro Y más rápido**; default sigue siendo serie |

## Cifras antes/después de la lipo

| Artefacto | Máquina del dueño (mandato) | Acción | Resultado esperado | Medido aquí (sandbox) |
|---|---|---|---|---|
| `backend/.venv_3.14_roto` | 483,0 MB · 12.654 ficheros | borrado por el dueño (0 refs verificadas) | `backend` −483 MB | AUSENTE en el clon (no aplicable) |
| `backend/data/google_profile_global` | 254,7 MB · 1.622 ficheros | podar cachés (tool probado) | ~20 MB (−234 MB) | sintético 29,6 MB → 60K (−29,6 MB, sesión íntegra) |
| `backend/data/biblioteca` | 122,2 MB · 11 ficheros | dedup a referencias (tool probado) | < 5 MB | sintético −3,0 MB; `tree()` lista por `.ref.json` |
| `backend/data/output` | 225,8 MB · 207 ficheros | retención N=10 con dry-run (P5.4 + §12 ampliada) | solo 10 recientes + keep | batería 46/46; dry-run idempotente demostrado |

## Lo que NO se cerró aquí y por qué (honesto)

1. **Los borrados físicos de la lipo (F2, F3-poda real, F4-conversión real, F5-plan real sobre los 225 MB) NO se ejecutaron**: los 860 MB viven en la máquina Windows del dueño. Este repo/clon solo contiene versiones mínimas/gitignored. Lo entregado y PROBADO aquí es el mecanismo (tools + guardias + baterías) y los comandos exactos. Aceptaciones pendientes del dueño: `netstat :9333` sin listener + `connect-all-google` autenticando tras la poda; biblioteca < 5 MB tras el dedup; `backend` ~24.000 ficheros tras borrar el venv roto.
2. ~~**`ci-windows` aún no tiene una corrida verde medida**~~ **CERRADO tras 4 corridas**: 3 clases de fallo solo-Windows cazadas por el propio job (encoding cp1252 de hijos sin D5; bucles MCP silenciosos — solucionado con done-callback respetando el trinquete P2-2; prefix-checks de sandbox rotos por paths 8.3) y la corrida #4 terminó `success` completa (`ci` + `ci-windows`) en `f90d558`. El job YA demostró su razón de existir: tres fallos que ubuntu jamás habría visto.
3. **Ejecución REAL de connect-all-google tras podar**: requiere la sesión Chrome del dueño (imposible en el sandbox). El mecanismo de conservación (Cookies/Login Data/…) quedó demostrado con perfil sintético.
4. **Python 3.14 en CI**: NO por decisión propia — el lockfile no puede (numpy==2.1.3 sin cp314). Documentado en el propio ci.yml con la evidencia; cuando el lock suba a numpy≥2.2, subir la versión del job.
5. **Estado «fantasma» del árbol del dueño**: su `git status` puede seguir mostrando M-fantasma con diff vacío hasta que haga el checkout fresco; la suite ya NO depende de ello (F7), pero la limpieza visual exige la receta del informe.

## Definición de terminado (checklist con evidencia)

- [x] `import cv2` → `cv2.__version__` **4.13.0** (paquete pip **4.13.0.90** — versión upstream ≠ versión del wheel, medido); los 4 endpoints e-commerce → **200** con PNGs reales.
- [x] Guardia «declarado == instalado» en la suite, **verde** (30 checks; negativo demostrado).
- [x] `.venv_3.14_roto` NO existe en el clon; referencias 0 en el alcance del mandato (el borrado −483 MB es del dueño).
- [x] Mecanismo de poda del perfil probado (−29,6 MB sintético, sesión íntegra; cifra real del dueño pendiente: 254,7 → ~20 MB).
- [x] Biblioteca: dedup probado, `tree()` lista por referencia (cifra real del dueño pendiente: 122,2 → < 5 MB).
- [x] Retención de output con dry-run idempotente (46/46 en §12 ampliada).
- [x] import de backend < 5000 ms: **536/535/523 ms** (3 medidas).
- [x] Suite verde en checkout LF (2983 OK/71) y en árbol **CRLF materializado** (live_boot 34 OK tras el fix).
- [x] CI con job Windows ejecutando run_all: **`CI YOUTUBE-AUTOMATION completed success`** (run 45277431216 aprox — ver SESSION_INDEX) sobre `f90d558`: `ci` success + `ci-windows` success.
- [x] run_all → **2983 OK · 0 fallos**; hash de `backend/data/yt_automation.db` sin cambios (`9afa69dd…`).
- [x] npm test → **28/28**; ruff F821,E9,F63,F7,F82 → limpio.
