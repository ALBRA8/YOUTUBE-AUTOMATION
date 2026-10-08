"""
HANDS · Verificación, file verification y captura (§12, §22, §23).

* VerificationEngine — toda operación crítica define ACTION / EXPECTED /
  OBSERVED / VERDICT (§12). Veredictos: PASS · FAIL · UNKNOWN.
  DISCIPLINA (§11-§12): observación ausente o error inesperado en la
  comprobación ⇒ UNKNOWN (NUNCA PASS por defecto).

* verify_file — verificación de ficheros (§23): existence, path, size,
  timestamp, extension, hash opcional y validación de medios opcional por
  magic bytes (PNG/JPEG/WEBP/MP4/WEBM) — crítico para futuras descargas de
  Flow (un HTML de error disfrazado de .mp4 NO pasa).

* CaptureCapability (§22) — protocolo de captura preparado para
  screenshot/window/file/operation; NullCapture responde honestamente que
  la captura no está disponible. La evidencia NUNCA depende solo de
  screenshots: el estado estructurado es siempre la fuente primaria.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from .contracts import ValidationError
from .evidence import sha256_file


# ════════════════════════════════════════════════════════════════════════
# §12 · VERIFICATION ENGINE
# ════════════════════════════════════════════════════════════════════════
class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass
class VerificationResult:
    """ACTION / EXPECTED / OBSERVED / VERDICT (§12)."""
    verdict: Verdict
    expected: Any = None
    observed: Any = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.verdict is Verdict.PASS

    def to_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict.value,
                "expected": _jsonable(self.expected),
                "observed": _jsonable(self.observed),
                "details": _jsonable(self.details)}


def _jsonable(obj: Any) -> Any:
    """Convierte a JSON-able: to_dict, callables⇒etiqueta, resto tal cual."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if callable(obj):
        return f"<callable:{getattr(obj, '__name__', 'anon')}>"
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()
                if not callable(v)}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return str(obj)


class VerificationEngine:
    """Evalúa expected vs observed con disciplina UNKNOWN (§12).

    Formas de `expected` admitidas:
      * dict spec: {"kind": "file_exists", "path": ...}
                   {"kind": "state_equals", "value": ...}
                   {"kind": "window_is", "value": ...}
                   {"kind": "element_present", "target": {...}}
                   {"kind": "predicate", "name": ...}   (con fn=callable)
      * callable(observed) -> bool
    """

    def verify(self, expected: Any, observed: Any,
               *, fn: Callable[[Any], bool] | None = None) -> VerificationResult:
        # 1) callable directa
        if callable(expected) or fn is not None:
            predicate = fn or expected
            if observed is None:
                return VerificationResult(Verdict.UNKNOWN, expected="<callable>",
                                          observed=None,
                                          details={"reason": "observed ausente"})
            try:
                ok = bool(predicate(observed))
            except Exception as exc:              # noqa: BLE001 — error ⇒ UNKNOWN
                return VerificationResult(
                    Verdict.UNKNOWN, expected="<callable>", observed=observed,
                    details={"reason": f"predicate error: {type(exc).__name__}: {exc}"})
            return VerificationResult(Verdict.PASS if ok else Verdict.FAIL,
                                      expected="<callable>", observed=observed)

        # 2) spec por kind
        if isinstance(expected, dict) and "kind" in expected:
            kind = expected["kind"]
            try:
                ok, details = self._evaluate_kind(kind, expected, observed)
            except Exception as exc:              # noqa: BLE001 — error ⇒ UNKNOWN
                return VerificationResult(
                    Verdict.UNKNOWN, expected=expected, observed=observed,
                    details={"reason": f"verification error: "
                                       f"{type(exc).__name__}: {exc}"})
            return VerificationResult(Verdict.PASS if ok else Verdict.FAIL,
                                      expected=expected, observed=observed,
                                      details=details)

        # 3) igualdad simple
        if observed is None:
            return VerificationResult(Verdict.UNKNOWN, expected=expected,
                                      observed=None,
                                      details={"reason": "observed ausente"})
        ok = observed == expected
        return VerificationResult(Verdict.PASS if ok else Verdict.FAIL,
                                  expected=expected, observed=observed)

    # ── kinds ────────────────────────────────────────────────────────────
    def _evaluate_kind(self, kind: str, expected: dict[str, Any], observed: Any
                       ) -> tuple[bool, dict[str, Any]]:
        if kind == "file_exists":
            path = Path(expected["path"])
            return path.is_file(), {"path": str(path)}

        if kind == "state_equals":
            actual = getattr(observed, "state", None)
            if actual is None and isinstance(observed, dict):
                actual = observed.get("state")
            value = expected["value"]
            return actual == value, {"expected": value, "actual": actual}

        if kind == "window_is":
            actual = getattr(observed, "window", None)
            if actual is None and isinstance(observed, dict):
                actual = observed.get("window")
            value = expected["value"]
            return actual == value, {"expected": value, "actual": actual}

        if kind == "window_contains":
            actual = getattr(observed, "window", None)
            if actual is None and isinstance(observed, dict):
                actual = observed.get("window")
            value = expected["value"]
            return bool(actual) and str(value).lower() in str(actual).lower(), \
                {"expected_contains": value, "actual": actual}

        if kind == "element_value":
            finder = getattr(observed, "find_element", None)
            if finder is None:
                return False, {"reason": "observación sin elementos"}
            ref = expected.get("ref")
            expected_value = expected.get("value")

            def _by_ref(el) -> bool:
                return el.ref_id == ref

            el = finder(_by_ref) if ref else None
            if el is None:
                return False, {"reason": f"elemento {ref!r} no encontrado"}
            actual = (el.extra or {}).get("value")
            return actual == expected_value, {"ref": ref,
                                              "expected": expected_value,
                                              "actual": actual}

        if kind == "element_present":
            finder = getattr(observed, "find_element", None)
            if finder is None:
                return False, {"reason": "observación sin elementos"}
            field_name = expected.get("field", "semantic")
            value = expected.get("value")

            def _pred(el) -> bool:
                return getattr(el, field_name, None) == value

            el = finder(_pred)
            return el is not None, {"field": field_name, "value": value,
                                    "ref": el.ref_id if el else None}

        if kind == "predicate":
            fn = expected.get("fn")
            if not callable(fn):
                raise ValidationError("kind=predicate exige fn callable")
            return bool(fn(observed)), {"predicate": expected.get("name", "?")}

        raise ValidationError(f"kind de verificación desconocido: \"{kind}\"")


