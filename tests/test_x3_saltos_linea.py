# -*- coding: utf-8 -*-
"""X3 · Higiene de saltos de línea: ningún texto versionado con CR doblado.

Los editores de Windows pueden doblar el CR y dejar "\r\r\n" (CRCRLF) en los
archivos. grep línea a línea NO lo detecta fiable (el \r extra queda pegado al
contenido de la línea), así que este test lee cada archivo versionado en
MODO BINARIO y falla si contiene b"\r\r\n".

Excluye binarios (.ttf, .png, .jpg, .mp3, .mp4, ...): pueden contener la
secuencia por casualidad dentro de datos comprimidos (p. ej. Montserrat-
ExtraBold.ttf la contenía sin ser un fallo de texto).

Regla de escritura futura: SIEMPRE escribir con LF (ver .gitattributes).
"""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Extensiones binarias: nunca se analizan como texto
BINARIOS = {
    ".ttf", ".otf", ".woff", ".woff2",           # fuentes
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp",  # imágenes
    ".mp3", ".wav", ".m4a", ".mp4", ".mov", ".webm",   # audio/video
    ".zip", ".pdf", ".exe", ".dll", ".sqlite", ".db",  # otros
}

# Patrones que .gitattributes debe fijar en LF (X3)
EOL_LF_REQUERIDOS = ("*.py", "*.js", "*.html", "*.css", "*.md",
                     "*.json", "*.txt", "*.yml", "*.sh")

# Binarios que .gitattributes debe marcar como binary
BINARY_REQUERIDOS = ("*.ttf", "*.png", "*.jpg", "*.mp3", "*.mp4")


def _archivos_versionados() -> list[str]:
    """Lista de archivos versionados por git (nombres por byte, -z, sin grep)."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                         capture_output=True, timeout=60)
    assert out.returncode == 0, "git ls-files falló"
    return [n.decode("utf-8", "surrogateescape")
            for n in out.stdout.split(b"\0") if n]


def test_x3_ningun_texto_versionado_con_crcrlf():
    """Ningún archivo de texto versionado puede contener b"\\r\\r\\n"."""
    ofensores = []
    for rel in _archivos_versionados():
        p = REPO / rel
        if not p.is_file():
            continue
        if p.suffix.lower() in BINARIOS:
            continue
        if b"\r\r\n" in p.read_bytes():
            ofensores.append(rel)
    assert not ofensores, (
        "Archivos de texto con CR doblado (\\r\\r\\n) — normalizar a LF: "
        + ", ".join(ofensores))


def test_x3_app_mcp_js_es_lf_puro():
    """El panel app-mcp.js quedó normalizado a LF (cero bytes CR)."""
    data = (REPO / "backend" / "static" / "app-mcp.js").read_bytes()
    assert b"\r" not in data, (
        "backend/static/app-mcp.js sigue con CR (debe ser LF puro)")


def test_x3_gitattributes_fija_lf_y_marca_binarios():
    """.gitattributes debe fijar eol=lf en el texto versionado y marcar binarios."""
    ga = REPO / ".gitattributes"
    assert ga.is_file(), "Falta .gitattributes"
    contenido = ga.read_text(encoding="utf-8")
    for patron in EOL_LF_REQUERIDOS:
        assert patron in contenido, f".gitattributes no fija {patron} con eol=lf"
    for patron in BINARY_REQUERIDOS:
        assert patron in contenido, f".gitattributes no marca {patron} como binario"


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
