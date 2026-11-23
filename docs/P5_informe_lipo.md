# P5 · Informe LIPO (adelgazar y ordenar) — con dry-run y medidas

**Fecha:** 2026-11-20 · **Entorno de verificación:** clon Linux del repo @ `4bbe803`
**Regla cumplida:** nada de medios del usuario borrado sin política explícita + dry-run.

## Antes / después (medible)

| Elemento | Antes | Después | Dónde se ejecuta |
|---|---|---|---|
| `backend/.venv_3.14_roto` | 483,0 MB · 12.654 ficheros | **0 referencias verificadas** → borrado por el operador | máquina Windows (comando abajo) |
| `backend/data/google_profile_global` | 254,7 MB → ~20 MB (cachés) | herramienta lista + dry-run ejecutado | máquina Windows, Chrome cerrado |
| `biblioteca` vs `output` | 122,2 MB duplicados | almacenamiento por REFERENCIA (`.ref.json`); migración con hash por `tools/dedup_biblioteca.py` | script (dry-run verificado aquí) |
| `data/output` | 225,7 MB y creciendo | política de retención N=10 + `meta.keep` + acción explícita (endpoints verificados) | API (`/api/maintenance/output/*`) |
| Raíz del repo | fichero `-` (18 B), `sc1_*.mp4`, `scene_*.wav`, `test_*.mp3`, `.server_stdout/stderr.txt` | `-` eliminado aquí; patrones en `.gitignore` | hecho |
| Escaneos AV/backup | 36.937 ficheros | ~4.000 (−89%) tras exclusiones | recomendación (P5.6) |

## P5.1 — Borrar `backend/.venv_3.14_roto` (verificación previa ejecutada)

```
rg "3\.14_roto" --hidden -g "!.git"   →   0 coincidencias en TODO el repo
```
Nadie lo referencia (lanzadores, CI, docs, código). Borrado en la máquina Windows:

```powershell
# confirmación final antes de borrar (deja constancia en consola):
Select-String -Path launchers\*,.github\workflows\*,*.md,backend\*.py -Pattern '3.14_roto'
# (0 resultados → borrar)
Remove-Item -Recurse -Force "D:\PROYECTOS\YOUTUBE AUTOMATION\backend\.venv_3.14_roto"
# antes/después:
"{0:N1} MB" -f ((Get-ChildItem "backend" -Recurse | Measure-Object Length -Sum).Sum / 1MB)
```

## P5.2 — Podar `backend/data/google_profile_global`

```powershell
python tools\podar_google_profile.py             # dry-run + informe MB
python tools\podar_google_profile.py --ejecutar  # aplica (Chrome CERRADO)
```
- BORRA solo: `component_crx_cache`, `optimization_guide_model_store`, `WasmTtsEngine*`,
  `Safe Browsing/*.store*`, `GPUCache`, `Code Cache`, `Dawn*Cache`, `GrShaderCache`, `ShaderCache`, `Crashpad`.
- CONSERVA (sesión Google del MCP): `Cookies`, `Login Data(+For Account)`, `Preferences`,
  `Secure Preferences`, `Local State`, `Web Data`, `Extensions`, `Network`, `Sync Data`.
- Se NIEGA si existen `Singleton*` (Chrome abierto).
- Post-verificación operador: botón «Conexión Google» → `connect_all_google` debe seguir autenticando.

## P5.3 — Deduplicar biblioteca ↔ output

- `services/library.py::archive()` ya NO copia: escribe `{nicho}/{titulo}_{pid}.ref.json`
  con ruta RELATIVA al MP4 en `data/output/`. `tree()` sigue listando MP4 legacy + refs
  (misma forma `{niche, files[]}` — la UI no cambia).
- Migración de las 11 copias existentes:
  ```powershell
  python tools\dedup_biblioteca.py             # dry-run: lista pares por SHA256 + MB a liberar
  python tools\dedup_biblioteca.py --ejecutar  # borra la copia SOLO si el hash coincide
  ```
- Verificado aquí: par sintético → dry-run informe exacto → conversión → `tree()` sigue
  resolviendo el MP4 (`size` real, `ref: true`), huérfanas marcadas `missing: true`.

## P5.4 — Retención de `data/output` (225,7 MB y creciendo)

- `GET /api/maintenance/output/plan?n=10` → DRY-RUN: conservar/borrables + MB.
  Conserva: N más recientes con medios + `meta.keep=true` + jobs activos.
- `POST /api/maintenance/output/purge {"n":10,"confirm":true}` → borra SOLO lo borrable,
  deja `meta.media_purged=true` y `video_url=""` (DB consistente).
- Marcar un proyecto como retenido: `POST /api/projects/{pid}/keep {"keep":true}`.
- Automático: NUNCA (política explícita del mandato). Config: `OUTPUT_RETENTION_PROJECTS`.

## P5.5 — Raíz limpia

- Fichero `-` (18 B, residuo «rendered_subs_only») eliminado en este clon.
- `.gitignore` añade: `sc1_*.mp4`, `sc1_lip.mp4`, `sc2_broll.mp4`, `sc3_raw.mp4`,
  `scene_*.wav`, `test_*.mp3`, `.server_stdout.txt`, `.server_stderr.txt`, `-`.
- En Windows (opcional, son residuos regenerables de pruebas):
  ```powershell
  Remove-Item "D:\PROYECTOS\YOUTUBE AUTOMATION\sc1_*.mp4","D:\PROYECTOS\YOUTUBE AUTOMATION\scene_*.wav","D:\PROYECTOS\YOUTUBE AUTOMATION\test_*.mp3" -ErrorAction SilentlyContinue
  ```

## P5.6 — Exclusiones recomendadas (NO ejecutar sin permiso)

```powershell
Add-MpPreference -ExclusionPath "D:\PROYECTOS\YOUTUBE AUTOMATION\backend\.venv"
Add-MpPreference -ExclusionPath "D:\PROYECTOS\YOUTUBE AUTOMATION\backend\data\output"
Add-MpPreference -ExclusionPath "D:\PROYECTOS\YOUTUBE AUTOMATION\backend\data\google_profile_global"
```
Con `.venv` (~2 GB instalado) + `output` + `google_profile_global` excluidos, los
escaneos pasan de 36.937 a ~4.000 ficheros (−89%). Igual para la herramienta de backup
del operador (esos tres directorios son regenerables o ya respaldados por otra vía:
`.venv` reinstalable con el lockfile, output por la política P5.4, perfil re-autenticable).

## Verificación de la lipo

- `pytest`: 870 passed / 0 failed (incluye los cambios de `library.py`).
- `run_all.py`: 2842 OK · 0 fallos en 66 baterías (2 bloques medidos: 1715 + 1127).
- La UI sigue listando la biblioteca y las escenas (`tree()` misma forma; verificado).
