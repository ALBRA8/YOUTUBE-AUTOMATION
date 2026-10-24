"""
YOUTUBE AUTOMATION v2.0 — Catálogo y Galería de Voces (INT-040)
Catálogo enriquecido de voces neuronales (Edge TTS $0 + Gemini TTS Studio)
con soporte de preescucha interactiva y caché local determinista.
"""
import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any

import config
from services import gemini_client

log = logging.getLogger("voices_catalog")

PREVIEWS_DIR = Path(config.DATA_DIR) / "voice_previews"
DEFAULT_SAMPLE_TEXT = "Hola, seré la voz principal de tu video. ¿Qué te parece cómo sueno?"

VOICES_CATALOG: list[dict[str, Any]] = [
    # ── Edge TTS (100% Gratuitas e Ilimitadas) ─────────────────────────────
    {
        "id": "es-CO-SalomeNeural",
        "name": "Salomé",
        "provider": "edge",
        "country": "Colombia",
        "flag": "🇨🇴",
        "locale": "es-CO",
        "gender": "Femenina",
        "tone": "Cálida y dinámica",
        "description": "Voz magnética de ritmo perfecto. La más popular para YouTube Shorts y TikTok.",
        "sample_text": "¡Hola! Soy Salomé. Te contaré historias fascinantes con el mejor ritmo para atrapar a tu audiencia.",
        "tags": ["Recomendada", "Shorts", "Viral", "Storytelling"],
    },
    {
        "id": "es-CO-GonzaloNeural",
        "name": "Gonzalo",
        "provider": "edge",
        "country": "Colombia",
        "flag": "🇨🇴",
        "locale": "es-CO",
        "gender": "Masculina",
        "tone": "Juvenil y moderno",
        "description": "Tono fresco, conversacional y fluido. Excelente para vlogs, tecnología y curiosidades.",
        "sample_text": "Qué tal, soy Gonzalo. Conmigo tus videos tendrán una vibra moderna y cercana.",
        "tags": ["Juvenil", "Curiosidades", "Tecnología"],
    },
    {
        "id": "es-MX-JorgeNeural",
        "name": "Jorge",
        "provider": "edge",
        "country": "México",
        "flag": "🇲🇽",
        "locale": "es-MX",
        "gender": "Masculina",
        "tone": "Enérgico y contundente",
        "description": "Voz potente con máxima retención. Ideal para ganchos virales, datos impactantes y acción.",
        "sample_text": "¡Atención! Soy Jorge. Si buscas enganchar a la gente desde el segundo cero, soy tu voz.",
        "tags": ["Viral", "Impacto", "Alta Retención"],
    },
    {
        "id": "es-MX-DaliaNeural",
        "name": "Dalia",
        "provider": "edge",
        "country": "México",
        "flag": "🇲🇽",
        "locale": "es-MX",
        "gender": "Femenina",
        "tone": "Expresiva y versátil",
        "description": "Locución clara, amigable y muy articulada. Ideal para tutoriales, resúmenes y educación.",
        "sample_text": "Hola a todos, soy Dalia. Haré que tus explicaciones se entiendan fácil y con mucha naturalidad.",
        "tags": ["Educación", "Tutoriales", "Clara"],
    },
    {
        "id": "es-AR-TomasNeural",
        "name": "Tomás",
        "provider": "edge",
        "country": "Argentina",
        "flag": "🇦🇷",
        "locale": "es-AR",
        "gender": "Masculina",
        "tone": "Carismático y reflexivo",
        "description": "Estilo cercano y envolvente con cadencia rioplatense. Genial para ensayos y debates.",
        "sample_text": "Hola, soy Tomás. Vamos a sumergirnos juntos en historias y reflexiones que valen la pena.",
        "tags": ["Carismático", "Debate", "Storytelling"],
    },
    {
        "id": "es-AR-ElenaNeural",
        "name": "Elena",
        "provider": "edge",
        "country": "Argentina",
        "flag": "🇦🇷",
        "locale": "es-AR",
        "gender": "Femenina",
        "tone": "Pausada y elegante",
        "description": "Tono sobrio y seguro. Excelente para finanzas personales, análisis y temas serios.",
        "sample_text": "Buenas, soy Elena. La claridad y precisión son clave para entender conceptos complejos.",
        "tags": ["Finanzas", "Elegante", "Análisis"],
    },
    {
        "id": "es-ES-AlvaroNeural",
        "name": "Álvaro",
        "provider": "edge",
        "country": "España",
        "flag": "🇪🇸",
        "locale": "es-ES",
        "gender": "Masculina",
        "tone": "Profundo y misterioso",
        "description": "Timbre grave y cinematográfico. La opción número 1 para documentales, terror y misterios históricos.",
        "sample_text": "Bienvenidos. Soy Álvaro. Adentrémonos en los secretos mejor guardados de la historia.",
        "tags": ["Documental", "Misterio", "Cinematográfico"],
    },
    {
        "id": "es-ES-ElviraNeural",
        "name": "Elvira",
        "provider": "edge",
        "country": "España",
        "flag": "🇪🇸",
        "locale": "es-ES",
        "gender": "Femenina",
        "tone": "Formal y narrativa",
        "description": "Pronunciación impecable de estándar europeo. Para biografías, ciencia y noticias.",
        "sample_text": "Hola, soy Elvira. Cada descubrimiento tiene detrás una gran historia por contar.",
        "tags": ["Noticias", "Ciencia", "Biografías"],
    },
    {
        "id": "es-US-AlonsoNeural",
        "name": "Alonso",
        "provider": "edge",
        "country": "US Latino",
        "flag": "🇺🇸",
        "locale": "es-US",
        "gender": "Masculina",
        "tone": "Ritmo alto y comercial",
        "description": "Entonación comercial y dinámica. Perfecta para motivación, fitness y anuncios UGC.",
        "sample_text": "¡Vamos con todo! Soy Alonso y hoy vamos a romper límites con la mejor energía.",
        "tags": ["Motivación", "Comercial", "Fitness"],
    },
    {
        "id": "es-US-IsabellaNeural",
        "name": "Isabella",
        "provider": "edge",
        "country": "US Latino",
        "flag": "🇺🇸",
        "locale": "es-US",
        "gender": "Femenina",
        "tone": "Fresca y contemporánea",
        "description": "Estilo joven, espontáneo y actual. Ideal para moda, tendencias de internet y entretenimiento.",
        "sample_text": "¡Hola, chicos! Soy Isabella y les traigo lo más nuevo y viral del momento.",
        "tags": ["Tendencias", "Moda", "Entretenimiento"],
    },
    {
        "id": "es-CL-LorenzoNeural",
        "name": "Lorenzo",
        "provider": "edge",
        "country": "Chile",
        "flag": "🇨🇱",
        "locale": "es-CL",
        "gender": "Masculina",
        "tone": "Sereno y descriptivo",
        "description": "Cadencia suave y descriptiva. Excelente para relatos de naturaleza y viajes.",
        "sample_text": "Hola a todos, soy Lorenzo. Acompáñenme a explorar paisajes y relatos inolvidables.",
        "tags": ["Viajes", "Naturaleza", "Calma"],
    },
    {
        "id": "es-PE-AlexNeural",
        "name": "Alex",
        "provider": "edge",
        "country": "Perú",
        "flag": "🇵🇪",
        "locale": "es-PE",
        "gender": "Masculina",
        "tone": "Neutro y didáctico",
        "description": "Acento neutro altamente comprensible en toda Latinoamérica y España.",
        "sample_text": "Hola, soy Alex. Mi objetivo es explicarte cada detalle de forma clara y directa.",
        "tags": ["Neutro", "Didáctico", "Universal"],
    },

    # ── Gemini TTS (Modelos Multimodales de Google) ────────────────────────
    {
        "id": "Fenrir",
        "name": "Fenrir",
        "provider": "gemini",
        "country": "Google Studio",
        "flag": "🎖️",
        "locale": "es-US",
        "gender": "Masculina",
        "tone": "Épica y dramática",
        "description": "Voz premium con modulación cinematográfica ultra-realista. Resalta tensión y clímax.",
        "sample_text": "Las sombras ocultan lo que pocos se atreven a buscar. Soy Fenrir.",
        "tags": ["Premium", "Épica", "Cinematográfica"],
    },
    {
        "id": "Puck",
        "name": "Puck",
        "provider": "gemini",
        "country": "Google Studio",
        "flag": "🎖️",
        "locale": "es-US",
        "gender": "Masculina",
        "tone": "Enérgica y pícara",
        "description": "Voz juvenil, rápida y llena de carisma. Para comedia, retos y contenido informal.",
        "sample_text": "¡No te lo vas a creer! Soy Puck y esto se va a poner muy interesante.",
        "tags": ["Premium", "Energía", "Humor"],
    },
    {
        "id": "Charon",
        "name": "Charon",
        "provider": "gemini",
        "country": "Google Studio",
        "flag": "🎖️",
        "locale": "es-US",
        "gender": "Masculina",
        "tone": "Solemne y profunda",
        "description": "Timbre maduro y respetable. Ideal para narrativas de imperios, guerras y filosofía.",
        "sample_text": "El tiempo no perdona a los imperios. Soy Charon y te relataré su caída.",
        "tags": ["Premium", "Solemne", "Historia"],
    },
    {
        "id": "Kore",
        "name": "Kore",
        "provider": "gemini",
        "country": "Google Studio",
        "flag": "🎖️",
        "locale": "es-US",
        "gender": "Femenina",
        "tone": "Cálida y envolvente",
        "description": "Prosodia natural impecable y tono tranquilizador. Ideal para bienestar y motivación.",
        "sample_text": "Respira hondo. Soy Kore y quiero compartir contigo un mensaje que puede transformar tu día.",
        "tags": ["Premium", "Cálida", "Bienestar"],
    },
    {
        "id": "Aoede",
        "name": "Aoede",
        "provider": "gemini",
        "country": "Google Studio",
        "flag": "🎖️",
        "locale": "es-US",
        "gender": "Femenina",
        "tone": "Artística y fluida",
        "description": "Modulación melódica y cautivadora. Destaca en literatura, mitología y biografías íntimas.",
        "sample_text": "Cada historia es un viaje. Soy Aoede y te invito a descubrir este nuevo relato.",
        "tags": ["Premium", "Artística", "Literatura"],
    },
]


