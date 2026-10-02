"""
YOUTUBE AUTOMATION v2.0 — Cliente NVIDIA NIM (agente VÓRTICE, v2.12.1 CEREBROS)
Endpoint OpenAI-compatible: https://integrate.api.nvidia.com/v1/chat/completions

v2.12.1 · CEREBROS: el usuario elige con qué modelo piensa VÓRTICE (como los
"cerebros" de OpenClaw). Catálogo construido probando el catálogo REAL de la
clave contra /v1/models (2026-10): muchos nombres conocidos ya dan 410 Gone o
404, así que solo entran los que respondieron en vivo.

Diseño probado contra la API real:
- SSE streaming SIEMPRE: los modelos pesados tardan en producir el primer
  byte; con stream el timeout de lectura se aplica ENTRE chunks y detecta
  cuelgues sin matar respuestas largas.
- Salud POR MODELO en memoria (ok/latencia/error): el cerebro elegido va
  primero y los sanos se adelantan al resto; kimi-k3 caído no bloquea nada.
- Multimodal: los mensajes pueden traer content tipo lista
  ([{type:text},{type:image_url}]) — los cerebros con vision=True lo soportan.
- Los modelos de razonamiento pueden emitir <think>…</think> inline o
  reasoning_content; el contenido final se limpia de los dos.
"""
import json
import logging
import re
import time

import httpx

import config

log = logging.getLogger("nvidia")

# presupuesto de lectura por intento (segundos sin recibir NINGÚN byte/chunk)
_ATTEMPT_READ_TIMEOUT = 25.0
# tope total de una respuesta (protección ante streams infinitos)
_OVERALL_DEADLINE = 110.0
# mientras un modelo esté "ok" en caché no se re-prueba su estado
_HEALTH_TTL = 900.0

_THINK_RE = re.compile(r"<think>.*?</think>", re.S)

# ─────────────────────────── catálogo CEREBROS (v2.12.1) ──────────────────
# Cada entrada fue PROBADA en vivo contra la API (scripts/test_nvidia_models2.py).
# order = orden por defecto de la cadena de failover.
CEREBROS: list[dict] = [
    {"alias": "deepseek", "model": "deepseek-ai/deepseek-v4.1-flash",
     "name": "DeepSeek Flash", "emoji": "⚡",
     "desc": "El motor diario: fiable, buen JSON", "vision": False},
    {"alias": "gpt-oss", "model": "openai/gpt-oss-20b",
     "name": "GPT-OSS 20B", "emoji": "🚀",
     "desc": "Ultrarrápido (~1s), JSON limpio", "vision": False},
    {"alias": "llama-11b", "model": "meta/llama-3.2-11b-vision-instruct",
     "name": "Llama 11B Visión", "emoji": "👁️",
     "desc": "Ve imágenes (capturas, miniaturas), velocista", "vision": True},
    {"alias": "llama-90b", "model": "meta/llama-3.2-90b-vision-instruct",
     "name": "Llama 90B Visión", "emoji": "🔎",
     "desc": "Visión premium: análisis fino de imágenes", "vision": True},
    {"alias": "nemotron", "model": "nvidia/nemotron-3-super-120b-a12b",
     "name": "Nemotron 120B", "emoji": "🧠",
     "desc": "Cerebro grande de NVIDIA, razona bien", "vision": False},
    {"alias": "kimi-k3", "model": "moonshotai/kimi-k3",
     "name": "Kimi K3", "emoji": "🌙",
     "desc": "El favorito de la casa (hoy NVIDIA lo tiene lento)", "vision": False},
]

# salud por modelo: model → {"ok": bool, "ts": float, "lat": float, "err": str}
_HEALTH: dict[str, dict] = {}
_LAST_OK: str | None = None   # último modelo que respondió una llamada completa


def available() -> bool:
    return bool(config.NVIDIA_API_KEY)


def last_model() -> str:
    """Último modelo que respondió una llamada completa (para el badge UI)."""
    return _LAST_OK or config.NVIDIA_MODEL


def find_cerebro(alias_or_model: str) -> dict | None:
    needle = (alias_or_model or "").strip()
    for c in CEREBROS:
        if needle in (c["alias"], c["model"]):
            return c
    return None


def cerebro_by_model(model: str) -> dict | None:
    return find_cerebro(model)


def active_cerebro() -> dict:
    """Cerebro correspondiente a config.NVIDIA_MODEL (o el 1º si es custom)."""
    c = cerebro_by_model(config.NVIDIA_MODEL)
    if c:
        return c
    return {"alias": "custom", "model": config.NVIDIA_MODEL, "name": config.NVIDIA_MODEL,
            "emoji": "🛠️", "desc": "modelo personalizado (.env)", "vision": False}


