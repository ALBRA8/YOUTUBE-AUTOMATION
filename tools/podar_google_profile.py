#!/usr/bin/env python3
"""
P5.2 · PODAR backend/data/google_profile_global (254,7 MB → ~20 MB).

Borra SOLO cachés REGENERABLES de Chrome dentro del perfil global del MCP.
NUNCA toca la sesión de Google (es la sesión que `connect_all_google` usa):

  BORRA (regenerables):        component_crx_cache, optimization_guide_
  model_store, WasmTtsEngine*, Safe Browsing/*.store/*, GPUCache, Code Cache,
  DawnGraphiteCache, DawnWebGPUCache, GrShaderCache, ShaderCache

  CONSERVA (sesión):           Cookies, Cookies-journal, Login Data(+For
  Account), Preferences, Secure Preferences, Local State, 'Web Data',
  Extensions, Extension State, Network/Cookies, Sync Data, storage/

REGLAS DEL MANDATO:
  · DRY-RUN por defecto (imprime qué borraría y cuántos MB libera).
  · --ejecutar borra. Chrome DEBE estar cerrado (el script lo verifica por
    los Singleton* del perfil y se niega si están presentes).
  · Después de podar: botón «Conexión Google» → connect_all_google debe
    seguir autenticando (Cookies/Login Data intactos).

Uso (Windows):
  cd D:\PROYECTOS\YOUTUBE AUTOMATION
  python tools\podar_google_profile.py             # dry-run + informe
  python tools\podar_google_profile.py --ejecutar  # aplica
"""
import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROFILE = REPO / "backend" / "data" / "google_profile_global"

# directorios/caches regenerables (relativos al perfil)
BORRAR_DIRS = [
    "component_crx_cache",
    "optimization_guide_model_store",
    "GPUCache",
    "Code Cache",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    "GrShaderCache",
    "ShaderCache",
    "Crashpad",
]
BORRAR_GLOBS = [
    "WasmTtsEngine*",
    "Safe Browsing/*.store*",
    "Safe Browsing/cookies*",
    "*.log",
]
# archivos que JAMÁS se tocan (sesión de Google / MCP)
CONSERVAR = [
    "Cookies", "Cookies-journal",
    "Login Data", "Login Data-journal", "Login Data For Account",
    "Preferences", "Secure Preferences",
    "Local State",
    "Web Data", "Web Data-journal",
    "Extensions", "Extension State", "Extension Scripts",
    "Network",           # Network/Cookies = cookies modernas de Chrome
    "Sync Data",
    "Default/Cookies", "Default/Login Data", "Default/Preferences",
    "Default/Network", "Default/Extensions",
    "Default/Secure Preferences", "Default/Web Data",
]


def _size_of(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    if p.is_dir():
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return 0


def _candidatos() -> list[Path]:
    cand: list[Path] = []
    if not PROFILE.exists():
        return cand
    for name in BORRAR_DIRS:
        p = PROFILE / name
        if p.exists():
            cand.append(p)
    for pat in BORRAR_GLOBS:
        cand.extend(PROFILE.glob(pat))
    return cand


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ejecutar", action="store_true",
                    help="aplica la poda (por defecto SOLO dry-run)")
    args = ap.parse_args()

    if not PROFILE.exists():
        print(f"perfil no existe: {PROFILE}")
        return 0

    total = _size_of(PROFILE)
    cand = _candidatos()
    a_borrar = sum(_size_of(p) for p in cand)

    # guard: Chrome abierto con ESTE perfil → Singleton* presentes
    singletons = list(PROFILE.glob("Singleton*"))
    if args.ejecutar and singletons:
        print("REFUSIDO: el perfil tiene Singleton* — Chrome está (o estuvo) "
              "abierto con él. CIERRA Chrome y reintenta.")
        return 2

    print(f"perfil: {PROFILE}")
    print(f"tamaño actual: {total / (1024*1024):.1f} MB")
    print(f"regenerables a borrar: {a_borrar / (1024*1024):.1f} MB "
          f"(quedaría ~{(total - a_borrar) / (1024*1024):.1f} MB)")
    for p in cand:
        print(f"  · {p.relative_to(REPO)}  ({_size_of(p) / (1024*1024):.1f} MB)")
    print("\nSE CONSERVAN (sesión Google del MCP):",
          ", ".join(CONSERVAR[:8]), "…")

    if not args.ejecutar:
        print("\nDRY-RUN: nada borrado. Repite con --ejecutar para aplicar "
              "(Chrome cerrado).")
        return 0

    liberado = 0
    for p in cand:
        try:
            sz = _size_of(p)
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            liberado += sz
            print(f"  ✓ borrado {p.relative_to(REPO)} ({sz / (1024*1024):.1f} MB)")
        except OSError as e:
            print(f"  ! no se pudo borrar {p}: {e}")
    print(f"\nListo: {liberado / (1024*1024):.1f} MB liberados. "
          "Verifica después: «Conexión Google» (connect_all_google) debe "
          "seguir autenticando — Cookies/Login Data intactos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
