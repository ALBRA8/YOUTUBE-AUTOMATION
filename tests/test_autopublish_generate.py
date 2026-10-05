#!/usr/bin/env python3
"""Prueba hermética del DEFECTO autopublish en POST /api/projects/{pid}/generate.

Defecto P-2: con body {"autopublish": true}, los modos CONTRATO
(guion_json / production_json) nunca autopublican: en orchestrator._run la
variable local `result` SOLO se asigna en la rama else (script_gen,
L505); las ramas de contrato (L462/L473) no la crean y el PASO 6
(autopublicar, L601) la evalúa igual → NameError, capturado por el
except del propio PASO 6 (L609) → el proyecto queda "ready" (nunca
"published"), el video NO se pierde y el publicador jamás se invoca.

Causa fuera del alcance de P-2 (pipeline/orchestrator.py): el parche
mínimo propuesto al integrador es:
    + result = None                     (antes del PASO 1)
    - str(final), result["title"],      →  str(final), (result or project)["title"],
    - description=_description(result,  →  description=_description(result or {}, project),
La sonda _parche_aplicado() detecta ese parche: las secciones de contrato
(R/C/D2) validan el comportamiento VIGENTE (defecto) o el corregido
según esté aplicado o no, de modo que la batería queda verde antes Y
después del parche del integrador.

Técnica hermética (mismo patrón que test_lanzar_preflight.py):
- módulo `database` FAKE inyectado en sys.modules ANTES de importar la app;
- se ejecuta el _run REAL con los pasos pesados mockeados (imágenes, TTS,
  Whisper, FFmpeg, biblioteca) y el publicador YouTube SIEMPRE mockeado;
- el endpoint real POST /api/projects/{pid}/generate se ejercita vía
  httpx ASGITransport (sin uvicorn, sin red, sin lifespan/backups);
- únicas escrituras: data/output/s2auto_*/ (se limpian al final).

Uso:  python3 tests/test_autopublish_generate.py   ·   python3 -m pytest tests/
"""
import asyncio
import importlib
import logging
import shutil
import sys
import traceback
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
PIDS = []          # carpetas s2auto_* creadas bajo backend/data/output/
DURS = [3.0, 2.5]  # duraciones devueltas por el TTS mockeado


def _purge_app_modules():
    """Deja el entorno limpio para importar la app con la DB fake (orden-
    independiente dentro de un mismo proceso pytest)."""
    exactos = {"database", "config", "security", "main", "mcp_server"}
    for m in list(sys.modules):
        if m in exactos or m.split(".")[0] in ("pipeline", "services"):
            del sys.modules[m]


def _parche_aplicado() -> bool:
    """True si el integrador ya aplicó el parche BLOQUEO en orchestrator."""
    src = (BACKEND / "pipeline" / "orchestrator.py").read_text(encoding="utf-8")
    return ("(result or project)" in src) or ("if result else project" in src)


# ── módulo database FAKE (fiel a las firmas reales de database.py) ────────
class _FakeDB:
    def __init__(self):
        self.projects: dict[str, dict] = {}
        self.scenes: dict[str, list] = {}
        self.jobs: dict[str, dict] = {}
        self.create_job_calls: list[tuple] = []
        self._n = 0

    def _new_id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}_{self._n:04d}"

    def init_db(self):  # la app real llama a esto al importar database
        pass

    def create_project(self, **fields) -> dict:
        pid = fields.get("id") or self._new_id("proj")
        rec = {"id": pid, "title": "sin título", "mode": "idea",
               "style": "historias-reales", "format": "short",
               "status": "draft", "progress": 0, "meta": {}}
        rec.update(fields)
        self.projects[pid] = rec
        return dict(rec)

    def get_project(self, pid):
        rec = self.projects.get(pid)
        return dict(rec) if rec else None

    def update_project(self, pid, **kw):
        self.projects.setdefault(pid, {}).update(kw)

    def delete_project(self, pid):
        self.projects.pop(pid, None)

    def list_projects(self, limit=100):
        return [dict(p) for p in self.projects.values()][:limit]

    def replace_scenes(self, pid, escenas):
        self.scenes[pid] = [dict(e) for e in escenas]

    def get_scenes(self, pid):
        return [dict(e) for e in self.scenes.get(pid, [])]

    def update_scene(self, sid, **kw):
        for lst in self.scenes.values():
            for sc in lst:
                if sc.get("id") == sid:
                    sc.update(kw)

    def get_avatar(self, aid):
        return None

    def create_job(self, project_id, kind="pipeline"):
        jid = self._new_id("job")
        self.jobs[jid] = {"id": jid, "project_id": project_id, "kind": kind,
                          "status": "running", "progress": 0}
        self.create_job_calls.append((project_id, jid))
        return jid

    def update_job(self, jid, **kw):
        self.jobs.setdefault(jid, {}).update(kw)

    def active_job_for_project(self, pid):
        for j in reversed(list(self.jobs.values())):
            if j["project_id"] == pid and j["status"] == "running":
                return dict(j)
        return None


