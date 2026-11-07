# SES-2026-11-06-05 · Hermeticidad total de tests (H1-H3) + higiene de secretos

Fecha: 2026-11-06 · Modelo: Z.ai/GLM · Base: d0cab7d (+ commits de esta sesión)

## H1 · Tests herméticos (cero DNS, cero internet) — commit `6e7cca3`

1. **test_p0_2_ssrf_siblings::test_broll_link_publico_sigue_funcionando**
   dependía de DNS real: `security.validar_url` resuelve videos.pexels.com
   (security.py:102 `socket.getaddrinfo`) y sin DNS el fetch devolvía False.
   Fix: el test parchea SOLO la resolución (getaddrinfo → IP pública
   ficticia 93.184.216.34) en SU scope; la LÓGICA de validar_url no se toca
   (sigue evaluando is_private/is_loopback sobre la IP que recibe).

2. **test_p0_1_product_ssrf** generaba imágenes reales: tras el rechazo de
   la URL de producto, la cadena de fallback llegaba al plan B
   (`_zai_image` → CLI `z-ai` externo, hasta 120 s por intento, generación
   vía servicio externo). Fix: doble de prueba `pipeline.images._zai_image`
   → devuelve False → degrada a placeholder PIL local. El test sigue
   midiendo lo suyo (product_raw.png jamás creado desde URLs SSRF) y ahora
   tarda 0.65 s (antes >90 s).

3. **Guardia de red en conftest (sustituye al parche DNS parcial P1-1)**:
   - `getaddrinfo` estricto: resuelve SIN red las IP literales,
     localhost/testserver y la lista blanca documentada
     (youtube/example.com → IP ficticia heredada de P1-1); cualquier otro
     nombre → OSError "H1c".
   - `socket.socket.connect/connect_ex`: solo loopback (127.0.0.0/8, ::1)
     y AF_UNIX; lo demás → OSError / EHOSTUNREACH.
   - `gethostbyname(_ex)`: misma política.
   - Smoke propio: DNS externo bloqueado, connect a IP pública bloqueado,
     loopback permitido, IP literal se resuelve sin DNS (4/4).
   - Nota honesta: cubre el PROCESO pytest; los subprocess que algún test
     levante solo hablan loopback.

## H2 · Higiene de secretos — commit de esta sesión

- `CONTEXTO YOUTUBE/05_TESTS/ANTIGRAVITY_VALIDACION_PRODUCCION.md:19`
  guardaba el prefijo del PAT del chat (`ghp_IoIr...`) → REDACTADO. La nota
  ahora fija la regla: NUNCA pedir/guardar/escribir tokens en ficheros,
  notas ni logs; el push lo hace el dueño con su credential helper.
- `tests/test_h2_secrets_hygiene.py` (2 tests): barrido de *.md/*.txt del
  repo (fuera de backend/ y tests/, donde viven los dobles FALSOS de las
  pruebas de redacción de selfaudit/test_hands) por prefijos
  ghp_/github_pat_/AKIA/sk-/xox/AIza + regresión exacta del fragmento.
- **Nota honesta para el dueño**: el fragmento sigue en el HISTORIAL de git
  (commits anteriores). No se reescribe historia sin orden explícita; la
  mitigación correcta es revocar/rotar el PAT — sigue PENDIENTE DE
  CONFIRMACIÓN POR EL DUEÑO. Nada de esto elimina la responsabilidad de
  rotar el token.

## H3 · Verificación sin internet — totales reales

- El sandbox SÍ tenía internet al correr (curl a pollinations → HTTP 200):
  la hermeticidad no es un accidente de red caída, la guardia la impone.
- **pytest** (`python -m pytest tests/ -q`): **536 passed en 58.54 s, 0
  fallos, 0 warnings** con la guardia activa. Antes de H1: 534 en 3:06 —
  la diferencia de tiempo era exactamente la generación real de imágenes.
- **run_all.py** (53 baterías, cada una con la guardia sitecustomize
  inyectada por PYTHONPATH — cubre batería Y procesos hijos):
  **2627 OK · 0 fallos en 53/53 baterías**, incluidas 20/24/51
  (int025 77, security_hardening 47, int028 65 — pasan limpias; los
  "colgados" históricos eran el patrón de sesión del sandbox).
- Mecanismo: `PYTHONPATH=/home/z/my-project/scripts/hermetic_sitecustomize`
  (sitecustomize.py con la misma guardia H1c; se importa solo en cada
  proceso python).

## Commits de esta sesión

- `6e7cca3` test(H1): hermeticidad total de pytest — cero DNS, cero internet.
- H2: higiene de secretos (nota redactada + test guardia).
- Cierre de sesión: LEEME/ROADMAP + este archivo.

## Pendiente para el dueño

- Revocar/rotar el PAT que circuló por el chat (incluido el prefijo que
  estaba en las notas y sigue en el historial de git).
- El push de esta sesión lo hago con el mecanismo existente; si la
  autenticación fallara, reporto y NO pido token por chat (regla H2).
