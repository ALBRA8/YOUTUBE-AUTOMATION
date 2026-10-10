# EXECUTION CONTRACT V1.0 — spec de ejecución, gate de configuración y validación contractual (FASE 7)

> **Estado:** IMPLEMENTADO en hermético (1754 checks · 34 baterías).
> **Flow real: NO PROBADO** — el primer REAL FLOW E2E + HANDS CAPABILITY
> AUDIT es el paso pendiente (ver §8). Nada de lo aquí descrito inventa
> capacidades de Flow: lo no observado es null/unknown/UNVERIFIABLE.

---

## 1. El problema que cierra

La auditoría (Codex) documentó la fuga:

```
Production JSON: duration_target = 8
  → adapter: 8 ✓   → flow_export: 8 ✓ (entry["duration"])
  → flow_jobs.enqueue_project: SE PIERDE (solo leía prompt/título)
  → extensión: solo recibía prompt
  → Flow: conservaba su estado de UI (p. ej. 5s)
  → asset de 5s aceptado por el backend
```

El Execution Contract V1.0 hace imposible esa fuga: el spec viaja en la
PROPIA fila del job, la extensión configura y verifica ANTES de generar, el
backend valida el asset real contra el spec, y un job que incumple el
contrato JAMÁS termina en DONE.

## 2. Tres capas del contrato (P1 / P2 / SPEC)

| Capa | Columna | Regla |
|---|---|---|
| **P1** prompt original | `flow_jobs.prompt` | Inmutable. Jamás se toca para resolver duración/modelo/aspecto/outputs/audio/resolución/referencias. |
| **P2** adaptación operacional | `flow_jobs.prompt_adapted` | Solo `flow_adaptation` (clases con evidencia). CONFIG ≠ ADAPTACIÓN. |
| **SPEC** ejecución | `flow_jobs.execution_spec` (JSON) | Petición al proveedor. Viaja verbatim job→extensión→HANDS. Nunca edita el prompt. |

## 3. execution_spec (schema_version "1.0")

```json
{
  "schema_version": "1.0",
  "duration":       {"requested": 8,    "required": true, "tolerance_seconds": 0},
  "model":          {"requested": null, "required": false},
  "aspect_ratio":   {"requested": "9:16", "required": true},
  "outputs":        {"requested": 1,    "required": true},
  "audio":          {"requested": null, "required": false},
  "resolution":     {"requested": null, "required": false},
  "references": [], "start_frame": null, "end_frame": null,
  "compatibility_policy": {"allow_inherited_state": false,
                           "generate_requires_verified": true,
                           "retry_on_config_error": false},
  "verification": {"duration": {"method": "ffprobe", "tolerance_seconds": 0,
                                "transport_epsilon_s": 0.25},
                   "aspect_ratio": {"method": "ffprobe", "relative_tolerance": 0.02},
                   "audio": {"method": "ffprobe", "gate": "register_only"},
                   "outputs": {"method": "transport"}}
}
```

Fuentes reales (nada inventado): `duration` ← entry de `build_script_json`
(production_unit.duration_target → duración de escena → VIDEO_SECONDS del
export); `aspect_ratio` ← format del proyecto (short→9:16, long→16:9, otro→
null+no-required); `outputs` ← hecho del transporte (1 asset por job);
`references` ← production_unit (§15: transportar ≠ ejecutar); `model`/
`audio`/`resolution` ← sin fuente → null. El audio del production_unit
(asmr/sfx) es audio FINAL del proyecto (TTS/render), no audio nativo de Flow.

## 4. Transporte completo

```
Production JSON → production_json.py (duration_target)
  → build_script_json (entry.duration + references)
  → flow_jobs.enqueue_project (execution_spec JSON + exec_state=QUEUED)
  → claim_next (SELECT * → job JSON verbatim, spec parseado)
  → bridge.js / background.js (__bridgeHandleJob lee job.execution_spec)
  → flowConfigFn(spec) en la pestaña de Flow (DOM-only)
  → progreso: POST /api/extension/flow/jobs/{id}/progress?token=
  → hands/flow_controls.py (ConfigGate — mismo vocabulario de veredictos)
```

