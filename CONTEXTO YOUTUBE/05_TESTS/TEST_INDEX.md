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

## Límite de evidencia
Estos conteos no se volvieron a ejecutar en esta sesión. Tests simulados/HTTP validan sus capas, no Google Flow real.

## Prueba pendiente
**TEST-FLOW-START-FRAME-REAL — BLOCKED / NOT RUN.** Imagen conocida → job ALBRA → request capturado → mediaId de entrada correlacionado → vídeo resultante comprobado. PASS requiere request real sanitizada y correlación de la imagen correcta.