# ── estado compartido de los mocks ─────────────────────────────────────────
UPLOAD_CALLS: list[dict] = []   # cada llamada al publicador (siempre mock)
EVENTS: list[dict] = []         # cada evento broker.publish (SSE)
ORCH_ERRORS: list[str] = []     # logs ERROR del logger "orchestrator"
_DONE_TASKS: dict[str, asyncio.Task] = {}
PUBLISHER = {"modo": "ok"}      # "ok" | "fail"


def _instalar_mocks(orch):
    """Sustituye los pasos pesados del pipeline por dobles instantáneos."""
    import database as db  # el fake

    OUTPUT = orch.OUTPUT_DIR

    # ── publicador YouTube SIEMPRE mockeado (jamás red) ──
    UPLOAD_CALLS.clear()
    PUBLISHER["modo"] = "ok"

    def _upload(video_path, title, description="", tags=None, private=True,
                **kw):
        UPLOAD_CALLS.append({"video": str(video_path), "title": title,
                             "description": description,
                             "tags": list(tags or []), "private": private})
        if PUBLISHER["modo"] == "fail":
            raise RuntimeError("quota exceeded (403)")
        return "ytS2autoOK01"

    orch.youtube_publish.upload = _upload

    # ── guionista (solo modos idea/script; los contratos no lo tocan) ──
    async def _from_idea(*a, **k):
        return "RAW"

    async def _from_script(*a, **k):
        return "RAW"

    def _build_result(raw):
        return {"title": "Título del guionista IA", "hook": "Gancho viral",
                "scenes": [{"id": "s1", "narration": "uno"},
                           {"id": "s2", "narration": "dos"}]}

    orch.script_gen.from_idea = _from_idea
    orch.script_gen.from_script = _from_script
    orch.script_gen.build_result = _build_result

    # ── imágenes / TTS / whisper / render / biblioteca ──
    async def _gen_all(*a, **k):
        return None

    async def _tts(*a, **k):
        return (list(DURS), [[] for _ in DURS])

    async def _full(*a, **k):
        return "voice_full.wav"

    def _words(*a, **k):
        return "words_timeline.json"

    async def _rs(*a, **k):
        return [f"clip_{i}.mp4" for i in range(len(DURS))]

    async def _cc(*a, **k):
        return "video_silent.mp4"

    async def _mux(*a, **k):
        return "video_raw.mp4"

    async def _burn(proj, raw, words):
        out = OUTPUT / proj["id"] / f"{proj['id']}_final.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"FAKE-VIDEO-BYTES")  # <1 KiB: library.archive real NO archivaría
        return out

    def _thumb(*a, **k):
        return None

    def _clean(pid):
        return 0

    orch.imgs.generate_all = _gen_all
    orch.tts_step.synthesize_scenes = _tts
    orch.tts_step.build_full_track = _full
    orch.tts_step.save_words_timeline = _words
    orch.video.render_scenes = _rs
    orch.video.concat_clips = _cc
    orch.video.mux_audio_music = _mux
    orch.video.burn_subtitles = _burn
    orch.video.make_thumbnail = _thumb
    orch.video.cleanup_intermediates = _clean
    orch.library_svc.archive = lambda p, v: None  # biblioteca fuera del disco

    # ── espías: eventos SSE, finalización de jobs y logs del orquestador ──
    EVENTS.clear()
    _orig_publish = orch.broker.publish

    async def _publish_spy(job_id, event):
        EVENTS.append(dict(event, job_id=job_id))
        return await _orig_publish(job_id, event)

    orch.broker.publish = _publish_spy

    _orig_job_done = orch._job_done

    def _job_done_spy(job_id, task):
        _DONE_TASKS[job_id] = task
        _orig_job_done(job_id, task)

    orch._job_done = _job_done_spy

    class _Cap(logging.Handler):
        def emit(self, record):
            if record.levelname == "ERROR":
                ORCH_ERRORS.append(record.getMessage())

    _h = _Cap()
    logging.getLogger("orchestrator").addHandler(_h)
    return _h


