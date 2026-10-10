# HANDS V1.0 — Capa de Ejecución Física (AISLADA)

> **Estado de integración oficial (FASE 7): `PARTIAL CONNECTED: Execution
> Contract V1.0 contract layer (FlowOperator+ConfigGate+MockFlowControlAdapter
> TESTED; ExtensionBridgeDriver enabled=False por defecto; E2E real pendiente)`**
>
> HANDS se construyó AL LADO del sistema actual, no ENCIMA de él (§3 del brief).
> No importa nada del orquestador; nada del orquestador importa a HANDS.
> La conexión de la CAPA DE CONTRATO (Execution Contract V1.0) está hecha y
> TESTED sobre mocks (§9); la ejecución física real con Flow sigue pendiente
> (NOT_VERIFIED). La puerta completa está descrita en `future_integration.py`.

---

## 1. Filosofía (§5)

```text
YOUTUBE-AUTOMATION = WHAT  (qué historia, qué prompt, qué escena)
HANDS              = EXECUTION (ejecutar operaciones controladas)
FLOW OPERATOR      = HOW within Google Flow
DESKTOP OPERATOR   = HOW within Desktop
```

HANDS **no es un agente creativo**: no inventa prompts, historias, escenas,
personajes ni estilos. Recibe instrucciones operativas externas y las ejecuta
bajo permisos explícitos, con observación, verificación, evidencia y parada
segura. Un prompt vacío es rechazado (`ValidationError`) — la fuente creativa
sigue siendo el backend (`flow_export.build_script_json`).

---

## 2. Arquitectura

```text
FUTURA INTEGRACIÓN (NO CONECTADA — §37)
        │  HAND_REQUEST → [HandAdapter] → HAND_RESULT
        ▼
   HANDS CONTRACT (contracts.py)
        │
        ├── HandsRuntime (runtime.py) ── sesión + locks + kill switch + evidencia
        │        │
        │        ├── ActionEngine (action_engine.py)
        │        │     OBSERVE → IDENTIFY → ACTION → OBSERVE → VERIFY
        │        │
        │        ├── DesktopOperator (desktop.py)
        │        │     ├── MockDesktopBackend      (TESTED)
        │        │     └── PhysicalDesktopBackend  (NOT_VERIFIED, triple candado)
        │        │
        │        └── FlowOperator (flow_operator.py)
        │              ├── MockFlowDriver          (TESTED)
        │              └── ExtensionBridgeDriver   (contrato HTTP real, OFF)
        │
        ├── Permisos/Allowlists (permissions.py)   DENY BY DEFAULT (§16)
        ├── Workspace (workspace.py)               frontera fs (§18)
        ├── WaitEngine (waits.py)                  8 kinds, timeout obligatorio (§10)
        ├── VerificationEngine (verification.py)   PASS/FAIL/UNKNOWN + files (§12/§23)
        ├── RecoveryEngine (recovery.py)           presupuesto acotado (§24)
        ├── LockManager/FileLock (locks.py)        desktop/browser/flow (§20)
        ├── EvidenceLayer/AuditTrail (evidence.py) hashes + redacción (§21/§31/§32)
        ├── KillSwitch (killswitch.py)             parada segura (§27)
        ├── Sessions (sessions.py)                 auditables (§19)
        └── MockEnvironment (mocks.py)             todo simulado (§34)
```

Mapa de módulos (paquete `backend/services/hands/`):

