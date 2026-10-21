"""
Scene Asset Resolver — Resolución determinista de referencias locales para Google Flow.

Responsabilidades puras:
1. Extraer referencias desde scene.meta.production_unit.references o scene.references.
2. Normalizar formatos soportados (dict con path/file/uri o strings de ruta).
3. Validar existencia y consistencia de archivos locales en disco.
4. Generar nombres de activo deterministas aptos para Google Flow ([a-zA-Z0-9_-]{1,24}).
5. Formatear la inyección de menciones @{asset_name} en el prompt.

Sin dependencias de Chrome, red ni llamadas MCP.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")


@dataclass(frozen=True)
class ResolvedAssetRef:
    source_index: int
    raw_reference: Any
    local_path: Path | None
    asset_name: str
    is_valid: bool
    is_required: bool = False
    skip_reason: str | None = None


def sanitize_asset_name(raw_name: str, fallback: str = "asset") -> str:
    """Normaliza un nombre para activo de Flow: alfanumérico + guiones, longitud 1..24."""
    cleaned = _SAFE_NAME_RE.sub("_", (raw_name or "").strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = fallback
    return cleaned[:24]


def extract_raw_references(scene: dict) -> list[Any]:
    """Extrae la lista de referencias desde los metadatos de la escena o su clave directa."""
    if not isinstance(scene, dict):
        return []
    meta = scene.get("meta") or {}
    punit = meta.get("production_unit") if isinstance(meta, dict) else {}
    if isinstance(punit, dict) and "references" in punit:
        refs = punit.get("references")
    else:
        refs = scene.get("references")
    if isinstance(refs, list):
        return refs
    if refs is not None and not isinstance(refs, (list, tuple)):
        return [refs]
    return []


def resolve_scene_references(scene: dict, project: dict | None = None) -> list[ResolvedAssetRef]:
    """
    Resuelve cada referencia declarada en la escena hacia un ResolvedAssetRef.
    Valida rutas locales y asigna nombres deterministas libres de colisión.
    """
    raw_list = extract_raw_references(scene)
    if not raw_list:
        return []

    resolved: list[ResolvedAssetRef] = []
    seen_names: set[str] = set()

    for idx, item in enumerate(raw_list):
        local_p: Path | None = None
        target_name: str = ""
        is_required: bool = False
        skip_reason: str | None = None

        if isinstance(item, str):
            candidate = item.strip()
            if candidate.startswith(("http://", "https://", "gs://")):
                skip_reason = "REMOTE_URL"
            else:
                local_p = Path(candidate)
                target_name = local_p.stem
        elif isinstance(item, dict):
            is_required = bool(item.get("required") or item.get("mandatory"))
            for key in ("local_path", "path", "filePath", "file", "uri"):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    if val.strip().startswith(("http://", "https://", "gs://")):
                        skip_reason = "REMOTE_URL"
                    else:
                        local_p = Path(val.strip())
                    break

            if item.get("name") and isinstance(item.get("name"), str):
                target_name = item["name"].strip()
            elif local_p:
                target_name = local_p.stem
            elif item.get("role") and isinstance(item.get("role"), str):
                target_name = item["role"].strip()

            if not local_p and not skip_reason and item.get("url"):
                skip_reason = "REMOTE_URL"
        else:
            skip_reason = "UNSUPPORTED_TYPE"

        # Validación del archivo en disco
        is_valid = False
        if local_p is not None and not skip_reason:
            try:
                resolved_path = local_p.resolve()
                if resolved_path.is_file() and resolved_path.stat().st_size > 0:
                    local_p = resolved_path
                    is_valid = True
                else:
                    skip_reason = "NOT_FOUND"
            except OSError:
                skip_reason = "NOT_FOUND"

        if not target_name:
            target_name = f"ref_{idx + 1}"

        clean_name = sanitize_asset_name(target_name, fallback=f"ref_{idx + 1}")
        # Desambiguación de colisiones en la misma escena
        unique_name = clean_name
        counter = 2
        while unique_name in seen_names:
            suffix = f"_{counter}"
            unique_name = f"{clean_name[:24 - len(suffix)]}{suffix}"
            counter += 1
        seen_names.add(unique_name)

        resolved.append(
            ResolvedAssetRef(
                source_index=idx,
                raw_reference=item,
                local_path=local_p,
                asset_name=unique_name,
                is_valid=is_valid,
                is_required=is_required,
                skip_reason=skip_reason,
            )
        )

    return resolved


def inject_flow_asset_mentions(prompt: str, ready_asset_names: list[str]) -> str:
    """
    Inyecta ordenadamente las menciones @{asset_name} en el prompt sin romper llaves
    ni alterar la creatividad original. Si ready_asset_names está vacío, devuelve el prompt original.
    """
    base_prompt = (prompt or "").strip()
    if not ready_asset_names:
        return base_prompt

    valid_names = [n.strip() for n in ready_asset_names if n and n.strip()]
    if not valid_names:
        return base_prompt

    if len(valid_names) == 1:
        mention_clause = f"Referencing @{{{valid_names[0]}}}:"
    elif len(valid_names) == 2:
        mention_clause = f"Referencing @{{{valid_names[0]}}} and @{{{valid_names[1]}}}:"
    else:
        formatted = ", ".join(f"@{{{name}}}" for name in valid_names[:-1])
        mention_clause = f"Referencing {formatted}, and @{{{valid_names[-1]}}}:"

    if base_prompt:
        return f"{mention_clause} {base_prompt}"
    return mention_clause
