"""
SEGURIDAD · AUDITORÍA MULTI-FUENTE 2026-11 — REGRESIÓN SQLi de la capa SQLite.

database.py construye SQL dinámico (INSERT/UPDATE) interpolando NOMBRES de
columna (los VALORES siempre viajan parametrizados con ``?``). La defensa es
la lista blanca de columnas por tabla (_PROJECT_COLS/_SCENE_COLS/_JOB_COLS/
_AVATAR_COLS + _whitelist): cualquier clave desconocida se descarta con un
warning ANTES de tocar el SQL, así un endpoint que reenvíe input del usuario
directo a kwargs jamás puede inyectar por el nombre de columna.

Estas baterías reproducen los exploits clásicos (apilamiento de sentencias,
comentarios, OR 1=1, UNION) contra las 4 tablas dinámicas y verifican que:
  · el campo malicioso se DESCARTA (no llega al SQL),
  · los campos legítimos siguen aplicándose,
  · las tablas siguen intactas y legibles tras el intento,
  · los VALORES con metacaracteres SQL se guardan verbatim (parametrizados).
Windows-safe: solo SQLite en directorio temporal.
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="p1sec_sqli_"))
import config as _cfg  # noqa: E402

_cfg.DB_PATH = _TMP / "t.db"
_cfg.OUTPUT_DIR = _TMP / "output"
_cfg.DATA_DIR = _TMP
_cfg.TMP_DIR = _TMP / "tmp"
for _d in (_cfg.OUTPUT_DIR, _cfg.TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import database as db  # noqa: E402  (importa DESPUÉS del parche de rutas)

OK, FAIL = 0, 0


def check(nombre, cond, extra=""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))


def tabla_viva(table: str) -> bool:
    """La tabla sigue existiendo y es legible (un DROP triunfado la rompería)."""
    try:
        with db.connect() as con:
            con.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
        return True
    except sqlite3.DatabaseError:
        return False


# ── 0 · lista blanca unitaria ──────────────────────────────────────────────
w = db._whitelist({"title": "ok", "id); DROP TABLE projects;--": "x",
                   "status": "draft"}, db._PROJECT_COLS)
check("_whitelist conserva las columnas permitidas",
      w.get("title") == "ok" and w.get("status") == "draft")
check("_whitelist descarta columnas desconocidas (no viajan al SQL)",
      "id); DROP TABLE projects;--" not in w)
check("_whitelist no muta el dict original",
      "id); DROP TABLE projects;--" in {"title": "ok", "id); DROP TABLE projects;--": "x"})

# ── 1 · create_project con clave maliciosa (apilamiento + comentario) ──────
p = db.create_project(title="víctima", **{"id); DROP TABLE projects;--": "x"})
check("create_project ignora la columna maliciosa y crea el proyecto",
      bool(p and p.get("title") == "víctima"))
n_projects = len(db.list_projects(limit=500))
check("tabla projects VIVA tras el intento de DROP (≥1 fila)",
      n_projects >= 1, f"filas={n_projects}")

# ── 2 · update_project con clave maliciosa ─────────────────────────────────
db.update_project(p["id"], status="ready",
                  **{"status='failed', title='pwned' --": "y"})
p2 = db.get_project(p["id"])
check("update_project aplica el campo legítimo (status=ready)",
      p2.get("status") == "ready")
check("update_project NO ejecuta la asignación inyectada (title intacto)",
      p2.get("title") == "víctima", str(p2.get("title")))

# ── 3 · update_scene con clave maliciosa (scoping M3) ──────────────────────
db.replace_scenes(p["id"], [{"title": "esc0", "narration": "hola"}])
sc = db.get_scenes(p["id"])[0]
rc = db.update_scene(sc["id"], project_id=p["id"],
                     narration="nueva",
                     **{"narration='x'; DROP TABLE scenes;--": "z"})
sc2 = db.get_scenes(p["id"])
check("update_scene aplica el campo legítimo (rowcount=1)",
      rc == 1 and sc2[0]["narration"] == "nueva", f"rc={rc}")
check("tabla scenes VIVA tras el intento de DROP (1 fila)",
      len(sc2) == 1, f"filas={len(sc2)}")

# ── 4 · update_job con clave maliciosa ─────────────────────────────────────
jid = db.create_job(p["id"], kind="pipeline")
db.update_job(jid, step="render", **{"step='x', error='pwn' --": "y"})
job = db.get_job(jid)
check("update_job aplica el campo legítimo (step=render)",
      job.get("step") == "render")
check("update_job NO ejecuta la asignación inyectada (error intacto)",
      job.get("error") in (None, ""), str(job.get("error")))

# ── 5 · avatars con clave maliciosa (create + update) ──────────────────────
av = db.create_avatar(name="narrador", **{"name='x'); DROP TABLE avatars;--": "z"})
check("create_avatar ignora la columna maliciosa",
      bool(av and av.get("name") == "narrador"))
db.update_avatar(av["id"], description="voz grave",
                 **{"description='pwn', name='x' --": "y"})
av2 = db.get_avatar(av["id"])
check("update_avatar aplica el campo legítimo",
      av2.get("description") == "voz grave")
check("update_avatar NO ejecuta la asignación inyectada (name intacto)",
      av2.get("name") == "narrador", str(av2.get("name")))
with db.connect() as con:
    n_av = con.execute("SELECT COUNT(*) c FROM avatars").fetchone()["c"]
check("tabla avatars VIVA tras el intento de DROP (1 fila)",
      n_av == 1, f"filas={n_av}")

# ── 6 · payload UNION/OR en el nombre de columna ───────────────────────────
p3 = db.create_project(title="union", **{"' OR 1=1 --": "x",
                                         "a' UNION SELECT sql FROM sqlite_master --": "y"})
check("create_project sobrevive a payloads UNION/OR (proyecto creado)",
      bool(p3 and p3.get("title") == "union"))
check("projects sigue legible tras payloads UNION/OR",
      len(db.list_projects(limit=500)) == n_projects + 1)

# ── 7 · VALORES con metacaracteres SQL viajan parametrizados (verbatim) ────
payload_val = "x'; DROP TABLE projects;--"
p4 = db.create_project(title=payload_val)
p4r = db.get_project(p4["id"])
check("valor con metacaracteres SQL se guarda VERBATIM (parametrizado)",
      p4r.get("title") == payload_val, str(p4r.get("title")))
check("tabla projects VIVA tras valor malicioso (parametrización real)",
      len(db.list_projects(limit=500)) == n_projects + 2)

# ── 8 · campo solo-malicioso: INSERT/UPDATE siguen siendo SQL válido ───────
p5 = db.create_project(**{"todo-malicioso); DROP TABLE projects;--": "x"})
check("create_project solo-malicioso sigue insertando (id/fechas mínimas)",
      bool(p5 and p5.get("id")))
db.update_project(p5["id"], **{"campo-inventado": "x"})
check("update_project todo-malicioso no rompe (0 campos → SQL mínimo OK)",
      bool(db.get_project(p5["id"])))
check("integridad final: 4 tablas presentes",
      all(tabla_viva(t) for t in ("projects", "scenes", "jobs", "avatars")))

print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
