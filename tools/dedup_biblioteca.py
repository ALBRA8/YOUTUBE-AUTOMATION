#!/usr/bin/env python3
r"""
P5.3 · DEDUPLICAR data/biblioteca vs data/output (referencias en vez de copias).

Las copias legacy de la biblioteca (MP4 que `archive()` duplicaba antes del
cambio a referencias) se convierten en .ref.json + borrado de la copia.

REGLA DE ORO (mandato): NUNCA se borra un medio sin política explícita y
sin dry-run previo. Este script:
  · DRY-RUN (default): SOLO informa qué convertiría y cuántos MB liberaría
    (por TAMAÑO + SHA256 — dos archivos se consideran el mismo medio solo
    si ambos coinciden).
  · --ejecutar: crea el .ref.json y BORRA la copia SOLO si el hash del
    destino en biblioteca es idéntico al del MP4 en data/output/. Si el
    target no existe o el hash difiere, NO toca nada (queda listado como
    sin-ref).

Uso (Windows):
  cd D:\PROYECTOS\YOUTUBE AUTOMATION
  python tools\dedup_biblioteca.py            # dry-run + informe
  python tools\dedup_biblioteca.py --ejecutar # aplica (los hashes mandan)
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LIB_DIR = REPO / "backend" / "data" / "biblioteca"
OUT_DIR = REPO / "backend" / "data" / "output"
REF_SUFFIX = ".ref.json"


def sha256_of(p: Path, buf: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(buf):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ejecutar", action="store_true",
                    help="aplica la conversión (por defecto SOLO dry-run)")
    args = ap.parse_args()

    if not LIB_DIR.exists():
        print("biblioteca no existe (nada que deduplicar)")
        return 0

    # índice de MP4 de output por tamaño → [(path, sha)]
    print("Indexando data/output …")
    out_index: dict[int, list[Path]] = {}
    for mp4 in OUT_DIR.rglob("*.mp4"):
        out_index.setdefault(mp4.stat().st_size, []).append(mp4)

    convertibles, huérfanas = [], []
    liberar = 0
    print(f"Escaneando {LIB_DIR} …")
    for mp4 in sorted(LIB_DIR.rglob("*.mp4")):
        size = mp4.stat().st_size
        pid_hint = None
        # el nombre legacy es <slug>_<pid6>.mp4 → recuperamos el project_id
        # real comparando por hash contra los candidatos de output
        cands = out_index.get(size, [])
        match = None
        hash_copy = sha256_of(mp4)
        for c in cands:
            if sha256_of(c) == hash_copy:
                match = c
                break
        if match:
            rel_pid = match.parent.name  # data/output/<pid>/<file>.mp4
            convertibles.append((mp4, match, rel_pid, size))
            liberar += size
        else:
            huérfanas.append(mp4)

    print("\n═══ INFORME ({} dry-run {} ═══".format(
        "" if args.ejecutar else "· ", ""))
    print(f"copias convertibles: {len(convertibles)}  → liberar {liberar / (1024*1024):.1f} MB")
    for mp4, match, pid, size in convertibles:
        print(f"  · {mp4.relative_to(REPO)} == {match.relative_to(REPO)} ({size/1024/1024:.1f} MB)")
    if huérfanas:
        print(f"MP4 SIN equivalente en output (NO se tocan): {len(huérfanas)}")
        for m in huérfanas:
            print(f"  ! {m.relative_to(REPO)}")
    if not args.ejecutar:
        print("\nDRY-RUN: no se ha borrado ni escrito nada. Repite con --ejecutar para aplicar.")
        return 0

    print("\nEjecutando conversión …")
    for mp4, match, pid, size in convertibles:
        niche_dir = mp4.parent
        rel = Path("..") / ".." / "output" / pid / match.name
        ref = mp4.with_suffix(REF_SUFFIX)
        ref.write_text(json.dumps({
            "ref": str(rel), "sha256_size": size,
            "migrado_de_copia": True, "legacy_name": mp4.name,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        mp4.unlink()  # SOLO tras verificar hash idéntico (arriba)
        print(f"  ✓ {mp4.name} → {ref.name} (liberados {size/1024/1024:.1f} MB)")
    print("Listo. La UI sigue listando los vídeos vía las referencias (.ref.json).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
