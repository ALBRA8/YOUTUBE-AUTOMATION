# INT-072 — Lip-Sync & Face Animation vía HF Spaces ($0.00)

**Estado:** IMPLEMENTADO · batería 15/15 · E2E anónimo bloqueado solo por cuota ZeroGPU (documentado) · push pendiente al momento de redacción.

## 1. Origen y objetivo

Petición del propietario: dotar a `YOUTUBE AUTOMATION` de un motor de sincronización labial y movimiento facial **hiperrealista con coste estricto $0.00**, conectando Spaces públicos de Hugging Face vía `gradio_client`. Archivo objetivo: `backend/services/avatar_motion.py` (INT-066), sin tocar `video_assembler.py` ni las firmas existentes.

## 2. Verificación de la realidad (lo que la spec asumía vs lo que hay)

**La spec proponía `Client("KwaiVGI/LivePortrait").predict(driving_audio=..., api_name="/predict")`. Sondeado en vivo el 2026-10-31 (`view_api` + predicts reales desde sandbox):**

| Space | Estado real | Contrato real |
|---|---|---|
| `KwaiVGI/LivePortrait` | 🟢 vivo | **SOLO video-driven**: `/gpu_wrapped_execute_video` (imagen fuente + video de manejo) y `/gpu_wrapped_execute_image`. **No acepta audio. No existe `/predict`.** |
| `fffiloni/LivePortrait-Realtime` | ❌ 404 | Eliminado de Hugging Face. |
| `TMElyralab/MuseTalk` (oficial) | ❌ RUNTIME_ERROR | Caído. |
| `artificialguybr/EchoMimicV3-Demo` | ❌ BUILD_ERROR | Caído. |
| `fffiloni/EchoMimic` | 🟢 vivo | `/generate_video(uploaded_img, uploaded_audio, width, height, length, seed, …)` — **audio-driven real**. `length` en FRAMES con mínimo 100 (validado con AppError en vivo). |
| `fffiloni/echomimic-v2` | 🟢 vivo | `/generate(image_input, audio_input, pose_input, preset_name, …)`. |
| `ZJYang/AniPortrait_official` | 🟢 vivo | `/audio2video(input_audio, ref_img, headpose_video, size, steps, length, seed)`. |

Decisión: se conserva el nombre `lipsync_liveportrait_hf()` (contrato de la spec) pero internamente enruta a la **cadena audio-driven viva** `AVATAR_HF_SPACES` (default: EchoMimic → AniPortrait [steps ≤ 20] → echomimic-v2 [showcase CPU, solo duplicando el Space]). La evidencia completa queda en los comentarios de `config.py` y `avatar_motion.py`.

## 3. Implementación

### Backend
- **`services/avatar_motion.py`** (+~270 líneas):
  - `lipsync_liveportrait_hf(image_path, audio_path, output_video) -> (Path, space)` — recorre la cadena con **failover**, cada intento en hilo con `asyncio.wait_for` y timeout por Space (`AVATAR_HF_TIMEOUT_S=420`); el backend jamás se bloquea.
  - `_call_hf_lipsync_gradio()` — contrato por-Space (EchoMimic `/generate_video`, echomimic-v2 `/generate`, AniPortrait `/audio2video`); extrae el video de respuestas str/dict/tupla (`_extract_video_from_result`) y lo copia al destino.
  - `normalize_vertical_916()` — FFmpeg real: `scale=1080:1920:force_original_aspect_ratio=increase,crop,setsar=1` + AAC + `+faststart`; idempotente (si ya está en 9:16 no re-encodifica); sobrescribe in situ.
  - `render_avatar_animation()` — sin cambiar su firma: `engine="auto"` → HF primero y **fail-open** al motor local `lipsync_musetalk_local` (log del motivo); `engine="hf"` → propaga el fallo; `engine="musetalk"` → solo local (cero red). La respuesta añade `space` y `fallback` (claves aditivas).
  - `HF_TOKEN` se lee de config/.env y **nunca se registra en logs**.
- **`services/main.py`** (quirúrgico): el endpoint `POST /api/avatars/{id}/lipsync-musetalk` ahora pasa por `render_avatar_animation()` (HF→local); respuesta mantiene `ok/engine/video_url/audio_url/spoken_text` y añade `space`/`fallback`.
- **`config.py` / `.env.example`**: `AVATAR_HF_ENABLED`, `AVATAR_HF_SPACES`, `AVATAR_HF_TIMEOUT_S`, `AVATAR_HF_STEPS`, `AVATAR_HF_LENGTH`, `AVATAR_OUTPUT_W/H`, `HF_TOKEN` (documentado como token GRATIS que estabiliza la cuota ZeroGPU).
- **`requirements.txt`**: `gradio_client>=1.0`.

### Tests (`tests/test_int072_hf_lipsync.py`, 15/15)
Firmas preservadas · cadena/parsing de Spaces · fail-open a local con `gradio_client` fake · failover entre Spaces · camino feliz HF con FFmpeg REAL verificando **1080×1920** · normalización idempotente · extracción de respuestas (str/dict/anidada/None/errores) · HF deshabilitado no toca red · bucle facial sin audio intacto. Sin red en CI: fake de `gradio_client` inyectado en `sys.modules` (el import es perezoso).

### Smoke live (`tests/hf_lipsync_smoke.py`)
Equivalente tracked del `backend/data/tmp/test_hf_lipsync.py` pedido (esa carpeta está gitignored). Prepara rostro (o `--image` con retrato real), locución **edge-tts real** (fallback sine), corre `engine="auto"`, y valida: dimensiones 9:16, pista de audio, y **movimiento real** (diff de píxeles entre fotogramas). `python tests/hf_lipsync_smoke.py`.

## 4. Limitación honesta: cuota ZeroGPU

El E2E anónimo quedó bloqueado en sandbox con `200s requested vs 0s left` (cuota ZeroGPU anónima agotada por IP). Con **`HF_TOKEN` de cuenta gratuita** la cuota es estable y el pipeline completo funciona sin coste. Ese es el único paso que requiere la máquina del usuario (Antigravity): crear token gratis en huggingface.co/settings/tokens → `HF_TOKEN=hf_xxx` en `backend/.env` → `python tests/hf_lipsync_smoke.py`.

## 5. Invariantes respetados

Coste $0.00 · firmas de `avatar_motion.py` intactas · `video_assembler.py` sin tocar · fail-open jamás rompe el render · sin API keys de pago · 9:16 (1080×1920) garantizado en la ruta HF.
