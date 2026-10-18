# ─────────────────────────────────────────────────────────────────────
# YOUTUBE HARNESS — knowledge.py (mandato §10, §11, §12)
# ─────────────────────────────────────────────────────────────────────
# CONOCIMIENTO DE DOMINIO estructurado del arnés.
#
# Origen: auditoría P2-a de backend/services/agent.py (VÓRTICE v3) +
# fuentes canónicas del repo (database.py, orchestrator.py, niches.py,
# themes.py, flow_jobs.py, production_doctor, video_qa, youtube_publish).
#
# REGLA DE ORO (§12): este conocimiento debe permitir que un host nuevo
# reproduzca el trabajo de VÓRTICE sin VÓRTICE:
#   VÓRTICE eliminado + host nuevo + YouTube Harness = misma capacidad.
#
# NO es una copia de SYSTEM_BRAIN (ese string mezcla identidad del
# trabajador con conocimiento del puesto). Aquí el conocimiento es del
# PUESTO: qué existe, qué significa, qué es seguro y cómo se clasifica
# un error. La identidad ("Eres VÓRTICE…") NO migra: pertenece al
# trabajador, no al arnés.
#
# Los catálogos VIVOS (nichos, estilos, avatares, cerebros LLM) NO se
# duplican aquí: se consultan vía operaciones del arnés
# (youtube.list_niches / list_styles / list_avatars / system_status).
# ─────────────────────────────────────────────────────────────────────
from __future__ import annotations

from .contracts import EXTERNAL_STATES

KNOWLEDGE_VERSION = "1.0"

# ── 1. LIFECYCLE (§11) — estados internos reales + significado ──────
LIFECYCLE: list[dict] = [
    {"state": "draft", "meaning": "Proyecto creado, aún sin producir. "
        "Punto de entrada de youtube.create y de la ingesta Production JSON."},
    {"state": "queued", "meaning": "Declarado en el schema pero la fábrica "
        "hoy no lo escribe para proyectos (la cola real es flow_jobs). "
        "Normalizado a QUEUED por contrato."},
    {"state": "scripting", "meaning": "Guion en generación (guion_json / "
        "Production JSON → escenas)."},
    {"state": "images", "meaning": "Imágenes por escena en generación."},
    {"state": "tts", "meaning": "Locución por escena (edge=$0 ilimitado o "
        "gemini=premium)."},
    {"state": "align", "meaning": "Alineación audio-subtítulo por palabra."},
    {"state": "render", "meaning": "Montaje MP4 con FFmpeg (recetas de "
        "cámara, transiciones, estilo visual)."},
    {"state": "subtitles", "meaning": "Subtítulos (estilo hormozi) sobre el "
        "render; fase de verificación del resultado."},
    {"state": "ready", "meaning": "Video final listo; QA forense disponible; "
        "candidato a publicación."},
    {"state": "published", "meaning": "Publicado en YouTube (youtube_id "
        "asignado; idempotencia de publicación activa)."},
    {"state": "failed", "meaning": "Paso roto. step_label y error dicen el "
        "paso exacto. youtube.recover / youtube.production_doctor son las "
        "vías de recuperación; si es recuperable, el estado externo es "
        "RECOVERABLE."},
]

# Nota de honestidad: 'importing', 'processing' y 'publishing' existen
# como estados de paso en el orchestrator (vía import y vía Flow);
# se normalizan (RUNNING/VERIFYING) sin inventar estados nuevos.

