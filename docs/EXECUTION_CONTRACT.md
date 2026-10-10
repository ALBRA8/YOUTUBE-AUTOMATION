# EXECUTION CONTRACT V1.1 — spec de ejecución, gate de configuración y validación contractual (FASE 7 + 7.1)

> **Estado:** IMPLEMENTADO en hermético (1831 checks · 34 baterías).
> **Flow real: NO PROBADO** — el primer REAL FLOW E2E + HANDS CAPABILITY
> AUDIT es el paso pendiente (ver §8). Nada de lo aquí descrito inventa
> capacidades de Flow: lo no observado es null/unknown/UNVERIFIABLE.
>
> **V1.1 (FASE 7.1)** corrige **CF-E2E-01 — PRE-GENERATION CONTRACT GATE
> NOT ENFORCED (P0)**, demostrado por el primer E2E real: un job con
> `duration requested=8.0/required=true` llegó a esperar al watchdog (~15
> min) y terminó `PROVIDER_FAILURE/dead` aunque la UI de la sesión exponía
> 5s sin opción configurable de 8s — evidencia suficiente para
> `CONFIG_UNSUPPORTED` antes de Generate. Ver §12.

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
contamina otro). **V1.1 (§7.1):** para video con controles required
pre-generación, `CONTROLS_VERIFIED` es estado del SERVIDOR — solo se escribe
vía `/generate-consent` — y `GENERATION_SUBMITTED` solo se acepta desde
`CONTROLS_VERIFIED` (cualquier salto desde QUEUED/CAPS/CONFIGURED →
`contract_gate_required`). El estado `status` de la cola: `done` solo desde
CONTRACT_VALIDATED; CONFIG_*/ASSET_INVALID → `dead` inmediato
(independiente de attempts). `FLOW_WATCHDOG_TIMEOUT` NO es terminal de
máquina: etiqueta el veredicto LOCAL del watchdog (retry por attempts).

## 6. Gate de configuración (§6: PROHIBIDO generar con estado heredado)

Para cada control `required=true && requested!=null`, la última observación
debe ser **VERIFIED con el valor pedido Y configurada por ESTA ejecución**
(`control_results[control].configured == true`: set + relectura propios).
Un valor que YA estaba seleccionado en la sesión de Flow NO cuenta como
verificación cuando `allow_inherited_state=false` (política por defecto del
spec): es UNVERIFIABLE — TEST 9 del mandato FASE 7.1. Si no:

| Veredicto del control | Decisión del gate | Comportamiento |
|---|---|---|
| VERIFIED (configurado y releído = pedido) | `ALLOW_GENERATE` | Se genera |
| UNSUPPORTED (control no existe/no editable/no hay opción para el valor) | `CONFIG_UNSUPPORTED` | NO se genera; terminal |
| MISMATCH (releído ≠ pedido) | `CONFIG_MISMATCH` | NO se genera; terminal |
| UNVERIFIABLE (no pudo releerse O valor heredado sin configuración propia) | `CONFIG_UNVERIFIABLE` | NO se genera; terminal |

Un solo vocabulario, tres implementaciones espejo verificadas por
cross-check (gate JS ≡ `execution_contract.config_gate` ≡ `hands.ConfigGate`).

### 6.1 CONSENTIMIENTO DE GENERACIÓN (V1.1 — la corrección de CF-E2E-01)

El juez del contrato es el SERVIDOR, no el cliente. Antes de pulsar
Generate, la extensión/HANDS llama:

```
POST /api/extension/flow/jobs/{id}/generate-consent?token=
     {capabilities, control_results, client_decision, client_detail}
```

El backend re-evalúa `config_gate(spec, capabilities, control_results)`:

- **ALLOW** → `exec_state=CONTROLS_VERIFIED` (escrito por el servidor) y
  `{ok, allowed: true}` — solo entonces procede GENERATION_SUBMITTED.
- **DENY** → terminal INMEDIATO en la misma transacción: `status=dead`,
  `exec_state=CONFIG_*`, `error="CONFIG_*: detalle"`, `contract_result`
  con el registro completo del gate (`kind: pre_generation_gate`). Sin
  retry, sin P2, sin adaptación — jamás DONE.
- **Video sin execution_spec** → DENY CONFIG_UNVERIFIABLE (fail-closed:
  fila legacy → regenerar la cola con enqueue_project).
