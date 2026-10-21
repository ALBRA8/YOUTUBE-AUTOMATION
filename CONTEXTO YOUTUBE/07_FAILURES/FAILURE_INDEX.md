# FAILURE INDEX

## FAIL-001 — Declaración histórica de Flow Bridge real sin código presente
- **Estado:** incidente histórico documentado en `ESTADO_REAL.md`.
- **Descripción:** se reportó un Flow Bridge terminado que entonces no existía en repo (sin commit/rama/stash).
- **Consecuencia:** se reforzó `tests/test_humos_infra.py` y el inventario honesto.
- **Lección:** ninguna capacidad se declara terminada sin código localizable y tests que respalden la afirmación.

## GAP-002 — Start Frame Google Flow no contractual ni demostrado
- **Estado:** OPEN / NOT_DEMONSTRATED; no llamar fallo real observado.
- **Descripción:** no hay contrato verificable y no se encontró binding en camino Flow auditado.
- **Acción:** capturar request real antes de implementar.

## RISK-003 — Secretos en HAR
- **Estado:** riesgo abierto con mitigación definida.
- **Mitigación:** sanear cookies, tokens, credenciales, datos personales y URLs firmadas antes de compartir.

## RISK-004 — Confundir respuesta con request
- **Estado:** regla de auditoría.
- **Descripción:** mediaId en respuesta no demuestra mediaId enviado como input.

## FAIL-005 — Telemetría nula en LIVE Gate por ingestión restrictiva de fetch(Request)
- **Estado:** RESOLVED LOCALLY & VERIFIED (PENDING LIVE GATE).
- **Incidencia:** En el LIVE Gate del commit `85ab666bc283509c1617feabefc98aee3bac5ed4`, Google Flow renderizó el video real con Start Frame, pero `window.__FLOW_RPC_OBS__` emitió valores `null` en todos sus campos de telemetría (`LIVE FAIL`).
- **Causa Raíz Forense:** Google Flow invoca `window.fetch` pasando una instancia de `Request` (`fetch(new Request(url, ...))`) sin proveer un objeto `init`. El interceptor de `extension/injector.js` leía únicamente `init ? init.body : null`, provocando que `parseFreqEntries(null)` devolviera `[]` y el parser posicional nunca fuera alcanzado.
- **Solución implementada:** Ingestión polimórfica en `extension/injector.js` mediante clonación segura preventiva `input.clone().text()`, duck-typing cross-realm para `URLSearchParams`/`FormData`, aislamiento pasivo de `ReadableStream`, corrección F5 de precedencia explícita (`hasExplicitBody`) y coordinación causal de eventos de telemetría (`onSettled`).
- **Mitigación verificada:** 244/244 tests aprobados en laboratorio (F1: 64, F2: 67, eb1hJf Dual+F5: 58, Harness: 55).
- **Acción pendiente:** Solicitud de autorización de LIVE Gate para verificación en producción.
