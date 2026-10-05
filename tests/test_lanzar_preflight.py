#!/usr/bin/env python3
"""Prueba hermética del PREFLIGHT DE LANZAMIENTO (barrera draft → ejecución).

Ejercita el flujo REAL completo, sin servidor ni SQLite real:
  MCP _dispatch("submit_production_json", {production_json, lanzar:false})
      → services.production_json.ingest          (SUBMIT, crea draft)
  MCP _dispatch("lanzar_proyecto", {project_id})
      → pipeline.orchestrator.start_pipeline      (LANZAR, debe preflightar)

Técnica hermética (mismo patrón que test_production_json.py / test_merge_216_pyav.py):
- módulo `database` FAKE inyectado en sys.modules ANTES de importar;
- `orchestrator._run` se sustituye por una grabadora (el objeto bajo prueba
  es la barrera del preflight, no el pipeline en sí);
- única escritura real: production.json bajo data/output/<pid>/ (se limpia).

Copia canónica (fuente de verdad) dentro del repo: el backend se resuelve
relativo al propio repositorio (tests/../backend).

Uso:  cd yt_automation_v2 && python3 tests/test_lanzar_preflight.py
      python3 -m pytest tests/ -q     (cada batería = 1 test pytest)
"""
import asyncio
import json
import shutil
import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ✓ {nombre}")
    else:
        FAIL += 1
        print(f"  ✗ {nombre} {extra}")


def _reset_app_modules():
    """Purga de sys.modules los módulos de la app (y cualquier `database`
    fake dejado por otra batería en el mismo proceso, p.ej. bajo pytest),
    para que esta batería importe siempre estado fresco y coherente."""
    for name in [m for m in sys.modules
                 if m == "database"
                 or m.split(".")[0] in ("config", "security", "services",
                                        "pipeline")]:
        sys.modules.pop(name, None)


# ── módulo database FAKE (fiel a las firmas reales de database.py) ────────
class _FakeDB:
    def __init__(self):
        self.projects: dict[str, dict] = {}
        self.scenes: dict[str, list] = {}
        self.jobs: dict[str, dict] = {}
        self.avatars: dict[str, dict] = {}
        self.create_job_calls: list[tuple] = []
        self.create_project_calls = 0
        self._n = 0

    def _new_id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}_{self._n:04d}"

    def create_project(self, **fields) -> dict:
        self.create_project_calls += 1
        pid = fields.get("id") or self._new_id("proj")
        rec = {"id": pid, "status": "draft", "progress": 0, "meta": {},
               "created_at": "t", "updated_at": "t"}
        rec.update(fields)
        self.projects[pid] = rec
        return dict(rec)

    def get_project(self, pid):
        rec = self.projects.get(pid)
        return dict(rec) if rec else None

    def update_project(self, pid, **kw):
        self.projects.setdefault(pid, {}).update(kw)

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
        return self.avatars.get(aid)

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


