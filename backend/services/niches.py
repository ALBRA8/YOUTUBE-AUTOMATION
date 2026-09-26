"""
YOUTUBE AUTOMATION v2.0 — Módulo "Desde Nicho"
Plantillas predeterminadas por nicho: cada nicho trae su prompt base,
estilo visual, formato, voz y subtítulos por defecto. El creador elige
el nicho → el motor compone la idea (plantilla + ángulo aleatorio
anti-repetición) → fabrica guion, imágenes, animación y video SOLO,
y archiva el resultado en biblioteca/{nicho}/{titulo}.mp4.

Persistencia: data/niches.json (auto-siembra con los 8 integrados,
totalmente editable desde el dashboard o la API).
"""
import json
import random
import re
import threading
import unicodedata
from pathlib import Path

from config import DATA_DIR

NICHES_PATH = Path(DATA_DIR) / "niches.json"
# RLock (reentrante): upsert/delete toman el lock y luego llaman a
# list_templates(), que también lo toma — con Lock plano sería deadlock.
_LOCK = threading.RLock()

# ── los 8 nichos integrados (plantilla predeterminada cada uno) ──────────
BUILTIN_NICHES: list[dict] = [
    {
        "id": "superheroes", "emoji": "🦸", "name": "Superhéroes",
        "description": "Orígenes, poderes, batallas y sacrificios de héroes (reales o de ficción).",
        "prompt": ("Escribe un video corto de superhéroes: un origen, poder, batalla o sacrificio "
                   "realmente impactante. Datos concretos, ritmo ágil, gancho en los 2 primeros "
                   "segundos y cierre que invita a comentar."),
        "style": "auto", "format": "short", "voice": "", "subtitles": "hormozi",
    },
    {
        "id": "historia", "emoji": "🏛️", "name": "Historia",
        "description": "Imperios, guerras, traiciones y personajes que cambiaron el mundo.",
        "prompt": ("Escribe un video corto de historia: un evento o personaje real con un giro "
                   "poco conocido. Cronología clara, datos verificables, suspenso creciente y "
                   "una reflexión final que conecte con el presente."),
        "style": "auto", "format": "short", "voice": "", "subtitles": "hormozi",
    },
    {
        "id": "misterio", "emoji": "🔎", "name": "Misterio",
        "description": "Enigmas, desapariciones y teorías que erizan la piel.",
        "prompt": ("Escribe un video corto de misterio: un caso real sin resolver o una teoría "
                   "inquietante. Pistas escalonadas, preguntas retóricas, tono envolvente y "
                   "final abierto que obligue a debatir en comentarios."),
        "style": "auto", "format": "short", "voice": "", "subtitles": "hormozi",
    },
    {
        "id": "motivacion", "emoji": "🔥", "name": "Motivación",
        "description": "Disciplina, hábitos e historias de superación que empujan a actuar.",
        "prompt": ("Escribe un video corto de motivación: una historia real de superación o un "
                   "hábito que cambia vidas. Frases cortas y directas, energía alta, ejemplo "
                   "concreto y llamada a la acción firme."),
        "style": "auto", "format": "short", "voice": "", "subtitles": "hormozi",
    },
    {
        "id": "datos-curiosos", "emoji": "🤯", "name": "Datos Curiosos",
        "description": "Datos que rompen el scroll: ciencia, cuerpo humano, dinero, espacio.",
        "prompt": ("Escribe un video corto de datos curiosos: 4-6 datos reales y verificables "
                   "que sorprendan de inmediato. Cada dato con su explicación de una frase, "
                   "sin relleno, y un dato final aún más fuerte que el primero."),
        "style": "auto", "format": "short", "voice": "", "subtitles": "hormozi",
    },
    {
        "id": "terror", "emoji": "👻", "name": "Terror",
        "description": "Relatos oscuros, leyendas y casos reales que dan escalofríos.",
        "prompt": ("Escribe un video corto de terror: una leyenda urbana o caso real escalofriante. "
                   "Ambiente construido frase a frase, silencios estratégicos, descenso gradual "
                   "hacia el golpe final."),
        "style": "auto", "format": "short", "voice": "", "subtitles": "hormozi",
    },
    {
        "id": "animales", "emoji": "🐾", "name": "Animales",
        "description": "El reino animal en su estado más puro: instintos, récord y rescates.",
        "prompt": ("Escribe un video corto de animales: un comportamiento, récord o rescate real "
                   "que asombre. Comparaciones humanas para dar escala, datos concretos y un "
                   "cierre emotivo."),
        "style": "auto", "format": "short", "voice": "", "subtitles": "hormozi",
    },
    {
        "id": "tecnologia", "emoji": "🤖", "name": "Tecnología e IA",
        "description": "IA, inventos y el futuro que ya llegó (con datos reales).",
        "prompt": ("Escribe un video corto de tecnología/IA: un avance real con implicaciones "
                   "sorprendentes. Explicación simple sin tecnicismos, ejemplo cotidiano y una "
                   "pregunta incómoda sobre el futuro."),
        "style": "auto", "format": "short", "voice": "", "subtitles": "hormozi",
    },
]

