#!/usr/bin/env python3
"""
BATERÍA DE TESTS — INT-028 · Absorción del agente (VÓRTICE → Agente General)

Escenario objetivo: UN solo cerebro para todo el sistema conversacional.
  · services/agent.py (VÓRTICE) RETIRADO: el archivo no existe y el módulo
    ya no es importable.
  · services/general_agent.py es el cerebro ÚNICO: API pública IDÉNTICA
    (plan/execute/build_context/SYSTEM_BRAIN/DESTRUCTIVE_ACTIONS/VALID_ACTIONS),
    cadena NVIDIA → Gemini → regex local intacta, reglas M9 intactas.
  · main.py redirige: `from services import (general_agent as agent_svc, …)`
    — el contrato /api/chat (needs_confirm/pending + confirm) no cambia.
  · Puente del arnés: legacy.AGENT_ACTION_TO_OPERATION consistente con
    VALID_ACTIONS; equivalence_report() documenta el retiro ejecutado.
  · Cero marca VÓRTICE activa en el cerebro ni en la UI (solo historia
    documentada en comentarios).

Regresión cubierta (todo hermético: cero red, cero LLM, cero filesystem real):
  S1 retiro real · S2 API pública · S3 planificador local · S4 execute+fakes
  S5 sin marca VÓRTICE · S6 puente arnés · S7 contratos estructurales.

Convención del repo: script stdlib (sin pytest), 0 dependencias externas.
"""
import asyncio
import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

BACKEND = ROOT / "backend"
_OK, _FAIL = [0], [0]


def check(nombre: str, cond) -> None:
    if cond:
        _OK[0] += 1
        print(f"  ✓ {nombre}")
    else:
        _FAIL[0] += 1
        print(f"  ✗ {nombre}")


def resumen() -> int:
    print(f"\n═══ {_OK[0]} OK · {_FAIL[0]} fallos ═══")
    return 0 if _FAIL[0] == 0 else 1


# ═══════════════════════════════ S1 · retiro real de agent.py ══════════════
print("── S1. retiro real de agent.py (VÓRTICE)")
check("services/agent.py NO existe en el árbol",
      not (BACKEND / "services" / "agent.py").exists())
check("services/general_agent.py SÍ existe",
      (BACKEND / "services" / "general_agent.py").exists())
check("el módulo services.agent ya no es importable",
      importlib.util.find_spec("services.agent") is None)
import services.general_agent as ga  # noqa: E402

# ═══════════════════════════ S2 · API pública idéntica ═════════════════════
print("── S2. API pública del cerebro único")
check("plan() existe y es async",
      inspect.iscoroutinefunction(ga.plan))
check("execute() existe y es async",
      inspect.iscoroutinefunction(ga.execute))
check("build_context() existe", callable(ga.build_context))
check("SYSTEM_BRAIN presente (str rico)",
      isinstance(ga.SYSTEM_BRAIN, str) and len(ga.SYSTEM_BRAIN) > 800)
check("_HELP_TEXT presente", isinstance(ga._HELP_TEXT, str) and "Agente General" in ga._HELP_TEXT)
check("VALID_ACTIONS = las mismas 10 acciones",
      set(ga.VALID_ACTIONS) == {
          "create_video", "create_niche", "delete_niche", "delete_project",
          "cleanup_failed", "list_projects", "list_niches",
          "project_status", "help", "none"} and len(ga.VALID_ACTIONS) == 10)
check("DESTRUCTIVE_ACTIONS = las mismas 3 (M9)",
      set(ga.DESTRUCTIVE_ACTIONS) == {"delete_niche", "delete_project",
                                      "cleanup_failed"}
      and len(ga.DESTRUCTIVE_ACTIONS) == 3)
check("VALID_PLATFORMS intactas",
      ga.VALID_PLATFORMS == {"youtube", "tiktok", "instagram", "facebook"})