| Componente del brief | Módulo |
|---|---|
| Runtime | `runtime.py` (`HandsRuntime`, `HandsConfig`) |
| Contracts | `contracts.py` (estados, errores, ops, acciones, targets, observación) |
| Desktop Operator | `desktop.py` |
| Flow Operator | `flow_operator.py` |
| Observation | `contracts.py` (`Observation`) + `observe()` de los backends |
| Target Identification | `identify.py` (`TargetResolver`) |
| Action Engine | `action_engine.py` |
| Wait Engine | `waits.py` |
| Verification | `verification.py` (+ file verification + captura) |
| Recovery | `recovery.py` |
| Permissions | `permissions.py` |
| Allowlists | `permissions.py` (`PermissionModel`, `Allowlists`, `CommandRule`) |
| Workspace | `workspace.py` |
| Sessions | `sessions.py` |
| Locks | `locks.py` |
| Evidence | `evidence.py` |
| Kill Switch | `killswitch.py` |
| Audit | `evidence.py` (`AuditTrail`) + `selfaudit.py` (§40) |
| Tests | `tests/test_hands*.py` (4 baterías, 267 checks) |
| Mocks | `mocks.py` + backends mock |
| Integración futura | `future_integration.py` |

---

## 3. Contratos clave

### 3.1 Estados (§11)

`IDLE · RUNNING · WAITING · COMPLETED · FAILED · TIMEOUT · BLOCKED · UNKNOWN · STOPPED`

Máquina de estados con transiciones explícitas. **`UNKNOWN` jamás transiciona
a `COMPLETED`** (primero re-observación → `RUNNING` → verificar). Una sesión
cerrada estando `UNKNOWN` queda `FAILED` honesta con conflicto registrado.

### 3.2 Taxonomía de errores (§29)

`VALIDATION_ERROR · PERMISSION_DENIED · TARGET_NOT_FOUND · TIMEOUT ·
ACTION_FAILED · VERIFICATION_FAILED · RECOVERY_FAILED · BLOCKED · UNKNOWN ·
STOPPED` — nunca un error genérico único. `PERMISSION_DENIED` deriva en
estado `BLOCKED` (§16: denegado no se intenta).

### 3.3 Operaciones (§6)

`Op`: OBSERVE, FOCUS, OPEN, CLOSE, CLICK, DOUBLE_CLICK, TYPE, PASTE, HOTKEY,
SCROLL, DRAG, WAIT, VERIFY, CAPTURE, DOWNLOAD, COPY, MOVE, RENAME,
EXECUTE_ALLOWED, STOP, RECOVER.
`FlowOp`: OPEN_FLOW, OPEN_PROJECT, SELECT_PROJECT, SET_PROMPT,
SET_CONFIGURATION, START_GENERATION, WAIT_GENERATION, DETECT_RESULT,
DOWNLOAD_RESULT, VERIFY_RESULT, REPORT_RESULT.

### 3.4 Modelo de acción (§7) y targets (§8)

Toda acción importante: `OBSERVE → IDENTIFY → ACTION → OBSERVE → VERIFY`.
El `ActionEngine` garantiza además: kill switch → permisos → idempotencia
(§26) → evidencia. Jerarquía de identificación: semántico → accessibility →
texto → DOM → visual → **coordenadas (último recurso, vetadas por política:
`allow_coordinate_fallback=False` por defecto)**.

### 3.5 Resultado de operación (§30)

`OperationResult`: `{operation_id, name, operator, status, result,
verification{expected, observed, verdict}, evidence_ids, errors, duration_ms,
started_at, finished_at}` — serializable y hasheado en evidencia.

---

## 4. Seguridad

* **Deny-by-default en 5 categorías** (§16/§17): application, domain,
  filesystem, command, browser. Sin allowlist declarada, TODO es `BLOCKED`.
* **Comandos**: binario exacto + prefijos de argv declarados
  (`CommandRule`). `allow_shell` es fijo `False` — HANDS jamás ejecuta shell.
* **Filesystem**: workspace aislado con 8 áreas (workspace/assets/downloads/
  exports/tmp/evidence/logs/sessions). `PathBoundary` resuelve symlinks y
  bloquea escapes (probado con symlink hacia fuera).
* **Secretos** (§32): redacción automática por patrones (api keys, bearer,
  JWT, cookies, passwords) en toda evidencia, error y audit entry.
* **Físico (§35)**: `PhysicalDesktopBackend` con triple candado —
  consentimiento explícito (`consent_token`), mapeo declarado op→argv
  (`command_map`) y allowlist de comandos. Sin executor inyectado
  explícitamente, nada toca el PC real.
