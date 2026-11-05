"""
YOUTUBE AUTOMATION v2.0 — INT-090 · Biblioteca de Personajes y Blindaje
de Universos.

PROBLEMA QUE RESUELVE: los universos visuales se cruzan. Un proyecto con
Cocardo (cartoon animado) y Valeria (live-action real) al mismo tiempo
produce un video incoherente y desperdicia cuota de generación (Nano
Banana no puede renderizar a Valeria; Veo 3.1 no puede renderizar a
Cocardo).

FUENTE DE VERDAD (biblioteca en disco, versionada en el repo):

    backend/data/avatars/<id>/descripcion.json
    {
      "id": "cocardo",
      "nombre": "Cocardo",
      "universo": "animado",            # animado | real | hiper | neutro
      "modelo": "nano-banana-2.1",      # motor visual del universo
      "voz": "es-CO-GonzaloNeural",
      "incompatible_con": ["real", "hiper"],
      "flow_project_id": null,          # enlace a Google Flow (nativo)
      "flow_character_id": null
    }

REGLA DE ORO DE UNIVERSOS:
· Los avatares de la biblioteca definen las reglas POR UNIVERSO:
  «incompatible_con» se agrega en un mapa universo → universos prohibidos.
· Dos avatares conviven en un proyecto solo si NINGUNO de los dos prohíbe
  el universo del otro. Mismo universo: siempre compatible. Universo
  «neutro»: nunca entra en conflicto (no prohíbe a nadie y nadie lo
  prohíbe) — es la voz narradora sin rostro.
· El universo de un avatar de DB se resuelve: 1º campo explícito
  (columna «universo»), 2º match por slug del nombre contra la biblioteca
  («Cocardo 🐸» → cocardo → animado), 3º «neutro» (silencio honesto).
· La validación se hace en POST /api/projects ANTES de gastar recursos:
  avatares incompatibles → HTTP 400 con mensaje explicativo claro.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

import config
import database as db

log = logging.getLogger("universos")

# Biblioteca canónica en disco (binding por valor en import-time, igual
# que el resto de servicios — ver tests/conftest.py).
AVATARS_LIB = Path(config.DATA_DIR) / "avatars"

UNIVERSOS = ("animado", "real", "hiper", "neutro")


# ── carga de la biblioteca ────────────────────────────────────────────────
def _slug(text: str) -> str:
    """Slug ASCII estable («Cocardo 🐸» → «cocardo») — mismo espíritu que
    project_workspace.slugify pero sin dependencia del pipeline."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or ""


def biblioteca() -> dict[str, dict]:
    """Lee TODAS las descripciones de backend/data/avatars/*/descripcion.json.

    Lectura fresca en cada llamada (3 archivos JSON — coste despreciable)
    para que PATCH de flow-linking se refleje al instante. Los directorios
    rotos se saltan con warning, nunca rompen el catálogo."""
    out: dict[str, dict] = {}
    if not AVATARS_LIB.is_dir():
        return out
    for d in sorted(AVATARS_LIB.iterdir()):
        if not d.is_dir():
            continue  # los retratos runtime (*.png) viven al ras aquí
        f = d / "descripcion.json"
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — un JSON roto no mata la biblioteca
            log.warning("descripcion.json ilegible: %s", f)
            continue
        if not isinstance(data, dict) or not data.get("id"):
            continue
        data.setdefault("universo", "neutro")
        data.setdefault("incompatible_con", [])
        data.setdefault("flow_project_id", None)
        data.setdefault("flow_character_id", None)
        out[data["id"]] = data
    return out


def _reglas_universo() -> dict[str, set[str]]:
    """Mapa universo → set de universos prohibidos, agregado desde la
    biblioteca (la fuente de verdad la define cada personaje canónico)."""
    reglas: dict[str, set[str]] = {}
    for av in biblioteca().values():
        u = av.get("universo")
        if u not in UNIVERSOS:
            continue
        prohibidos = {str(x) for x in (av.get("incompatible_con") or [])}
        reglas.setdefault(u, set()).update(prohibidos)
    return reglas


