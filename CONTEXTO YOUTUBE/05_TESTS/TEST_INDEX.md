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


## TEST-SUITE-F5-CONSOLIDADA (2026-10-20)
**Estado:** PASS 100% EN VM/HARNESS (244/244 CHECKS VERIFICADOS).

Resultados de la validación final agrupada:
1. `tests/test_flow_batchexecute.py` (F1): **64 OK · 0 fallos**.
2. `tests/test_flow_startframe_fase2.py` (F2): **67 OK · 0 fallos**.
3. `tests/test_flow_startframe_eb1hjf.py` (Dual eb1hJf + Post-Autopsia + F5): **58 OK · 0 fallos**.
   - Incluye 11 checks de ingestión polimórfica (Request, URLSearchParams, Duck-typing, Streams).
   - Incluye 9 checks F5 de precedencia explícita (`body: ""` y `body: null`), orden causal determinista y resiliencia ante errores de stream.
4. `tests/test_harness.py` (YouTube Harness V1): **55 OK · 0 fallos**.

**Total Consolidado:** 244 OK · 0 fallos.

### Límite de evidencia:
Estas 244 pruebas validan con rigor algorítmico y de microtareas la implementación de `extension/injector.js` en V8 (Node.js hermético). No equivalen a una prueba LIVE en Chrome contra la infraestructura real de Google Flow.
