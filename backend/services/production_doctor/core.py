"""
PRODUCTION DOCTOR V1.0 — núcleo: taxonomía de errores, Finding, Report
y AUDIT TRAIL persistente.

Filosofía (contrato del Doctor):
  DIAGNOSTICAR → EXPLICAR → REPARAR → VALIDAR.   Nunca ERROR → CAMBIO ARBITRARIO.

· Cada problema es un Finding medido con evidencia real (nada de suposiciones).
· Toda reparación se registra en data/doctor/audit_trail.jsonl con
  antes/después, motivo y test de validación (regla 10 del contrato).
· El Doctor NO modifica nunca contenido creativo (Production JSON, prompts,
  duration_target, continuidad): sus reparaciones viven en repairs.py y son
  una lista blanca cerrada de transformaciones deterministas.
· Si no puede determinar la causa → UNKNOWN + «HUMAN INVESTIGATION REQUIRED».
  Si el problema es de un servicio externo (Google Flow) →
  EXTERNAL_SERVICE_ERROR. Nunca disfraza un error real de PASS.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import config


# ── taxonomía (regla 5 del contrato) ─────────────────────────────────────────
class Clasificacion(str, Enum):
    BUG_CONFIRMED = "BUG_CONFIRMED"
    CONTRACT_VIOLATION = "CONTRACT_VIOLATION"
    DATA_ERROR = "DATA_ERROR"
    CONFIG_ERROR = "CONFIG_ERROR"
    ENVIRONMENT_ERROR = "ENVIRONMENT_ERROR"
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"
    TEST_FAILURE = "TEST_FAILURE"
    UNKNOWN = "UNKNOWN"


SEVERIDADES = ("critical", "error", "warn", "info")

CAPAS = {
    "A": "INPUT", "B": "ADAPTER", "C": "FLOW_EXPORT", "D": "FLOW_JOBS",
    "E": "EXTENSION", "F": "GOOGLE_FLOW", "G": "ASSET_VALIDATION",
    "H": "QA", "I": "RENDER",
}

# Componente → baterías herméticas que lo ejercitan (DOCTOR VERIFY, regla 7).
# Rutas relativas a la raíz del repo (mismo convenio que tests/run_all.py).
REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_POR_COMPONENTE = {
    "production_json": ["tests/test_production_json.py"],
    "adapter": ["tests/test_production_json.py"],
    "flow_export": ["tests/test_flow_contract_p1.py"],
    "flow_jobs": ["tests/test_flow_bridge.py", "tests/test_concurrencia.py"],
    "extension": ["tests/test_bridge_e2e.py"],
    "video_qa": ["tests/test_qa_forensics.py"],
    "orchestrator": ["tests/test_lanzar_preflight.py"],
    "doctor": ["tests/test_production_doctor.py",
               "tests/test_doctor_preflight.py"],
}


def doctor_dir() -> Path:
    """Carpeta del Doctor bajo data/ (audit trail + último informe)."""
    d = Path(config.DATA_DIR) / "doctor"
    return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Finding (regla 5: cada problema con sus campos obligatorios) ─────────────
@dataclass
class Finding:
    id: str                       # p.ej. DOC-D-LEASE-VENCIDO#proj_abc
    capa: str                     # A..I / ENV (clave de CAPAS)
    componente: str               # p.ej. flow_jobs, production_json, manifest
    titulo: str
    clasificacion: str            # Clasificacion.*.value
    severidad: str                # critical|error|warn|info
    evidencia: dict               # hechos medidos, nunca suposiciones
    causa_probable: str
    reparacion_disponible: bool = False
    reparacion_accion: str | None = None      # id en repairs.SAFE_REPAIRS
    validacion_requerida: list[str] = field(default_factory=list)
    reparado: bool = False
    detalle_reparacion: str | None = None
    requiere_humano: bool = False             # UNKNOWN → human investigation

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def finding(cid: str, capa: str, componente: str, titulo: str,
            clasificacion: Clasificacion | str, severidad: str,
            evidencia: dict, causa_probable: str,
            reparacion: str | None = None,
            validacion: list[str] | None = None) -> Finding:
    """Constructor canónico: marca reparacion_disponible según la lista blanca
    y exige severidad válida (defensa contra clasificaciones inventadas)."""
    if severidad not in SEVERIDADES:
        raise ValueError(f"severidad inválida: {severidad}")
    cls = clasificacion.value if isinstance(clasificacion, Clasificacion) \
        else str(clasificacion)
    return Finding(
        id=cid, capa=capa, componente=componente, titulo=titulo,
        clasificacion=cls, severidad=severidad, evidencia=evidencia,
        causa_probable=causa_probable,
        reparacion_disponible=bool(reparacion), reparacion_accion=reparacion,
        validacion_requerida=list(validacion or []),
        requiere_humano=(cls == Clasificacion.UNKNOWN.value))


# ── audit trail (regla 10) ───────────────────────────────────────────────────
class AuditTrail:
    """Registro append-only de reparaciones en data/doctor/audit_trail.jsonl.

    Cada línea: timestamp, finding_id, diagnostico, archivo_afectado,
    funcion_afectada, cambio, motivo, test_ejecutado, resultado_antes,
    resultado_despues. Nunca se reescribe (solo append)."""

    def __init__(self, base_dir: Path | None = None):
        self.dir = Path(base_dir) if base_dir else doctor_dir()
        self.path = self.dir / "audit_trail.jsonl"

    def append(self, *, finding_id: str, diagnostico: str,
               archivo_afectado: str, funcion_afectada: str, cambio: str,
               motivo: str, test_ejecutado: str, resultado_antes: str,
               resultado_despues: str, modo: str = "fix") -> dict:
        entry = {
            "timestamp": _now_iso(),
            "finding_id": finding_id,
            "diagnostico": diagnostico,
            "archivo_afectado": archivo_afectado,
            "funcion_afectada": funcion_afectada,
            "cambio": cambio,
            "motivo": motivo,
            "test_ejecutado": test_ejecutado,
            "resultado_antes": resultado_antes,
            "resultado_despues": resultado_despues,
            "modo": modo,
        }
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # línea dañada no tumba la lectura del trail
        return out


# ── resumen y reporte ────────────────────────────────────────────────────────
def resumen_de(findings: list[Finding]) -> dict:
    """Conteos por clasificación / capa / severidad + repartos clave."""
    por_cls: dict[str, int] = {}
    por_capa: dict[str, int] = {}
    por_sev: dict[str, int] = {}
    reparables = 0
    for f in findings:
        por_cls[f.clasificacion] = por_cls.get(f.clasificacion, 0) + 1
        por_capa[f.capa] = por_capa.get(f.capa, 0) + 1
        por_sev[f.severidad] = por_sev.get(f.severidad, 0) + 1
        if f.reparacion_disponible and not f.reparado:
            reparables += 1
    return {
        "total": len(findings),
        "por_clasificacion": por_cls,
        "por_capa": por_capa,
        "por_severidad": por_sev,
        "reparables_pendientes": reparables,
        "requieren_humano": sum(1 for f in findings if f.requiere_humano),
    }


@dataclass
class DoctorReport:
    """Resultado de un modo del Doctor (audit/fix/verify/report/preflight)."""
    modo: str
    ts: str
    findings: list[Finding] = field(default_factory=list)
    acciones: list[dict] = field(default_factory=list)   # audit trail aplicado
    verify: dict | None = None
    resumen: dict = field(default_factory=dict)
    duracion_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "doctor": "PRODUCTION DOCTOR",
            "version": "1.0",
            "modo": self.modo,
            "ts": self.ts,
            "duracion_s": round(self.duracion_s, 2),
            "resumen": self.resumen or resumen_de(self.findings),
            "findings": [f.to_dict() for f in self.findings],
            "acciones": self.acciones,
            "verify": self.verify,
        }

    def guardar(self) -> Path:
        """Persiste el informe como último reporte (REPORT lo lee)."""
        d = doctor_dir()
        d.mkdir(parents=True, exist_ok=True)
        out = d / "last_report.json"
        out.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1),
                       encoding="utf-8")
        return out


def cargar_ultimo_reporte() -> dict | None:
    p = doctor_dir() / "last_report.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None


class Crono:
    """Cronómetro mínimo para duracion_s del reporte."""

    def __enter__(self):
        self.t0 = time.monotonic()
        return self

    def __exit__(self, *exc):
        self.s = time.monotonic() - self.t0