check("todos los VALID_ACTIONS están documentados en SYSTEM_BRAIN",
      all(a in ga.SYSTEM_BRAIN for a in
          ("create_video", "create_niche", "delete_niche", "delete_project",
           "cleanup_failed", "list_projects", "list_niches",
           "project_status", "help", "none")))
check("regla M9 documentada en el cerebro (confirmación, nunca «ya lo hice»)",
      "pedirá confirmación" in ga.SYSTEM_BRAIN)

# ══════════════════════════ S3 · planificador local ════════════════════════
print("── S3. planificador local (regex/parse/sanitize — degradación $0)")
out = ga._plan_local("crea un video sobre el imperio romano")
check("create_video por regex (idea+format)",
      out["action"] == "create_video"
      and "imperio romano" in out["params"]["idea"]
      and out["params"]["format"] == "short" and out["engine"] == "local")
out = ga._plan_local("crea un video largo y documental sobre el océano")
check("formato long detectado",
      out["action"] == "create_video" and out["params"]["format"] == "long")
out = ga._plan_local("vórtice, crea un video sobre bermudas")
check("alias legacy tolerado («vórtice, crea…»)",
      out["action"] == "create_video" and "bermudas" in out["params"]["idea"])
out = ga._plan_local("muéstrame mis proyectos")
check("list_projects por regex", out["action"] == "list_projects")
out = ga._plan_local("cómo va el video de las bermudas")
check("project_status por regex",
      out["action"] == "project_status" and "bermudas" in out["params"]["project_name"])
out = ga._plan_local("hola qué tal")
check("charla → help con _HELP_TEXT",
      out["action"] == "help" and out["reply"] is ga._HELP_TEXT)
p = ga._sanitize_params({"idea": "x" * 500, "format": "cuadrado",
                         "platforms": ["youtube", "telegram", "tiktok"],
                         "style": "s" * 99, "emoji": "🙂‍↔️🙂‍↔️🙂‍↔️"})
check("sanitize recorta y filtra",
      len(p["idea"]) == 180 and "format" not in p
      and p["platforms"] == ["youtube", "tiktok"]
      and len(p["style"]) == 40)
raw = "```json\n{\"reply\": \"hola\", \"action\": \"list_projects\", \"params\": {}}\n```"
check("_extract_json quita fences y toma el objeto balanceado",
      json.loads(ga._extract_json(raw))["action"] == "list_projects")
plan_out = ga._parse_plan("{\"reply\":\"ok\",\"action\":\"nuclear\",\"params\":{}}",
                          "mensaje semilla", model="fake")
check("acción desconocida → none + idea semilla", plan_out["action"] == "none")
plan_out = ga._parse_plan("{\"reply\":\"\",\"action\":\"create_video\",\"params\":{}}",
                          "mensaje semilla", model="fake")
check("reply vacío → «Hecho ✅» e idea = mensaje",
      plan_out["reply"] == "Hecho ✅" and plan_out["params"]["idea"] == "mensaje semilla")
plan_out = ga._parse_plan("el modelo describió la imagen sin JSON", "msg",
                          model="fake", lenient=True)
check("modo visión lenient acepta texto plano como reply",
      plan_out["action"] == "none" and "imagen" in plan_out["reply"])

# ═══════════════ S4 · execute() contra fakes (motor real simulado) ═════════
print("── S4. execute() contra fakes (create/M9-delete/cleanup/listas)")


class FakeDB:
    def __init__(self, projects=None):
        self.projects = list(projects or [])
        self.deleted = []
        self.created = []

    def list_projects(self, limit=40):
        return list(self.projects)[:limit]

    def create_project(self, **kw):
        p = {"id": "a1b2c3d4e5f6", "status": "draft", **kw}
        self.created.append(p)
        self.projects.insert(0, p)
        return p

    def delete_project(self, pid):
        self.deleted.append(pid)
        self.projects = [p for p in self.projects if p["id"] != pid]

    def update_project(self, pid, **kw):
        for p in self.projects:
            if p["id"] == pid:
                p.update(kw)

    def list_avatars(self):
        return [{"id": "av1", "name": "Sofía Explora", "voice": "es-MX",
                 "style": "neo-anime", "tts_provider": "edge"}]