DB: 3 columnas nuevas con migración idempotente (`execution_spec`,
`exec_state`, `contract_result`). La columna `status` (queued/claimed/done/
dead) sigue mandando la cola: leases, heartbeats, retry y zombie recovery
INTACTOS.

## 5. Máquina de estados (§9 del mandato)

```
QUEUED → CLAIMED → FLOW_TAB_READY → CAPABILITIES_CAPTURED → CONTROLS_CONFIGURED
      → CONTROLS_VERIFIED → GENERATION_SUBMITTED → GENERATION_OBSERVED
      → ASSET_DOWNLOADED → ASSET_VALIDATED → CONTRACT_VALIDATED → DONE
```

Terminales: `CONFIG_UNSUPPORTED · CONFIG_UNVERIFIABLE · CONFIG_MISMATCH ·
PROVIDER_FAILURE · ASSET_INVALID · DEAD`. El progreso (`set_exec_state` +
`/progress`) es lineal y jamás rebobina (la evidencia de un intento no
contamina otro). `status` del job: `done` solo desde CONTRACT_VALIDATED;
CONFIG_* y ASSET_INVALID → `dead` inmediato (independiente de attempts).

## 6. Gate de configuración (§6: PROHIBIDO generar con estado heredado)

Para cada control `required=true && requested!=null`, la última observación
debe ser **VERIFIED** con el valor pedido (normalización `8s`≡8). Si no:

| Veredicto del control | Decisión del gate | Comportamiento |
|---|---|---|
| VERIFIED (releído = pedido) | `ALLOW_GENERATE` | Se genera |
| UNSUPPORTED (control no existe/no editable) | `CONFIG_UNSUPPORTED` | NO se genera; terminal |
| MISMATCH (releído ≠ pedido) | `CONFIG_MISMATCH` | NO se genera; terminal |
| UNVERIFIABLE (no pudo releerse) | `CONFIG_UNVERIFIABLE` | NO se genera; terminal |

Un solo vocabulario, tres implementaciones espejo verificadas por
cross-check (gate JS ≡ `execution_contract.config_gate` ≡ `hands.ConfigGate`).
El estado heredado YA en el valor pedido es VERIFIED (§6 prohíbe generar con
un valor DISTINTO al pedido, no con el pedido ya configurado).

## 7. Validación contractual del asset (§13)

Tras la descarga, `complete()` mide el MP4 REAL con ffprobe y compara
**REQUESTED vs OBSERVED FLOW vs ACTUAL ASSET**:

- `duration`: |actual − requested| ≤ tolerance + 0.25s (epsilon de
  contenedor, documentado; la política es `tolerance_seconds` del spec: 0).
- `aspect_ratio`: w/h del asset vs pedido, tolerancia relativa 2%.
- `outputs`: exactamente 1 asset por job (transporte).
- `audio`: REGISTRO honesto (requested/observed_flow/asset_native_audio/
  final_project_audio) — el audio nativo de Flow es observable, no exigible.
- `references`: registro honesto (transportadas ≠ ejecutadas).

Resultado persistido en `flow_jobs.contract_result`. `CONTRACT_VIOLATION` →
`ValueError("ASSET_INVALID: ...")` (422) + job `dead` terminal +
`exec_state=ASSET_INVALID` + fail() posterior 409 (sin retry). **Jamás DONE.**

## 8. HANDS conectado (capa mecánica OBSERVE/CONTROL/VERIFY)