# ════════════════════════════════════════════════════════════════════════
# §23 · FILE VERIFICATION
# ════════════════════════════════════════════════════════════════════════
# magic bytes mínimos (sin dependencias): suficiente para rechazar un HTML
# de error guardado como .mp4 o un texto guardado como .png
_MEDIA_SIGNATURES: tuple[tuple[str, bytes], ...] = (
    ("png", b"\x89PNG\r\n\x1a\n"),
    ("jpeg", b"\xff\xd8\xff"),
    ("webp", b"RIFF"),                       # + "WEBP" en offset 8
    ("webm", b"\x1a\x45\xdf\xa3"),           # EBML
    # ("mp4", ...) — caja ftyp en offset 4, manejada aparte
)


def sniff_media_kind(path: str | Path) -> str | None:
    """Detecta el tipo de medio real por magic bytes (None si desconocido)."""
    p = Path(path)
    try:
        with p.open("rb") as fh:
            head = fh.read(16)
    except OSError:
        return None
    for kind, signature in _MEDIA_SIGNATURES:
        if head[: len(signature)] == signature:
            if kind == "webp" and head[8:12] != b"WEBP":
                continue
            return kind
    # MP4/quicktime: bytes 4-8 == 'ftyp'
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mp4"
    return None


@dataclass
class FileCheck:
    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class FileVerificationResult:
    path: str
    verdict: Verdict
    checks: list[FileCheck] = field(default_factory=list)
    sha256: str | None = None
    media_kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "verdict": self.verdict.value,
                "checks": [c.to_dict() for c in self.checks],
                "sha256": self.sha256, "media_kind": self.media_kind}


def verify_file(path: str | Path, *,
                must_exist: bool = True,
                min_size: int | None = None,
                max_size: int | None = None,
                extensions: tuple[str, ...] | None = None,
                modified_after: float | None = None,
                sha256_expected: str | None = None,
                media_kind: str | None = None) -> FileVerificationResult:
    """Verificación completa de un fichero (§23) — PASS/FAIL/UNKNOWN.

    unknowns: fichero inexistente cuando must_exist=False ⇒ UNKNOWN (no FAIL:
    puede ser legítimo que aún no exista — la disciplina §12 manda).
    """
    p = Path(path)
    checks: list[FileCheck] = []
    exists = p.is_file()
    digest: str | None = None
    kind: str | None = None

    if not exists:
        checks.append(FileCheck("existence", not must_exist,
                                "no existe" if must_exist else "aún no existe (permitido)"))
        verdict = Verdict.FAIL if must_exist else Verdict.UNKNOWN
        return FileVerificationResult(str(p), verdict, checks)

    checks.append(FileCheck("existence", True))
    checks.append(FileCheck("path", os.path.isabs(str(p)), str(p.resolve())))

    size = p.stat().st_size
    if min_size is not None:
        checks.append(FileCheck("min_size", size >= min_size, f"size={size}"))
    if max_size is not None:
        checks.append(FileCheck("max_size", size <= max_size, f"size={size}"))

    if extensions:
        ext = p.suffix.lower().lstrip(".")
        checks.append(FileCheck("extension", ext in {e.lstrip(".").lower() for e in extensions},
                                f".{ext}"))

    if modified_after is not None:
        mtime = p.stat().st_mtime
        checks.append(FileCheck("modified_after", mtime > modified_after,
                                f"mtime={mtime}"))

    if sha256_expected:
        digest = sha256_file(p)
        checks.append(FileCheck("sha256", digest == sha256_expected,
                                digest or "no legible"))

    if media_kind:
        kind = sniff_media_kind(p)
        checks.append(FileCheck("media_kind", kind == media_kind,
                                f"detected={kind}"))

    verdict = Verdict.PASS if all(c.passed for c in checks) else Verdict.FAIL
    return FileVerificationResult(str(p), verdict, checks, digest, kind)


# ════════════════════════════════════════════════════════════════════════
# §22 · CAPTURE
# ════════════════════════════════════════════════════════════════════════
@runtime_checkable
class CaptureCapability(Protocol):
    """Protocolo de captura (§22) — preparado, nunca exigido."""

    def screenshot(self) -> bytes | None: ...

    def window_state(self) -> dict[str, Any] | None: ...

    def file_state(self, path: str | Path) -> dict[str, Any] | None: ...

    def operation_reference(self, ref: str) -> dict[str, Any] | None: ...


class NullCapture:
    """Captura honestamente no disponible (entorno sin soporte)."""

    def screenshot(self) -> bytes | None:
        return None

    def window_state(self) -> dict[str, Any] | None:
        return None

    def file_state(self, path: str | Path) -> dict[str, Any] | None:
        p = Path(path)
        if not p.is_file():
            return None
        stat = p.stat()
        return {"path": str(p), "size": stat.st_size, "mtime": stat.st_mtime}

    def operation_reference(self, ref: str) -> dict[str, Any] | None:
        return {"ref": ref, "capture": "not_available"}
