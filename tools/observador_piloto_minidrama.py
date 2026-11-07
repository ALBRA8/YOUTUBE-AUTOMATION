#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PILOTO MÍNIMO · Observador del Gate 0 y Gate 3 — UN episodio corto.

QUÉ ES: herramienta de OBSERVACIÓN (no genera nada, no toca Flow, no toca
orquestador ni HANDS). Recorre los ítems del checklist del
`CONTEXTO YOUTUBE/05_TESTS/PLAN_PILOTO_SERIE_NOTEBOOKLM.md` reducidos a un
episodio corto y dictamina por ítem:

    PASS              hay evidencia real observada y cumple
    FAIL              hay evidencia y NO cumple (se registra el detalle)
    NOT_DEMONSTRATED  lo que exige la máquina del dueño y/o Flow real
                      (sesiones Google, extensión Chrome, generación real)

VEREDICTO GLOBAL: FAIL si algún ítem falla; NOT_DEMONSTRATED si quedan
ítems sin demostrar y ninguno falla; PASS solo si TODO tiene evidencia.

ESTADO: PREPARADO, NO EJECUTADO (NOT_DEMONSTRATED). Requiere la máquina
del dueño con ALBRA levantado, sesión Google/Flow y la extensión Chrome.

USO (máquina del dueño):
  1. Arranca ALBRA (launchers/INICIAR-ALBRA.vbs) con Flow conectado.
  2. python tools/observador_piloto_minidrama.py --proyecto <pid> \
         [--url http://127.0.0.1:8000]
  3. El reporte se guarda en data/output/<pid>/qa/observador_piloto_*.
     Re-ejecutar tras cada avance del piloto: el observador solo LEE.

Higiene: el barrido de logs usa SOLO detección de prefijos conocidos
(nunca guarda el valor detectado; redacta como "SECRETO REDACTADO").
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

PASS, FAIL, PEND = "PASS", "FAIL", "NOT_DEMONSTRATED"

# Prefijos vigilados (mismos familias que tests/test_h2_secrets_hygiene.py).
# Se usa para DETECTAR y REDACTAR; jamás se escribe el valor hallado.
_SECRETOS = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{4,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
]

# ── Checklist del piloto mínimo (única fuente) ──────────────────────────────
GATE0_ITEMS = (
    ("g0_repo_sha", "repo actualizado y SHA anotado", "local"),
    ("g0_backend_health", "/api/health responde OK", "local"),
    ("g0_doctor_audit", "Production Doctor audit/report guardado", "local"),
    ("g0_preflight", "REAL FLOW PREFLIGHT PASS", "local+sesion"),
    ("g0_autopublish_off", "autopublicación y cron/fábrica desactivados", "local"),
    ("g0_secretos_panel", "claves configuradas desde el panel", "dueno"),
    ("g0_sesiones_validas", "sesión NotebookLM y Flow válida", "dueno"),
    ("g0_extension_bridge", "extensión Chrome + Puente Backend activo", "dueno"),
)

GATE3_ITEMS = (
    ("g3_prueba_minima", "prueba mínima de 1 escena en Flow real (ANTIGRAVITY §4)", "flow"),
    ("g3_job_done_asset", "job done + asset en ruta esperada + QA sin errores", "flow"),
    ("g3_clips_episodio", "6 clips del episodio corto generados y válidos (Fase E)", "flow"),
    ("g3_voz_render", "locución + subtítulos + render ejecutados", "flow"),
    ("g3_mp4_reproducible", "MP4 final: duración/resolución/audio verificados", "local"),
    ("g3_video_qa_report", "reporte video_qa guardado junto al proyecto", "local"),
    ("g3_logs_saneados", "logs/evidencias sin secretos", "local"),
)


def dictamina(items: list[dict]) -> str:
    """Veredicto global puro a partir de ítems {id, estado}."""
    estados = {i.get("estado") for i in items}
    if FAIL in estados:
        return FAIL
    if estados <= {PASS} and items:
        return PASS
    return PEND


def barrido_secretos(texto: str) -> tuple[bool, int]:
    """(limpio, nº de hallazgos). Redacción: NUNCA se devuelve el valor."""
    hallazgos = sum(len(p.findall(texto or "")) for p in _SECRETOS)
    return hallazgos == 0, hallazgos


def observa_mp4(ruta: Path) -> dict:
    """Observa un MP4 con ffprobe (binario local; sin red). Nunca inventa:
    si no hay archivo o ffprobe, NOT_DEMONSTRATED."""
    if not ruta.is_file():
        return {"estado": PEND, "detalle": f"no existe {ruta}"}
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {"estado": PEND, "detalle": "ffprobe no disponible"}
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(ruta)],
            capture_output=True, text=True, timeout=30,
        ).stdout
        info = json.loads(out or "{}")
        fmt = info.get("format", {})
        streams = info.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
        return {"estado": PASS,
                "duracion_s": float(fmt.get("duration", 0) or 0),
                "resolucion": f"{video.get('width', '?')}x{video.get('height', '?')}",
                "audio": bool(audio),
                "detalle": f"ffprobe OK sobre {ruta.name}"}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"estado": FAIL, "detalle": f"ffprobe falló: {exc}"}