- `hands/flow_controls.py` (NUEVO): `ControlVerdict` (SUPPORTED/UNSUPPORTED/
  UNVERIFIABLE/MISMATCH/VERIFIED), `Capabilities`, `ControlResult`,
  `FlowControlAdapter` Protocol (discover/read_state/set_duration/set_model/
  set_aspect_ratio/set_outputs/set_audio/set_resolution/verify),
  `MockFlowControlAdapter` (UI simulada con scenarios missing/frozen/
  stale_read), `ConfigGate` (spec+adapter → decisión, evidencia refs
  `job_id`).
- `FlowOperator`: `discover_capabilities()`, `configure_from_spec()`,
  GATE en `start_generation()` — sin `driver.submit` si el gate no da
  ALLOW. `FlowJobSpec.execution_spec`.
- `FlowOp` nuevos: DISCOVER_CAPABILITIES, SET_MODEL, SET_DURATION,
  SET_ASPECT_RATIO, SET_OUTPUTS, SET_AUDIO, SET_RESOLUTION, VERIFY_CONTROLS.
- `future_integration.ExecutionContractHandAdapter`: puerta HAND_REQUEST real
  para la capa contrato (`INTEGRATION_STATUS: PARTIAL CONNECTED — contract
  layer`). `NotConnectedAdapter` sigue como default (§37 intacto).
- **La ejecución DOM real** la hace la extensión 2.4.0 (`flowConfigFn`) dentro
  de la pestaña de Flow — HANDS define el contrato, la extensión es el
  ejecutor mecánico en la UI, el backend es el juez (gate + validación).

## 9. Control matrix (estado honesto)

| Control | Discover | Configure | Verify | Status |
|---|---|---|---|---|
| Duration | mock TESTED / Flow NO PROBADO | mock TESTED / Flow NO PROBADO | mock+ffprobe TESTED | Implementado; requiere E2E real |
| Model | mock TESTED / Flow NO PROBADO | mock TESTED / Flow NO PROBADO | mock TESTED | requested null (sin fuente); N/A hoy |
| Aspect | mock TESTED / Flow NO PROBADO | mock TESTED / Flow NO PROBADO | mock+ffprobe TESTED | Implementado; requiere E2E real |
| Outputs | N/A (transporte) | N/A (transporte) | ffprobe TESTED | Implementado (1 asset/job) |
| Audio | mock TESTED / Flow NO PROBADO | NO (register_only) | registro TESTED | Registro honesto; sin gate |
| Resolution | mock TESTED / Flow NO PROBADO | mock TESTED / Flow NO PROBADO | mock TESTED | requested null (sin fuente) |
| References | N/A | NO (sin política segura) | NO VERIFICABLE | transportadas + registro honesto (§15) |

## 10. Errores de configuración ≠ adaptación (§10/§11)

`flow_adaptation.py` clasifica los prefijos estructurales del contrato con
prioridad máxima: **J** CONFIG_UNSUPPORTED, **K** CONFIG_UNVERIFIABLE, **L**
CONFIG_MISMATCH, **M** ASSET_CONTRACT_VIOLATION (confianza HIGH, fuente
`execution_contract`, alcance CONFIGURACION). Política: sin reintento, sin
P2, sin `FLOW_ADAPTATION_REQUIRED` — un error de configuración no se
"resuelve" reescribiendo el prompt. Las clases A-I de Flow Observability
V1.1 quedan intactas (watchdog → A, etc.).

## 11. Baterías

| Batería | Cubre | Checks |
|---|---|---|
| `test_execution_contract.py` | núcleo: spec sin invención, gate, validación ffprobe real, estados | 69 |
| `test_execution_transport.py` | §17-A transporte completo + migración DB | 54 |
| `test_flow_contract_states.py` | §17-C/D/E estados y errores terminales | 63 |
| `test_hands_contract.py` | HANDS: descubrimiento/control/gate/evidencia/sin-coordenadas | 55 |
| `test_flow_config_gate.py` | extensión 2.4.0: flowConfigFn DOM-only + cross-check | 68 |

Suite canónica: **1754 checks · 34 baterías** (`tests/run_all.py`).
