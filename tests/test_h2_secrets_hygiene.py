# -*- coding: utf-8 -*-
"""H2 · Higiene de secretos: las NOTAS del repo no contienen prefijos de token.

Lección: la nota ANTIGRAVITY_VALIDACION_PRODUCCION.md guardaba el prefijo
del PAT que circuló por el chat (`ghp_IoIr...`). Regla H2: no pedir, no
guardar ni escribir tokens en ningún archivo, nota ni log del repo.

Alcance del barrido: *.md y *.txt del repo FUERA de backend/ y tests/
(ahí viven los dobles de prueba intencionales de redacción — selfaudit.py,
test_hands.py — que usan tokens FALSOS para verificar el enmascarado; son
pruebas de seguridad, no secretos).

Prefijos vigilados: PAT de GitHub (ghp_/gho_/ghu_/ghs_/ghr_/github_pat_),
AWS (AKIA), OpenAI (sk-…), Slack (xox…), Google (AIza).

Ejecutar: python3 -m pytest tests/test_h2_secrets_hygiene.py -q
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Cualquier aparición de estos prefijos seguidos de material de token real
# (4+ caracteres) en NOTAS es un fallo de higiene. Los dobles de prueba
# falsos del código (ghp_supersecreto, ghp_xxxxxxxxxx) viven en tests/ y
# backend/ y quedan fuera del barrido por diseño.
PATRONES = {
    "PAT GitHub clásico": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{4,}"),
    "PAT GitHub fino": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{10,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "OpenAI-like": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "Slack": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
}

EXCLUIDAS = (".git", "backend", "tests", ".venv", "node_modules", "__pycache__")


def _notas_del_repo():
    for md in REPO.rglob("*"):
        if not md.suffix.lower() in (".md", ".txt"):
            continue
        rel = md.relative_to(REPO)
        if any(part in EXCLUIDAS for part in rel.parts):
            continue
        if "CONTEXTO YOUTUBE" in str(rel) or True:
            yield md


def test_notas_sin_prefijos_de_token():
    filtrados = []
    for ruta in _notas_del_repo():
        try:
            texto = ruta.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for nombre, patron in PATRONES.items():
            m = patron.search(texto)
            if m:
                filtrados.append(f"{ruta.relative_to(REPO)} → {nombre}: {m.group(0)}")
    assert not filtrados, (
        "H2: prefijos de token en notas del repo (ni el prefijo de un token "
        "que circuló por chat): " + "; ".join(filtrados))


def test_el_fragmento_historico_ghp_IoIr_no_vuelve():
    """Regresión exacta del fragmento redactado en esta sesión."""
    for ruta in _notas_del_repo():
        try:
            texto = ruta.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        assert "ghp_IoIr" not in texto, f"el fragmento volvió: {ruta}"


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
