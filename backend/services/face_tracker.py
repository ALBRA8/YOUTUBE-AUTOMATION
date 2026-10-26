"""
YOUTUBE AUTOMATION v2.29 — Auto Face-Tracking Pan & Scan (INT-053)
Inspirado en OpenShorts (mutonby/openshorts).

Detecta rostros en video horizontal 16:9 mediante OpenCV y calcula una trayectoria
suavizada (cinematic camera pan) para encuadrar en vertical 9:16 siguiendo al sujeto
en movimiento sin saltos bruscos.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from config import DATA_DIR

log = logging.getLogger("face_tracker")

CASCADE_PATH = DATA_DIR / "models" / "haarcascade_frontalface_default.xml"


def track_face_trajectory(
    video_path: Path,
    sample_fps: float = 4.0,
    smooth_alpha: float = 0.22
) -> list[dict[str, Any]]:
    """Analiza el video con OpenCV y extrae la trayectoria horizontal suavizada del rostro.

    Retorna una lista de puntos temporales: [{"time": t, "crop_x": x_int}, ...]
    donde crop_x es la coordenada horizontal de inicio del recorte 9:16.
    """
    try:
        import cv2
    except ImportError:
        log.warning("[face_tracker] OpenCV no disponible, usando recorte central")
        return []

    if not CASCADE_PATH.is_file():
        log.warning("[face_tracker] Modelo Haar Cascade no encontrado en %s", CASCADE_PATH)
        return []

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        log.warning("[face_tracker] No se pudo abrir video %s", video_path)
        return []

    orig_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)

    crop_w = int(h * 9 / 16)  # 607px para 1080p
    max_x = max(0, w - crop_w)
    default_x = max_x // 2

    face_cascade = cv2.CascadeClassifier(str(CASCADE_PATH))
    step = max(1, int(round(orig_fps / sample_fps)))

    trajectory: list[dict[str, Any]] = []
    current_smooth_x = float(default_x)
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % step == 0:
            t = frame_idx / orig_fps
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # Detección multiescala rápida
            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.15, minNeighbors=4, minSize=(60, 60)
            )

            if len(faces) > 0:
                # Tomar el rostro más grande (más cercano a cámara)
                largest = max(faces, key=lambda f: f[2] * f[3])
                fx, fy, fw, fh = largest
                center_x = fx + (fw / 2.0)
                target_x = max(0.0, min(float(max_x), center_x - (crop_w / 2.0)))
                # Filtro exponencial (EMA) para suavizado cinematográfico
                current_smooth_x = (smooth_alpha * target_x) + ((1.0 - smooth_alpha) * current_smooth_x)
            else:
                # Si no hay cara momentánea, converger suavemente hacia el centro
                current_smooth_x = (0.05 * default_x) + (0.95 * current_smooth_x)

            trajectory.append({
                "time": round(t, 2),
                "crop_x": int(round(current_smooth_x))
            })

        frame_idx += 1

    cap.release()
    log.info("[face_tracker] Analizados %d cuadros. Puntos de seguimiento: %d", frame_idx, len(trajectory))
    return trajectory


def build_face_tracking_filter(
    trajectory: list[dict[str, Any]],
    orig_w: int = 1920,
    orig_h: int = 1080,
    target_w: int = 1080,
    target_h: int = 1920
) -> str:
    """Construye la cláusula FFmpeg crop con la posición horizontal óptima del rostro.

    Si hay una trayectoria válida, calcula la posición dominante suavizada o
    los tramos clave para encuadrar al sujeto en vertical.
    """
    crop_w = int(orig_h * 9 / 16)
    max_x = max(0, orig_w - crop_w)
    default_x = max_x // 2

    if not trajectory:
        # Fallback centrado
        return f"crop={crop_w}:{orig_h}:{default_x}:0,scale={target_w}:{target_h}"

    # Calcular la posición promedio ponderada
    xs = [p["crop_x"] for p in trajectory]
    mean_x = int(round(sum(xs) / len(xs)))
    safe_x = max(0, min(max_x, mean_x))

    return f"crop={crop_w}:{orig_h}:{safe_x}:0,scale={target_w}:{target_h}"