- **Consent no disponible (red/409)** → la extensión falla CERRADA
  (`CONFIG_UNVERIFIABLE`): jamás genera a ciegas.

Tres capas de enforcement (defensa en profundidad):

1. **Extensión (ejecutor):** `flowConfigFn` (discover/configure/verify DOM)
   + `__flowGateDecision` (pre-filtro espejo) + llamada OBLIGATORIA a
   `/generate-consent` antes de inyectar/Generate; `injectScene` re-ejecuta
   el gate+consent en TODO punto de entrada (retry RETRY_SCENE, resume
   zombi del Service Worker — vías E5/E6 de la auditoría).
2. **`set_exec_state` (juez de estados):** VERIFIED/SUBMITTED rechazados
   (`contract_gate_required`) para video gated si el servidor no los puso.
3. **`complete()` (barrera backstop):** un video gated cuyo exec_state
   nunca alcanzó CONTROLS_VERIFIED → dead CONFIG_UNVERIFIABLE + 422, sin
   asset, sin DONE (cualquier cliente que burle 1 y 2 — p. ej. extensión
   vieja — falla cerrado aquí).

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
(El prefijo `ASSET_INVALID:` en `fail()` es también terminal inmediato.)

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
- **La ejecución DOM real** la hace la extensión 2.4.1 (`flowConfigFn`) dentro
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

## 11. Clasificación honesta de fallos (V1.1 — §7.1/H)

`fail()` etiqueta `exec_state` según la evidencia, JAMÁS por defecto:

| Error | exec_state | Cola |
|---|---|---|
| `CONFIG_*:` / `ASSET_INVALID:` | terminal del contrato | dead inmediato, sin adaptación |
| `FLOW_WATCHDOG_TIMEOUT:` (o legacy `watchdog:` / `timeout-local:`) | `FLOW_WATCHDOG_TIMEOUT` (LOCAL) | retry por attempts (2/2) |
| resto (evidencia de proveedor post-generación) | `PROVIDER_FAILURE` | retry por attempts + capa adaptación video dead |

`FLOW_WATCHDOG_TIMEOUT` es agotamiento del watchdog LOCAL sin evidencia
específica del proveedor — **jamás se convierte automáticamente en
PROVIDER_FAILURE** (CF-E2E-01/H: la DB decía PROVIDER_FAILURE mientras el
ledger honestamente decía A/LOCAL/LOW). El ledger de Flow Adaptation
clasifica el watchdog como **A / FLOW_WATCHDOG_TIMEOUT, causalidad LOCAL,
confidence LOW** (intacto).

## 12. Lo que el E2E real demostró y lo que NO (5s)

- **CF-E2E-01**: la configuración required NO verificada llegaba a
  Generate; corregido con el consentimiento obligatorio (§6.1). Ahora un
  spec 8.0/required con UI que solo expone 5s termina `CONFIG_UNSUPPORTED`
  o `CONFIG_UNVERIFIABLE` ANTES de Generate: sin espera de 15 min, sin
  watchdog, sin retry, sin adaptación, terminal bien clasificado.
- **Los 5s observados son capacidad observada de ESA sesión**, no una
  verdad universal del proveedor: NO hay regla "Flow=5s", NO hay conversión
  silenciosa 8s→5s, NO hay retiming/fallback sin política contractual
  explícita, NO se toca Creative Engine / Niche Blueprints / Production
  JSON para acomodar duraciones.
- El watchdog no determina por sí solo la causa raíz del proveedor (§11).
- El estado heredado de la sesión de Flow no cuenta como configuración
  válida cuando `allow_inherited_state=false` (§6).

## 13. Baterías

| Batería | Cubre | Checks |
|---|---|---|
| `test_execution_contract.py` | núcleo: spec sin invención, gate + v1.1 allow_inherited_state, validación ffprobe real, estados | 77 |
| `test_execution_transport.py` | §17-A transporte completo + migración DB | 54 |
| `test_flow_contract_states.py` | §17-C/D/E + §7.1: consent ALLOW/DENY, barrera, watchdog, TESTS 1-10 | 93 |
| `test_hands_contract.py` | HANDS: descubrimiento/control/gate/evidencia/sin-coordenadas | 55 |
| `test_flow_config_gate.py` | extensión 2.4.1: flowConfigFn DOM-only + cross-check + TEST 1/9 | 99 |

Suite canónica: **1831 checks · 34 baterías** (`tests/run_all.py`).
