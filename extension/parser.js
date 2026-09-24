/* =============================================================================
 * parser.js — Motores de Parseo de Prompts (manual 3.2 / 3.3)
 * -----------------------------------------------------------------------------
 * Convierte los objetos estructurados generados por el backend de Python
 * (ImagePrompt / VideoPrompt, contrato types.ts) en prompts de texto optimizados
 * para los modelos Imagen 3 / Veo dentro de Google Labs.
 *
 * Compartido: popup (via <script>) y background (via importScripts).
 * ========================================================================== */
'use strict';

function _parserCap(s) {
  s = String(s || '').trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

function _parserClean(s) {
  return String(s == null ? '' : s).trim();
}

/**
 * parseImagePromptToText(prompt: ImagePrompt): string
 * Formato de salida esperado (manual 3.3):
 *   Subjects: An adult athlete running.
 *   Environment: Real outdoor water obstacle course.
 *   Lighting: Natural bright daylight.
 *   Composition: Close-up, shot on Sony A7R IV.
 *   Style: Hyper-realistic documentary photography.
 */
function parseImagePromptToText(prompt) {
  if (!prompt) return '';
  if (typeof prompt === 'string') return _parserClean(prompt);
  const parts = [];
  const subjects = Array.isArray(prompt.subjects)
    ? prompt.subjects.map(_parserClean).filter(Boolean)
    : (_parserClean(prompt.subjects) ? [_parserClean(prompt.subjects)] : []);
  if (subjects.length) parts.push('Subjects: ' + subjects.join(' '));
  if (_parserClean(prompt.environment)) parts.push('Environment: ' + _parserClean(prompt.environment));
  if (_parserClean(prompt.lighting)) parts.push('Lighting: ' + _parserClean(prompt.lighting));
  if (_parserClean(prompt.composition)) parts.push('Composition: ' + _parserClean(prompt.composition));
  if (_parserClean(prompt.style)) parts.push('Style: ' + _parserClean(prompt.style));
  return parts.join('\n');
}

/**
 * parseVideoPromptToText(imagePrompt, videoPrompt?): string
 * Formato de salida esperado (manual 3.3):
 *   "Animate this image. Runner leaping onto inflatable ball.
 *    Slow cinematic zoom in. Base details: ..."
 */
function parseVideoPromptToText(imagePrompt, videoPrompt) {
  const base = parseImagePromptToText(imagePrompt);
  if (!videoPrompt) return 'Animate this image.\n' + base;
  const bits = ['Animate this image.'];
  const motion = _parserClean(videoPrompt.motion);
  if (motion) bits.push(motion.replace(/\.\s*$/, '') + '.');
  const cam = _parserClean(videoPrompt.camera_movement);
  if (cam) bits.push(_parserCap(cam.replace(/\.\s*$/, '')) + '.');
  if (base) bits.push('Base details: ' + base);
  return bits.join(' ');
}

/**
 * buildPromptForScene(scene, mode): string
 * Toma una escena del script.json (acepta camelCase y snake_case) y devuelve
 * el texto final a inyectar segun el tipo de contenido seleccionado.
 */
function buildPromptForScene(scene, mode) {
  if (!scene) return '';
  const img = scene.imagePrompt || scene.image_prompt || null;
  const vid = scene.videoPrompt || scene.video_prompt || null;
  let text = mode === 'videos'
    ? parseVideoPromptToText(img, vid)
    : parseImagePromptToText(img);
  if (!text) text = _parserClean(scene.prompt);
  // Recorte defensivo: prompts extremadamente largos pueden rechazarse en Flow.
  if (text.length > 1800) text = text.slice(0, 1800);
  return text.trim();
}

/* UMD-lite: permite probarlo con require() en Node sin romper el navegador. */
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { parseImagePromptToText, parseVideoPromptToText, buildPromptForScene };
}