def valida_clips_episodio(ruta_json: Path) -> dict:
    """Valida el paquete de clips del episodio con el validador Fase E
    (Python puro). No implementa biblia ni aprobaciones."""
    try:
        datos = json.loads(ruta_json.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"estado": PEND, "detalle": f"paquete no legible: {exc}"}
    clips = datos.get("clips") if isinstance(datos, dict) else datos
    if not isinstance(clips, list):
        return {"estado": FAIL, "detalle": "formato sin lista de clips"}
    from services.minidrama_clip_validator import validar_episodio
    res = validar_episodio(clips)
    if res["ok"]:
        return {"estado": PASS, "detalle": f"{res['n_clips']} clips válidos (Fase E)"}
    malos = [f for f in res["fallos_episodio"]]
    malos += [f for c in res["clips"] for f in c["fallos"]]
    return {"estado": FAIL, "detalle": f"{len(malos)} fallos de Fase E",
            "fallos": malos[:10]}


def _api(url: str, timeout: float = 8.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:  # loopback
        return json.loads(r.read().decode("utf-8"))


def observa_gate0(base_url: str, doctor_dir: Path | None) -> list[dict]:
    """Observa los ítems Gate 0 que puede ver SIN generar nada."""
    items: list[dict] = []
    # SHA del repo (local)
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                             capture_output=True, text=True,
                             timeout=15).stdout.strip()
        items.append({"id": "g0_repo_sha", "estado": PASS if sha else PEND,
                      "detalle": sha or "sin SHA"})
    except OSError as exc:
        items.append({"id": "g0_repo_sha", "estado": PEND, "detalle": str(exc)})
    # health (loopback)
    try:
        health = _api(f"{base_url}/api/health")
        ok = str(health.get("status", health.get("ok", ""))).lower() in (
            "ok", "true", "healthy")
        items.append({"id": "g0_backend_health", "estado": PASS if ok else FAIL,
                      "detalle": f"health={health}"})
    except Exception as exc:  # noqa: BLE001 — sin backend: pendiente, no crash
        items.append({"id": "g0_backend_health", "estado": PEND,
                      "detalle": f"backend no alcanzable ({exc}) — márcalo "
                                 "en la máquina del dueño"})
    # doctor audit
    informe = None
    if doctor_dir and doctor_dir.is_dir():
        cand = sorted(doctor_dir.glob("*doctor*")) + sorted(
            doctor_dir.glob("*preflight*"))
        informe = cand[-1] if cand else None
    items.append({"id": "g0_doctor_audit", "estado": PASS if informe else PEND,
                  "detalle": str(informe) if informe else
                             "sin informe Doctor/preflight guardado"})
    # preflight: el veredicto lo da el doctor/preflight real en la máquina
    items.append({"id": "g0_preflight", "estado": PEND,
                  "detalle": "requiere REAL FLOW PREFLIGHT en la máquina del "
                             "dueño (NOT_DEMONSTRATED aquí)"})
    # autopublish/cron apagados: decisión operativa del dueño en el panel
    items.append({"id": "g0_autopublish_off", "estado": PEND,
                  "detalle": "confírmalo en el panel y anótalo con fecha"})
    # ítems que SOLO el dueño puede demostrar
    items += [
        {"id": "g0_secretos_panel", "estado": PEND,
         "detalle": "confirmación del dueño; NUNCA pegar claves aquí"},
        {"id": "g0_sesiones_validas", "estado": PEND,
         "detalle": "sesión Google/Flow visible solo en la máquina del dueño"},
        {"id": "g0_extension_bridge", "estado": PEND,
         "detalle": "botón «Puente Backend» activo, solo en el host"},
    ]
    return items


