# TEST INDEX

## Inventario reportado por ESTADO_REAL.md
Los conteos son los declarados por el inventario del repo; no se reejecutaron durante la actualización de memoria.

- `test_production_json.py`: 76 checks.
- `test_flow_contract_p1.py`: 44.
- `test_flow_bridge.py`: 48.
- `test_golden_fixture.py`: 30.
- `test_qa_forensics.py`: 30.
- `test_concurrencia.py`: 18.
- `test_chaos.py`: 28.
- `test_10_escenas.py`: 44.
- `e2e_bridge_mock.js` + `test_bridge_e2e.py`: 26 checks de harness + 24 Python.
- `test_live_boot.py` y smoke scripts: 33.
- `test_production_doctor.py`: 54.
- `test_doctor_preflight.py`: 38.
- `test_security_hardening.py`: 47.
- `test_memorydv.py`: 36.
- `test_skills_autonomia.py`: 34.
- HANDS: `test_hands.py` 121, `test_hands_operators.py` 58, `test_hands_chaos.py` 33.
- `test_flow_video_v3.py`: 123.
- `test_extension_error_tile.py`: 65.
- `test_flow_observability_v11.py`: 59.
- Harness de observabilidad Start Frame: 15/15 escenarios y F1 64/64, según reporte del commit `2d0a99b85fa8c7f224b5c8660708411b1617e32a`.

## Límite de evidencia
Estos conteos no se volvieron a ejecutar en esta sesión. Tests simulados/HTTP/harness validan sus capas, no Google Flow real.

## TEST-FLOW-START-FRAME-REAL
**Estado:** IN_PROGRESS / CAPTURA MANUAL REAL PARCIAL.

Se realizó una generación real en Google Flow usando el modo `Fotogramas`, con una imagen conocida colocada en `Iniciar` y `Finalizar` vacío. La generación produjo vídeo y la extensión observó tráfico `batchexecute` real.

La captura actual contiene 4 observaciones `WuwhI`, pero todavía no se ha extraído de forma concluyente cuál corresponde a la generación ni si su estructura contiene el `mediaId` de Start Frame. Por tanto, **no es PASS todavía**.

### Siguiente lectura
Usar únicamente las observaciones ya almacenadas:

```js
window.__FLOW_RPC_OBS__
  .filter(x => x.rpcid === "WuwhI")
  .map((x,i) => ({
    n: i,
    operation: x.operation,
    videoModelKey: x.videoModelKey,
    aspectRatio: x.aspectRatio,
    count: x.count,
    startFrame: x.startFrame,
    ids: x.ids
  }))
```

No generar otro vídeo hasta clasificar esta captura.

## GoogleFlowMCP bridge — 2026-10-20
**Estado:** pruebas reportadas PASS; LIVE pendiente. Los resultados siguientes provienen del informe de Antigravity y no se reejecutaron al actualizar este índice.

- `tests/test_flow_mcp_bridge.py`: 21/21 PASS reportado.
- `tests/flow_batchexecute_eb1hjf_mock.js`: regresión mock F5.1 PASS reportado.
- `tests/test_harness.py`: 55 OK reportado.
- `tools/GoogleFlowMCP`: `npm test`, 3/3 PASS reportado.

**Límite:** los tests aislados y mocks no demuestran una generación real por Google Flow. LIVE TEST 1 sigue pendiente hasta preparar el perfil dedicado y ejecutar una imagen controlada con autorización explícita.
