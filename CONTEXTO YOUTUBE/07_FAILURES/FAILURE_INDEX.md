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