class FakeOrch:
    def __init__(self):
        self.started = []

    async def start_pipeline(self, pid):
        self.started.append(pid)
        return f"job-{pid}"


class FakeNiches:
    def __init__(self):
        self.tpls = [{"id": "tpl1", "name": "Finanzas", "emoji": "💰",
                      "description": "dinero", "prompt": "plantilla",
                      "style": "graphic-novel", "format": "long",
                      "voice": "es-CO", "subtitles": "shorts"}]

    def get_template(self, name):
        return next((t for t in self.tpls if t["name"].lower() == name.lower()),
                    None)

    def list_templates(self):
        return list(self.tpls)

    def upsert_template(self, data):
        data = {"id": f"tpl{len(self.tpls) + 1}", **data}
        self.tpls.append(data)
        return data

    def delete_template(self, tid):
        self.tpls = [t for t in self.tpls if t["id"] != tid]

    @staticmethod
    def compose_idea(tpl, seed):
        return (seed or "") + " — " + tpl["name"]


_orig_niches = ga.niches_svc
ga.niches_svc = FakeNiches()  # patch hermético del servicio de nichos

db, orch = FakeDB(), FakeOrch()
r = asyncio.run(ga.execute({"action": "create_video", "reply": "",
                            "params": {"idea": "imperio romano",
                                       "format": "short"}},
                           db, orch, db.list_avatars()))
check("create_video idea-path: proyecto + job",
      r["action"] == "create_video" and r["project"]["mode"] == "idea"
      and orch.started == ["a1b2c3d4e5f6"] and r["job_id"] == "job-a1b2c3d4e5f6")
r = asyncio.run(ga.execute({"action": "create_video", "reply": "",
                            "params": {"idea": "bolsa", "nicho": "finanzas"}},
                           db, orch, db.list_avatars()))
check("create_video nicho-path: herencia de plantilla + compose_idea",
      r["project"]["mode"] == "nicho" and r["project"]["niche"] == "Finanzas"
      and r["project"]["meta"]["idea"].endswith("Finanzas")
      and r["project"]["meta"]["subtitle_style"] == "shorts")
r = asyncio.run(ga.execute({"action": "create_video", "reply": "",
                            "params": {"idea": "misterios",
                                       "avatar": "sofía explora"}},
                           db, orch, db.list_avatars()))
check("avatar heredado (voz/tts/estilo + reply)",
      r["project"]["avatar_id"] == "av1"
      and r["project"]["tts_provider"] == "edge"
      and "Sofía Explora" in r["reply"])
r = asyncio.run(ga.plan("crea un video sobre misterios con sofía explora",
                        None, db.list_avatars(), None))
check("plan() detecta avatar por nombre en cualquier motor",
      r["action"] == "create_video"
      and r["params"].get("avatar") == "Sofía Explora")

# M9 · delete_project: ambiguo REFUSADO, título EXACTO único (puente), id exacto
db = FakeDB([{"id": "0123456789ab", "title": "Bermudas", "status": "ready"},
             {"id": "0123456789cd", "title": "Bermudas II", "status": "failed"},
             {"id": "0123456789ef", "title": "Romano", "status": "draft"},
             {"id": "0123456789ff", "title": "Caído", "status": "failed"}])
r = asyncio.run(ga.execute({"action": "delete_project", "reply": "",
                            "params": {"project_name": "bermuda"}}, db, None, []))
check("M9 ambiguo (2 matches, sin exacto) → NO ejecuta y lista",
      r["action"] == "none" and db.deleted == []
      and "0123456789ab" in r["reply"])
r = asyncio.run(ga.execute({"action": "delete_project", "reply": "",
                            "params": {"project_id": "zz"}}, db, None, []))
