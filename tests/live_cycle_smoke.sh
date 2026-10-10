#!/usr/bin/env bash
# CICLO COMPLETO REAL del Flow Bridge sobre HTTP vivo (sandbox aislado):
#   proyecto → escenas → enqueue → claim → complete(PNG real) → 409 doble
#   complete → 422 HTML → fail ×2 → guard de tipo → complete(MP4 real)
#   → project_done → auto-render → status → video_qa.
# La última escena es solo-imagen (contrato P1): 2 escenas → 3 jobs.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SANDBOX="${TMPDIR:-/tmp}/yt_cycle_smoke_$$"
PORT=${CYCLE_SMOKE_PORT:-8766}
BASE="http://127.0.0.1:$PORT"
DBF="$SANDBOX/backend/data/yt_automation.db"
WORK="$SANDBOX/work"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ✗ FALLO: $1"; }

jget() { python3 -c "
import sys, json
d = json.load(sys.stdin)
for k in '$1'.split('.'):
    d = d[k] if isinstance(d, dict) else d[int(k)]
print(json.dumps(d) if isinstance(d,(dict,list)) else d)
"; }

rm -rf "$SANDBOX"; mkdir -p "$SANDBOX" "$WORK"
cp -r "$REPO/backend" "$SANDBOX/backend"
find "$SANDBOX/backend" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
rm -rf "$SANDBOX/backend/data"
python3 -c "
from PIL import Image
Image.new('RGB', (640, 360), (30, 120, 200)).save('$WORK/escena.png')
"
ffmpeg -loglevel error -f lavfi -i testsrc=duration=1:size=320x240:rate=10 \
       -pix_fmt yuv420p -y "$WORK/escena.mp4"
# [execution-contract v1] clip de video CUMPLE el contrato del job de la
# escena 1 (duration 2.0 insertada en DB → spec requested=2.0; format short
# → aspect 9:16): complete() valida REQUESTED vs ACTUAL con ffprobe.
ffmpeg -loglevel error -f lavfi -i testsrc=duration=2:size=720x1280:rate=10 \
       -pix_fmt yuv420p -y "$WORK/video.mp4"
[ -s "$WORK/escena.png" ] && [ -s "$WORK/escena.mp4" ] && [ -s "$WORK/video.mp4" ] \
    && ok "assets de prueba generados (PNG + MP4 reales + MP4 conforme al contrato)" \
    || { bad "no se pudieron generar assets"; exit 1; }

echo "── 1. servidor vivo"
cd "$SANDBOX/backend"
python3 -m uvicorn main:app --host 127.0.0.1 --port "$PORT" > "$SANDBOX/server.log" 2>&1 &
SPID=$!
UP=0
for _ in $(seq 1 40); do curl -s -o /dev/null -m 1 "$BASE/docs" && { UP=1; break; }; sleep 0.5; done
[ "$UP" = 1 ] && ok "uvicorn arriba" || { bad "sin servidor"; head -20 "$SANDBOX/server.log"; exit 1; }

echo "── 2. proyecto + escenas reales en DB del sandbox"
PID=$(curl -s -X POST "$BASE/api/projects" -H "Content-Type: application/json" \
      -d '{"title":"ciclo-completo","mode":"idea"}' | jget id)
[ -n "$PID" ] && ok "proyecto $PID" || { bad "sin proyecto"; kill $SPID; exit 1; }
python3 - "$DBF" "$PID" <<'PY'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
for i in (0, 1):
    con.execute("""INSERT INTO scenes(id, project_id, idx, title, narration,
        image_prompt, duration, status, meta) VALUES(?,?,?,?,?,?,?,?,?)""",
        (f"sc{i}", sys.argv[2], i, f"Escena {i+1}", f"Narración {i+1}",
         "plano de prueba cinematográfico", 2.0, "pending", "{}"))
con.commit(); con.close()
PY
ok "2 escenas insertadas en DB sandbox"

echo "── 3. enqueue desde build_script_json (fuente única)"
ENQ=$(curl -s -X POST "$BASE/api/extension/flow/jobs/enqueue" \
      -H "Content-Type: application/json" -d "{\"project_id\":\"$PID\",\"fmt\":\"transformacion\"}")
N=$(echo "$ENQ" | jget created 2>/dev/null)
[ "$N" = "3" ] && ok "enqueue creó 3 jobs (2 imagen + 1 video; última escena solo-imagen)" || bad "enqueue: $ENQ"

echo "── 4. claim + complete con PNG real"
J1=$(curl -s "$BASE/api/extension/flow/jobs/next?worker=w-ciclo" | jget job)
ID1=$(echo "$J1" | jget id); TK1=$(echo "$J1" | jget job_token); KIND1=$(echo "$J1" | jget kind); SN1=$(echo "$J1" | jget scene_number)
[ "$KIND1" = "image" ] && [ "$SN1" = "1" ] && ok "claim 1: imagen escena 1 (orden correcto)" || bad "claim 1: $J1"
C1=$(curl -s -w "\n%{http_code}" -X POST "$BASE/api/extension/flow/jobs/$ID1/complete?token=$TK1" \
     -H "Content-Type: image/png" --data-binary @"$WORK/escena.png")
echo "$C1" | tail -1 | grep -q 200 && echo "$C1" | head -1 | grep -q "Escena_01_flow.png" \
    && ok "complete imagen → 200, asset en convención canónica" \
    || bad "complete imagen: $C1"

echo "── 5. doble complete → 409 (token de una sola era)"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/extension/flow/jobs/$ID1/complete?token=$TK1" \
       -H "Content-Type: image/png" --data-binary @"$WORK/escena.png")
[ "$CODE" = "409" ] && ok "doble complete rechazado con 409" || bad "esperaba 409, llegó $CODE"

echo "── 6. imagen escena 2: HTML → 422 → fail ×2 → guard de tipo → PNG real"
J2=$(curl -s "$BASE/api/extension/flow/jobs/next?worker=w-ciclo" | jget job)
ID2=$(echo "$J2" | jget id); TK2=$(echo "$J2" | jget job_token)
[ "$(echo "$J2" | jget kind)" = "image" ] && [ "$(echo "$J2" | jget scene_number)" = "2" ] \
    && ok "claim 2: imagen escena 2 (imagen antes que video)" || bad "claim 2: $J2"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/extension/flow/jobs/$ID2/complete?token=$TK2" \
       -H "Content-Type: text/html" --data-binary "<html>Error de Flow</html>")
[ "$CODE" = "422" ] && ok "HTML basura rechazado con 422" || bad "esperaba 422, llegó $CODE"
F=$(curl -s -X POST "$BASE/api/extension/flow/jobs/$ID2/fail?token=$TK2" -H "Content-Type: application/json" -d '{"error":"html no válido"}')
echo "$F" | grep -q '"status": *"queued"' && ok "fail 1/3 → vuelve a queued" || bad "fail: $F"
J3=$(curl -s "$BASE/api/extension/flow/jobs/next?worker=w-ciclo" | jget job)
ID3=$(echo "$J3" | jget id); TK3=$(echo "$J3" | jget job_token)
[ "$ID3" = "$ID2" ] && ok "re-claim devuelve el MISMO job" || bad "re-claim distinto: $J3"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/extension/flow/jobs/$ID3/complete?token=$TK3" \
       -H "Content-Type: video/mp4" --data-binary @"$WORK/escena.mp4")
[ "$CODE" = "422" ] && ok "guard de tipo: MP4 en job de imagen → 422" || bad "guard de tipo: esperaba 422, llegó $CODE"
curl -s -X POST "$BASE/api/extension/flow/jobs/$ID3/fail?token=$TK3" -H "Content-Type: application/json" \
     -d '{"error":"asset de otro tipo"}' | grep -q '"attempts": *2' \
    && ok "fail 2/3 → attempts=2, aún queued (imagen tolera 3)" || bad "fail 2 no acumuló attempts"
J4=$(curl -s "$BASE/api/extension/flow/jobs/next?worker=w-ciclo" | jget job)
ID4=$(echo "$J4" | jget id); TK4=$(echo "$J4" | jget job_token)
C4=$(curl -s -w "\n%{http_code}" -X POST "$BASE/api/extension/flow/jobs/$ID4/complete?token=$TK4" \
     -H "Content-Type: image/png" --data-binary @"$WORK/escena.png")
echo "$C4" | tail -1 | grep -q 200 && echo "$C4" | head -1 | grep -q "Escena_02_flow.png" \
    && ok "complete imagen escena 2 → 200" || bad "complete imagen 2: $C4"

echo "── 7. último job (video escena 1) → project_done + auto-render"
J=$(curl -s "$BASE/api/extension/flow/jobs/next?worker=w-ciclo" | jget job)
ID=$(echo "$J" | jget id); TK=$(echo "$J" | jget job_token)
echo "$J" | grep -q '"kind": *"video"' && ok "claim final: video escena 1" || bad "claim final: $J"
LAST=$(curl -s -X POST "$BASE/api/extension/flow/jobs/$ID/complete?token=$TK" -H "Content-Type: video/mp4" --data-binary @"$WORK/video.mp4")
echo "$LAST" | grep -q '"project_done": *true' && ok "último complete → project_done=true" || bad "project_done: $LAST"
echo "$LAST" | grep -q '"renderable": *true' && ok "assets mapeados a escenas → renderable=true" || bad "renderable: $LAST"
echo "$LAST" | grep -q '"auto_render": *true' && ok "auto-render disparado (orchestrator)" || bad "auto_render: $LAST"

echo "── 8. estado final + video QA"
ST=$(curl -s "$BASE/api/extension/flow/jobs/status/$PID")
echo "$ST" | python3 -c "
import sys, json
c = json.load(sys.stdin)['counts']
assert c == {'queued':0,'claimed':0,'done':3,'dead':0}, c
" && ok "status final: 3 done, 0 pendientes, 0 dead" || bad "status: $ST"
QA=$(curl -s "$BASE/api/video_qa/$PID")
echo "$QA" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['ok'] and d['summary']['scenes'] == 2, d
print(d['status'])
" > "$WORK/qa_status" && ok "video_qa sobre assets reales (status: $(cat "$WORK/qa_status"))" || bad "video_qa: $QA"

echo "── 9. limpieza"
curl -s -X DELETE "$BASE/api/projects/$PID" > /dev/null
kill $SPID 2>/dev/null; wait $SPID 2>/dev/null
if grep -qi traceback "$SANDBOX/server.log"; then
  # los tracebacks del render de fondo son esperados en sandbox (sin TTS);
  # un traceback es "real" si su BLOQUE completo no menciona el render
  python3 - "$SANDBOX/server.log" <<'PY'
import re, sys
log = open(sys.argv[1], encoding="utf-8", errors="replace").read()
blocks = re.findall(
    r"Traceback \(most recent call last\):.*?(?=\nTraceback |\n?\Z)",
    log, re.S)
HINTS = ("_run_flow_render", "orchestrator", "tts", "edge_tts",
         "Preflight de producto", "start_flow_render")
reales = [b for b in blocks if not any(h in b for h in HINTS)]
sys.exit(1 if reales else 0)
PY
  if [ $? -eq 0 ]; then
    ok "solo tracebacks del render de fondo (esperado: sandbox sin claves TTS)"
  else
    bad "traceback NO relacionado con render de fondo:"
    grep -n -A6 -i traceback "$SANDBOX/server.log" | head -24
  fi
else
  ok "server.log sin tracebacks"
fi
rm -rf "$SANDBOX"

echo
echo "═══ $PASS OK · $FAIL fallos ═══"
exit $FAIL
