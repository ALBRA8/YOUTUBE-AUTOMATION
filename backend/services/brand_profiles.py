"""
YOUTUBE AUTOMATION v2.0 — Servicio de Brand Profiles Persistentes (INT-042)
Gestión de identidad persistente de canal/marca:
- Nombre, Nicho, Audiencia Objetivo, Tono de Voz
- Estilo Visual, Voz TTS & Proveedor preferidos
- Preset de Subtítulos de Alta Retención
- Reglas y Directivas de Prompting para el Guion
- Perfil por defecto y autofill para proyectos nuevos o existentes.
"""
import json
import logging
from typing import Any, Dict, List, Optional

import database as db

log = logging.getLogger("brand_profiles")

DEFAULT_STARTER_PROFILE = {
    "name": "Canal Principal / Shorts Virales",
    "niche": "Curiosidades y Misterios",
    "audience": "Audiencia joven (18-35) en TikTok/Shorts que busca dopamina rápida y datos sorprendentes.",
    "tone": "Directo, intrigante, con alta urgencia y ritmo acelerado.",
    "visual_style": "cinematic",
    "voice": "es-ES-AlvaroNeural",
    "tts_provider": "edge-tts",
    "subtitle_style": "hormozi",
    "prompt_rules": (
        "1. Gancho de impacto en los primeros 3 segundos sin decir 'bienvenidos' ni 'hola'.\n"
        "2. Frases concisas (máximo 12 palabras por oración).\n"
        "3. Mantener tensión narrativa hasta la última escena."
    ),
    "is_default": 1,
    "meta": {},
}