def main() -> int:
    global OK, FAIL
    OK, FAIL = 0, 0
    _reset_app_modules()

    _FAKE = _FakeDB()
    sys.modules["database"] = types.SimpleNamespace(**{
        name: getattr(_FAKE, name) for name in dir(_FakeDB) if not name.startswith("_")
    })

    # imports REALES (con database ya suplantado)
    from pipeline import orchestrator  # noqa: E402
    from services import mcp_server  # noqa: E402
    from services import production_json as pj  # noqa: E402
    from services.themes import STYLES  # noqa: E402

    ESTILOS = {s["id"] for s in STYLES}

    # ── sustituto de orchestrator._run: graba y queda vivo (job "activo") ──
    RUN_CALLS: list[tuple] = []
    _STOP = asyncio.Event()

    async def _fake_run(job_id, project_id, autopublish=False):
        RUN_CALLS.append((job_id, project_id, autopublish))
        await _STOP.wait()

    orchestrator._run = _fake_run

    # ── bucle único para toda la prueba (los Task sobreviven entre casos) ──
    LOOP = asyncio.new_event_loop()

    def run(coro):
        return LOOP.run_until_complete(coro)

    # ── payloads de demostración ──────────────────────────────────────────
    VALID = {
        "project": {"title": "Preflight demo VÁLIDO", "format": "short"},
        "sequence": [
            {"id": "v1", "type": "scene", "narration": "Primera unidad",
             "image_prompt": "a red pan on marble, steam, no text", "duration": 5},
            {"id": "v2", "type": "scene", "narration": "Segunda unidad",
             "image_prompt": "coffee cup close up, morning light, no text",
             "duration": 4},
        ],
        "auto_start": False,
    }
    INVALID = {
        "project": {"title": "Preflight demo INVÁLIDO", "format": "short"},
        "sequence": [
            {"id": "u1", "type": "scene", "narration": "Unidad completa",
             "image_prompt": "macro of a miniature kitchen, no text", "duration": 5},
            {"id": "u2", "type": "scene", "narration": "Unidad SIN prompt de imagen",
             "duration": 4},
        ],
        "auto_start": False,
    }

    PIDS = []  # carpetas reales bajo OUTPUT_DIR a limpiar al final

    def submit(payload, lanzar=False):
        """Puerta SUBMIT real: MCP → _t_submit_production_json → production_json.ingest."""
        res = run(mcp_server._dispatch("submit_production_json",
                                       {"production_json": payload, "lanzar": lanzar}))
        if res.get("project_id"):
            PIDS.append(res["project_id"])
        return res

    def lanzar(pid):
        """Puerta LANZAR real: MCP → _t_lanzar_proyecto → orchestrator.start_pipeline."""
        return run(mcp_server._dispatch("lanzar_proyecto", {"project_id": pid}))

    try:
        # ══ A. submit VÁLIDO con lanzar=false → draft aceptado, sin job ════════
        print("── A. submit_production_json(lanzar=false) con JSON VÁLIDO")
        res_a = submit(dict(VALID), lanzar=False)
        pid_ok = res_a["project_id"]
        check("submit válido → ok", res_a.get("ok") is True, json.dumps(res_a)[:120])
        check("modo production_json", res_a.get("modo") == "production_json")
        check("2 unidades", res_a.get("unidades") == 2)
        check("draft sin job (job_id None)", res_a.get("job_id") is None)
        check("production.json en disco",
              (pj.OUTPUT_DIR / pid_ok / "production.json").exists())
        check("sin jobs creados aún", _FAKE.create_job_calls == [])

        # ══ B. lanzar_proyecto del draft VÁLIDO → ACEPTA y crea job ════════════
        print("── B. lanzar_proyecto(draft válido) → ACEPTA")
        res_b = lanzar(pid_ok)
        check("lanzado=True", res_b.get("lanzado") is True, json.dumps(res_b)[:120])
        jid_ok = res_b.get("job_id")
        check("job_id devuelto", bool(jid_ok))
        check("un único create_job para el proyecto",
              _FAKE.create_job_calls == [(pid_ok, jid_ok)])
        check("pipeline _run invocado 1 vez con el proyecto",
              RUN_CALLS == [(jid_ok, pid_ok, False)])
        check("job vivo registrado en JOBS",
              bool(orchestrator.JOBS.get(jid_ok, {}).get("task")))
        check("preflight NO bloqueó lo ejecutable", res_b.get("ok") is True)

        # ══ C. idempotencia: relanzar el mismo proyecto → mismo job, sin 2º _run
        print("── C. lanzar_proyecto repetido → mismo job activo")
        res_c = lanzar(pid_ok)
        check("devuelve el MISMO job_id", res_c.get("job_id") == jid_ok,
              json.dumps(res_c)[:120])
        check("_run NO se invocó de nuevo", len(RUN_CALLS) == 1)

        # ══ D. submit INVÁLIDO con lanzar=false → draft aceptado (diseño) ══════
        print("── D. submit_production_json(lanzar=false) con JSON INVÁLIDO (u2 sin image_prompt)")
        res_d = submit(json.dumps(INVALID, ensure_ascii=False), lanzar=False)
        pid_bad = res_d["project_id"]
        check("la ingesta ACEPTA el draft incompleto (por diseño)",
              res_d.get("ok") is True and res_d.get("job_id") is None)
        check("reporte de ejecución guardado en meta con 1 bloqueada",
              res_d.get("validacion_ejecucion", {}).get("unidades_bloqueadas") == 1
              or (_FAKE.projects[pid_bad]["meta"].get("production_json", {})
                  .get("validacion_ejecucion", {}).get("unidades_bloqueadas") == 1))

        # ══ E. lanzar_proyecto del draft INVÁLIDO → RECHAZA sin job fantasma ═══
        print("── E. lanzar_proyecto(draft inválido) → RECHAZA")
        jobs_antes = list(_FAKE.create_job_calls)
        err_e = None
        try:
            lanzar(pid_bad)
        except ValueError as e:
            err_e = str(e)
        check("ValueError con política «no se puede lanzar»",
              err_e is not None and "no se puede lanzar" in err_e, repr(err_e))
        check("nombra el campo image_prompt",
              err_e is not None and "image_prompt" in err_e)
        check("nombra la unidad exacta sequence[1] (u2)",
              err_e is not None and "sequence[1]" in err_e and "(u2)" in err_e)
        check("apunta al Creative Engine como fuente del arreglo",
              err_e is not None and "Creative Engine" in err_e)
        check("NO se creó job fantasma",
              _FAKE.create_job_calls == jobs_antes,
              f"antes={jobs_antes} ahora={_FAKE.create_job_calls}")
        check("_run sigue invocado solo 1 vez", len(RUN_CALLS) == 1)
        check("el proyecto rechazado sigue en draft (no processing/failed)",
              _FAKE.projects[pid_bad].get("status") == "draft")
        check("la carpeta del proyecto se conservó (trazabilidad)",
              (pj.OUTPUT_DIR / pid_bad / "production.json").exists())

        # ══ F. paridad: la misma política existe en la puerta submit (auto_start)
        print("── F. paridad con la puerta submit (ingest auto_start=True)")
        proyectos_antes = _FAKE.create_project_calls
        err_f = None
        try:
            run(pj.ingest(dict(INVALID), ESTILOS, lambda g: _FAKE.create_project(
                title=g.get("titulo") or "x", mode="production_json"),
                auto_start_override=True))
        except ValueError as e:
            err_f = str(e)
        check("submit con lanzar=true del JSON inválido → ValueError",
              err_f is not None and "no se puede lanzar" in err_f
              and "image_prompt" in err_f, repr(err_f))
        check("nada creado por el intento bloqueado",
              _FAKE.create_project_calls == proyectos_antes)

        # ══ G. no-regresión: proyecto SIN production.json lanza normal ═════════
        print("── G. no-regresión legacy (modo idea, sin production.json)")
        leg = _FAKE.create_project(id="proj_legacy", title="Legacy idea", mode="idea")
        PIDS.append("proj_legacy")
        run(orchestrator.start_pipeline("proj_legacy"))
        check("legacy lanza sin preflight (no-op)",
              any(pid == "proj_legacy" for _, pid, _ap in RUN_CALLS))

        # ══ H. production.json borrado del disco → no bloquea ══════════════════
        print("── H. draft válido cuyo production.json fue borrado → lanza")
        res_h = submit(dict(VALID), lanzar=False)
        pid_h = res_h["project_id"]
        shutil.rmtree(pj.OUTPUT_DIR / pid_h, ignore_errors=True)
        run(orchestrator.start_pipeline(pid_h))
        check("sin contrato en disco → preflight no-op y lanza",
              any(pid == pid_h for _, pid, _ap in RUN_CALLS))

        # ══ I. production.json corrupto → aviso y continúa (no tumba el lanz.) ═
        print("── I. production.json corrupto → aviso, continúa")
        res_i = submit(dict(VALID), lanzar=False)
        pid_i = res_i["project_id"]
        (pj.OUTPUT_DIR / pid_i / "production.json").write_text("{corrupto", "utf-8")
        run(orchestrator.start_pipeline(pid_i))
        check("archivo dañado no tumba el lanzamiento",
              any(pid == pid_i for _, pid, _ap in RUN_CALLS))

        # ══ resumen de la demostración ═════════════════════════════════════════
        print("\n── DEMOSTRACIÓN (flujo submit → lanzar)")
        print(f"  · submit(VÁLIDO,   lanzar=false) → draft   : ok (pid {pid_ok})")
        print(f"  · lanzar(VÁLIDO)             → job {jid_ok} · pipeline iniciado")
        print(f"  · submit(INVÁLIDO, lanzar=false) → draft   : ok (pid {pid_bad})")
        print(f"  · lanzar(INVÁLIDO)           → RECHAZADO  : {err_e[:90]}…")

    finally:
        # teardown: cancelar tasks vivas (mismo loop), limpiar carpetas
        for jid in list(orchestrator.JOBS):
            orchestrator.cancel_job(jid)
        try:
            LOOP.run_until_complete(asyncio.sleep(0.1))
        except Exception:  # noqa: BLE001
            pass
        LOOP.close()
        for pid in PIDS:
            shutil.rmtree(pj.OUTPUT_DIR / pid, ignore_errors=True)

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


def test_bateria_lanzar_preflight():
    """Entrada pytest: la batería completa como un único test."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
