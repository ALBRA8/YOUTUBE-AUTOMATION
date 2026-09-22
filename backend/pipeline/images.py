"""
YOUTUBE AUTOMATION v2.0 — Paso 2: Imágenes HÍBRIDAS
1. Primario: Gemini 2.5 Flash Image (gratis ~500/día con key estándar)
2. Plan B:   cola de la extensión Chrome (ImageFX automatizado) si Gemini falla
3. Plan C:   placeholder degradado con PIL para no bloquear el render
"""
import asyncio
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


def scene_dir(project_id: str) -> Path:
    d = OUTPUT_DIR / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def full_prompt(scene: dict, project: dict) -> str:
    style = get_style(project["style"])
    custom = (project.get("meta") or {}).get("custom_style_prompt")
    style_desc = custom or style["prompt"]
    extra = ", no text, no letters, no watermark"
    # Consistencia de personaje: si el proyecto tiene avatar, fijamos su
    # apariencia (traducida a inglés por el schema PRO) en TODOS los prompts
    # para que el personaje sea igual en cada escena.
    avatar = (project.get("meta") or {}).get("avatar") or None
    if avatar:
        extra += (", " + avatar_schema.scene_suffix(avatar))
    return f"{scene['image_prompt']}, {style_desc}{extra}"


async def generate_scene_image(scene: dict, project: dict, idx: int) -> tuple[Path, str]:
    """Devuelve (ruta_imagen, método_usado)."""
    out = scene_dir(project["id"]) / f"scene_{idx:02d}.png"
    prompt = full_prompt(scene, project)

    # 1) Gemini 2.5 Flash Image
    if gemini_client.available():
        try:
            data = await gemini_client.generate_image(prompt)
            out.write_bytes(data)
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
            return out, "extension"
        except Exception as e:  # noqa: BLE001
            log.warning("Imagen de extensión falló: %s", e)

    # 3) Plan C: placeholder elegante
    _placeholder(out, scene, project, idx)
    return out, "placeholder"


def _placeholder(out: Path, scene: dict, project: dict, idx: int) -> None:
    if not PIL_OK:
        out.write_bytes(b"")
        return
    from services.themes import STYLES
    grad = next((s["grad"] for s in STYLES if s["id"] == project["style"]), "#333")
    c1, c2 = grad.replace("linear-gradient(135deg,", "").rstrip(")").split(",")
    img = Image.new("RGB", (1080, 1920), c1.strip())
    draw = ImageDraw.Draw(img)
    c2rgb = tuple(int(c2.strip().lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    for y in range(1920):
        t = y / 1920
        rgb = tuple(int(int(c1.strip().lstrip("#")[i:i + 2], 16) * (1 - t) + c2rgb[i] * t)
                    for i in range(3))
        draw.line([(0, y), (1080, y)], fill=rgb)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)


async def generate_all(project: dict, scenes: list[dict], on_progress=None,
                       is_cancelled=None) -> list[str]:
    """Genera las imágenes de todas las escenas (2 en paralelo)."""
    paths: list[str] = ["" for _ in scenes]
    sem = asyncio.Semaphore(2)

    async def one(i, sc):
        if is_cancelled and is_cancelled():
            return
        async with sem:
            path, method = await generate_scene_image(sc, project, i)
            paths[i] = str(path)
            db.update_scene(sc["id"], image_path=str(path), status="image")
            if on_progress:
                await on_progress(i + 1, len(scenes), method)

    await asyncio.gather(*(one(i, sc) for i, sc in enumerate(scenes)))
    return paths