# ── 2. DOMAIN OBJECTS (§11) ─────────────────────────────────────────
DOMAIN_OBJECTS: list[dict] = [
    {"object": "project", "meaning": "Unidad de producción: título, estado, "
        "formato, estilo, voz, nicho, plataformas, meta. Vive en SQLite y "
        "en OUTPUT_DIR/<project_id>."},
    {"object": "scene", "meaning": "Escena de un proyecto: narración, "
        "image_prompt, status (pending|image|audio|done|failed), archivos "
        "de imagen/audio. SIEMPRE pertenece a un project_id."},
    {"object": "avatar", "meaning": "Personaje DNA con look y voz propios "
        "(se crea por UI/API; el pipeline lo usa como identidad visual)."},
    {"object": "niche", "meaning": "Carpeta temática. Un nicho-plantilla "
        "trae emoji, descripción y prompt predeterminado: el motor compone "
        "idea = plantilla + ángulo anti-repetición. También existen nichos "
        "libres; «Sin nicho» = sin carpeta."},
    {"object": "style", "meaning": "Estilo visual: 'auto' + catálogo fijo "
        "(graphic-novel, neo-anime, pixar-3d, terror-cartoon, …). Nunca "
        "inventar ids fuera del catálogo (youtube.list_styles)."},
    {"object": "camera_recipe", "meaning": "Receta de cámara: movimiento/"
        "encuadre aplicado al render por el pipeline."},
    {"object": "production_json", "meaning": "Creative Production JSON: el "
        "contrato creativo externo (schema 1.0). Puerta formal: "
        "youtube.submit_production / youtube.validate_production. La "
        "fábrica NO inventa: errores estructurales → VALIDATION; avisos → "
        "defaults mecánicos declarados."},
    {"object": "asset", "meaning": "Artefacto generado (imagen, audio, "
        "clip Flow, MP4). Los assets Flow llegan por la cola (flow_jobs) "
        "con validación de formato (PIL/ffprobe/Execution Contract)."},
    {"object": "flow_job", "meaning": "Trabajo de la cola Flow para la "
        "extensión Chrome: queued → claimed (lease + job_token + worker) "
        "→ done | dead. Recuperable por lease vencida (recover)."},
    {"object": "final_video", "meaning": "MP4 final del proyecto "
        "(video_url); su QA forense es video_qa; su puerta de salida es "
        "youtube.publish (idempotente, con QA gate)."},
    {"object": "publication", "meaning": "Subida a YouTube: estado en "
        "meta.publish_state (DRAFT→PUBLISHING→PUBLISHED/FAILED) + job "
        "kind=publish auditable. Un proyecto con youtube_id no se "
        "re-publica (409 por diseño)."},
]

# ── 3. PRODUCTION SEMANTICS (§11) ───────────────────────────────────
PRODUCTION_SEMANTICS: list[dict] = [
    {"verb": "crear", "operation": "youtube.create",
     "meaning": "Registrar la intención de producción como proyecto "
     "draft. NO produce nada por sí solo; el lanzamiento es explícito."},
    {"verb": "lanzar", "operation": "youtube.launch",
     "meaning": "Arrancar el pipeline (preflight incluido): guion → "
     "imágenes → TTS → align → render → subtítulos → ready. El preflight "
     "puede REFUSAR el lanzamiento (CONFIG_*): eso es el contrato "
     "protegiendo pruebas reales."},
    {"verb": "verificar", "operation": "youtube.video_qa / project_status",
     "meaning": "Comprobar evidencia real: QA forense del MP4 (pantalla "
     "negra/azul, audio silencioso), estado de cola Flow, exec_state del "
     "Execution Contract. Verificar NUNCA inventa: devuelve lo medido."},
    {"verb": "recuperar", "operation": "youtube.recover / production_doctor",
     "meaning": "Leases Flow vencidas se re-encolan (máx intentos y "
     "ciclos por contrato); el doctor diagnostica capas A-I y aplica SOLO "
     "reparaciones de lista blanca. Lo no reparable queda FAILED honesto."},
    {"verb": "publicar", "operation": "youtube.publish",
     "meaning": "Subir a YouTube. Externo e idempotente: QA gate del "
     "render final + un solo youtube_id por proyecto + historial auditable."},
]

# ── 4. SAFETY SEMANTICS (§11 + reglas M9 extraídas de agent.py) ─────
SAFETY_SEMANTICS: list[dict] = [
    {"rule": "destructivas con permiso propio",
     "detail": "youtube.delete y youtube.cleanup exigen youtube.destroy. "
     "Tener youtube.production.* NO da acceso destructivo."},
    {"rule": "cero fuzzy en destructivas (regla M9)",
     "detail": "Borrado exige project_id EXACTO y validado (12 hex). Solo "
     "si no viene id, un match de título EXACTO único sirve de puente; "
     "cero o múltiples candidatos → NO se ejecuta (se listan máx 5)."},
    {"rule": "confirmación host-side",
     "detail": "El arnés ejecuta destructivas cuando la solicitud viene "
     "autenticada y con permiso; el HOST es responsable de la "
     "confirmación humana (HITL) previa. VÓRTICE delega igual hoy: "
     "plan() nunca ejecuta; el dashboard pide confirmación."},
    {"rule": "publicación con barrera",
     "detail": "youtube.publish exige video listo, QA del render final "
     "sin errores y credenciales YouTube configuradas; idempotencia 409."},
    {"rule": "cancelación limpia",
     "detail": "youtube.cancel marca cancelled el job activo; el pipeline "
     "respeta la cancelación cooperativa; los estados quedan coherentes."},
    {"rule": "limpieza acotada",
     "detail": "youtube.cleanup borra SOLO intermedios del proyecto "
     "(clips); el MP4 final, imágenes, Flow y audio se conservan."},
    {"rule": "recuperación honesta",
     "detail": "recover solo re-encola lo con lease vencida según "
     "contrato (MAX_ATTEMPTS/MAX_LEASE_CYCLES); jamás inventa éxito."},
]

