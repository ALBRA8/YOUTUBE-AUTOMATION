"""
YOUTUBE AUTOMATION v2.0 — Biblioteca en disco organizada por nichos
Cada video terminado se archiva como:
    data/biblioteca/{nicho}/{titulo-del-video}.mp4
con un sidecar .json (metadatos). Nombre de archivo legible + marcador
del id de proyecto anti-colisión.
"""
import json
import logging
import re
import unicodedata
from pathlib import Path

log = logging.getLogger("library")

BASE_DIR = Path(__file__).resolve().parent.parent
LIB_DIR = BASE_DIR / "data" / "biblioteca"


def _slug(text: str) -> str:
    norm = unicodedata.normalize("NFKD", str(text or ""))
    clean = "".join(c for c in norm if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "_", clean).strip("_") or "video"


def archive(project: dict, video_path: str | Path) -> Path | None:
    """Copia el MP4 terminado a biblioteca/{nicho}/{titulo}.mp4.
    Idempotente: si ya está archivado (misma ruta) no repite."""
    src = Path(video_path)
    if not src.exists() or src.stat().st_size < 1024:
        return None
    niche = _slug(project.get("niche") or "general")
    title = _slug(project.get("title") or project.get("id"))[:80]
    name = f"{title}_{project.get('id', '')[:6]}.mp4" if project.get("id") else f"{title}.mp4"
    dest_dir = LIB_DIR / niche
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    if dest.resolve() == src.resolve():
        return dest
    try:
        dest.write_bytes(src.read_bytes())
        dest.with_suffix(".json").write_text(json.dumps({
            "project_id": project.get("id"),
            "title": project.get("title"),
            "niche": project.get("niche"),
            "format": project.get("format"),
            "duration_s": (project.get("meta") or {}).get("total_duration"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("archivado en biblioteca: %s", dest)
        return dest
    except OSError as e:  # noqa: BLE001 — archivar no debe tumbar el pipeline
        log.warning("no se pudo archivar en biblioteca: %s", e)
        return None


def tree() -> list[dict]:
    """Contenido de la biblioteca: [{niche, files:[{name,size,modified}]}]."""
    if not LIB_DIR.exists():
        return []
    out = []
    for d in sorted(LIB_DIR.iterdir()):
        if not d.is_dir():
            continue
        files = []
        for f in sorted(d.glob("*.mp4")):
            st = f.stat()
            files.append({"name": f.name, "size": st.st_size,
                          "modified": st.st_mtime})
        if files:
            out.append({"niche": d.name, "files": files})
    return out
