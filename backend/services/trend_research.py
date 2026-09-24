"""
YOUTUBE AUTOMATION v2.1.2 — Investigación de tendencias $0 (pre-guion)
Patrón Agent-Reach: yt-dlp da metadata REAL de YouTube (títulos, vistas,
duraciones, canales, comentarios) SIN API KEY y sin coste marginal.

Flujo: research_topic(query) → videos + insights → ideas_from_research()
       ideas con Gemini si hay key; heurístico local si no (sigue siendo $0).
El orquestador/dashboards usan esto para elegir QUÉ video producir antes de
quemar cuota de generación.
"""
import asyncio
import logging
import re
import statistics
from collections import Counter
from urllib.parse import quote_plus

import config
from services import gemini_client

log = logging.getLogger("trends")

STOPWORDS = set("""
de la que el en y a los del se las por un para con no una su al lo como mas
más pero sus le ya o este si sí porque esta entre cuando muy sin sobre también
tambien me hasta hay donde quien desde todo nos durante todos uno les ni
contra otros ese eso ante ellos e esto mi mí antes algunos qué que unos yo
otro otras otra el tanto esa estos mucho quienes nada muchos cual poco ella
estar estas algunas algo nosotros tu te ti eres fue eran era sono son
the of and to in is it you that for on with as are this be was but not have
from your they what he she his her at or an we my so if then can will just
""".split())

IDEAS_SCHEMA = {
    "type": "object",
    "properties": {
        "ideas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "angle": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["title", "angle", "why"],
            },
        },
    },
    "required": ["ideas"],
}


def probe_ytdlp() -> dict:
    """Sonda de disponibilidad (módulo python o binario). Patrón probe_command."""
    try:
        import yt_dlp
        ver = getattr(getattr(yt_dlp, "version", None), "__version__", None)
        return {"available": True, "mode": "module", "version": ver}
    except ImportError:
        pass
    try:
        import subprocess
        p = subprocess.run(["yt-dlp", "--version"], capture_output=True,
                           text=True, timeout=15)
        if p.returncode == 0:
            return {"available": True, "mode": "binary", "version": p.stdout.strip()}
    except Exception:  # noqa: BLE001
        pass
    return {"available": False, "mode": None, "version": None,
            "hint": "pip install yt-dlp"}


def _fetch_videos(query: str, max_videos: int, with_comments: bool,
                  cookies_from_browser: str | None = None) -> list[dict]:
    """Descarga metadata (sin video) de los primeros resultados de búsqueda."""
    import yt_dlp

    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "socket_timeout": 20, "retries": 2, "playlistend": max_videos,
        "extract_flat": False,  # metadata completa (vistas, duración)
    }
    if with_comments:
        opts["getcomments"] = True
    if cookies_from_browser:
        # tupla (navegador, perfil, keyring, contenedor) — API oficial yt-dlp
        opts["cookiesfrombrowser"] = (cookies_from_browser,)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{max_videos}:{query}", download=False)

    out: list[dict] = []
    for e in (info.get("entries") or []):
        if not e:
            continue
        url = e.get("webpage_url") or ""
        if not url.startswith("http") and e.get("id"):
            url = "https://www.youtube.com/watch?v=" + str(e["id"])
        comments = []
        if with_comments:
            for c in (e.get("comments") or [])[:10]:
                if isinstance(c, dict) and c.get("text"):
                    comments.append(c["text"][:200])
        out.append({
            "title": (e.get("title") or "")[:160],
            "url": url,
            "views": int(e.get("view_count") or 0),
            "likes": int(e.get("like_count") or 0),
            "duration": round(float(e.get("duration") or 0), 1),
            "uploader": (e.get("uploader") or e.get("channel") or "")[:80],
            "description": (e.get("description") or "")[:500],
            "comments": comments,
        })
    return out


def _translate_ytdlp_error(e: Exception) -> str:
    s = str(e)
    if "Sign in to confirm" in s or "not a bot" in s:
        return ("YouTube exige verificación anti-bot para esta IP (típico en "
                "servidores/VPNs de datacenter). Soluciones $0: 1) corre el "
                "backend desde tu PC (IP residencial); 2) pasa "
                "cookies_from_browser=\"chrome\"|\"firefox\" para reusar tu "
                "sesión de YouTube.")
    if "timed out" in s.lower() or "timeout" in s.lower():
        return "Red lenta bloqueando YouTube — reintenta o reduce max_videos"
    return s[:200]


