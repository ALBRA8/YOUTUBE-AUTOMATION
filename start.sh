#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════
#  ALBRA - START · experiencia "npm run dev" — Linux/Mac/WSL
#  ./start.sh  →  venv (con spinner) + salud de pip (ensurepip → recrear
#  .venv corrupto) + deps (barras reales, auto-reparación, upgrade pip)
#  + uvicorn --reload primer plano
#  Flags:  --fresh   fuerza reinstalar dependencias
# ════════════════════════════════════════════════════════════════
set -e
# salida sin buffer: pip/uvicorn en streaming, nunca parece congelado
export PYTHONUNBUFFERED=1
FRESH=0
[ "${1:-}" = "--fresh" ] && FRESH=1
cd "$(dirname "$0")/backend"

# ── verify_deps: 14 módulos de arranque vía find_spec (instantáneo) ──
verify_deps() {
    "$PY" - <<'PYEOF' 2>/dev/null
import importlib.util as u, sys
mods = ("fastapi uvicorn dotenv multipart httpx google.genai PIL apscheduler "
        "edge_tts yt_dlp googleapiclient google_auth_oauthlib faster_whisper "
        "av").split()
sys.exit(0) if all(u.find_spec(m) for m in mods) else sys.exit(1)
PYEOF
}

# [1/4] entorno virtual con SPINNER animado (solo la primera vez)
PY=.venv/bin/python
# ruedas binarias maduras primero: 3.12/3.11/3.10 antes que 3.13/3.14
PYBASE=$(command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3 || true)
[ -n "$PYBASE" ] || { echo "[ERROR] Python 3 no encontrado (instala python.org o apt)"; exit 1; }
if [ ! -x .venv/bin/python ]; then
    echo "[1/4] Preparando entorno virtual — avance abajo..."
    "$PYBASE" -m venv .venv & VP=$!
    SPIN='|/-\'; i=0
    while kill -0 "$VP" 2>/dev/null; do
        printf '\r  %c Creando entorno virtual — %ss transcurridos...   ' \
            "${SPIN:$((i % 4)):1}" "$i"
        i=$((i + 1)); sleep 1
    done
    if ! wait "$VP"; then
        printf '\r  [ERROR] No se pudo crear el entorno virtual.            \n'
        exit 1
    fi
    printf '\r  [OK] Entorno virtual creado — %ss                      \n' "$i"
else
    echo "[1/4] Entorno virtual OK — backend/.venv"
fi

# [1b/4] salud de pip: un .venv puede existir y aun así estar cojo (sin pip
# dentro, p.ej. creación interrumpida) → "No module named pip" al instalar.
if ! "$PY" -m pip --version >/dev/null 2>&1; then
    echo "  [AUTO-REPARACIÓN] pip falta o está roto en .venv — probando ensurepip..."
    "$PY" -m ensurepip --upgrade >/dev/null 2>&1 || true
fi
if ! "$PY" -m pip --version >/dev/null 2>&1; then
    echo "  [AUTO-REPARACIÓN] ensurepip falló: .venv corrupto — recreando desde cero..."
    rm -f .venv/.deps_ok
    rm -rf .venv
    "$PYBASE" -m venv .venv --upgrade-deps 2>/dev/null || { rm -rf .venv; "$PYBASE" -m venv .venv; } || {
        echo "[ERROR] No se pudo recrear el .venv (disco/permisos/antivirus)"; exit 1; }
    "$PY" -m pip --version >/dev/null 2>&1 || { echo "[ERROR] pip sigue sin responder tras recrear el .venv"; exit 1; }
fi

# [2/4] dependencias: marker sha256 + verificación 14 módulos + auto-reparación
SIG=$(sha256sum requirements.txt | cut -d' ' -f1)
OLD=""
[ -f .venv/.deps_ok ] && OLD=$(cat .venv/.deps_ok)
[ "$FRESH" = "1" ] && OLD="x"
NEED=1
if [ "$SIG" = "$OLD" ] && verify_deps; then
    echo "[2/4] Dependencias OK — 14/14 módulos verificados, instalación omitida"
    NEED=0
fi
if [ "$NEED" = "1" ]; then
    if [ "$SIG" = "$OLD" ]; then
        echo "[2/4] AVISO: entorno incompleto detectado — AUTO-REPARACIÓN..."
    else
        echo "[2/4] Instalando dependencias — solo la 1a vez o si requirements.txt cambió..."
    fi
    echo "  Actualizando pip del venv (evita cuelgues compilando wheels en Python 3.14)..."
    "$PY" -u -m pip install --upgrade pip --progress-bar on --disable-pip-version-check -v || \
        echo "  [AVISO] pip no se actualizó — continúo con el pip actual"
    "$PY" -u -m pip install --no-input --progress-bar on --prefer-binary --disable-pip-version-check -v -r requirements.txt
    if ! verify_deps; then
        echo "[ERROR] pip terminó pero faltan módulos. Ejecuta: ./start.sh --fresh"
        exit 1
    fi
    echo "$SIG" > .venv/.deps_ok
    echo "  [OK] 14/14 módulos verificados tras la instalación"
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