def _ensure_table():
    """Garantiza que la tabla brand_profiles exista."""
    with db.connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS brand_profiles (
                id             TEXT PRIMARY KEY,
                name           TEXT NOT NULL,
                niche          TEXT NOT NULL DEFAULT '',
                audience       TEXT NOT NULL DEFAULT '',
                tone           TEXT NOT NULL DEFAULT '',
                visual_style   TEXT NOT NULL DEFAULT 'auto',
                voice          TEXT NOT NULL DEFAULT 'es-ES-AlvaroNeural',
                tts_provider   TEXT NOT NULL DEFAULT 'edge-tts',
                subtitle_style TEXT NOT NULL DEFAULT 'hormozi',
                prompt_rules   TEXT NOT NULL DEFAULT '',
                is_default     INTEGER NOT NULL DEFAULT 0,
                meta           TEXT NOT NULL DEFAULT '{}',
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_brand_profiles_default ON brand_profiles(is_default)")


def _row_to_profile(row) -> Dict[str, Any]:
    if not row:
        return {}
    d = dict(row)
    if "meta" in d and isinstance(d["meta"], str):
        try:
            d["meta"] = json.loads(d["meta"] or "{}")
        except Exception:
            d["meta"] = {}
    d["is_default"] = bool(d.get("is_default", 0))
    return d


def list_brand_profiles() -> List[Dict[str, Any]]:
    """Lista todos los perfiles guardados, ordenados con el predeterminado primero."""
    _ensure_table()
    with db.connect() as con:
        rows = con.execute(
            "SELECT * FROM brand_profiles ORDER BY is_default DESC, updated_at DESC"
        ).fetchall()

    profiles = [_row_to_profile(r) for r in rows]
    if not profiles:
        starter = seed_starter_profile()
        return [starter] if starter else []
    return profiles


def get_brand_profile(profile_id: str) -> Optional[Dict[str, Any]]:
    """Obtiene un perfil específico por ID."""
    _ensure_table()
    with db.connect() as con:
        row = con.execute(
            "SELECT * FROM brand_profiles WHERE id = ?", (profile_id,)
        ).fetchone()
    if not row:
        return None
    return _row_to_profile(row)


def get_default_brand_profile() -> Optional[Dict[str, Any]]:
    """Obtiene el perfil configurado como predeterminado activo."""
    _ensure_table()
    with db.connect() as con:
        row = con.execute(
            "SELECT * FROM brand_profiles WHERE is_default = 1 ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    if row:
        return _row_to_profile(row)
    
    profiles = list_brand_profiles()
    if profiles:
        return profiles[0]
    return None


def create_brand_profile(data: Dict[str, Any]) -> Dict[str, Any]:
    """Crea un nuevo perfil de canal/marca."""
    _ensure_table()
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("El nombre del canal/perfil de marca es obligatorio.")

    profile_id = (data.get("id") or "").strip()
    if not profile_id:
        profile_id = f"bp_{db.new_id()}"

    niche = (data.get("niche") or "").strip()
    audience = (data.get("audience") or "").strip()
    tone = (data.get("tone") or "").strip()
    visual_style = (data.get("visual_style") or "auto").strip()
    voice = (data.get("voice") or "es-ES-AlvaroNeural").strip()
    tts_provider = (data.get("tts_provider") or "edge-tts").strip()
    subtitle_style = (data.get("subtitle_style") or "hormozi").strip()
    prompt_rules = (data.get("prompt_rules") or "").strip()
    is_default = 1 if data.get("is_default") else 0
    meta = data.get("meta") or {}
    meta_json = json.dumps(meta, ensure_ascii=False) if isinstance(meta, dict) else "{}"

    now = db.now()

    with db.connect() as con:
        # Si es el primer perfil de la tabla, forzar is_default=1
        count = con.execute("SELECT COUNT(*) as c FROM brand_profiles").fetchone()["c"]
        if count == 0:
            is_default = 1

        if is_default:
            con.execute("UPDATE brand_profiles SET is_default = 0")

        con.execute(
            """
            INSERT INTO brand_profiles (
                id, name, niche, audience, tone, visual_style,
                voice, tts_provider, subtitle_style, prompt_rules,
                is_default, meta, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id, name, niche, audience, tone, visual_style,
                voice, tts_provider, subtitle_style, prompt_rules,
                is_default, meta_json, now, now
            )
        )

    log.info("[brand_profiles] Perfil '%s' creado (%s)", name, profile_id)
    return get_brand_profile(profile_id) or {}


def update_brand_profile(profile_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Actualiza campos de un perfil existente."""
    _ensure_table()
    existing = get_brand_profile(profile_id)
    if not existing:
        return None

    allowed_fields = [
        "name", "niche", "audience", "tone", "visual_style",
        "voice", "tts_provider", "subtitle_style", "prompt_rules",
        "is_default", "meta"
    ]
    updates = {}
    for f in allowed_fields:
        if f in data:
            updates[f] = data[f]

    if "name" in updates:
        updates["name"] = updates["name"].strip()
        if not updates["name"]:
            raise ValueError("El nombre del canal/perfil de marca no puede estar vacío.")

    with db.connect() as con:
        if updates.get("is_default"):
            con.execute("UPDATE brand_profiles SET is_default = 0 WHERE id != ?", (profile_id,))
            updates["is_default"] = 1
        elif "is_default" in updates:
            updates["is_default"] = 1 if updates["is_default"] else 0

        set_clauses = []
        params = []
        for k, v in updates.items():
            if k == "meta" and isinstance(v, dict):
                set_clauses.append("meta = ?")
                params.append(json.dumps(v, ensure_ascii=False))
            else:
                set_clauses.append(f"{k} = ?")
                params.append(v)

        if set_clauses:
            set_clauses.append("updated_at = ?")
            params.append(db.now())
            params.append(profile_id)
            con.execute(
                f"UPDATE brand_profiles SET {', '.join(set_clauses)} WHERE id = ?",
                params
            )

    log.info("[brand_profiles] Perfil '%s' actualizado", profile_id)
    return get_brand_profile(profile_id)


def delete_brand_profile(profile_id: str) -> bool:
    """Elimina un perfil. Si era el default, transfiere el default a otro perfil disponible."""
    _ensure_table()
    profile = get_brand_profile(profile_id)
    if not profile:
        return False

    was_default = profile.get("is_default", False)

    with db.connect() as con:
        con.execute("DELETE FROM brand_profiles WHERE id = ?", (profile_id,))
        if was_default:
            next_row = con.execute(
                "SELECT id FROM brand_profiles ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if next_row:
                con.execute("UPDATE brand_profiles SET is_default = 1 WHERE id = ?", (next_row["id"],))

    log.info("[brand_profiles] Perfil '%s' eliminado", profile_id)
    return True


def set_default_brand_profile(profile_id: str) -> Optional[Dict[str, Any]]:
    """Establece un perfil existente como predeterminado global."""
    _ensure_table()
    profile = get_brand_profile(profile_id)
    if not profile:
        return None

    with db.connect() as con:
        con.execute("UPDATE brand_profiles SET is_default = 0")
        con.execute("UPDATE brand_profiles SET is_default = 1, updated_at = ? WHERE id = ?",
                    (db.now(), profile_id))

    return get_brand_profile(profile_id)


def seed_starter_profile() -> Dict[str, Any]:
    """Siembra un perfil inicial predeterminado si no hay ninguno."""
    _ensure_table()
    with db.connect() as con:
        count = con.execute("SELECT COUNT(*) as c FROM brand_profiles").fetchone()["c"]
        if count > 0:
            row = con.execute("SELECT * FROM brand_profiles ORDER BY is_default DESC LIMIT 1").fetchone()
            return _row_to_profile(row)

    log.info("[brand_profiles] Sembrando perfil inicial por defecto...")
    return create_brand_profile(DEFAULT_STARTER_PROFILE)


def apply_brand_profile_to_project(profile_id: str, project_id: Any) -> Dict[str, Any]:
    """
    Aplica las configuraciones del perfil de marca al proyecto indicado:
    - Voz y proveedor TTS
    - Estilo visual
    - Nicho
    - Subtítulo preset en meta
    - Snapshot completo del Brand Profile en meta['brand_profile']
    - Reglas de prompt y tono en meta
    """
    _ensure_table()
    if isinstance(project_id, dict):
        project_id = project_id.get("id", "")
    project_id = str(project_id).strip()

    profile = get_brand_profile(profile_id)
    if not profile:
        raise ValueError(f"Perfil de marca no encontrado: '{profile_id}'")

    p = db.get_project(project_id)
    if not p:
        raise ValueError(f"Proyecto no encontrado: '{project_id}'")

    meta = p.get("meta") or {}
    meta["subtitle_style"] = profile.get("subtitle_style", "hormozi")
    meta["brand_profile_id"] = profile["id"]
    meta["brand_profile"] = profile
    meta["tone"] = profile.get("tone", "")
    meta["audience"] = profile.get("audience", "")
    meta["prompt_rules"] = profile.get("prompt_rules", "")

    update_kwargs = {
        "voice": profile.get("voice") or p.get("voice"),
        "tts_provider": profile.get("tts_provider") or p.get("tts_provider"),
        "niche": profile.get("niche") or p.get("niche"),
        "meta": meta,
    }
    # Solo actualizar estilo si el perfil define uno específico y no es auto
    if profile.get("visual_style") and profile.get("visual_style") != "auto":
        update_kwargs["style"] = profile["visual_style"]

    with db.connect() as con:
        # Verificar si la columna brand_profile_id existe en projects
        cols = [r[1] for r in con.execute("PRAGMA table_info(projects)").fetchall()]
        if "brand_profile_id" in cols:
            con.execute("UPDATE projects SET brand_profile_id = ? WHERE id = ?", (profile["id"], project_id))

    db.update_project(project_id, **update_kwargs)
    log.info("[brand_profiles] Perfil '%s' aplicado exitosamente al proyecto '%s'", profile["name"], project_id)
    return db.get_project(project_id) or {}


def format_prompt_directives(profile: Optional[Dict[str, Any]] = None) -> str:
    """
    Genera un bloque de instrucciones de marca inyectable directamente al motor
    de generación de guiones (Creative Engine / LLM).
    """
    if not profile:
        profile = get_default_brand_profile()
    if not profile:
        return ""

    directives = [
        f"=== REGLAS DE MARCA Y CANAL: {profile.get('name', 'General')} ===",
        f"- Nicho / Temática: {profile.get('niche', 'General')}",
        f"- Audiencia Objetivo: {profile.get('audience', 'Audiencia general')}",
        f"- Tono de Voz y Ritmo: {profile.get('tone', 'Dinámico y cautivador')}",
    ]
    if profile.get("prompt_rules"):
        directives.append(f"- Reglas Estrictas de Guion:\n{profile.get('prompt_rules')}")
    directives.append("==================================================")
    return "\n".join(directives)