* **Bridge (§37)**: `ExtensionBridgeDriver` deshabilitado por defecto;
  hablaría SOLO el contrato HTTP congelado del Flow Bridge existente
  (enqueue/status) — HANDS no compite por ser worker.

---

## 5. Operación

### 5.1 Uso canónico

```python
from services.hands import HandsRuntime

runtime = HandsRuntime({
    "workspace_root": "backend/data/hands",   # o ruta propia
    "permissions": {
        "applications": ["notepad-mock"],
        "domains": ["flow.google.com", "labs.google.com", "127.0.0.1"],
        "commands": [],
        "filesystem_roots": [],
        "browser_urls": ["https://flow.google.com/*"],
    },
})

with runtime.session(operator="desktop", locks=("desktop",)) as h:
    r = h.desktop.open_app("notepad-mock")          # ActionEngine §7 completo
    r = h.desktop.click(TargetSpec(semantic="notepad-mock.prompt_input"))
    r = h.desktop.type_text(target, "texto")
```

### 5.2 Sesiones y evidencia (§19/§21)

Cada `runtime.session(...)` abre `sessions/hands_<id>.json` (persistido al
abrir, en cada acción y al cerrar) y `evidence/evidence_<id>.jsonl` con
registros hasheados (SHA-256 del payload canónico y de ficheros
referenciados). Consulta posterior: `runtime.sessions.get(id)` y
`evidence.query(action=..., result=...)`.

### 5.3 Locks (§20)

Locks con nombre (`desktop`, `browser`, `flow`) con dueño y timeout:
ocupado ⇒ `BLOCKED`. Re-adquisición por el mismo dueño ⇒ error (doble claim).
`FileLock` añade coordinación cross-process con caducidad de dueño muerto.

### 5.4 Kill switch (§27)

`runtime.stop(reason)`: detiene acciones nuevas (check antes de cada paso),
cancela esperas en curso (`StoppedError`), detiene backends, libera locks,
preserva evidencia y cierra la sesión con `final_status=STOPPED`.

### 5.5 Recovery (§24) y timeouts (§25)

`RecoveryPolicy{max_retries, backoff_s, backoff_multiplier, retry_on}` —
presupuesto acotado (total = 1 + max_retries); errores no reintentables
(PERMISSION_DENIED, BLOCKED, STOPPED, VALIDATION_ERROR) se propagan sin
retry. Entre intentos: OBSERVE → WAIT(backoff) → VERIFY(precheck) → RECOVER.
Todos los timeouts viven en `TimeoutsConfig` (configurables, validados > 0).

---

## 6. CLI

```bash
cd yt_automation_v2
python3 -m services.hands info        # versión + estado de integración
python3 -m services.hands selfaudit   # auditoría automática §40
python3 -m services.hands cleanroom   # validación clean-room §42
```

---

## 7. Testing (§33/§34)

| Batería | Área | Checks |
|---|---|---|
| `tests/test_hands.py` | Núcleo: contratos, permisos, workspace, sesiones, locks, evidencia, waits, verificación, recovery, kill switch, identify, engine, runtime | 121 |
| `tests/test_hands_operators.py` | Operadores: desktop mock, físico con candados, flow operator, adaptador bridge (HTTP simulado), integración futura, self-audit, clean-room | 58 |
| `tests/test_hands_chaos.py` | Failure+chaos: timeouts, UI cambia, permisos, BLOCKED, recovery agotado, UNKNOWN, kill switch, fichero lento, descarga fallida, locks muertos | 33 |

Determinismo: `FakeClock` hace los timeouts instantáneos; `MockEnvironment`
simula desktop/browser/flow/files/processes sin PC real ni red.

---

## 8. Límites y capacidades NO verificadas (§43)