# ── anti-repetición: ángulos que se combinan con la plantilla ────────────
ANGLES = [
    "enfocado en el dato más absurdo que casi nadie conoce",
    "contado como una crónica policial, pista por pista",
    "desde la perspectiva del personaje menos esperado",
    "empezando por el final y reconstruyendo qué pasó",
    "comparando con un caso moderno equivalente",
    "centrado en el error o la casualidad que lo cambió todo",
    "con formato de top 3 ascendente, guardando el mejor para el final",
    "desmintiendo la versión popular y contando la real",
    "como si fuera una alerta urgente que acaba de salir a la luz",
    "cerrando con una pregunta polémica para los comentarios",
]


def _slug(text: str) -> str:
    """minúsculas + sin tildes: 'Tecnología e IA' → 'tecnologia e ia'."""
    norm = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in norm if not unicodedata.combining(c)).strip().lower()


def _seed() -> None:
    """Crea data/niches.json con los integrados si el archivo no existe."""
    if NICHES_PATH.exists():
        return
    NICHES_PATH.parent.mkdir(parents=True, exist_ok=True)
    NICHES_PATH.write_text(
        json.dumps(BUILTIN_NICHES, ensure_ascii=False, indent=2), encoding="utf-8")


_seed()


def list_templates() -> list[dict]:
    with _LOCK:
        try:
            data = json.loads(NICHES_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — archivo corrupto → resiembra
            data = BUILTIN_NICHES
            NICHES_PATH.write_text(
                json.dumps(BUILTIN_NICHES, ensure_ascii=False, indent=2), encoding="utf-8")
    return data if isinstance(data, list) else BUILTIN_NICHES


def get_template(id_or_name: str) -> dict | None:
    """Busca por id o por nombre, tolerante a tildes/mayúsculas
    ('TECNOLOGIA E IA' encuentra 'Tecnología e IA')."""
    want = _slug(id_or_name)
    for t in list_templates():
        if _slug(t.get("id")) == want or _slug(t.get("name")) == want:
            return t
    return None


def upsert_template(tpl: dict) -> dict:
    name = (tpl.get("name") or "").strip()
    if not name:
        raise ValueError("el nicho necesita un nombre")
    tid = _slug(tpl.get("id") or name).replace(" ", "_")[:40]
    with _LOCK:
        data = list_templates()
        entry = {
            "id": tid,
            "emoji": (tpl.get("emoji") or "📁").strip()[:8],
            "name": name[:60],
            "description": (tpl.get("description") or "").strip()[:300],
            "prompt": (tpl.get("prompt") or "").strip()[:2000],
            "style": tpl.get("style") or "auto",
            "format": tpl.get("format") or "short",
            "voice": tpl.get("voice") or "",
            "subtitles": tpl.get("subtitles") or "hormozi",
        }
        data = [entry if _slug(t.get("id")) == _slug(tid) else t for t in data]
        if not any(_slug(t.get("id")) == _slug(tid) for t in data):
            data.append(entry)
        NICHES_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry


def delete_template(tid: str) -> bool:
    want = _slug(tid)
    with _LOCK:
        data = list_templates()
        keep = [t for t in data if _slug(t.get("id")) != want]
        if len(keep) == len(data):
            return False
        NICHES_PATH.write_text(
            json.dumps(keep, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def folder_name(tpl: dict) -> str:
    """Carpeta de biblioteca para el nicho: ascii, minúsculas, con guiones."""
    base = _slug(tpl.get("name") or tpl.get("id") or "general")
    return re.sub(r"[^a-z0-9]+", "_", base).strip("_") or "general"


def compose_idea(tpl: dict, user_adjust: str | None = None) -> str:
    """Plantilla del nicho + ángulo aleatorio (anti-repetición) + ajuste
    opcional del creador. 10 ángulos ⇒ decenas de corridas del mismo nicho
    producen variantes distintas."""
    angle = random.choice(ANGLES)
    parts = [tpl.get("prompt") or "", f"Enfoque de esta edición: {angle}."]
    if user_adjust and user_adjust.strip():
        parts.append(f"Además, el creador pide: {user_adjust.strip()}")
    return "\n".join(p for p in parts if p)
