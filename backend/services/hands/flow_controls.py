"""
HANDS — Flow Control Adapter V1.0 (capa mecánica del Execution Contract).

HANDS es la capa mecánica de OBSERVE / CONTROL / VERIFY (no es cerebro
creativo): descubre qué controles expone Google Flow realmente, intenta
configurarlos SOLO vía DOM/accesibilidad/selectores semánticos (§16 del
mandato: jamás coordenadas, jamás tabs[0], jamás títulos como mecanismo),
relee el estado tras cada cambio y verifica. Sobre esta evidencia decide el
gate: generar SOLO con controles required VERIFIED.

Integra los contratos V1.0 existentes sin reemplazarlos:
  - contracts.py  → TargetSpec/Observation/OperationResult/State/ErrorCode
  - verification.py → disciplina PASS/FAIL/UNKNOWN (UNKNOWN jamás pasa)
  - evidence.py   → registro hasheado con refs={"job_id": ...} (§12: evidencia
                    asociada a job_id/attempt, jamás mezclada entre intentos)
  - identify.py   → TargetResolver (jerarquía semántico→a11y→texto→DOM;
                    coordenadas vetadas por defecto)

Resultados de cada operación de control (§8 del mandato):
    SUPPORTED | UNSUPPORTED | UNVERIFIABLE | MISMATCH | VERIFIED

Regla crítica (§6): si el spec pide 8s y Flow muestra 5s, NO SE GENERA —
o se configura a 8s y se verifica 8s, o el gate declara CONFIG_MISMATCH /
CONFIG_UNSUPPORTED / CONFIG_UNVERIFIABLE. Jamás se acepta en silencio el
estado heredado de la UI.

NO SE INVENTAN CAPACIDADES: si un control no aparece en la observación,
su capability es available=False/editable=False/verifiable=False/observed=None
con la evidencia de la observación que lo demuestra.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

# Reexporta los veredictos del contrato para un único vocabulario
from services.execution_contract import (  # noqa: F401
    ALLOW_GENERATE, CONFIG_MISMATCH, CONFIG_UNVERIFIABLE, CONFIG_UNSUPPORTED,
    MISMATCH, SUPPORTED, UNSUPPORTED, UNVERIFIABLE, VERIFIED,
)


class ControlVerdict(str, Enum):
    """Veredicto de una operación de control (§8)."""
    SUPPORTED = SUPPORTED
    UNSUPPORTED = UNSUPPORTED
    UNVERIFIABLE = UNVERIFIABLE
    MISMATCH = MISMATCH
    VERIFIED = VERIFIED


# Controles conocidos por el adaptador (orden del gate).
CONTROLS = ("duration", "model", "aspect_ratio", "outputs", "audio",
            "resolution", "references")


@dataclass
class Capabilities:
    """Descubrimiento real de capacidades (§7). Por control:
    available/editable/verifiable/observed + source (de dónde se leyó) y
    evidence (referencia a la observación). Nada inventado: lo no observado
    es False/None."""
    controls: dict[str, dict] = field(default_factory=dict)

    def set(self, control: str, *, available: bool, editable: bool,
            verifiable: bool, observed: Any = None, source: str = "",
            evidence: dict | None = None) -> None:
        self.controls[control] = {
            "available": bool(available),
            "editable": bool(editable),
            "verifiable": bool(verifiable),
            "observed": observed,
            "source": source,
            "evidence": evidence or {},
        }

    def of(self, control: str) -> dict:
        return self.controls.get(control) or {
            "available": False, "editable": False, "verifiable": False,
            "observed": None, "source": "not_observed", "evidence": {},
        }

    def to_dict(self) -> dict:
        return {c: self.of(c) for c in CONTROLS if c in self.controls} or \
               dict(self.controls)


@dataclass
class ControlResult:
    """Resultado estructurado de intentar leer/configurar/verificar un control.
    requested (lo que el spec pide), observed_before/after (lo que Flow
    mostraba), verdict (ControlVerdict) y evidencia cruda. La evidencia NO se
    interpreta aquí: viaja cruda para el ledger/contract_result.

    configured [execution-contract v1.1] §7.1: True SOLO si la configuración
    la puso ESTA ejecución (set + relectura propios). Un valor heredado de la
    sesión (ya seleccionado antes de llegar) NO cuenta con
    allow_inherited_state=false — el gate de execution_contract lo trata como
    UNVERIFIABLE (CF-E2E-01, TEST 9 del mandato)."""
    control: str
    verdict: str
    requested: Any = None
    observed_before: Any = None
    observed_after: Any = None
    detail: str = ""
    evidence: dict = field(default_factory=dict)
    configured: bool = False

    def to_dict(self) -> dict:
        return {
            "control": self.control, "verdict": self.verdict,
            "requested": self.requested,
            "observed_before": self.observed_before,
            "observed_after": self.observed_after,
            "detail": self.detail, "evidence": self.evidence,
            "configured": self.configured,
        }


@runtime_checkable
class FlowControlAdapter(Protocol):
    """Abstracción limpia de los controles de Flow (§8 del mandato).

    Toda operación termina en SUPPORTED/UNSUPPORTED/UNVERIFIABLE/MISMATCH/
    VERIFIED. Ninguna asume que el control existe. Ninguna usa coordenadas:
    la implementación real (extensión, vía DOM) resuelve por
    semántico/accesibilidad/texto/roles con el resolver determinista actual.
    """

    def discover(self) -> Capabilities: ...

    def read_state(self) -> dict: ...

    def set_duration(self, value: Any) -> ControlResult: ...

    def set_model(self, value: Any) -> ControlResult: ...

    def set_aspect_ratio(self, value: Any) -> ControlResult: ...

    def set_outputs(self, value: Any) -> ControlResult: ...

    def set_audio(self, value: Any) -> ControlResult: ...

    def set_resolution(self, value: Any) -> ControlResult: ...

    def verify(self) -> dict: ...


class MockFlowControlAdapter:
    """Adaptador determinista de pruebas: modela una UI de Flow con controles
    reales (duration con opciones, aspect_ratio, model, resolution, outputs,
    audio). Configurable para escenarios de caos:
      - missing: controles que NO existen en la UI → UNSUPPORTED
      - frozen:  controles que aceptan el click pero NO cambian → MISMATCH
      - stale_read: releer devuelve el valor viejo → UNVERIFIABLE/MISMATCH
    Sin números mágicos de UI: cada control guarda observed (valor actual) y
    options (valores aceptables)."""

    def __init__(self, *, state: dict | None = None,
                 options: dict | None = None,
                 missing: tuple = (), frozen: tuple = (),
                 stale_read: tuple = (), clock=None):
        self.state: dict[str, Any] = dict({
            "duration": "5s", "aspect_ratio": "9:16", "model": None,
            "outputs": "1", "audio": None, "resolution": None,
        })
        self.state.update(state or {})  # override selectivo (UI real: los
        # controles no mencionados SIGUEN existiendo — jamás desaparecen
        # por no citarlos)
        self.options: dict[str, list] = dict(options or {
            "duration": ["4s", "5s", "6s", "8s"],
            "aspect_ratio": ["16:9", "9:16", "1:1"],
            "model": ["veo-2", "veo-3"],
            "outputs": ["1", "2", "4"],
            "audio": ["on", "off"],
            "resolution": ["720p", "1080p"],
        })
        self.missing = set(missing)
        self.frozen = set(frozen)
        self.stale_read = set(stale_read)
        self.log: list[dict] = []
        self.clock = clock

    # ── observación (solo DOM semántico simulado) ────────────────────────
    def discover(self) -> Capabilities:
        caps = Capabilities()
        for control in CONTROLS[:-1]:  # references no es control de UI
            if control in self.missing or control not in self.state:
                caps.set(control, available=False, editable=False,
                         verifiable=False, observed=None,
                         source="mock_discovery",
                         evidence={"reason": "control no presente en la UI"})
                continue
            caps.set(control, available=True,
                     editable=True,  # frozen ES editable: se clicka y no
                     # cambia → su veredicto es MISMATCH al releer (§8),
                     # no UNSUPPORTED (el control SÍ existe)
                     verifiable=control not in self.stale_read,
                     observed=self.state.get(control),
                     source="mock_discovery", evidence={"options":
                                                        self.options.get(control)})
        return caps

    def read_state(self) -> dict:
        return dict(self.state)

    # ── mecánica común: intentar → releer → verificar ────────────────────
    def _set(self, control: str, value: Any) -> ControlResult:
        before = self.state.get(control)
        self.log.append({"op": f"set_{control}", "requested": value,
                         "before": before})
        if control in self.missing or control not in self.options \
                or value is None:
            return ControlResult(
                control, UNSUPPORTED, requested=value, observed_before=before,
                detail="control no disponible en la UI",
                evidence={"scenario": "missing"})
        # El intento de cambio ocurre (click semántico simulado)…
        requested_txt = self._fmt(control, value)
        if requested_txt in [self._fmt(control, o) for o in
                             self.options.get(control, [])]:
            if control not in self.frozen:
                self.state[control] = requested_txt
        after = self._read_back(control)
        # [execution-contract v1.1] §7.1: TODO ControlResult que sale de _set
        # lleva configured=True — el set (+ relectura) de ESTA ejecución ES
        # configuración propia, aunque el valor ya estuviera seleccionado: el
        # gate distingue heredado (sin set) de verificado por nosotros.
        if after == requested_txt and requested_txt == self._fmt(control,
                                                                 before):
            # Ya estaba en el valor pedido y lo re-aplicamos/re-leyimos:
            # VERIFIED por configuración propia (set + relectura de esta
            # ejecución — §7.1; el heredado SIN set es cosa del gate).
            return ControlResult(control, VERIFIED, requested=value,
                                 observed_before=before, observed_after=after,
                                 detail="re-aplicado y verificado por relectura "
                                        "(configuración propia)",
                                 evidence={"re_read": True},
                                 configured=True)
        if after == requested_txt:
            return ControlResult(control, VERIFIED, requested=value,
                                 observed_before=before, observed_after=after,
                                 detail="cambiado y verificado por relectura",
                                 evidence={"re_read": True},
                                 configured=True)
        if control in self.stale_read or after is None:
            return ControlResult(control, UNVERIFIABLE, requested=value,
                                 observed_before=before, observed_after=after,
                                 detail="la relectura no devolvió el valor",
                                 evidence={"scenario": "stale_read"},
                                 configured=True)
        return ControlResult(control, MISMATCH, requested=value,
                             observed_before=before, observed_after=after,
                             detail=f"relectura={after!r} != pedido="
                                    f"{requested_txt!r}",
                             evidence={"scenario": "frozen_or_mismatch"},
                             configured=True)

    def _fmt(self, control: str, value: Any) -> Any:
        if control == "duration" and isinstance(value, (int, float)):
            return f"{int(value)}s"
        return value

    def _read_back(self, control: str):
        if control in self.stale_read:
            # La UI parece cambiar pero relee el valor viejo (§18: controles
            # que "parecen cambiar pero no cambian").
            return None
        return self.state.get(control)

    # ── API del Protocolo ────────────────────────────────────────────────
    def set_duration(self, value): return self._set("duration", value)

    def set_model(self, value): return self._set("model", value)

    def set_aspect_ratio(self, value): return self._set("aspect_ratio", value)

    def set_outputs(self, value): return self._set("outputs", value)

    def set_audio(self, value): return self._set("audio", value)

    def set_resolution(self, value): return self._set("resolution", value)

    def verify(self) -> dict:
        return {"state": self.read_state(),
                "source": "mock_flow_control_adapter"}


class ConfigGate:
    """Gate mecánico: spec + adapter → ALLOW_GENERATE o CONFIG_*.

    Recorre los controles del spec en orden; para cada control con
    requested no None:
      1. OBSERVE: capability desde adapter.discover()
      2. CONTROL: adapter.set_<control>(requested) (solo si editable)
      3. VERIFY: relectura + veredicto del ControlResult
    y delega la decisión final en execution_contract.config_gate (misma
    semántica backend/extensión/HANDS — un solo vocabulario).

    Evidencia: cada ControlResult se registra con refs={"job_id": job_id}
    cuando se aporta (§12). El gate JAMÁS toca el prompt (P1/P2 intactos).
    """

    _SETTERS = {"duration": "set_duration", "model": "set_model",
                "aspect_ratio": "set_aspect_ratio", "outputs": "set_outputs",
                "audio": "set_audio", "resolution": "set_resolution"}

    def __init__(self, adapter: FlowControlAdapter, evidence=None,
                 clock=None):
        self.adapter = adapter
        self.evidence = evidence  # EvidenceLayer opcional (hands)
        self.clock = clock

    def evaluate(self, spec: dict, *, job_id: str | None = None,
                 control_results: dict | None = None) -> dict:
        from services.execution_contract import config_gate as _decide
        caps = self.adapter.discover()
        results = dict(control_results or {})
        if not results:
            for control, setter in self._SETTERS.items():
                c = spec.get(control)
                if not isinstance(c, dict) or c.get("requested") is None:
                    continue
                # Controles verificados POST-transporte (outputs §13) o de
                # registro (audio §14): NO son controles pre-generación —
                # el gate no los sondea; config_gate los registra.
                metodo = ((spec.get("verification") or {}).get(control)
                          or {}).get("method")
                if metodo in ("transport", "register_only"):
                    continue
                if not caps.of(control).get("editable"):
                    results[control] = ControlResult(
                        control, UNSUPPORTED, requested=c.get("requested"),
                        observed_before=caps.of(control).get("observed"),
                        detail="control no editable según descubrimiento",
                        evidence={"capability": caps.of(control)})
                    self._record(results[control], job_id)
                    continue
                res = getattr(self.adapter, setter)(c.get("requested"))
                results[control] = res
                self._record(res, job_id)
        # El gate del contrato consume dicts (mismo vocabulario que la
        # extensión vía bridge): los ControlResult se serializan ANTES.
        results = {k: (v.to_dict() if isinstance(v, ControlResult) else v)
                   for k, v in results.items()}
        decision = _decide(spec, caps.to_dict(), results)
        # Evidencia del propio gate (acción de nivel superior).
        if self.evidence is not None:
            try:
                self.evidence.record(
                    "CONFIG_GATE", target=None,
                    expected_state={"decision": ALLOW_GENERATE},
                    observed_state={"decision": decision["decision"],
                                    "detail": decision["detail"]},
                    result="PASS" if decision["decision"] == ALLOW_GENERATE
                    else "FAIL",
                    refs={"job_id": job_id} if job_id else {},
                    operator="flow")
            except Exception:  # noqa: BLE001 — evidencia jamás rompe el gate
                pass
        out = dict(decision)
        out["capabilities"] = caps.to_dict()
        out["control_results"] = {
            k: (v.to_dict() if isinstance(v, ControlResult) else v)
            for k, v in out["control_results"].items()}
        return out

    def _record(self, res: ControlResult, job_id: str | None) -> None:
        if self.evidence is None:
            return
        try:
            self.evidence.record(
                f"SET_{res.control.upper()}", target=None,
                expected_state={"requested": res.requested},
                observed_state={"before": res.observed_before,
                                "after": res.observed_after,
                                "detail": res.detail,
                                "evidence": res.evidence},
                result="PASS" if res.verdict == VERIFIED else
                       ("FAIL" if res.verdict in (MISMATCH, UNSUPPORTED)
                        else "UNKNOWN"),
                refs={"job_id": job_id} if job_id else {},
                operator="flow")
        except Exception:  # noqa: BLE001 — evidencia jamás rompe el control
            pass