| Capacidad | Madurez |
|---|---|
| Contratos, permisos, workspace, sesiones, locks, evidencia, waits, verificación, recovery, kill switch, identificación, engine, runtime | **TESTED** (212 checks) |
| Desktop Operator sobre mock | **TESTED** |
| Flow Operator sobre driver mock | **TESTED** |
| Adaptador ExtensionBridgeDriver (protocolo HTTP) | **TESTED** contra servidor simulado con el contrato real |
| Adaptador ExtensionBridgeDriver contra backend REAL | **NOT_VERIFIED** — requiere backend vivo |
| PhysicalDesktopBackend sobre escritorio REAL | **NOT_VERIFIED** — requiere PC real + consentimiento + executor |
| Capturas de pantalla reales | **NOT_VERIFIED** (protocolo preparado; mock genera PNG de prueba) |
| Integración con YOUTUBE-AUTOMATION | **PARTIAL CONNECTED** (capa contrato Execution Contract V1.0 TESTED en mock, §9; E2E real pendiente) |

Nada se declara REAL_WORLD_VERIFIED: no ha habido ejecución física real.

---

## 9. Conexión Execution Contract V1.0 (FASE 7)

HANDS está CONECTADO a la tercera capa del contrato de ejecución
(`backend/services/execution_contract.py`, `schema_version="1.0"`) como su
capa mecánica OBSERVE/CONTROL/VERIFY. Estado: **capa de contrato TESTED en
mock; E2E con Flow real pendiente (NOT_VERIFIED)**.

### 9.1 Qué está conectado (y probado)

* **Contratos** (`contracts.py`): 8 `FlowOp` nuevos — `DISCOVER_CAPABILITIES`,
  `SET_MODEL`, `SET_DURATION`, `SET_ASPECT_RATIO`, `SET_OUTPUTS`, `SET_AUDIO`,
  `SET_RESOLUTION`, `VERIFY_CONTROLS` — todos categoría de permiso `domain`.
  Los 11 miembros legacy quedan intactos (contrato congelado).
* **Capa de controles** (`flow_controls.py`, ya existente): `ControlVerdict`,
  `Capabilities`, `ControlResult`, `FlowControlAdapter` (Protocol),
  `MockFlowControlAdapter` y `ConfigGate`. Veredictos únicos con el backend:
  `SUPPORTED/UNSUPPORTED/UNVERIFIABLE/MISMATCH/VERIFIED` y decisiones
  `ALLOW_GENERATE/CONFIG_UNSUPPORTED/CONFIG_UNVERIFIABLE/CONFIG_MISMATCH`.
* **FlowOperator** (`flow_operator.py`):
  - `controls_adapter` (kwarg opcional; si no, se hereda de
    `driver.controls_adapter` — `MockFlowDriver` lo construye siempre con
    parámetros todos opcionales `controls_state/missing/frozen/stale`);
  - `FlowJobSpec.execution_spec` (tercera capa; NUNCA edita el prompt P1 y
    NO viaja en `to_dict()` — transporte congelado);
  - `discover_capabilities()` — descubrimiento HONESTO: sin adaptador ⇒
    `FAILED` con `available=[]` (nada inventado);
  - `configure_from_spec(spec, job_id)` — `FlowOp.VERIFY_CONTROLS`: gate
    mecánico OBSERVE→CONTROL→VERIFY por control con
    `verification={expected: ALLOW_GENERATE, observed: decisión, verdict}`;
  - **GATE en `start_generation()`**: con `execution_spec` + adaptador el
    gate se evalúa SIEMPRE fresco ANTES de `driver.submit`; decisión ≠
    `ALLOW_GENERATE` ⇒ `FAILED` con `errors[0].code=VERIFICATION_FAILED`,
    `result={gate: decisión, refusado_por: "execution_contract",
    submitted: False}` y **sin submit** (la cola del driver queda intacta);
  - `set_configuration(params)`: con adaptador y `params["execution_spec"]`
    ejecuta el gate; sin spec o sin adaptador ⇒ comportamiento legacy exacto.