# ── 5. ERROR SEMANTICS (§11) — clasificación estable para el host ───
ERROR_SEMANTICS: list[dict] = [
    {"code": "VALIDATION", "external_status": "BLOCKED",
     "meaning": "Payload/Production JSON estructuralmente inválido "
     "(Creative boundary: la fábrica no inventa). Requiere corrección "
     "del host, no reintento."},
    {"code": "PERMISSION_*", "external_status": "BLOCKED",
     "meaning": "Permisos insuficientes o no otorgados por la credencial."},
    {"code": "NOT_FOUND", "external_status": "FAILED",
     "meaning": "El recurso (proyecto/job) no existe. No reintentar."},
    {"code": "CONFLICT", "external_status": "FAILED",
     "meaning": "Estado incompatible (idempotencia de publicación, job "
     "ya terminado, proyecto ya lanzado). No reintentar a ciegas."},
    {"code": "PREFLIGHT_REFUSED", "external_status": "BLOCKED",
     "meaning": "El gate de configuración (CONFIG_*) refusó generar: "
     "falta config real de Flow/proveedor. Configurar y reintentar."},
    {"code": "PROVIDER_FAILURE", "external_status": "RECOVERABLE",
     "meaning": "Fallo de proveedor externo (LLM/TTS/imagen). Reintento "
     "limitado por contrato; recover/doctor como vía."},
    {"code": "ASSET_INVALID", "external_status": "FAILED",
     "meaning": "Asset validado y rechazado por formato (PIL/ffprobe/"
     "Execution Contract). Requiere re-generación, no reintento ciego."},
    {"code": "WATCHDOG", "external_status": "RECOVERABLE",
     "meaning": "Lease/watchdog expiró: el flujo fue recuperado o es "
     "recuperable; evidencia cruda en observability (taxonomía A-I)."},
    {"code": "RATE_LIMITED", "external_status": "RECOVERABLE",
     "meaning": "Proveedor limitado temporalmente; la cola reintenta con "
     "cooldown; no escalar."},
    {"code": "INTERNAL", "external_status": "FAILED",
     "meaning": "Error no clasificado del servidor. Reportar con "
     "correlation_id; nunca oculto."},
]

# ── 6. FACTORY FACTS — hechos operativos del puesto (de SYSTEM_BRAIN
#      y del código, limpiados de identidad del trabajador) ──────────
FACTORY_FACTS: list[dict] = [
    {"fact": "La fábrica corre en local con coste base $0: TTS edge "
     "gratuito ilimitado, imágenes locales, FFmpeg local. Gemini y "
     "publicación YouTube requieren claves propias (token aparte)."},
    {"fact": "Formatos: short (9:16) y long (16:9). Plataformas válidas: "
     "youtube, tiktok, instagram, facebook."},
    {"fact": "Subtítulos estilo hormozi por defecto; alineación por "
     "palabra (align)."},
    {"fact": "Avatares: personajes DNA con look + voz propios; el nombre "
     "del avatar se resuelve exacto (luego substring) — nunca inventado."},
    {"fact": "Los nichos-plantilla componen la idea (plantilla + ángulo "
     "anti-repetición); un nicho borrado deja los videos en «Sin nicho»."},
    {"fact": "La cola Flow la consume la extensión Chrome con claim "
     "atómico, job_token de una sola era, worker_id y lease; el backend "
     "nunca asume éxito sin asset validado."},
    {"fact": "El Execution Contract define exec_state forward-only y "
     "terminales honestas (CONFIG_*, PROVIDER_FAILURE, ASSET_INVALID, "
     "DEAD): la fábrica NO demuestra lo que no midió."},
    {"fact": "Publicación: un proyecto ya publicado no se vuelve a "
     "publicar (idempotencia); el QA del render final bloquea la "
     "publicación con errores."},
]

# Nota de migración (auditoría P2-a): system brain de VÓRTICE tenía una
# cadena de cerebros obsoleta y un modelo de estados simplificado; aquí
# el conocimiento usa las fuentes canónicas (database.py/orchestrator.py/
# nvidia_client.py) — el arnés no hereda comentarios desactualizados.


def knowledge_manifest() -> dict:
    """Bloque de conocimiento para /manifest y documentación."""
    return {
        "knowledge_version": KNOWLEDGE_VERSION,
        "lifecycle": LIFECYCLE,
        "domain_objects": DOMAIN_OBJECTS,
        "production_semantics": PRODUCTION_SEMANTICS,
        "safety_semantics": SAFETY_SEMANTICS,
        "error_semantics": ERROR_SEMANTICS,
        "factory_facts": FACTORY_FACTS,
        "external_states": list(EXTERNAL_STATES),
    }
