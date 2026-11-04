"""
YOUTUBE AUTOMATION v2.0 — INT-086 · Espacio de trabajo modular de proyecto.

Estructura canónica y limpia para CADA proyecto (inspirada en la
arquitectura de recursos de Sloth `resources/skills/`):

    backend/data/projects/<nicho>_<slug_titulo>_<id_corto>/
    ├── marca.json          # identidad de canal: nicho, tono, voz, cierre
    ├── fuentes/            # material base: referencias del producto/receta
    ├── guion/              # guion.md (narrativa) + guion.json (escenas)
    ├── voz/                # narracion.wav (+ narracion_master.wav), voz.json
    ├── clips/              # clips generados (Flow/Veo) y B-roll procesado
    ├── out/                # video_final.mp4 + contact_sheet.png
    └── portada.png         # miniatura YouTube / cover Shorts

RETROCOMPATIBILIDAD TRANSPARENTE con `data/output/<pid>` (almacén físico
del pipeline desde la v1): la carpeta legacy NO se mueve ni se renombra —
más de 20 puntos de escritura (tts_step, video, images, orchestrator,
flow_import…) y las verificaciones fail-closed de contención
(security.safe_project_output_dir, M5/A8 de INT-080) dependen de que el
almacén viva literalmente en OUTPUT_DIR/<pid>; un symlink en sentido
contrario rompería `.resolve()` de todas esas rutas.

Por eso el workspace actúa como VISTA ORGANIZADA CANÓNICA:
- marca.json, guion/guion.md y guion/guion.json son archivos REALES.
- los medios pesados se exponen con ENLACES RELATIVOS al almacén legacy
  (cero duplicación de gigas): voz/narracion.wav, voz/voz.json,
  clips/, out/video_final.mp4…
- las imágenes ligeras se COPIAN con su extensión correcta
  (out/contact_sheet.png ← contact_sheet.jpg, portada.png ← thumb.jpg).

El pipeline heredado sigue funcionando byte a byte igual; el dashboard, la
API y el usuario ganan la estructura limpia y la identidad de canal.
"""
import json
import logging
import os
import re
import shutil
import unicodedata
from pathlib import Path

import config
import database as db

log = logging.getLogger("project_workspace")

# subcarpetas estándar del workspace (contrato INT-086)
SUBDIRS = ("fuentes", "guion", "voz", "clips", "out")


