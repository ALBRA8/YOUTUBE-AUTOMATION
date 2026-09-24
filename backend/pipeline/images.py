"""
YOUTUBE AUTOMATION v2.0 — Paso 2: Imágenes HÍBRIDAS
1. Primario: Gemini 2.5 Flash Image (gratis ~500/día con key estándar)
2. Plan B:   cola de la extensión Chrome (ImageFX automatizado) si Gemini falla
3. Plan C:   placeholder degradado con PIL para no bloquear el render
"""
import asyncio
import json
import logging
from pathlib import Path

import database as db
from config import OUTPUT_DIR
from services import gemini_client
from services import avatar_schema
from services.themes import get_style

log = logging.getLogger("images")
PIL_OK = True
try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    PIL_OK = False

# Consistencia visual entre escenas (patrón AI-Content-Automation-Engine):
# la primera imagen resuelta del proyecto se adjunta como referencia de
# estilo (img2img) a las siguientes. Mismo coste: sigue siendo 1 llamada
# generate_content por escena, solo multimodal.
STYLE_REF_SUFFIX = (", match the visual style of the attached reference image: "
                    "same color palette, same lighting, same illustration "
                    "technique, keep character appearance consistent")
STYLE_REF_META = "style_reference"  # flag en meta del proyecto (default True)


def _style_sidecar(image_path: str) -> Path:
    return Path(image_path).with_suffix(".style.json")


def _save_style_method(image_path: str, method: str) -> None:
    try:
        _style_sidecar(image_path).write_text(json.dumps({"method": method}))
    except Exception:  # noqa: BLE001
        pass


def _load_style_method(image_path: str) -> str | None:
    try:
        return json.loads(_style_sidecar(image_path).read_text()).get("method")
    except Exception:  # noqa: BLE001
        return None


def _reference_bytes(anchor_path: str) -> bytes | None:
    """Bytes de la imagen ancla SOLO si es de un proveedor real (sidecar
    method != placeholder). Un placeholder degradado como referencia
    contagiaría un estilo “gradiente plano” a todo el proyecto."""
    try:
        p = Path(anchor_path)
        if not p.exists() or p.stat().st_size < 512:
            return None
        if _load_style_method(anchor_path) == "placeholder":
            return None
        return p.read_bytes()
    except OSError:
        return None


def scene_dir(project_id: str) -> Path:
    d = OUTPUT_DIR / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def full_prompt(scene: dict, project: dict) -> str:
    style = get_style(project["style"])
    custom = (project.get("meta") or {}).get("custom_style_prompt")
    # "auto" → prompt vacío: no se añade ningún preset (el guion ya trae la
    # estética integrada en el image_prompt o se usa el neutro en fallback).
    style_desc = (custom or style["prompt"] or "").strip()
    extra = ", no text, no letters, no watermark"
    # Consistencia de personaje: si el proyecto tiene avatar, fijamos su
    # apariencia (traducida a inglés por el schema PRO) en TODOS los prompts
    # para que el personaje sea igual en cada escena.
    avatar = (project.get("meta") or {}).get("avatar") or None
    if avatar:
        extra += (", " + avatar_schema.scene_suffix(avatar))
    style_part = f", {style_desc}" if style_desc else ""
    return f"{scene['image_prompt']}{style_part}{extra}"


async def generate_scene_image(scene: dict, project: dict, idx: int,
                               ref_image: bytes | None = None) -> tuple[Path, str]:
    """Devuelve (ruta_imagen, método_usado).
    ref_image: bytes de la imagen ancla del proyecto para img2img (solo
    afecta a la llamada Gemini; planes B/C siguen igual)."""
    out = scene_dir(project["id"]) / f"scene_{idx:02d}.png"
    prompt = full_prompt(scene, project)
    if ref_image:
        prompt += STYLE_REF_SUFFIX

    # 1) Gemini 2.5 Flash Image
    if gemini_client.available():
        try:
            data = await gemini_client.generate_image(prompt, ref_image=ref_image)
            out.write_bytes(data)
            _save_style_method(str(out), "gemini")
            return out, "gemini"
        except Exception as e:  # noqa: BLE001
            log.warning("Gemini image falló escena %d: %s", idx, e)

    # 2) Plan B: imagen capturada por la extensión Chrome (ImageFX)
    ext = db.take_ext_image(project["id"])
    if ext:
        try:
            import urllib.request
            req = urllib.request.Request(ext["url"],
                                         headers={"User-Agent": "Mozilla/5.0"})
            data = await asyncio.to_thread(lambda: urllib.request.urlopen(req, timeout=30).read())
            out.write_bytes(data)
            _save_style_method(str(out), "extension")
            return out, "extension"
        except Exception as e:  # noqa: BLE001
            log.warning("Imagen de extensión falló: %s", e)

    # 3) Plan C: placeholder elegante
    _placeholder(out, scene, project, idx)
    _save_style_method(str(out), "placeholder")
    return out, "placeholder"


