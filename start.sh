#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════
#  ALBRA - START · experiencia "npm run dev" — Linux/Mac/WSL
#  ./start.sh  →  venv + deps + uvicorn --reload en primer plano
#  Flags:  --fresh   fuerza reinstalar dependencias
# ════════════════════════════════════════════════════════════════
set -e
FRESH=0
[ "${1:-}" = "--fresh" ] && FRESH=1
cd "$(dirname "$0")/backend"

# [1/4] entorno virtual (solo la primera vez)
if [ ! -x .venv/bin/python ]; then
    echo "[1/4] Creando entorno virtual backend/.venv — solo la primera vez..."
    python3 -m venv .venv
else
    echo "[1/4] Entorno virtual OK — backend/.venv"
fi
PY=.venv/bin/python

# [2/4] dependencias (solo si requirements.txt cambió — marker sha256)
SIG=$(sha256sum requirements.txt | cut -d' ' -f1)
OLD=""
[ -f .venv/.deps_ok ] && OLD=$(cat .venv/.deps_ok)
if [ "$FRESH" = "1" ]; then OLD="x"; fi
if [ "$SIG" != "$OLD" ]; then
    echo "[2/4] Instalando dependencias — solo la 1a vez o si requirements.txt cambió..."
    "$PY" -m pip install --disable-pip-version-check -r requirements.txt
    echo "$SIG" > .venv/.deps_ok
else
    echo "[2/4] Dependencias OK — sin cambios, instalación omitida"
fi

# [3/4] HOST/PORT desde .env (mismos defaults que config.py)
HOST=$(grep -E '^HOST=' .env 2>/dev/null | cut -d= -f2 | tr -d '"\r' || true)
PORT=$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2 | tr -d '"\r' || true)
HOST=${HOST:-127.0.0.1}
PORT=${PORT:-8000}
echo "[3/4] Config lista — HOST=$HOST PORT=$PORT"

# [4/4] servidor en PRIMER PLANO con hot-reload
echo "[4/4] ALBRA -> http://$HOST:$PORT  (Ctrl+C para detener)"
exec "$PY" -m uvicorn main:app --host "$HOST" --port "$PORT" --reload
