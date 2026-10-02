"""
YOUTUBE AUTOMATION v2.0 — Cliente NVIDIA NIM (agente VÓRTICE v3, v2.12.0)
Endpoint OpenAI-compatible: https://integrate.api.nvidia.com/v1/chat/completions

Diseño probado contra la API real (2026-10):
- SSE streaming SIEMPRE: los modelos pesados tardan en producir el primer
  byte; con stream el timeout de lectura se aplica ENTRE chunks y detecta
  cuelgues sin matar respuestas largas.
- Cadena de failover con caché de salud en memoria: si el modelo preferido
  (kimi-k3) cuelga o no existe para la cuenta, el agente sigue con el
  siguiente de la cadena SIN tocar nada — misma filosofía $0/graceful
  del resto del sistema. Tras 15 min se reintenta el preferido por si
  NVIDIA lo recuperó.
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
# mientras el modelo en caché esté "fresco" no se reintenta el preferido
_HEALTH_TTL = 900.0

_THINK_RE = re.compile(r"<think>.*?</think>", re.S)

_HEALTH = {"model": None, "ts": 0.0}


def available() -> bool:
    return bool(config.NVIDIA_API_KEY)


def last_model() -> str:
    """Modelo que respondió la última llamada completa (para el badge UI)."""
    return _HEALTH["model"] or config.NVIDIA_MODEL


def _chain() -> list[str]:
    seen, out = set(), []
    for m in [config.NVIDIA_MODEL, *getattr(config, "NVIDIA_FALLBACK_MODELS", [])]:
        m = (m or "").strip()
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


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


async def complete(messages: list[dict], temperature: float = 0.3,
                   max_tokens: int = 4096) -> str:
    """Texto final del modelo con failover por toda la cadena.
    Lanza RuntimeError si ningún modelo responde."""
    chain = _chain()
    healthy = _HEALTH["model"]
    if healthy in chain and time.time() - _HEALTH["ts"] < _HEALTH_TTL:
        chain = [healthy] + [m for m in chain if m != healthy]  # fast-path
    last_err: Exception | None = None
    for model in chain:
        try:
            txt = _clean(await _stream_once(model, messages, temperature, max_tokens))
            if not txt:
                raise RuntimeError("respuesta vacía")
            _HEALTH.update(model=model, ts=time.time())
            return txt
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.warning("NVIDIA %s falló (%s) — siguiente de la cadena",
                        model, str(e)[:120])
    raise RuntimeError(f"NVIDIA sin respuesta en toda la cadena: {last_err}")
