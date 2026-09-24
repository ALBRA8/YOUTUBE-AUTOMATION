"""
YOUTUBE AUTOMATION v2.0 — Originalidad verificable del modo URL
El modo "Desde URL" promete: recrear la ESTRUCTURA del viral con contenido
ORIGINAL ("similar pero no igual"). Esto solo es honesto si se MIDE.

Métrica (gratis, local, sin LLM):
- n-gramas de palabras (por defecto 5-gramas) del guion generado que
  aparecen textualmente en la transcripción de origen.
- longest_run: la secuencia de palabras consecutivas más larga compartida.

Regla práctica: un guion que reescribe con nuevo ángulo comparte <10-15%
de 5-gramas (solo nombres propios, cifras y frases hechas). Si comparte
más, el modelo copió → relanzamos con instrucción reforzada.
"""
import re

# umbral de 5-gramas compartidos (0.18 = 18%) por encima del cual se
# considera "demasiado copiado" y se relanza la generación
COPY_THRESHOLD = 0.18
NGRAM_SIZE = 5

_WORD_RE = re.compile(r"[\wáéíóúüñÁÉÍÓÚÜÑ]+", re.UNICODE)

# palabras vacías españolas para extraer keywords del fallback local $0
_STOPWORDS = set("""
de la que el en y a los se del las un por con no una su para es al lo
como más pero sus le ya o este sí porque esta entre cuando muy sin
sobre también me hasta hay donde quien desde todo nos durante todos
uno les ni contra otros ese eso ante ellos e esto mí antes algunos qué
unos yo otro otras otra él tanto esa estos mucho quienes nada muchos
cual poco ella estar estas algunas algo nosotros the and for you your
with that this are was were have has had not but they them their will
can all been just its from what when where who how if then than
so only about into out up down over under again once here there
""".split())


def tokens(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


def ngram_set(text: str, n: int = NGRAM_SIZE) -> set[tuple[str, ...]]:
    toks = tokens(text)
    if len(toks) < n:
        # texto demasiado corto para n-gramas: usamos el propio texto
        return {tuple(toks)} if toks else set()
    return {tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def copy_overlap(source: str, generated: str, n: int = NGRAM_SIZE) -> float:
    """Fracción [0..1] de n-gramas del guion generado que aparecen en el
    original. 0 = sin copia textual; 1 = copia literal."""
    gen = ngram_set(generated, n)
    if not gen:
        return 0.0
    src = ngram_set(source, n)
    if not src:
        return 0.0
    shared = sum(1 for g in gen if g in src)
    return shared / len(gen)


def longest_shared_run(source: str, generated: str) -> int:
    """Longitud (en palabras) de la secuencia consecutiva más larga que el
    guion comparte textualmente con el original. Un guion original sano
    rara vez supera 6-8 (nombres propios, cifras)."""
    src_toks = tokens(source)
    gen_toks = tokens(generated)
    if not src_toks or not gen_toks:
        return 0
    src_joined = " \x00 ".join(src_toks)  # separador imposible en tokens
    best = 0
    for i in range(len(gen_toks)):
        # ventana creciente desde la posición i; corta si ya no puede superar best
        for j in range(len(gen_toks) - i, best, -1):
            run = " \x00 ".join(gen_toks[i:i + j])
            if run in src_joined:
                best = max(best, j)
                break
    return best


def originality_report(source: str, generated: str) -> dict:
    return {
        "overlap": round(copy_overlap(source, generated), 4),
        "longest_run": longest_shared_run(source, generated),
        "too_similar": copy_overlap(source, generated) > COPY_THRESHOLD,
    }


def keywords(text: str, k: int = 6) -> list[str]:
    """Keywords de contenido (sin stopwords ni números puros) más
    frecuentes — para el fallback local $0 del modo URL, que así produce
    guiones con sustancia real de la transcripción y no frases plantilla
    genéricas."""
    freq: dict[str, int] = {}
    for t in tokens(text):
        if len(t) < 4 or t in _STOPWORDS or t.isdigit():
            continue
        freq[t] = freq.get(t, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, _ in ranked[:k]]