check("M9 project_id inválido → rechazo (fail-closed)",
      r["action"] == "none" and "inválido" in r["reply"])
r = asyncio.run(ga.execute({"action": "delete_project", "reply": "",
                            "params": {"project_id": "ffffffffffff"}}, db, None, []))
check("M9 project_id inexistente → rechazo honesto",
      r["action"] == "none" and "No existe" in r["reply"])
r = asyncio.run(ga.execute({"action": "delete_project", "reply": "",
                            "params": {"project_id": "0123456789ef"}}, db, None, []))
check("M9 project_id válido → borra",
      r["action"] == "delete_project" and "0123456789ef" in db.deleted)
r = asyncio.run(ga.execute({"action": "delete_project", "reply": "",
                            "params": {"project_name": "bermudas ii"}}, db, None, []))
check("M9 título EXACTO único → borra por pipeline seguro",
      r["action"] == "delete_project" and "0123456789cd" in db.deleted)

r = asyncio.run(ga.execute({"action": "cleanup_failed", "reply": ""}, db, None, []))
check("cleanup_failed borra SOLO failed y cuenta",
      r["deleted_count"] == 1 and "0123456789ff" in db.deleted)
r = asyncio.run(ga.execute({"action": "cleanup_failed", "reply": ""}, db, None, []))
check("cleanup_failed sin fallidos → mensaje limpio",
      r["deleted_count"] == 0 and "limpio" in r["reply"])

r = asyncio.run(ga.execute({"action": "list_projects", "reply": ""}, db, None, []))
check("list_projects devuelve hasta 6", len(r["projects"]) <= 6)
r = asyncio.run(ga.execute({"action": "list_niches", "reply": ""}, db, None, []))
check("list_niches lista plantillas",
      r["action"] == "list_niches" and "Finanzas" in r["reply"])
r = asyncio.run(ga.execute({"action": "create_niche", "reply": "",
                            "params": {"name": "Deportes", "emoji": "⚽"}},
                           db, None, []))
check("create_niche crea plantilla",
      any(t["name"] == "Deportes" for t in ga.niches_svc.list_templates()))
r = asyncio.run(ga.execute({"action": "delete_niche", "reply": "",
                            "params": {"name": "Finanzas"}}, db, None, []))
check("delete_niche elimina plantilla",
      r["action"] == "delete_niche"
      and not ga.niches_svc.get_template("Finanzas"))
r = asyncio.run(ga.execute({"action": "project_status", "reply": "",
                            "params": {"project_name": "bermudas"}}, db, None, []))
check("project_status informa estado del más relevante",
      r["action"] == "project_status" and "»" in r["reply"])
r = asyncio.run(ga.execute({"action": "help", "reply": ""}, db, None, []))
check("help responde con _HELP_TEXT", r["reply"] is ga._HELP_TEXT)

ga.niches_svc = _orig_niches  # restore

# plan() end-to-end SIN claves: mensaje vacío → help; degradación local
r = asyncio.run(ga.plan("", None, None, None))
check("plan(\"\") → help local (nunca lanza)",
      r["action"] == "help" and r["engine"] == "local")
r = asyncio.run(ga.plan("crea un video sobre romanos", None, None, None))
check("plan() sin claves degrada a regex local con avatar opcional",
      r["action"] == "create_video" and "romanos" in r["params"]["idea"])

# ══════════════════════ S5 · cero marca VÓRTICE activa ═════════════════════
print("── S5. cero marca VÓRTICE activa (cerebro + UI)")
check("SYSTEM_BRAIN sin identidad VÓRTICE", "VÓRTICE" not in ga.SYSTEM_BRAIN)
check("_HELP_TEXT sin identidad VÓRTICE", "VÓRTICE" not in ga._HELP_TEXT)
app_js = (BACKEND / "static" / "app.js").read_text(encoding="utf-8")
check("app.js sin «Agente VÓRTICE» en UI", "Agente VÓRTICE" not in app_js)
check("app.js sin «Soy VÓRTICE»", "Soy VÓRTICE" not in app_js)
check("app.js sin «VÓRTICE está pensando»", "VÓRTICE está pensando" not in app_js)
check("app.js con nuevo saludo del Agente General",
      "Soy el Agente General" in app_js and "who\">AGENTE" in app_js)