def observa_gate3(proyecto: str, base_url: str,
                  ruta_data: Path | None = None) -> list[dict]:
    """Observa los ítems Gate 3 del episodio corto (solo lectura)."""
    base = ruta_data or (BACKEND / "data" / "output" / proyecto)
    qa_dir = base / "qa"
    items: list[dict] = []
    # generación real: sin Flow real esto es NOT_DEMONSTRATED, y el
    # observador NO lo disimula
    items += [
        {"id": "g3_prueba_minima", "estado": PEND,
         "detalle": "exige Flow real en la máquina del dueño"},
        {"id": "g3_job_done_asset", "estado": PEND,
         "detalle": "exige jobs reales; un mock/test no cuenta"},
    ]
    # clips del episodio: si ya existe el paquete editorial, se valida
    paquete = base / "clips_episodio.json"
    res_clips = (valida_clips_episodio(paquete) if paquete.is_file()
                 else {"estado": PEND,
                       "detalle": f"sin paquete {paquete.name} aún "
                                  "(los clips llegan con Flow real)"})
    items.append({"id": "g3_clips_episodio", **res_clips})
    # voz/render: evidencia por archivos del proyecto
    render = base / "render"
    mp4s = sorted(render.glob("*.mp4")) if render.is_dir() else []
    final = mp4s[-1] if mp4s else None
    items.append({"id": "g3_voz_render",
                  "estado": PASS if final else PEND,
                  "detalle": str(final) if final else
                             "sin MP4 en render/ (pendiente de pipeline real)"})
    if final:
        items.append({"id": "g3_mp4_reproducible", **observa_mp4(final)})
    else:
        items.append({"id": "g3_mp4_reproducible", "estado": PEND,
                      "detalle": "no hay MP4 que observar todavía"})
    rep_qa = sorted(qa_dir.glob("*video_qa*")) if qa_dir.is_dir() else []
    items.append({"id": "g3_video_qa_report",
                  "estado": PASS if rep_qa else PEND,
                  "detalle": str(rep_qa[-1]) if rep_qa else
                             "sin reporte video_qa guardado"})
    # higiene de logs del proyecto (solo detección + redacción)
    limpio, hallazgos = True, 0
    for log in base.rglob("*.log"):
        try:
            ok, n = barrido_secretos(log.read_text(encoding="utf-8",
                                                   errors="replace"))
        except OSError:
            continue
        limpio &= ok
        hallazgos += n
    items.append({"id": "g3_logs_saneados",
                  "estado": PASS if limpio and hallazgos == 0 else
                            (FAIL if hallazgos else PEND),
                  "detalle": f"{hallazgos} hallazgo(s) redactado(s)"})
    return items


def redacta(pid: str, g0: list[dict], g3: list[dict]) -> tuple[str, dict]:
    """(texto markdown, dict completo). Guarda estados, nunca secretos."""
    ver0, ver3 = dictamina(g0), dictamina(g3)
    global_v = FAIL if FAIL in (ver0, ver3) else (
        PASS if (ver0, ver3) == (PASS, PASS) else PEND)
    completo = {
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "proyecto": pid,
        "gate0": {"veredicto": ver0, "items": g0},
        "gate3": {"veredicto": ver3, "items": g3},
        "veredicto_global": global_v,
        "regla": "NOT_DEMONSTRATED no es PASS: lo pendiente exige la "
                 "máquina del dueño y Flow real",
    }
    lineas = [f"# Observador del piloto mínimo — {pid}", "",
              f"- Fecha: {completo['fecha']}",
              f"- Gate 0: **{ver0}** · Gate 3: **{ver3}** · "
              f"Global: **{global_v}**", ""]
    for titulo, grupo in (("Gate 0 — Preparación segura", g0),
                          ("Gate 3 — Ejecución real controlada", g3)):
        lineas += [f"## {titulo}", "", "| ítem | estado | detalle |",
                   "|---|---|---|"]
        for it in grupo:
            det = str(it.get("detalle", "")).replace("|", "/")[:90]
            lineas.append(f"| {it['id']} | {it['estado']} | {det} |")
        lineas.append("")
    lineas += [f"> {completo['regla']}", ""]
    return "\n".join(lineas), completo


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Observador Gate 0/Gate 3 del piloto mínimo (solo lee)")
    ap.add_argument("--proyecto", required=True, help="id del proyecto piloto")
    ap.add_argument("--url", default="http://127.0.0.1:8000",
                    help="backend local (loopback)")
    ap.add_argument("--data", default=None,
                    help="raíz alternativa de data/output (opcional)")
    args = ap.parse_args(argv)

    base = Path(args.data) if args.data else (
        BACKEND / "data" / "output" / args.proyecto)
    qa_dir = base / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)

    g0 = observa_gate0(args.url, qa_dir)
    g3 = observa_gate3(args.proyecto, args.url, ruta_data=base)
    texto, completo = redacta(args.proyecto, g0, g3)

    estampa = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    (qa_dir / f"observador_piloto_{estampa}.md").write_text(
        texto, encoding="utf-8")
    (qa_dir / f"observador_piloto_{estampa}.json").write_text(
        json.dumps(completo, ensure_ascii=False, indent=2), encoding="utf-8")
    print(texto)
    print(f"VEREDICTO GLOBAL: {completo['veredicto_global']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
