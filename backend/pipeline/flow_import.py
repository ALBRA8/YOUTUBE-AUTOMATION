"""
Flow Import — Cierra el circuito: trae los assets REALES generados en Google Flow
(por la extensión Flow Script Processor) al pipeline de v2.

La extensión escribe en el disco del usuario:
    <PROYECTO>/Escena_01/imagen_1.png
    <PROYECTO>/Escena_01/video_1.mp4
    <PROYECTO>/Escena_02/imagen_1.png
    ...

Este módulo acepta un ZIP con esa estructura y:
1. Detecta carpetas Escena_XX / Scene_XX (insensible a mayúsculas, 1 o 2 dígitos).
2. Prioriza imagen (imagen_*.png/jpg/webp) y si no hay usa video_*.mp4/webm como póster.
3. Guarda los archivos en data/output/<pid>/flow/ y actualiza scene.image_path.
4. El render posterior (kind="flow_render") usa estos assets SIN regenerar
   guion ni imágenes: solo TTS → alineación → Ken Burns → subtítulos → MP4 final.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VID_EXT = {".mp4", ".webm", ".gif"}

_SCENE_DIR_RE = re.compile(r"^(?:escena|scene)[_\- ]?(\d{1,3})$", re.IGNORECASE)
_IMG_RE = re.compile(r"^(?:imagen|image|img|foto)[_\- ]?(\d+)?", re.IGNORECASE)
_VID_RE = re.compile(r"^(?:video|vid|clip)[_\- ]?(\d+)?", re.IGNORECASE)


def _sorted_numeric(names: list[str]) -> list[str]:
    """Ordena imagen_1, imagen_2, ... imagen_10 numéricamente."""
    def key(n: str):
        m = re.search(r"(\d+)", n)
        return (int(m.group(1)) if m else 0, n)
    return sorted(names, key=key)


def import_flow_zip(project_id: str, data: bytes, output_dir: Path,
                    overwrite: bool = True) -> dict:
    """Extrae el ZIP de la extensión y mapea Escena_XX → escenas del proyecto.

    - Imágenes (imagen_*.png/jpg/webp): se mapean a la escena y entran al render Ken Burns.
    - Videos (video_*.mp4/webm): se guardan como assets en flow/ para uso directo
      futura (el render actual anima imágenes, no concatena clips de video).

    Devuelve: {imported, mapped, missing, videos_saved, ignored, total_files}
    """
    zf = zipfile.ZipFile(io.BytesIO(data))
    # Escena_NN -> lista de (nombre_archivo, bytes)
    buckets: dict[int, list[tuple[str, bytes]]] = {}
    ignored = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        parts = [p for p in Path(info.filename).parts if p not in ("", "/")]
        if not parts:
            continue
        # busca el componente de carpeta Escena_XX (o raíz del zip como escena única)
        scene_no = None
        fname = parts[-1]
        for p in parts[:-1]:
            m = _SCENE_DIR_RE.match(p)
            if m:
                scene_no = int(m.group(1))
                break
        if scene_no is None and len(parts) == 1:
            # archivo suelto en raíz: intenta inferir por nombre imagen_3.png
            m = _IMG_RE.match(Path(fname).stem)
            if m and m.group(1):
                scene_no = int(m.group(1))
        if scene_no is None:
            ignored += 1
            continue
        if Path(fname).suffix.lower() not in (IMG_EXT | VID_EXT):
            ignored += 1
            continue
        buckets.setdefault(scene_no, []).append((fname, zf.read(info)))

    if not buckets:
        raise ValueError("No se encontraron carpetas Escena_XX / Scene_XX en el ZIP")

    flow_dir = output_dir / "flow"
    flow_dir.mkdir(parents=True, exist_ok=True)

    mapped, missing, videos_saved = [], [], []
    for scene_no, files in sorted(buckets.items()):
        imgs = _sorted_numeric([n for n, _ in files
                                if Path(n).suffix.lower() in IMG_EXT])
        vids = _sorted_numeric([n for n, _ in files
                                if Path(n).suffix.lower() in VID_EXT])
        # 1) imagen → entra al render Ken Burns
        if imgs:
            pick_name = imgs[0]
            content = next(b for n, b in files if n == pick_name)
            ext = Path(pick_name).suffix.lower()
            out_path = flow_dir / f"Escena_{scene_no:02d}_flow{ext}"
            if overwrite or not out_path.exists():
                out_path.write_bytes(content)
            mapped.append({"scene_number": scene_no, "file": str(out_path),
                           "kind": "image", "source_file": pick_name})
        else:
            missing.append(scene_no)
        # 2) videos del mismo Escena_XX → se preservan como assets
        for vn in vids:
            content = next(b for n, b in files if n == vn)
            ext = Path(vn).suffix.lower()
            vname = re.sub(r"[^A-Za-z0-9_.]", "_", Path(vn).stem) + ext
            out_path = flow_dir / f"Escena_{scene_no:02d}_{vname}"
            if overwrite or not out_path.exists():
                out_path.write_bytes(content)
            videos_saved.append({"scene_number": scene_no, "file": str(out_path),
                                 "source_file": vn})

    return {"imported": len(mapped), "mapped": mapped, "missing": missing,
            "videos_saved": videos_saved, "ignored": ignored,
            "total_files": sum(len(v) for v in buckets.values())}


def find_flow_videos(output_dir: Path, scene_indexes: list[int]) -> dict[int, Path]:
    """Localiza los videos REALES de Flow por escena (flow/Escena_XX_*.mp4|webm).

    scene_indexes son índices 0-based de las escenas del proyecto y el resultado
    se devuelve como {idx0: Path} — consumido directo por render_scenes().
    Las carpetas de la extensión son 1-based (Escena_01…), así que el glob usa
    idx+1: así el video de la Escena_02 JAMÁS se asigna a la escena 3 (bug
    off-by-one histórico detectado por test_flow_import_e2e).
    Cada candidato se valida con ffprobe: un video truncado/corrupto (descarga
    interrumpida de la extensión) se descarta y esa escena cae a Ken Burns
    sobre su imagen en vez de tumbar el render completo.
    """
    flow_dir = Path(output_dir) / "flow"
    out: dict[int, Path] = {}
    if not flow_dir.exists():
        return out
    from pipeline.video import probe_duration  # diferido: evita ciclos de import
    for idx in scene_indexes:
        no = idx + 1
        cands = sorted(flow_dir.glob(f"Escena_{no:02d}_*.mp4")) \
            + sorted(flow_dir.glob(f"Escena_{no:02d}_*.webm"))
        for cand in cands:
            if probe_duration(cand) > 0.3:
                out[idx] = cand
                break
    return out


def apply_to_scenes(scenes: list[dict], result: dict) -> int:
    """Asigna los archivos importados a las escenas (por número de escena, 1-based)."""
    by_no = {m["scene_number"]: m for m in result["mapped"]}
    applied = 0
    for sc in scenes:
        no = sc["idx"] + 1
        m = by_no.get(no)
        if m and m.get("file"):
            db_update_scene_image(sc["id"], m["file"])
            applied += 1
    return applied


def db_update_scene_image(scene_id: str, path: str) -> None:
    # import diferido para evitar dependencia circular con database.py
    import database as db
    db.update_scene(scene_id, image_path=path, status="image")