check("banner de la home rebrandeado", "<b>Agente General</b>" in app_js)
check("index.html sirve app.js?v=2.25.0",
      "app.js?v=2.25.0" in (BACKEND / "static" / "index.html").read_text(encoding="utf-8"))
main_src = (BACKEND / "main.py").read_text(encoding="utf-8")
check("main.py importa general_agent como agent_svc (redirect)",
      "general_agent as agent_svc" in main_src)
check("main.py sin import del módulo retirado",
      re.search(r"from services import \(\s*agent\b", main_src) is None
      and "import agent as" not in main_src)
check("docstring /api/chat apunta al Agente General",
      "Agente General (services/general_agent.py" in main_src)

# ══════════════════ S6 · puente del arnés consistente ══════════════════════
print("── S6. puente cerebro-chat → arnés (§12 ejecutado)")
from services.youtube_harness.legacy import (  # noqa: E402
    AGENT_ACTION_TO_OPERATION, equivalence_report, operation_for_agent_action)
from services.youtube_harness import capabilities as hcap  # noqa: E402

check("puente cubre EXACTAMENTE los VALID_ACTIONS del cerebro",
      set(AGENT_ACTION_TO_OPERATION) == set(ga.VALID_ACTIONS))
check("delete_project → youtube.delete (destructiva, M9)",
      AGENT_ACTION_TO_OPERATION["delete_project"] == "youtube.delete"
      and hcap.OPERATIONS["youtube.delete"].destructive)
check("create_video → youtube.create",
      AGENT_ACTION_TO_OPERATION["create_video"] == "youtube.create")
check("operation_for_agent_action roundtrip",
      operation_for_agent_action("list_projects") == "youtube.list_projects"
      and operation_for_agent_action("help") is None)
rep = equivalence_report()
check("equivalence_report documenta el retiro ejecutado",
      "Agente General" in rep["legacy_worker"]
      and "INT-028" in rep["legacy_worker"]
      and "VÓRTICE" in rep["legacy_worker"])
check("toda operación mapeada existe en el registro del arnés",
      all(i["operation_exists"] for i in rep["covered_by_harness"]))

# ═══════════════════ S7 · contratos estructurales (M9/hands) ═══════════════
print("── S7. contratos estructurales (gate M9 en /api/chat, hands denylist)")
check("gate M9 en /api/chat intacto (DESTRUCTIVE_ACTIONS)",
      "action not in agent_svc.DESTRUCTIVE_ACTIONS" in main_src)
check("contrato needs_confirm/pending intacto en /api/chat",
      '"needs_confirm": True' in main_src and '"pending":' in main_src)
selfaudit_src = (BACKEND / "services" / "hands" / "selfaudit.py").read_text(
    encoding="utf-8")
check("hands denylist incluye al nuevo cerebro y al retirado",
      '"services.general_agent"' in selfaudit_src
      and '"services.agent"' in selfaudit_src)
check("/_pycache_ sin rastro de agent (no rompe find_spec)",
      not (BACKEND / "services" / "__pycache__" / "agent.cpython-311.pyc").exists()
      or importlib.util.find_spec("services.agent") is None)
legacy_src = (BACKEND / "services" / "youtube_harness" / "legacy.py").read_text(
    encoding="utf-8")
check("legacy.py ya no exporta el símbolo VÓRTICE",
      "VORTICE_ACTION_TO_OPERATION" not in legacy_src
      and "operation_for_vortice_action" not in legacy_src)

sys.exit(resumen())