* **Evidencia (§12/§21)**: cada `SET_*`, `CONFIG_GATE`, `VERIFY_CONTROLS` y
  `START_GENERATION` queda registrado en la `EvidenceLayer` con
  `refs={"job_id": handle_key}` (correlación por job, jamás mezclada entre
  intentos). `CONFIG ≠ ADAPTACIÓN`: el gate jamás toca campos de prompt.
* **Puerta** (`future_integration.py`): `ExecutionContractHandAdapter`
  (HandAdapter real) ejecuta `flow.discover_capabilities`,
  `flow.configure_from_spec` y `flow.start_generation` contra un
  `FlowOperator` inyectado; devuelve un `HAND_RESULT` bien formado con
  `results=[OperationResult.to_dict()]`; operación desconocida ⇒
  `BlockedError` honesto. `NotConnectedAdapter` SIGUE siendo el default y su
  puerta propia permanece `NOT CONNECTED`.

`INTEGRATION_STATUS` (constante oficial única) pasó de `NOT CONNECTED` a:

```text
PARTIAL CONNECTED: Execution Contract V1.0 contract layer
(FlowOperator+ConfigGate+MockFlowControlAdapter TESTED;
ExtensionBridgeDriver enabled=False por defecto; E2E real pendiente)
```

### 9.2 Qué permanece honesto (NO verificado)

* **E2E real con Flow: NO PROBADO** — todo lo anterior está TESTED sobre
  `MockFlowControlAdapter`/`MockFlowDriver` (`tests/test_hands_contract.py`,
  55 checks). Ninguna capacidad "Flow real" se declara probada.
* `ExtensionBridgeDriver` sigue `enabled=False` POR DEFECTO (§37): hablar el
  contrato HTTP en vivo sigue siendo un paso pendiente del checklist.
* Sin adaptador de controles no hay gate ni configuración: se devuelve
  `FAILED` honesto con `available=[]` — HANDS no inventa capacidades.

### 9.3 Matriz de control (§21 del mandato — valores honestos)

| Control | Discover (capacidad) | Configure (SET_*) | Verify (relectura/gate) |
|---|---|---|---|
| Duration | mock **TESTED** · Flow real **NO PROBADO** | mock **TESTED** (`SET_DURATION`, opciones 4/5/6/8s) · Flow real **NO PROBADO** | mock **TESTED** (VERIFIED/UNSUPPORTED/UNVERIFIABLE/MISMATCH) · Flow real **NO PROBADO** (post: ffprobe ±tolerancia) |
| Model | mock **TESTED** · Flow real **NO PROBADO** | mock **TESTED** (`SET_MODEL`) · Flow real **NO PROBADO** | mock **TESTED** · Flow real **NO PROBADO** |
| Aspect ratio | mock **TESTED** · Flow real **NO PROBADO** | mock **TESTED** (`SET_ASPECT_RATIO`) · Flow real **NO PROBADO** | mock **TESTED** · Flow real **NO PROBADO** (post: ffprobe rel 2%) |
| Outputs | mock **TESTED** · Flow real **NO PROBADO** | registro por transporte (1 asset/job, §13) — el gate NO lo sondea | transporte: mock **TESTED** · Flow real **NO PROBADO** |
| Audio | mock **TESTED** · Flow real **NO PROBADO** | registro only (§14: observable, no exigible) | `register_only`: se REGISTRA, no bloquea · Flow real **NO PROBADO** |
| Resolution | mock **TESTED** · Flow real **NO PROBADO** | mock **TESTED** (`SET_RESOLUTION`) · Flow real **NO PROBADO** | mock **TESTED** · Flow real **NO PROBADO** |
| References | NO es control de UI ⇒ no inventado (transportado en spec) | no aplica (transportar ≠ ejecutar) | no aplica en pre-gate · Flow real **NO PROBADO** |

Vía de conexión real prevista: la capa DOM/a11y de la extensión implementa
`FlowControlAdapter` (semántico/accesibilidad/texto, §16 sin coordenadas) —
la mecanística ya está definida y probada en mock.