# ── naming ────────────────────────────────────────────────────────────────
def slugify(text: str, maxlen: int = 40) -> str:
    """Slug ASCII estable: «¿Pastel de Choclo? 🍰» → «pastel-de-choclo»."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:maxlen].strip("-") or "video"


def workspace_name(project: dict) -> str:
    """<nicho>_<slug_titulo>_<id_corto> — legible y único (id corta)."""
    pid = str(project.get("id") or "")
    nicho = slugify(project.get("niche") or "general", 24)
    titulo = slugify(project.get("title") or "video", 40)
    return f"{nicho}_{titulo}_{pid[:8]}"


def legacy_dir(project: dict) -> Path:
    """Almacén físico legacy (output/<pid>) — nunca se mueve."""
    return Path(config.OUTPUT_DIR) / str(project.get("id") or "")


def workspace_path(project: dict) -> Path:
    """Ruta canónica del workspace: data/projects/<nicho>_<slug>_<id8>."""
    return Path(config.PROJECTS_DIR) / workspace_name(project)


# ── marca.json (identidad de canal, INT-086.3) ───────────────────────────
def marca_from_template(tpl: dict, project: dict | None = None) -> dict:
    """marca.json desde una plantilla de nicho (precedencia: proyecto)."""
    marca = dict((tpl or {}).get("marca") or {})
    marca["cierre"] = dict(marca.get("cierre") or {})
    if not marca.get("nicho"):
        marca["nicho"] = ((project or {}).get("niche")
                          or (tpl or {}).get("id", "").split("-")[0] or "general")
    return marca


def marca_from_project(project: dict) -> dict:
    """marca.json mínimo desde los campos del proyecto (sin plantilla)."""
    return {
        "nicho": (project or {}).get("niche") or "general",
        "nombre_canal": "",
        "tono": "",
        "idioma": "es",
        "voz_default": (project or {}).get("voice") or "",
        "cierre": {},
    }


def write_marca(ws: Path, marca: dict) -> dict:
    """Escribe marca.json (identidad persistente del canal/proyecto)."""
    ws = Path(ws)
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "marca.json").write_text(
        json.dumps(marca, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return marca


def read_marca(project: dict) -> dict:
    """Lee marca.json del workspace ({} si no existe)."""
    try:
        p = workspace_path(project) / "marca.json"
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — marca es best-effort, nunca fatal
        log.debug("marca.json ilegible para %s", project.get("id"))
    return {}


# ── creación y resolución ─────────────────────────────────────────────────
def create_workspace(project: dict, marca: dict | None = None) -> Path:
    """Crea la estructura estándar del proyecto y su marca.json.

    Idempotente: si el workspace ya existe solo garantiza subcarpetas y
    marca. Devuelve la ruta del workspace."""
    ws = workspace_path(project)
    ws.mkdir(parents=True, exist_ok=True)
    for sub in SUBDIRS:
        (ws / sub).mkdir(exist_ok=True)
    if marca is None:
        marca = read_marca(project) or marca_from_project(project)
    if marca:
        try:
            write_marca(ws, marca)
        except Exception:  # noqa: BLE001
            log.warning("marca.json no escribible en %s", ws, exc_info=True)
    return ws


def resolve_workspace(project: dict) -> Path:
    """Ruta de trabajo REAL del proyecto.

    · Proyecto nuevo con workspace → data/projects/<nombre>/.
    · Proyecto legacy (solo output/<pid>) → su almacén físico, intacto."""
    ws = workspace_path(project)
    if ws.is_dir():
        return ws
    return legacy_dir(project)


def purge_workspace(project: dict) -> None:
    """Elimina la vista organizada (al borrar el proyecto). Los enlaces se
    desligan, NUNCA se sigue: el almacén legacy se borra por su cuenta vía
    security.safe_project_output_dir en DELETE /api/projects/{pid}."""
    try:
        shutil.rmtree(workspace_path(project), ignore_errors=True)
    except Exception:  # noqa: BLE001
        log.debug("workspace no purgable para %s", project.get("id"))


# ── publicación de artefactos (vista organizada) ─────────────────────────
def _link(target: Path, link_path: Path) -> bool:
    """Enlace RELATIVO link_path → target (idempotente, sin follow)."""
    try:
        if link_path.is_symlink():
            link_path.unlink()
        elif link_path.exists():
            return False  # archivo real del usuario: no se toca
        target = Path(target)
        if not target.exists():
            return False
        link_path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.relpath(target, link_path.parent), link_path)
        return True
    except Exception:  # noqa: BLE001
        log.debug("enlace fallido %s → %s", link_path, target, exc_info=True)
        return False


def _copy(src: Path, dst: Path) -> bool:
    """Copia ligera con extensión canónica (idempotente por mtime)."""
    try:
        src, dst = Path(src), Path(dst)
        if not src.is_file():
            return False
        if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
            return True
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except Exception:  # noqa: BLE001
        log.debug("copia fallida %s → %s", src, dst, exc_info=True)
        return False


def _guion_md(scenes: list[dict], project: dict) -> str:
    lines = [f"# {project.get('title') or 'Guion'}",
             ""]
    for sc in scenes:
        lines.append(f"## Escena {sc.get('idx', 0) + 1} — {sc.get('title') or ''}")
        lines.append("")
        lines.append(str(sc.get("narration") or "").strip())
        lines.append("")
    return "\n".join(lines)


def sync_artifacts(project: dict) -> dict:
    """Publica los artefactos canónicos del proyecto en su workspace.

    Se invoca tras los pasos clave del pipeline (guion, voz, render) y es
    BEST-EFFORT: nunca lanza, nunca toca el almacén legacy. Devuelve el
    mapa {ruta_relativa: destino} de lo publicado en esta pasada."""
    pid = str(project.get("id") or "")
    legacy = legacy_dir(project)
    published: dict[str, str] = {}
    try:
        ws = create_workspace(project)
        meta = project.get("meta") or {}

        # guion — archivos REALES generados desde BD (fuente de verdad);
        # vive FUERA del guard de legacy: el guion no depende del almacén.
        try:
            scenes = db.get_scenes(pid)
        except Exception:  # noqa: BLE001
            scenes = []
        if scenes:
            (ws / "guion" / "guion.md").write_text(
                _guion_md(scenes, project), encoding="utf-8")
            published["guion/guion.md"] = f"{len(scenes)} escenas"
            (ws / "guion" / "guion.json").write_text(
                json.dumps(scenes, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8")
            published["guion/guion.json"] = f"{len(scenes)} escenas"
        elif meta.get("script_text"):
            (ws / "guion" / "guion.md").write_text(
                str(meta["script_text"]), encoding="utf-8")
            published["guion/guion.md"] = "script_text"

        # medios pesados — enlaces relativos AL almacén legacy (si existe)
        if legacy.is_dir():
            # voz — enlaces relativos al almacén (voice_full.wav, words.json)
            if _link(legacy / "voice_full.wav", ws / "voz" / "narracion.wav"):
                published["voz/narracion.wav"] = "enlace → voice_full.wav"
            for master in sorted(legacy.glob("*master*.wav"))[:1]:
                if _link(master, ws / "voz" / "narracion_master.wav"):
                    published["voz/narracion_master.wav"] = f"enlace → {master.name}"
            if _link(legacy / "words.json", ws / "voz" / "voz.json"):
                published["voz/voz.json"] = "enlace → words.json"
            if _link(legacy / "audio_master.json", ws / "voz" / "audio_master.json"):
                published["voz/audio_master.json"] = "enlace → audio_master.json"

            # clips — directorio entero del pipeline (clips Flow/Veo + B-roll)
            clips_legacy = legacy / "clips"
            clips_ws = ws / "clips"
            if clips_legacy.is_dir() and not any(clips_ws.iterdir()):
                try:
                    clips_ws.rmdir()  # vacío → cede su lugar al enlace
                    os.symlink(os.path.relpath(clips_legacy, ws), clips_ws)
                    published["clips/"] = f"enlace → {clips_legacy.name}/"
                except OSError:
                    pass

            # out — video final (enlace) + hoja de contacto (copia .png)
            final = legacy / f"{pid}_final.mp4"
            if _link(final, ws / "out" / "video_final.mp4"):
                published["out/video_final.mp4"] = f"enlace → {final.name}"
            if _copy(legacy / "contact_sheet.jpg", ws / "out" / "contact_sheet.png"):
                published["out/contact_sheet.png"] = "copia ← contact_sheet.jpg"

            # portada — miniatura YouTube / cover (copia .png)
            if _copy(legacy / "thumb.jpg", ws / "portada.png"):
                published["portada.png"] = "copia ← thumb.jpg"
    except Exception:  # noqa: BLE001 — la vista nunca rompe el render
        log.warning("sync_artifacts(%s) falló (no fatal)", pid, exc_info=True)
    return published


# ── cierre automático de canal (INT-086.3) ────────────────────────────────
def inject_cierre(project: dict) -> bool:
    """Inyecta la frase de cierre de marca.json al final del guion.

    Añade «{cierre.frase}» a la NARRACIÓN de la última escena — así sube
    sola al TTS, al guion.md y a los subtítulos finales sin que el usuario
    la escriba cada vez. Idempotente (meta.cierre_inyectado) y honesta:
    no duplica si la frase o la cuenta ya están en la escena, y no toca el
    modo «audio» (la voz es del usuario — desincronizaría los subtítulos).
    """
    try:
        pid = str(project.get("id") or "")
        meta = dict(project.get("meta") or {})
        if project.get("mode") == "audio" or meta.get("cierre_inyectado"):
            return False
        cierre = (read_marca(project) or {}).get("cierre") or {}
        frase = str(cierre.get("frase") or "").strip()
        if not frase:
            return False
        scenes = db.get_scenes(pid)
        if not scenes:
            return False
        last = scenes[-1]
        narration = str(last.get("narration") or "").rstrip()
        cuenta = str(cierre.get("cuenta") or "").strip()
        if frase in narration or (cuenta and cuenta in narration):
            meta["cierre_inyectado"] = True
            db.update_project(pid, meta=meta)
            return False
        db.update_scene(last["id"], project_id=pid,
                        narration=f"{narration} {frase}".strip())
        meta["cierre_inyectado"] = True
        db.update_project(pid, meta=meta)
        log.info("cierre de canal inyectado en %s («%s»)", pid, frase[:40])
        return True
    except Exception:  # noqa: BLE001 — el cierre nunca rompe el pipeline
        log.warning("inject_cierre(%s) falló (no fatal)",
                    project.get("id"), exc_info=True)
        return False