def list_cerebros() -> list[dict]:
    """Catálogo + estado vivo para la UI (verde/rojo/gris + latencia)."""
    out = []
    act = active_cerebro()["alias"]
    for c in CEREBROS:
        h = _HEALTH.get(c["model"]) or {}
        ok = h.get("ok")
        out.append({**c, "active": c["alias"] == act,
                    "status": "ok" if ok else ("fail" if ok is False else "untested"),
                    "latency": h.get("lat"), "error": (h.get("err") or "")[:120]})
    return out


def set_preferred(alias_or_model: str) -> dict:
    """Cambia el cerebro preferido (persistido en .env por el endpoint)."""
    c = find_cerebro(alias_or_model)
    model = c["model"] if c else alias_or_model
    config.NVIDIA_MODEL = model
    return cerebro_by_model(model) or active_cerebro()


def _base_chain() -> list[str]:
    """Cerebro preferido + resto del catálogo + fallbacks del .env."""
    seen, out = set(), []
    for m in [config.NVIDIA_MODEL, *[c["model"] for c in CEREBROS],
              *getattr(config, "NVIDIA_FALLBACK_MODELS", [])]:
        m = (m or "").strip()
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _chain(prefer: str | None = None) -> list[str]:
    """Orden de intento: cerebro pedido explícito (SIEMPRE primero) →
    preferido de config (salvo que esté recién caído en caché: entonces
    al final, para no pagar su timeout en cada mensaje) → sanos →
    sin probar → caídos recientes."""
    base = _base_chain()
    now = time.time()
    ok, untested, fail = [], [], []
    for m in base:
        h = _HEALTH.get(m) or {}
        if h.get("ok") and now - h.get("ts", 0) < _HEALTH_TTL:
            ok.append(m)
        elif h.get("ok") is False and now - h.get("ts", 0) < _HEALTH_TTL:
            fail.append(m)
        else:
            untested.append(m)
    ordered = ok + untested + fail
    p = (prefer or "").strip()
    if p:
        c = find_cerebro(p)
        pm = c["model"] if c else p
        ordered = [pm] + [m for m in ordered if m != pm]
    else:
        head = base[0]
        ordered = [m for m in ordered if m != head]
        ordered = [head] + ordered if head not in fail else ordered + [head]
    return ordered


async def _stream_once(model: str, messages: list[dict], temperature: float,
                       max_tokens: int) -> str:
    """Una llamada SSE a un modelo. Lanza excepción si no responde."""
    body = {"model": model, "messages": messages, "temperature": temperature,
            "max_tokens": max_tokens, "stream": True}
    timeout = httpx.Timeout(connect=10.0, read=_ATTEMPT_READ_TIMEOUT,
                            write=10.0, pool=10.0)
    parts: list[str] = []
    t0 = time.time()
    async with httpx.AsyncClient(timeout=timeout) as cli:
        async with cli.stream(
                "POST", config.NVIDIA_BASE_URL + "/chat/completions",
                headers={"Authorization": "Bearer " + config.NVIDIA_API_KEY,
                         "Accept": "text/event-stream"},
                json=body) as r:
            if r.status_code != 200:
                raw = (await r.aread()).decode("utf-8", "replace")[:160]
                raise RuntimeError(f"HTTP {r.status_code}: {raw}")
            async for line in r.aiter_lines():
                if time.time() - t0 > _OVERALL_DEADLINE:
                    raise RuntimeError("respuesta excedió el tope total")
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    d = json.loads(payload)
                except Exception:  # noqa: BLE001
                    continue
                delta = ((d.get("choices") or [{}])[0].get("delta") or {})
                c = delta.get("content")
                if c:
                    parts.append(c)
    return "".join(parts)


def _clean(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


def _mark(model: str, ok: bool, lat: float = 0.0, err: str = "") -> None:
    global _LAST_OK
    if ok:
        _LAST_OK = model
    _HEALTH[model] = {"ok": ok, "ts": time.time(), "lat": lat, "err": err}


async def complete(messages: list[dict], temperature: float = 0.3,
                   max_tokens: int = 4096, prefer: str | None = None) -> str:
    """Texto final del modelo con failover por toda la cadena.
    `prefer`: alias o model id que el usuario quiere usar (va primero).
    Lanza RuntimeError si ningún modelo responde."""
    chain = _chain(prefer)
    last_err: Exception | None = None
    for model in chain:
        t0 = time.time()
        try:
            txt = _clean(await _stream_once(model, messages, temperature, max_tokens))
            if not txt:
                raise RuntimeError("respuesta vacía")
            _mark(model, True, lat=round(time.time() - t0, 1))
            return txt
        except Exception as e:  # noqa: BLE001
            last_err = e
            _mark(model, False, lat=round(time.time() - t0, 1), err=str(e)[:160])
            log.warning("NVIDIA %s falló (%s) — siguiente de la cadena",
                        model, str(e)[:120])
    raise RuntimeError(f"NVIDIA sin respuesta en toda la cadena: {last_err}")
