"""
HANDS · Modelo de permisos y allowlists (§16-§17).

REGLA ABSOLUTA: DENY BY DEFAULT.
Si una acción no está expresamente autorizada en la allowlist de su categoría,
el veredicto es DENY y la operación queda BLOCKED — nunca se intenta "a ver
si sale" (§16: no intentar automáticamente).

Categorías (§16):
  application — aplicaciones que HANDS puede abrir/cerrar/enfocar
  domain      — dominios de red/navegación autorizados (Flow, backend propio)
  filesystem  — raíces de filesystem dentro de las que HANDS opera
  command     — comandos/binarios ejecutables, con prefijos de argv permitidos
  browser     — prefijos de URL sobre los que se permiten acciones de navegador

Las allowlists son DATOS declarados por el configurador (§17: no hardcodear
permisos peligrosos); se serializan a dict para sesiones/auditoría (con la
misma estructura que se puede volcar a config JSON).
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .contracts import PermissionDeniedError


# ── categorías canónicas ─────────────────────────────────────────────────
APPLICATION = "application"
DOMAIN = "domain"
FILESYSTEM = "filesystem"
COMMAND = "command"
BROWSER = "browser"
CATEGORIES = (APPLICATION, DOMAIN, FILESYSTEM, COMMAND, BROWSER)


@dataclass
class PermissionDecision:
    """Veredicto explícito de una comprobación de permisos."""
    allowed: bool
    category: str
    reason: str
    rule: str | None = None       # regla de allowlist que autorizó (auditoría)

    @property
    def denied(self) -> bool:
        return not self.allowed

    def to_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "category": self.category,
                "reason": self.reason, "rule": self.rule}


def _allow(category: str, rule: str | None, why: str = "autorizado en allowlist") -> PermissionDecision:
    return PermissionDecision(True, category, why, rule)


def _deny(category: str, reason: str) -> PermissionDeniedError | PermissionDecision:
    """Devuelve decisión DENY (nunca lanza: el motor decide qué hacer)."""
    return PermissionDecision(False, category, reason, None)


@dataclass
class CommandRule:
    """Regla de allowlist de comandos (§17): binario + prefijos de argv.

    Ej.: CommandRule("ffmpeg", allowed_prefixes=("-version",), allow_no_args=True)
    · argv[0] debe coincidir EXACTAMENTE con el binario declarado.
    · argv[1:] debe empezar por alguno de allowed_prefixes (si se declara).
    · allow_no_args=True permite invocarlo sin argumentos.
    Nunca se ejecuta vía shell (sin shell=True jamás).
    """
    binary: str
    allowed_prefixes: tuple[tuple[str, ...], ...] = ()
    allow_no_args: bool = False
    description: str = ""

    def matches(self, argv: list[str]) -> bool:
        if not argv:
            return False
        if argv[0] != self.binary:
            return False
        args = tuple(argv[1:])
        if not args:
            return self.allow_no_args
        for prefix in self.allowed_prefixes:
            if args[: len(prefix)] == prefix:
                return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {"binary": self.binary,
                "allowed_prefixes": [list(p) for p in self.allowed_prefixes],
                "allow_no_args": self.allow_no_args,
                "description": self.description}


@dataclass
class PermissionModel:
    """Permisos declarados — DENY BY DEFAULT en las 5 categorías.

    filesystem_root(s) definen las ÚNICAS raíces tocables (§18 workspace);
    los paths se resuelven (symlinks incluidos) y deben caer dentro de una
    raíz autorizada. browser_urls son prefijos (fnmatch sobre URL completa).
    """
    applications: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    filesystem_roots: tuple[str, ...] = ()
    commands: tuple[CommandRule, ...] = ()
    browser_urls: tuple[str, ...] = ()
    allow_shell: bool = False          # SIEMPRE False: no existe ejecución por shell
    extra: dict[str, Any] = field(default_factory=dict)

    # ── application ──────────────────────────────────────────────────────
    def check_application(self, name: str) -> PermissionDecision:
        cat = APPLICATION
        if not self.applications:
            return _deny(cat, f"deny-by-default: allowlist de aplicaciones vacía (\"{name}\")")
        for rule in self.applications:
            if fnmatch.fnmatchcase(name, rule):
                return _allow(cat, rule)
            # títulos de ventana contienen el nombre de la app
            # ("notepad-mock — Ventana principal" casa con "notepad-mock")
            if rule and rule.lower() in name.lower():
                return _allow(cat, rule)
        return _deny(cat, f"aplicación \"{name}\" no está en allowlist {list(self.applications)}")

    # ── domain ───────────────────────────────────────────────────────────
    def check_domain(self, url_or_host: str) -> PermissionDecision:
        cat = DOMAIN
        host = _host_of(url_or_host)
        if not host:
            return _deny(cat, f"URL/host no interpretable: \"{url_or_host}\"")
        if not self.domains:
            return _deny(cat, f"deny-by-default: allowlist de dominios vacía (\"{host}\")")
        for rule in self.domains:
            if host == rule or host.endswith("." + rule.lstrip(".")):
                return _allow(cat, rule)
        return _deny(cat, f"dominio \"{host}\" no está en allowlist {list(self.domains)}")

    # ── browser (URLs) ───────────────────────────────────────────────────
    def check_browser(self, url: str) -> PermissionDecision:
        cat = BROWSER
        if not self.browser_urls:
            return _deny(cat, f"deny-by-default: allowlist de navegador vacía (\"{url}\")")
        for pattern in self.browser_urls:
            if fnmatch.fnmatchcase(url, pattern):
                return _allow(cat, pattern)
        return _deny(cat, f"URL \"{url}\" no casa con allowlist de navegador {list(self.browser_urls)}")

    # ── filesystem ───────────────────────────────────────────────────────
    def check_path(self, path: str | Path) -> PermissionDecision:
        """El path (resuelto, symlinks seguidos) debe caer dentro de una raíz."""
        cat = FILESYSTEM
        if not self.filesystem_roots:
            return _deny(cat, "deny-by-default: sin raíces de filesystem autorizadas")
        try:
            resolved = Path(path).expanduser().resolve(strict=False)
        except OSError as exc:
            return _deny(cat, f"path no resoluble: {exc}")
        for root in self.filesystem_roots:
            root_resolved = Path(root).expanduser().resolve(strict=False)
            try:
                resolved.relative_to(root_resolved)
            except ValueError:
                continue
            return _allow(cat, str(root_resolved))
        return _deny(cat, f"path \"{resolved}\" fuera de las raíces autorizadas "
                          f"{[str(r) for r in self.filesystem_roots]}")

    # ── command ──────────────────────────────────────────────────────────
    def check_command(self, argv: list[str]) -> PermissionDecision:
        cat = COMMAND
        if self.allow_shell:
            # Inalcanzable por construcción: el dataclass lo fija a False.
            return _deny(cat, "shell está prohibido por diseño en HANDS")
        if not self.commands:
            return _deny(cat, "deny-by-default: allowlist de comandos vacía "
                              f"(\"{argv[:1]}\")")
        for rule in self.commands:
            if rule.matches(argv):
                return _allow(cat, rule.binary)
        return _deny(cat, f"comando {argv!r} no autorizado por allowlist "
                          f"{[r.binary for r in self.commands]}")

    # ── helpers ──────────────────────────────────────────────────────────
    def require(self, decision: PermissionDecision) -> PermissionDecision:
        """Lanza PermissionDeniedError si la decisión es DENY (§16: BLOCKED)."""
        if decision.allowed:
            return decision
        raise PermissionDeniedError(decision.reason,
                                    details={"category": decision.category})

    def to_dict(self) -> dict[str, Any]:
        """Serialización para sesiones/auditoría (sin secretos por diseño)."""
        return {
            "applications": list(self.applications),
            "domains": list(self.domains),
            "filesystem_roots": list(self.filesystem_roots),
            "commands": [c.to_dict() for c in self.commands],
            "browser_urls": list(self.browser_urls),
            "allow_shell": self.allow_shell,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PermissionModel":
        data = data or {}
        commands = tuple(
            c if isinstance(c, CommandRule) else CommandRule(
                binary=c["binary"],
                allowed_prefixes=tuple(tuple(p) for p in c.get("allowed_prefixes", ())),
                allow_no_args=bool(c.get("allow_no_args", False)),
                description=c.get("description", ""),
            )
            for c in data.get("commands", ())
        )
        return cls(
            applications=tuple(data.get("applications", ())),
            domains=tuple(data.get("domains", ())),
            filesystem_roots=tuple(data.get("filesystem_roots", ())),
            commands=commands,
            browser_urls=tuple(data.get("browser_urls", ())),
            allow_shell=bool(data.get("allow_shell", False)),
            extra=dict(data.get("extra", {})),
        )


def _host_of(url_or_host: str) -> str | None:
    """Extrae host de una URL o devuelve el propio host saneado."""
    if not url_or_host:
        return None
    if "://" in url_or_host:
        try:
            return (urlsplit(url_or_host).hostname or "").lower() or None
        except ValueError:
            return None
    candidate = url_or_host.strip().lower().rstrip("/")
    # sin esquema: solo aceptamos formas de host plausibles
    if any(ch in candidate for ch in (" ", "/")) or candidate.startswith("."):
        return None
    return candidate or None


# ── Allowlists explícitas (§17) — envoltorios semánticos sobre el modelo ──
@dataclass
class Allowlists:
    """Bundle declarativo de las 5 allowlists; compone el PermissionModel."""
    applications: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    filesystem_roots: list[str] = field(default_factory=list)
    commands: list[CommandRule] = field(default_factory=list)
    browser_urls: list[str] = field(default_factory=list)

    def to_model(self) -> PermissionModel:
        return PermissionModel(
            applications=tuple(self.applications),
            domains=tuple(self.domains),
            filesystem_roots=tuple(self.filesystem_roots),
            commands=tuple(self.commands),
            browser_urls=tuple(self.browser_urls),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "applications": list(self.applications),
            "domains": list(self.domains),
            "filesystem_roots": list(self.filesystem_roots),
            "commands": [c.to_dict() for c in self.commands],
            "browser_urls": list(self.browser_urls),
        }