def _parse_grad(grad: str) -> tuple[str, str]:
    """Convierte cualquier grad en (c1, c2) hex válido.
    - 'linear-gradient(135deg,#a,#b)' → ('#a','#b')
    - '#a' solo → ('#a','#a') (degradado plano)
    - 3+ colores → primeros 2
    - formato con espacios o sin ',' → fallback ('#1a1a2e','#16213e')
    """
    if not grad or not isinstance(grad, str):
        return "#1a1a2e", "#16213e"
    g = grad.replace("linear-gradient(135deg,", "").rstrip(")").strip()
    # Tolerante a espacios
    parts = [p.strip() for p in g.split(",") if p.strip()]
    if len(parts) >= 2:
        c1, c2 = parts[0], parts[1]
    elif len(parts) == 1:
        c1 = c2 = parts[0]
    else:
        c1, c2 = "#1a1a2e", "#16213e"
    # Validar hex (#rrggbb o #rgb)
    def _is_hex(s: str) -> bool:
        s = s.lstrip("#")
        return len(s) in (3, 6) and all(c in "0123456789abcdefABCDEF" for c in s)
    if not _is_hex(c1):
        c1 = "#1a1a2e"
    if not _is_hex(c2):
        c2 = "#16213e"
    return c1, c2


def _placeholder(out: Path, scene: dict, project: dict, idx: int) -> None:
    if not PIL_OK:
        out.write_bytes(b"")
        return
    # Busca el grad del style del proyecto; si no existe, usa STYLES[0].
    # Esto hace el placeholder robusto a styles inválidos sin romper el pipeline.
    from services.themes import STYLES, get_style
    grad = get_style(project.get("style") or "").get("grad", "#1a1a2e,#16213e")
    c1, c2 = _parse_grad(grad)
    img = Image.new("RGB", (1080, 1920), c1)
    draw = ImageDraw.Draw(img)
    c1rgb = tuple(int(c1.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    c2rgb = tuple(int(c2.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    for y in range(1920):
        t = y / 1920
        rgb = tuple(int(c1rgb[i] * (1 - t) + c2rgb[i] * t) for i in range(3))
        draw.line([(0, y), (1080, y)], fill=rgb)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)


async def generate_all(project: dict, scenes: list[dict], on_progress=None,
                       is_cancelled=None) -> list[str]:
    """Genera las imágenes de todas las escenas (2 en paralelo).

    CONSISTENCIA VISUAL (style reference): la escena 0 se resuelve PRIMERO
    (cache o generación) y su imagen se adjunta como referencia de estilo a
    las demás (img2img). Desactivable con meta.style_reference=false."""
    paths: list[str] = ["" for _ in scenes]
    sem = asyncio.Semaphore(2)
    use_ref = bool((project.get("meta") or {}).get(STYLE_REF_META, True))

    async def one(i, sc, ref_image=None):
        if is_cancelled and is_cancelled():
            return
        # IDEMPOTENCIA (skip-if-exists): si ya hay una imagen válida en disco
        # para esta escena, reutilizarla. Un pipeline re-lanzado tras un fallo
        # NO vuelve a gastar cuota de generación en lo ya completado.
        existing = str(sc.get("image_path") or "")
        try:
            if existing and Path(existing).exists() and Path(existing).stat().st_size > 512:
                paths[i] = existing
                db.update_scene(sc["id"], image_path=existing, status="image")
                if on_progress:
                    await on_progress(i + 1, len(scenes), "cache")
                return
        except OSError:
            pass
        async with sem:
            path, method = await generate_scene_image(sc, project, i,
                                                      ref_image=ref_image)
            paths[i] = str(path)
            db.update_scene(sc["id"], image_path=str(path), status="image")
            if on_progress:
                await on_progress(i + 1, len(scenes), method)

    if not scenes:
        return paths

    # Ancla primero (secuencial): decide la identidad visual del proyecto.
    await one(0, scenes[0])
    ref = _reference_bytes(paths[0]) if use_ref else None
    if ref:
        log.info("style reference activa (ancla: %s) para %d escenas",
                 paths[0], len(scenes) - 1)
    await asyncio.gather(*(one(i, sc, ref_image=ref)
                           for i, sc in enumerate(scenes) if i > 0))
    return paths