# ── resolución de universo por avatar ─────────────────────────────────────
def universo_de(avatar: dict | None) -> str:
    """Universo de un avatar de DB: campo explícito → biblioteca (slug del
    nombre) → «neutro». Nunca lanza."""
    if not avatar:
        return "neutro"
    u = (avatar.get("universo") or "").strip().lower()
    if u in UNIVERSOS:
        return u
    bib = biblioteca().get(_slug(avatar.get("name") or ""))
    if bib:
        return bib.get("universo", "neutro")
    return "neutro"


def incompatibles(u1: str, u2: str) -> bool:
    """True si los universos u1 y u2 están en guerra (alguno prohíbe al
    otro). Mismo universo y «neutro» jamás entran en conflicto."""
    if not u1 or not u2 or u1 == u2 or u1 == "neutro" or u2 == "neutro":
        return False
    reglas = _reglas_universo()
    return u2 in reglas.get(u1, ()) or u1 in reglas.get(u2, ())


# ── validación de un proyecto (POST /api/projects) ────────────────────────
def conflictos_entre(avatar_ids: list[str]) -> list[str]:
    """Mensajes de conflicto explicativos entre los avatares asignados a un
    mismo proyecto. Lista vacía = compatible. Nunca lanza."""
    mensajes: list[str] = []
    vistos: list[tuple[str, str, str]] = []  # (id, nombre, universo)
    for aid in avatar_ids:
        try:
            av = db.get_avatar(str(aid))
        except Exception:  # noqa: BLE001 — DB caída: la validación es best-effort
            log.warning("universos: no se pudo leer avatar %s", aid, exc_info=True)
            av = None
        vistos.append((str(aid), (av or {}).get("name") or str(aid),
                       universo_de(av)))
    reglas = _reglas_universo()
    for i in range(len(vistos)):
        for j in range(i + 1, len(vistos)):
            aid_a, nom_a, u_a = vistos[i]
            aid_b, nom_b, u_b = vistos[j]
            if incompatibles(u_a, u_b):
                de_a = sorted(reglas.get(u_a, ()))
                de_b = sorted(reglas.get(u_b, ()))
                mensajes.append(
                    f"universos incompatibles: «{nom_a}» ({u_a}) no puede "
                    f"convivir con «{nom_b}» ({u_b}) en el mismo proyecto — "
                    f"{u_a} prohíbe {de_a}, {u_b} prohíbe {de_b}. Divide el "
                    f"video en dos proyectos (uno por universo).")
    return mensajes


def validar_compatibles(avatar_ids: list[str]) -> None:
    """Lanza ValueError con el mensaje explicativo si algún par de
    avatares del proyecto es incompatible. Llamar ANTES de gastar recursos."""
    if not avatar_ids:
        return
    mensajes = conflictos_entre(list(dict.fromkeys(avatar_ids)))
    if mensajes:
        raise ValueError(" · ".join(mensajes))


# ── enlace con Google Flow (personajes nativos) ───────────────────────────
def vincular_flow(lib_id: str, flow_project_id: str | None,
                  flow_character_id: str | None) -> dict:
    """Persiste flow_project_id / flow_character_id en la descripcion.json
    del personaje de la biblioteca (enlace directo con Flow). Devuelve la
    descripción actualizada. ValueError si el id no existe en la biblioteca."""
    bib = biblioteca()
    if lib_id not in bib:
        raise ValueError(f"«{lib_id}» no existe en la biblioteca "
                         f"({', '.join(sorted(bib)) or 'vacía'})")
    f = AVATARS_LIB / lib_id / "descripcion.json"
    data = bib[lib_id]
    if flow_project_id is not None:
        data["flow_project_id"] = str(flow_project_id).strip() or None
    if flow_character_id is not None:
        data["flow_character_id"] = str(flow_character_id).strip() or None
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    return data
