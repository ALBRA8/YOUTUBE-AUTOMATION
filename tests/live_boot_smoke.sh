#!/usr/bin/env bash
# BOOT SMOKE REAL: arranca uvicorn sobre una copia aislada del backend y
# golpea los endpoints por HTTP real. Detecta fallos que los tests ASGI en
# memoria no ven (startup, middleware, CORS, puertos, imports).
# Auto-localizante: sirve desde cualquier checkout del repo.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SANDBOX="${TMPDIR:-/tmp}/yt_boot_smoke_$$"
PORT=${BOOT_SMOKE_PORT:-8765}
BASE="http://127.0.0.1:$PORT"
PASS=0; FAIL=0

ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ FALLO: $1"; }

rm -rf "$SANDBOX"; mkdir -p "$SANDBOX"
cp -r "$REPO/backend" "$SANDBOX/backend"
find "$SANDBOX/backend" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
rm -rf "$SANDBOX/backend/data"

echo "── 1. arranque real de uvicorn (puerto $PORT)"
cd "$SANDBOX/backend"
python3 -m uvicorn main:app --host 127.0.0.1 --port "$PORT" > "$SANDBOX/server.log" 2>&1 &
SERVER_PID=$!
UP=0
for _ in $(seq 1 40); do
  curl -s -o /dev/null -m 1 "$BASE/docs" && { UP=1; break; }
  sleep 0.5
done
if [ "$UP" = "1" ]; then ok "uvicorn arrancó y sirve /docs"; else bad "uvicorn NO arrancó"; sed -n '1,40p' "$SANDBOX/server.log"; fi

if [ "$UP" = "1" ]; then
  echo "── 2. CORS preflight desde extensión Chrome"
  HDRS=$(curl -s -i -X OPTIONS "$BASE/api/extension/flow/jobs/next" \
      -H "Origin: chrome-extension://abcdefg" \
      -H "Access-Control-Request-Method: GET" \
      -H "Access-Control-Request-Headers: x-api-key,content-type")
  echo "$HDRS" | head -1 | grep -q "200\|204" && ok "OPTIONS preflight 2xx" || bad "preflight CORS: $(echo "$HDRS" | head -1)"
  echo "$HDRS" | grep -qi "access-control-allow-origin" && ok "header allow-origin presente" || bad "falta allow-origin"

  echo "── 3. proyecto real vía API"
  PID=$(curl -s -X POST "$BASE/api/projects" -H "Content-Type: application/json" \
        -d '{"title":"boot-smoke","mode":"idea"}' | python3 -c "import sys,json;print(json.load(sys.stdin).get('id',''))")
  [ -n "$PID" ] && ok "proyecto creado: $PID" || bad "no se pudo crear proyecto"

  echo "── 4. Flow Bridge por HTTP real"
  ST=$(curl -s "$BASE/api/extension/flow/jobs/status/$PID")
  echo "$ST" | python3 -c "import sys,json;d=json.load(sys.stdin);assert d['ok'] and d['counts']=={'queued':0,'claimed':0,'done':0,'dead':0}" \
      && ok "status inicial vacío y ok" || bad "status inesperado: $ST"
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/extension/flow/jobs/next?worker=w-smoke")
  [ "$CODE" = "204" ] && ok "next con cola vacía → 204" || bad "next esperaba 204, llegó $CODE"
  ENQ=$(curl -s -X POST "$BASE/api/extension/flow/jobs/enqueue" -H "Content-Type: application/json" \
        -d "{\"project_id\":\"$PID\"}")
  echo "$ENQ" | grep -q "escenas" && ok "enqueue sin escenas → error 400 con detalle" || bad "enqueue sin escenas: $ENQ"

  echo "── 5. observabilidad + video QA en vivo"
  MET=$(curl -s "$BASE/api/metrics")
  echo "$MET" | python3 -c "import sys,json;d=json.load(sys.stdin);assert 'projects' in d and 'flow_queue' in d" \
      && ok "GET /api/metrics con agregados" || bad "metrics: $MET"
  QA=$(curl -s "$BASE/api/video_qa/$PID")
  echo "$QA" | python3 -c "import sys,json;d=json.load(sys.stdin);assert d['ok'] and d['status'] in ('ok','warn','error') and 'summary' in d" \
      && ok "GET /api/video_qa/{pid} responde sin reventar" || bad "video_qa: $QA"

  echo "── 6. limpieza del proyecto de humo"
  [ -n "$PID" ] && curl -s -X DELETE "$BASE/api/projects/$PID" > /dev/null && ok "proyecto de humo borrado"
fi

kill $SERVER_PID 2>/dev/null; wait $SERVER_PID 2>/dev/null
if grep -qi "traceback" "$SANDBOX/server.log"; then
  bad "traceback en server.log:"; grep -n -A 5 -i traceback "$SANDBOX/server.log" | head -20
else
  ok "server.log sin tracebacks"
fi
rm -rf "$SANDBOX"

echo
echo "═══ $PASS OK · $FAIL fallos ═══"
exit $FAIL