async def research_topic(query: str, max_videos: int = 8,
                         with_comments: bool = False,
                         cookies_from_browser: str | None = None) -> dict:
    """Investiga un nicho en YouTube. Lanza RuntimeError si yt-dlp falta."""
    probe = probe_ytdlp()
    if not probe["available"]:
        raise RuntimeError("yt-dlp no disponible (" + probe.get("hint", "") + ")")
    max_videos = max(3, min(15, int(max_videos or 8)))
    try:
        videos = await asyncio.wait_for(
            asyncio.to_thread(_fetch_videos, query, max_videos, with_comments,
                              cookies_from_browser),
            timeout=240)
    except asyncio.TimeoutError:
        raise RuntimeError("La búsqueda excedió 240s (red lenta o YouTube saturado)")
    except RuntimeError:
        raise
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(_translate_ytdlp_error(e))
    if not videos:
        raise RuntimeError(f"Sin resultados para «{query}»")
    videos.sort(key=lambda v: v["views"], reverse=True)
    return {"query": query, "count": len(videos), "videos": videos,
            "insights": build_insights(videos)}


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-záéíóúüñ0-9]{3,}",
                                  (text or "").lower()) if t not in STOPWORDS]


def build_insights(videos: list[dict]) -> dict:
    """Estadísticas accionables sin LLM: vistas, duración dulce, keywords."""
    views = [v["views"] for v in videos if v["views"] > 0]
    durs = [v["duration"] for v in videos if v["duration"] > 30]
    kw = Counter()
    for v in videos:
        kw.update(_tokens(v["title"]))
    hooks = []
    for v in videos[:5]:
        words = (v["title"] or "").split()
        if len(words) >= 3:
            hooks.append(" ".join(words[:4]))
    return {
        "avg_views": int(statistics.mean(views)) if views else 0,
        "median_views": int(statistics.median(views)) if views else 0,
        "top_views": max(views) if views else 0,
        "median_duration_s": round(statistics.median(durs)) if durs else 0,
        "keywords": [k for k, _ in kw.most_common(12)],
        "hook_patterns": hooks,
        "uploaders": list({v["uploader"] for v in videos if v["uploader"]})[:6],
    }


def _heuristic_ideas(research: dict, n: int) -> list[dict]:
    """Ideas sin API key: patrones de títulos probados × keywords reales del nicho."""
    kws = research["insights"]["keywords"][:6] or ["misterio"]
    avg = research["insights"]["avg_views"]
    patterns = [
        ("Lo que NADIE te cuenta sobre {k}", "revelación contrarian con datos del nicho"),
        ("El lado oscuro de {k} que intentan ocultar", "tensión + curiosidad (brecha de información)"),
        ("3 datos sobre {k} que te van a shockear", "lista de choque, retención alta en shorts"),
        ("¿Por qué TODO el mundo habla de {k}?", "surfeo la tendencia con prueba social"),
        ("La VERDAD sobre {k} en 60 segundos", "promesa de resolución rápida"),
        ("Así cambió {k} para siempre", "narrativa de transformación"),
    ]
    out = []
    for i in range(min(n, 12)):
        k = kws[i % len(kws)]
        tpl, angle = patterns[i % len(patterns)]
        out.append({
            "title": tpl.format(k=k.capitalize()),
            "angle": angle,
            "why": f"Basado en {research['count']} videos reales del nicho "
                   f"(promedio {avg:,} vistas). Keyword probada: «{k}».".replace(",", "."),
        })
    return out[:n]


async def ideas_from_research(research: dict, n: int = 5) -> list[dict]:
    """Ideas de video a partir de la investigación real.
    Gemini (json estructurado) con fallback heurístico local."""
    n = max(1, min(10, int(n or 5)))
    if gemini_client.available():
        top = research["videos"][:8]
        lines = [f"- {v['title']} | {v['views']:,} vistas | {v['duration']:.0f}s"
                 .replace(",", ".") for v in top]
        ins = research["insights"]
        prompt = (
            f"Estás investigando el nicho «{research['query']}» en YouTube para "
            f"producir shorts 9:16 virales en ESPAÑOL.\n\n"
            f"Top videos reales por vistas:\n" + "\n".join(lines) + "\n\n"
            f"Keywords frecuentes: {', '.join(ins['keywords'])}\n"
            f"Duración mediana: {ins['median_duration_s']}s · "
            f"vistas promedio: {ins['avg_views']}\n\n"
            f"Genera {n} ideas de short que compitan con esos números: "
            f"título con hook brutal (máx 60 caracteres), ángulo narrativo "
            f"(cómo contarlo en 6-8 escenas) y por qué tiene potencial viral "
            f"según los datos. JSON con la schema dada.")
        try:
            data = await gemini_client.generate_json(prompt, schema=IDEAS_SCHEMA)
            ideas = data.get("ideas") or []
            if ideas:
                return ideas[:n]
        except Exception as e:  # noqa: BLE001
            log.warning("ideas Gemini falló (%s) → heurístico", e)
    return _heuristic_ideas(research, n)
