"""
HANDS · Workspace aislado y frontera de filesystem (§18).

HANDS opera en un workspace PROPIO y separado de la producción:

    <root>/
      workspace/   — area de trabajo general de HANDS
      assets/      — assets de referencia que HANDS puede leer/copiar
      downloads/   — descargas (p.ej. resultados de Flow)
      exports/     — exportaciones producidas por HANDS
      tmp/         — temporales de operación
      evidence/    — evidencia (captures, hashes, JSONL por sesión)
      logs/        — audit trail y logs operacionales
      sessions/    — sesiones persistidas (auditables)

El acceso general al filesystem está PROHIBIDO (§18/§28): toda ruta usada por
una operación pasa por PathBoundary, que resuelve symlinks y exige que la
ruta caiga dentro de una de las raíces autorizadas — si escapa, DENY.

Por defecto el runtime usa backend/data/hands/ (gitignored): los artefactos
físicos jamás van al árbol versionado (Regla de Oro del repo).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import PermissionDeniedError, ValidationError

HANDS_SUBDIRS: tuple[str, ...] = (
    "workspace", "assets", "downloads", "exports", "tmp", "evidence", "logs", "sessions",
)


@dataclass
class HandsWorkspace:
    """Workspace aislado con separación explícita de áreas (§18)."""

    root: Path

    def __init__(self, root: str | Path, *, create: bool = True):
        self.root = Path(root).expanduser().resolve(strict=False)
        if create:
            self.ensure_layout()

    # ── layout ───────────────────────────────────────────────────────────
    def ensure_layout(self) -> None:
        for sub in HANDS_SUBDIRS:
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    @property
    def workspace(self) -> Path:
        return self.root / "workspace"

    @property
    def assets(self) -> Path:
        return self.root / "assets"

    @property
    def downloads(self) -> Path:
        return self.root / "downloads"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    @property
    def tmp(self) -> Path:
        return self.root / "tmp"

    @property
    def evidence(self) -> Path:
        return self.root / "evidence"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def sessions(self) -> Path:
        return self.root / "sessions"

    # ── rutas validadas ──────────────────────────────────────────────────
    def path_for(self, area: str, name: str) -> Path:
        """Ruta segura para un fichero del área pedida (nombre saneado).

        El nombre NO puede contener traversal ('..', separadores absolutos);
        puede contener un subdirectorio relativo simple ('sub/archivo.txt').
        """
        if area not in HANDS_SUBDIRS:
            raise ValidationError(f"área de workspace desconocida: \"{area}\"",
                                  details={"area": area, "valid": list(HANDS_SUBDIRS)})
        if not name or name.startswith(("/", "\\")) or ".." in Path(name).parts:
            raise ValidationError(f"nombre de fichero inseguro: \"{name}\"",
                                  details={"name": name})
        candidate = (self.root / area / name).resolve(strict=False)
        base = (self.root / area).resolve(strict=False)
        try:
            candidate.relative_to(base)
        except ValueError:
            raise PermissionDeniedError(
                f"la ruta escapa del área {area}", details={"path": str(candidate)})
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate

    def roots(self) -> list[str]:
        """Raíces que HANDS declara como filesystem autorizado (§17)."""
        return [str(self.root)]

    def summary(self) -> dict[str, Any]:
        return {"root": str(self.root),
                "areas": {sub: str(self.root / sub) for sub in HANDS_SUBDIRS}}


@dataclass
class PathBoundary:
    """Guardia de filesystem: resuelve symlinks y exige raíz autorizada (§28).

    resolve() sigue symlinks: si algún componente es un symlink que sale de
    la raíz, la ruta RESUELTA cae fuera y se deniega (escape cerrado).
    """

    roots: tuple[Path, ...]

    def __init__(self, roots: list[str] | tuple[str, ...] | Path):
        if isinstance(roots, (str, Path)):
            roots = [roots]
        if not roots:
            raise ValidationError("PathBoundary exige al menos una raíz")
        self.roots = tuple(Path(r).expanduser().resolve(strict=False) for r in roots)

    def resolve_within(self, path: str | Path, *, must_exist: bool = False) -> Path:
        """Devuelve la ruta resuelta si cae dentro de alguna raíz; si no, DENY."""
        try:
            resolved = Path(path).expanduser().resolve(strict=False)
        except OSError as exc:
            raise PermissionDeniedError(f"path no resoluble: {exc}",
                                        details={"path": str(path)})
        for root in self.roots:
            try:
                resolved.relative_to(root)
                break
            except ValueError:
                continue
        else:
            raise PermissionDeniedError(
                f"path fuera de la frontera del workspace: \"{resolved}\"",
                details={"path": str(resolved), "roots": [str(r) for r in self.roots]})
        if must_exist and not resolved.exists():
            raise PermissionDeniedError(
                f"path inexistente (must_exist): \"{resolved}\"",
                details={"path": str(resolved)})
        return resolved