def _escena_prod(uid, target):
    """Escena con forma production_json (meta.production_unit)."""
    return {"id": f"sc_{uid}", "duration": target, "narration": f"narr {uid}",
            "meta": {"production_unit": {"id": uid, "duration_target": target}}}


async def _generate(app, pid, autopublish, orch):
    """POST /api/projects/{pid}/generate REAL (ASGI en memoria) + espera del job."""
    import httpx
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://testserver") as c:
        r = await c.post(f"/api/projects/{pid}/generate",
                         json={"autopublish": bool(autopublish)})
        cuerpo = r.json()
        jid = (cuerpo or {}).get("job_id")
        task = _DONE_TASKS.get(jid) or orch.JOBS.get(jid, {}).get("task")
        if task is not None:
            await task
    return r.status_code, cuerpo, jid


def main() -> int:
    _purge_app_modules()
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    _FAKE = _FakeDB()
    sys.modules["database"] = types.SimpleNamespace(**{
        n: getattr(_FAKE, n) for n in dir(_FAKE) if not n.startswith("_")})

    import database as db  # el fake (misma instancia)
    orch = importlib.import_module("pipeline.orchestrator")
    main_mod = importlib.import_module("main")
    app = main_mod.app

    OUTPUT = orch.OUTPUT_DIR
    handler = _instalar_mocks(orch)
    PARCHE = _parche_aplicado()

    LOOP = asyncio.new_event_loop()

    def run(coro):
        return LOOP.run_until_complete(coro)

    OK, FAIL = 0, 0

    def check(nombre, cond, extra=""):
        nonlocal OK, FAIL
        if cond:
            OK += 1
            print(f"  ✓ {nombre}")
        else:
            FAIL += 1
            print(f"  ✗ {nombre} {extra}")

    def nuevo_proyecto(pid, **kw):
        PIDS.append(pid)
        return db.create_project(id=pid, **kw)

    def video_en_disco(pid):
        return (OUTPUT / pid / f"{pid}_final.mp4").exists()

    def eventos(jid, tipo):
        return [e for e in EVENTS if e.get("job_id") == jid
                and e.get("type") == tipo]

    def logs_autopublish(txt):
        return [m for m in ORCH_ERRORS if "autopublish" in m and txt in m]

    try:
        # ══ R. REPRODUCCIÓN del NameError (contrato production_json, ap=true) ═
        print(f"── R. REPRODUCCIÓN NameError (production_json, autopublish=true)"
              f" · parche integrador {'APLICADO' if PARCHE else 'NO aplicado'}")
        r_pid = "s2auto_repro"
        nuevo_proyecto(r_pid, title="Repro autopublish", mode="production_json",
                       meta={"production_json": {"project": {"titulo": "Repro"},
                                                 "sequence": []}})
        db.replace_scenes(r_pid, [_escena_prod("v1", 3.0),
                                  _escena_prod("v2", 2.5)])
        st, cuerpo, jid_r = run(_generate(app, r_pid, True, orch))
        job_r = db.jobs[jid_r]
        proj_r = db.projects[r_pid]
        check("endpoint responde 200 {job_id}", st == 200 and bool(jid_r),
              f"{st} {cuerpo}")
        check("el pipeline NO se tumba: job done", job_r["status"] == "done",
              job_r.get("status", ""))
        if not PARCHE:
            check("R·DEFECTO: publicador NUNCA invocado (NameError antes de upload)",
                  not UPLOAD_CALLS, str(UPLOAD_CALLS)[:120])
            check("R·DEFECTO: proyecto queda 'ready', NUNCA 'published'",
                  proj_r["status"] == "ready" and not proj_r.get("youtube_id"),
                  f"{proj_r['status']}/{proj_r.get('youtube_id')}")
            msg = job_r.get("message", "")
            check("R·DEFECTO: error registrado: «autopublish falló … result»",
                  "autopublish falló" in msg and "result" in msg, msg[:120])
            check("R·DEFECTO: log ERROR del orquestador nombra 'result'",
                  bool(logs_autopublish("result")), str(ORCH_ERRORS)[-2:])
        else:
            check("R·parche: proyecto 'published' con youtube_id",
                  proj_r["status"] == "published"
                  and proj_r.get("youtube_id") == "ytS2autoOK01",
                  f"{proj_r['status']}/{proj_r.get('youtube_id')}")
            check("R·parche: upload con el título del proyecto",
                  UPLOAD_CALLS and UPLOAD_CALLS[0]["title"] == "Repro autopublish",
                  str(UPLOAD_CALLS[:1]))
        check("R: el video ya renderizado NO se pierde",
              video_en_disco(r_pid) and proj_r.get("video_url", "").endswith(
                  f"{r_pid}_final.mp4"))

        # ══ A. generate+autopublish EXITOSO (modo idea, publicador mock) ═════
        print("── A. autopublish EXITOSO (modo idea → rama con `result`)")
        a_pid = "s2auto_idea_ok"
        nuevo_proyecto(a_pid, title="Idea A", mode="idea")
        UPLOAD_CALLS.clear()
        EVENTS.clear()
        st, cuerpo, jid_a = run(_generate(app, a_pid, True, orch))
        job_a, proj_a = db.jobs[jid_a], db.projects[a_pid]
        check("endpoint 200 {job_id}", st == 200 and bool(jid_a))
        check("upload llamado EXACTAMENTE 1 vez", len(UPLOAD_CALLS) == 1,
              str(len(UPLOAD_CALLS)))
        up = UPLOAD_CALLS[0] if UPLOAD_CALLS else {}
        check("título = result['title'] del guionista",
              up.get("title") == "Título del guionista IA", up.get("title", ""))
        check("descripción = hook + firma del pipeline",
              "Gancho viral" in up.get("description", "")
              and "YT Automation" in up.get("description", ""))
        check("tags del estilo + base", up.get("tags", [])[:4]
              == ["shorts", "viral", "ia", "historias"], str(up.get("tags")))
        check("privacy private=True", up.get("private") is True)
        check("video subido es el MP4 final del proyecto",
              up.get("video", "").endswith(f"{a_pid}_final.mp4"),
              up.get("video", ""))
        check("proyecto 'published' con youtube_id",
              proj_a["status"] == "published"
              and proj_a.get("youtube_id") == "ytS2autoOK01",
              f"{proj_a['status']}/{proj_a.get('youtube_id')}")
        check("evento SSE 'published' emitido",
              eventos(jid_a, "published")
              and eventos(jid_a, "published")[0]["youtube_id"] == "ytS2autoOK01")
        check("job done y video en disco",
              job_a["status"] == "done" and video_en_disco(a_pid))

        # ══ B. fallo REAL de publicación (el publicador lanza excepción) ═════
        print("── B. fallo REAL de publicación (upload lanza RuntimeError)")
        b_pid = "s2auto_pubfail"
        nuevo_proyecto(b_pid, title="Idea B", mode="idea")
        UPLOAD_CALLS.clear()
        EVENTS.clear()
        PUBLISHER["modo"] = "fail"
        st, cuerpo, jid_b = run(_generate(app, b_pid, True, orch))
        job_b, proj_b = db.jobs[jid_b], db.projects[b_pid]
        PUBLISHER["modo"] = "ok"
        msg_b = job_b.get("message", "")
        check("endpoint 200 (el fallo de publish NO rompe la petición)",
              st == 200 and bool(jid_b))
        check("job 'done': el pipeline terminó, solo falló la subida",
              job_b["status"] == "done", job_b["status"])
        check("proyecto 'ready' con video_url conservado",
              proj_b["status"] == "ready"
              and proj_b.get("video_url", "").endswith(f"{b_pid}_final.mp4"),
              f"{proj_b['status']}/{proj_b.get('video_url')}")
        check("el video ya renderizado NO se pierde", video_en_disco(b_pid))
        check("error real registrado: «autopublish falló: quota exceeded (403)»",
              "autopublish falló" in msg_b and "quota exceeded (403)" in msg_b,
              msg_b[:120])
        check("NUNCA es NameError («result» ausente del mensaje)",
              "result" not in msg_b, msg_b[:120])
        check("youtube_id NO asignado y sin evento 'published'",
              not proj_b.get("youtube_id") and not eventos(jid_b, "published"))
        check("log ERROR del orquestador con el motivo real",
              bool(logs_autopublish("quota exceeded")))

        # ══ C. proyecto production_json (meta.production_json + units) ═══════
        print("── C. production_json completo (production_unit en escenas, ap=true)")
        c_pid = "s2auto_prodjson"
        nuevo_proyecto(c_pid, title="Producción C", mode="production_json",
                       meta={"production_json": {
                           "project": {"titulo": "Producción C", "formato": "short"},
                           "sequence": [{"id": "v1"}, {"id": "v2"}]}})
        db.replace_scenes(c_pid, [_escena_prod("v1", 3.0),
                                  _escena_prod("v2", 2.5)])
        UPLOAD_CALLS.clear()
        EVENTS.clear()
        st, cuerpo, jid_c = run(_generate(app, c_pid, True, orch))
        job_c, proj_c = db.jobs[jid_c], db.projects[c_pid]
        escenas_c = db.get_scenes(c_pid)
        pu1 = (escenas_c[0].get("meta") or {}).get("production_unit") or {}
        check("endpoint 200 y job done", st == 200 and job_c["status"] == "done")
        check("desviaciones de duración registradas en production_unit",
              pu1.get("duration_actual") == 3.0
              and pu1.get("duration_deviation") == 0.0, str(pu1)[:120])
        check("video en disco y video_url del proyecto",
              video_en_disco(c_pid)
              and proj_c.get("video_url", "").endswith(f"{c_pid}_final.mp4"))
        if not PARCHE:
            check("C·DEFECTO VIGENTE: ap=true en contrato NO publica "
                  "(parche BLOQUEO-PARA-INTEGRADOR pendiente)",
                  proj_c["status"] == "ready" and not UPLOAD_CALLS
                  and "result" in job_c.get("message", ""),
                  f"{proj_c['status']}/{job_c.get('message', '')[:80]}")
        else:
            check("C·parche: contrato SÍ publica con el título del proyecto",
                  proj_c["status"] == "published"
                  and UPLOAD_CALLS[0]["title"] == "Producción C")
        check("job done en cualquier escenario (el defecto nunca tumba el pipeline)",
              job_c["status"] == "done")

        # ══ D. legacy (rama lo permite) y guion_json (contrato) ══════════════
        print("── D1. legacy mode='script' + autopublish=true → SÍ publica")
        d_pid = "s2auto_legacy"
        nuevo_proyecto(d_pid, title="Legacy D", mode="script",
                       meta={"script_text": "Guion heredado de la v1"})
        UPLOAD_CALLS.clear()
        EVENTS.clear()
        st, cuerpo, jid_d = run(_generate(app, d_pid, True, orch))
        proj_d, job_d = db.projects[d_pid], db.jobs[jid_d]
        check("legacy 200 y upload 1 vez con el título del guion",
              st == 200 and len(UPLOAD_CALLS) == 1
              and UPLOAD_CALLS[0]["title"] == "Título del guionista IA",
              str(UPLOAD_CALLS[:1]))
        check("legacy 'published' con youtube_id",
              proj_d["status"] == "published"
              and proj_d.get("youtube_id") == "ytS2autoOK01",
              proj_d["status"])
        check("legacy job done", job_d["status"] == "done")

        print("── D2. contrato guion_json + autopublish=true")
        g_pid = "s2auto_guionjson"
        nuevo_proyecto(g_pid, title="Guion JSON G", mode="guion_json")
        db.replace_scenes(g_pid, [
            {"id": "gs1", "duration": 3.0, "narration": "guion uno"},
            {"id": "gs2", "duration": 2.5, "narration": "guion dos"}])
        UPLOAD_CALLS.clear()
        EVENTS.clear()
        st, cuerpo, jid_g = run(_generate(app, g_pid, True, orch))
        proj_g, job_g = db.projects[g_pid], db.jobs[jid_g]
        check("guion_json 200 y job done", st == 200 and job_g["status"] == "done")
        if not PARCHE:
            check("D2·DEFECTO VIGENTE: contrato guion_json tampoco publica",
                  proj_g["status"] == "ready" and not UPLOAD_CALLS
                  and "result" in job_g.get("message", ""),
                  f"{proj_g['status']}/{job_g.get('message', '')[:80]}")
        else:
            check("D2·parche: guion_json publica con el título del proyecto",
                  proj_g["status"] == "published"
                  and UPLOAD_CALLS[0]["title"] == "Guion JSON G")
        check("video del contrato en disco", video_en_disco(g_pid))

        # ══ E. REGRESIÓN CERO: autopublish=false ⇒ idéntico a siempre ════════
        print("── E. regresión: autopublish=false en los 4 modos")
        uploads_antes = len(UPLOAD_CALLS)
        pub_antes = len([e for e in EVENTS if e.get("type") == "published"])
        casos_e = [
            ("s2auto_e_prod", "production_json",
             {"production_json": {"project": {"titulo": "E"}, "sequence": []}},
             [_escena_prod("v1", 3.0), _escena_prod("v2", 2.5)]),
            ("s2auto_e_guion", "guion_json", {},
             [{"id": "es1", "duration": 3.0}, {"id": "es2", "duration": 2.5}]),
            ("s2auto_e_idea", "idea", {}, []),
            ("s2auto_e_script", "script", {"script_text": "texto"}, []),
        ]
        esperado_msg = f"Video listo · {sum(DURS):.0f}s"
        for pid_e, modo, meta_e, escenas_e in casos_e:
            nuevo_proyecto(pid_e, title=f"E {modo}", mode=modo, meta=dict(meta_e))
            if escenas_e:
                db.replace_scenes(pid_e, escenas_e)
            errs_antes = len(ORCH_ERRORS)
            st, cuerpo, jid_e = run(_generate(app, pid_e, False, orch))
            job_e, proj_e = db.jobs[jid_e], db.projects[pid_e]
            check(f"E/{modo}: 200 + job done + 'ready' + mensaje íntegro",
                  st == 200 and job_e["status"] == "done"
                  and proj_e["status"] == "ready"
                  and job_e.get("message") == esperado_msg,
                  f"{st}/{job_e['status']}/{proj_e['status']}/"
                  f"{job_e.get('message')!r}")
            check(f"E/{modo}: sin errores de autopublish en logs",
                  len(ORCH_ERRORS) == errs_antes,
                  str(ORCH_ERRORS[errs_antes:]))
        check("REGRESIÓN: cero llamadas al publicador durante E (ap=false)",
              len(UPLOAD_CALLS) == uploads_antes,
              f"+{len(UPLOAD_CALLS) - uploads_antes}")
        check("REGRESIÓN: cero eventos 'published' durante E (ap=false)",
              len([e for e in EVENTS if e.get("type") == "published"])
              == pub_antes)
        check("REGRESIÓN: videos de E en disco",
              all(video_en_disco(p) for p, _, _, _ in casos_e))

        # ══ demostración ═════════════════════════════════════════════════════
        print("\n── DEMOSTRACIÓN")
        print(f"  · parche integrador aplicado : {PARCHE}")
        print(f"  · R  production_json ap=true : job done · video conservado · "
              f"publicador {'llamado' if UPLOAD_CALLS else 'NUNCA llamado (DEFECTO)'}")
        print(f"  · A  idea ap=true            : published (ytS2autoOK01)")
        print(f"  · B  fallo real de upload    : job done · video intacto · "
              f"error 'quota exceeded (403)' registrado (no NameError)")
        print(f"  · C/D2 contratos ap=true     : "
              f"{'published (parche)' if PARCHE else 'DEFECTO vigente: NameError capturado, sin publicación'}")
        print(f"  · E  ap=false (4 modos)      : regresión cero, publicador intacto")

    finally:
        for jid in list(orch.JOBS):
            orch.cancel_job(jid)
        try:
            LOOP.run_until_complete(asyncio.sleep(0.05))
        except Exception:  # noqa: BLE001
            pass
        LOOP.close()
        logging.getLogger("orchestrator").removeHandler(handler)
        for pid in list(dict.fromkeys(PIDS)):
            shutil.rmtree(OUTPUT / pid, ignore_errors=True)

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


def test_autopublish_generate():
    """Entrada pytest: la batería completa debe quedar en verde."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