def get_all_voices(
    provider: str | None = None,
    gender: str | None = None,
    country: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Devuelve la lista curada de voces con filtros opcionales."""
    voices = list(VOICES_CATALOG)
    if provider:
        voices = [v for v in voices if v["provider"].lower() == provider.lower()]
    if gender:
        voices = [v for v in voices if v["gender"].lower() == gender.lower()]
    if country:
        voices = [v for v in voices if country.lower() in v["country"].lower()]
    if query:
        q = query.strip().lower()
        voices = [
            v for v in voices
            if q in v["name"].lower()
            or q in v["country"].lower()
            or q in v["tone"].lower()
            or q in v["description"].lower()
            or any(q in t.lower() for t in v.get("tags", []))
        ]
    return voices


def get_voice_by_id(voice_id: str) -> dict[str, Any] | None:
    """Busca una voz por su ID."""
    vid = (voice_id or "").strip()
    return next((v for v in VOICES_CATALOG if v["id"].lower() == vid.lower()), None)


def _preview_cache_path(voice_id: str, text: str, ext: str = ".mp3") -> Path:
    """Calcula la ruta de almacenamiento en caché para una preescucha."""
    PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    hash_txt = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
    clean_id = voice_id.replace(":", "_").replace("/", "_")
    return PREVIEWS_DIR / f"preview_{clean_id}_{hash_txt}{ext}"


async def synthesize_preview(
    voice_id: str,
    text: str | None = None,
    provider: str | None = None,
) -> tuple[Path, float, str]:
    """
    Sintetiza un fragmento de audio de muestra para preescucha en la UI.
    Usa caché en disco para respuesta inmediata (<1ms tras la primera generación).
    Devuelve (ruta_archivo, duracion_segundos, formato_mime).
    """
    voice = get_voice_by_id(voice_id)
    prov = (provider or (voice["provider"] if voice else "edge")).lower()
    txt = (text or (voice["sample_text"] if voice else DEFAULT_SAMPLE_TEXT)).strip()

    if prov == "gemini":
        cache_file = _preview_cache_path(voice_id, txt, ext=".wav")
        mime = "audio/wav"
        if cache_file.exists() and cache_file.stat().st_size > 1024:
            return cache_file, 3.0, mime

        if not gemini_client.available():
            raise RuntimeError("Gemini API Key no está configurada para preescucha de voz Gemini")

        wav_bytes = await gemini_client.tts_pcm(txt, voice=voice_id)
        cache_file.write_bytes(wav_bytes)
        return cache_file, 3.0, mime

    # Default a Edge TTS (MP3 nativo ultra-rápido)
    cache_file = _preview_cache_path(voice_id, txt, ext=".mp3")
    mime = "audio/mpeg"
    if cache_file.exists() and cache_file.stat().st_size > 1024:
        return cache_file, 3.0, mime

    import edge_tts
    comm = edge_tts.Communicate(txt, voice_id, rate="+0%")
    await comm.save(str(cache_file))
    return cache_file, 3.0, mime
