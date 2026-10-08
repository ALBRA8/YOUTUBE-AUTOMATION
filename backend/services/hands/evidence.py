"""
HANDS · Evidencia, audit trail y redacción de secretos (§21, §31, §32).

* redact / redact_obj — scrub automático de secretos (API keys, tokens,
  passwords, cookies, Authorization). Toda evidencia, error y log pasa por
  aquí ANTES de persistirse (§32: nunca registrar secretos).
* EvidenceLayer — capa de evidencia append-only por sesión (JSONL):
  timestamp, session_id, operator, action, target, expected_state,
  observed_state, result, referencias (screenshot/fichero), hash SHA-256
  del payload y del fichero referenciado, error. Consultable después (§21).
* AuditTrail — log operacional append-only que permite reconstruir qué
  ocurrió, cuándo, quién, con qué objetivo, qué observó, qué hizo y qué
  resultado obtuvo (§31), siempre redactado.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .contracts import new_id, now_iso


# ════════════════════════════════════════════════════════════════════════
# §32 · REDACCIÓN DE SECRETOS
# ════════════════════════════════════════════════════════════════════════
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # esquemas explícitos clave=valor / json
    (re.compile(r"(?i)\b(api[_-]?key|apikey|token|secret|password|passwd|pwd|"
                r"authorization|cookie|session[_-]?id|bearer)\b(\s*[=:]\s*)(\S+)"),
     r"\1\2[REDACTED]"),
    # claves con formato conocido
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "[REDACTED]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"), "[REDACTED]"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), "[REDACTED]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED]"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{8,}"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[REDACTED-JWT]"),
)


def redact(text: str) -> str:
    """Sustituye secretos detectados en un texto por [REDACTED]."""
    if not isinstance(text, str):
        return text
    out = text
    for pattern, replacement in _SECRET_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def redact_obj(obj: Any) -> Any:
    """Redacción recursiva + conversión a JSON-able (to_dict si existe)."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {redact(str(k)): redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        seq = [redact_obj(v) for v in obj]
        return seq if isinstance(obj, list) else tuple(seq)
    if isinstance(obj, (bool, int, float)) or obj is None:
        return obj
    if hasattr(obj, "to_dict"):
        return redact_obj(obj.to_dict())
    return str(obj)


# ════════════════════════════════════════════════════════════════════════
# hashing util
# ════════════════════════════════════════════════════════════════════════
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: str | Path, *, chunk: int = 1 << 20) -> str | None:
    """SHA-256 de un fichero (None si no existe / no es legible)."""
    p = Path(path)
    if not p.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with p.open("rb") as fh:
            while True:
                block = fh.read(chunk)
                if not block:
                    break
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def canonical_json(obj: Any) -> str:
    """JSON canónico determinista para hashing de payloads."""
    return json.dumps(redact_obj(obj), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


# ════════════════════════════════════════════════════════════════════════
# §21 · EVIDENCE LAYER
# ════════════════════════════════════════════════════════════════════════
class EvidenceLayer:
    """Evidencia append-only por sesión (JSONL) + consultas posteriores.

    Cada registro lleva hash SHA-256 del propio payload canónico y, si se
    referencia un fichero, hash del fichero (§21). Persistencia atómica por
    línea (append + flush) para sobrevivir kills a mitad de sesión.
    """

    FIELDS = ("timestamp", "session_id", "operator", "action", "target",
              "expected_state", "observed_state", "result", "refs",
              "file_hash", "error", "hash", "evidence_id")

    def __init__(self, evidence_dir: str | Path, session_id: str,
                 operator: str = "desktop"):
        self.session_id = session_id
        self.operator = operator
        self.dir = Path(evidence_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"evidence_{session_id}.jsonl"
        self._count = 0

    # ── escritura ────────────────────────────────────────────────────────
    def record(self, action: str, *, target: Any = None,
               expected_state: Any = None, observed_state: Any = None,
               result: str = "UNKNOWN", refs: dict[str, Any] | None = None,
               error: Any = None, operator: str | None = None) -> dict[str, Any]:
        """Añade un registro de evidencia (redactado + hasheado)."""
        payload = {
            "timestamp": now_iso(),
            "session_id": self.session_id,
            "operator": operator or self.operator,
            "action": action,
            "target": target,
            "expected_state": expected_state,
            "observed_state": observed_state,
            "result": result,
            "refs": refs or {},
            "error": error,
        }
        file_hash = None
        ref_file = (refs or {}).get("file")
        if ref_file:
            file_hash = sha256_file(ref_file)
        rec = dict(payload)
        rec["file_hash"] = file_hash
        rec["hash"] = sha256_text(canonical_json(payload))
        rec["evidence_id"] = new_id("ev")
        line = json.dumps(redact_obj(rec), ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
        self._count += 1
        return rec

    # ── lectura/consulta ─────────────────────────────────────────────────
    def all_records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue          # línea corrupta tolerada (append-only honesto)
        return out

    def query(self, *, action: str | None = None, result: str | None = None,
              since: str | None = None) -> list[dict[str, Any]]:
        out = []
        for rec in self.all_records():
            if action and rec.get("action") != action:
                continue
            if result and rec.get("result") != result:
                continue
            if since and (rec.get("timestamp") or "") < since:
                continue
            out.append(rec)
        return out

    def manifest(self) -> dict[str, Any]:
        recs = self.all_records()
        return {
            "session_id": self.session_id,
            "path": str(self.path),
            "records": len(recs),
            "results": _count_by(recs, "result"),
            "actions": _count_by(recs, "action"),
            "sha256": sha256_file(self.path),
        }


def _count_by(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for rec in records:
        value = str(rec.get(key))
        out[value] = out.get(value, 0) + 1
    return out


# ════════════════════════════════════════════════════════════════════════
# §31 · AUDIT TRAIL
# ════════════════════════════════════════════════════════════════════════
class AuditTrail:
    """Log operacional append-only (JSONL redactado) para reconstrucción."""

    def __init__(self, logs_dir: str | Path, name: str = "audit_trail.jsonl"):
        self.dir = Path(logs_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / name

    def append(self, event: str, session_id: str | None = None,
               operator: str | None = None, **detail: Any) -> dict[str, Any]:
        entry = {
            "timestamp": now_iso(),
            "event": event,
            "session_id": session_id,
            "operator": operator,
            "detail": redact_obj(detail),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            fh.flush()
        return entry

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
