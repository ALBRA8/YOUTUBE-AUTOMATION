"""
YOUTUBE AUTOMATION v2.0 — Biblioteca en disco organizada por nichos
Cada video terminado se archiva como:
    data/biblioteca/{nicho}/{titulo-del-video}.mp4
con un sidecar .json (metadatos). Nombre de archivo legible + marcador
del id de proyecto anti-colisión.

[P5.3 · dedup biblioteca↔output] ANTES: `archive()` copiaba el MP4 completo
(read_bytes→write_bytes): el mismo vídeo vivía DOS veces en disco
(data/output/<pid>/<pid>_final.mp4 + data/biblioteca/<nicho>/<t>.mp4;
medido: 122,2 MB duplicados). AHORA: la biblioteca guarda una REFERENCIA
(.ref.json con ruta relativa a output/) — el concepto de biblioteca y la
UI (GET /api/library → misma forma {niche, files[]}) quedan intactos, pero
ya no hay segundo MP4. Los MP4 antiguos (copias legacy) siguen listándose
para no romper nada existente; tools/dedup_biblioteca.py convierte las
copias legacy a referencias con dry-run previo.
"""
import json
import logging
import re
import unicodedata
from pathlib import Path

log = logging.getLogger("library")

BASE_DIR = Path(__file__).resolve().parent.parent
LIB_DIR = BASE_DIR / "data" / "biblioteca"
OUTPUT_DIR = BASE_DIR / "data" / "output"

REF_SUFFIX = ".ref.json"


def _slug(text: str) -> str:
    norm = unicodedata.normalize("NFKD", str(text or ""))
    clean = "".join(c for c in norm if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "_", clean).strip("_") or "video"


def archive(project: dict, video_path: str | Path) -> Path | None:
    """ARCHIVA POR REFERENCIA (P5.3): escribe .ref.json que apunta al MP4 de
    data/output/ (ruta RELATIVA — la biblioteca sobrevive a mover la carpeta
    del repo). Idempotente: si la referencia ya existe, no repite.
    Devuelve la ruta del .ref.json (meta.library_path sigue funcionando)."""
    src = Path(video_path)
    if not src.exists() or src.stat().st_size < 1024:
        return None
    niche = _slug(project.get("niche") or "general")
    title = _slug(project.get("title") or project.get("id"))[:80]
    name = f"{title}_{project.get('id', '')[:6]}{REF_SUFFIX}" if project.get("id") else f"{title}{REF_SUFFIX}"
    dest_dir = LIB_DIR / niche
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    try:
        rel = Path("..") / ".." / "output" / project.get("id", "") / src.name
        dest.write_text(json.dumps({
            "project_id": project.get("id"),
            "title": project.get("title"),
            "niche": project.get("niche"),
            "format": project.get("format"),
            "duration_s": (project.get("meta") or {}).get("total_duration"),
            "ref": str(rel),                       # relativo a este .ref.json
            "sha256_size": src.stat().st_size,     # sanity: el target debe pesar esto
            "archived_at": __import__("time").time(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("archivado en biblioteca (referencia): %s → %s", dest, rel)
        return dest
    except OSError as e:  # noqa: BLE001 — archivar no debe tumbar el pipeline
        log.warning("no se pudo archivar en biblioteca: %s", e)
        return None


def _stat_of(ref_entry: dict, ref_file: Path) -> dict | None:
    """Resuelve la referencia y devuelve {size, modified, target} del MP4
    real, o None si el target ya no existe (referencia huérfana honesta)."""
    raw = str(ref_entry.get("ref") or "")
    if not raw:
        return None
    try:
        target = (ref_file.parent / raw).resolve()
        if not target.is_file():
            return None
        st = target.stat()
        # sanity: si el target pesa distinto al archivado, alguien lo
        # regeneró — la referencia sigue válida (misma ruta canónica)
        return {"size": st.st_size, "modified": st.st_mtime,
                "target": str(target)}
    except OSError:
        return None


def tree() -> list[dict]:
    """Contenido de la biblioteca: [{niche, files:[{name,size,modified}]}].
    Lista MP4 legacy (copias reales) Y referencias (.ref.json → output/).
    Mantiene EXACTAMENTE la forma que la UI ya consume (P5.3)."""
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
        for r in sorted(d.glob(f"*{REF_SUFFIX}")):
            try:
                entry = json.loads(r.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            stat = _stat_of(entry, r)
            if stat:
                files.append({"name": r.stem[:-len(".ref")] if r.stem.endswith(".ref") else r.stem,
                              "size": stat["size"],
                              "modified": stat["modified"],
                              "ref": True,
                              "path": stat["target"]})
            else:
                files.append({"name": r.stem, "size": 0, "modified": 0,
                              "ref": True, "missing": True})
        if files:
            out.append({"niche": d.name, "files": files})
    return out
