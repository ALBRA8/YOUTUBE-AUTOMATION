#!/usr/bin/env python3
"""BATERÍA · YOUTUBE HARNESS CONTRACT V1 (runtime HTTP, ASGI en proceso).

Cubre el mandato TRANSFORMACIÓN FINAL §6-§18:
· contrato estricto (version/ids/permisos/metadata) — nunca silencio
· manifiesto sin secretos + operations + riesgo + destructivas
· permisos: faltantes/desconocidos/admin/scopes de credencial (fail-closed)
· ejecuciones: libro idempotente + 404
· operaciones reales sobre la fábrica (create/status/validate/delete)
· normalización de estados (§9) + equivalencia legacy VÓRTICE (§12)
· herencia de seguridad: auth_guard y csrf_guard SIN bypass (§18)
Windows-safe: sin Node/bash; httpx.ASGITransport como las security.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import asyncio  # noqa: E402
import httpx  # noqa: E402

_OK = 0
_FAIL = 0


def check(nombre: str, cond: bool, extra: str = "") -> None:
    global _OK, _FAIL
    if cond:
        _OK += 1
        print(f"  ✓ {nombre}")
    else:
        _FAIL += 1
        print(f"  ✗ {nombre} {extra}")


# ── entorno aislado (patrón security): parchear config ANTES de importar
_TMP = Path(tempfile.mkdtemp(prefix="harness_bat_"))
import config as _cfg  # noqa: E402
_cfg.DB_PATH = _TMP / "db.sqlite"
_cfg.OUTPUT_DIR = _TMP / "out"
_cfg.DATA_DIR = TMP_DIR = _TMP / "data"  # noqa: N806 (alias legible)
_cfg.TMP_DIR = _TMP / "tmp"
for _p in (_cfg.OUTPUT_DIR, _cfg.DATA_DIR, _cfg.TMP_DIR):
    _p.mkdir(parents=True, exist_ok=True)

import main as _main  # noqa: E402
import database as db  # noqa: E402
import security as _security  # noqa: E402
from services.youtube_harness import contracts as hc  # noqa: E402
from services.youtube_harness import capabilities as hcap  # noqa: E402
from services.youtube_harness.legacy import (  # noqa: E402
    VORTICE_ACTION_TO_OPERATION, equivalence_report)

_APP = _main.app


async def _post(client, **kw):
    return await client.post("/api/harness/v1/execute", **kw)


def _req(eid: str, op: str, perms: list[str] | None = None,
         inp: dict | None = None, **extra) -> dict:
    return {"contract_version": "1.0", "execution_id": eid,
            "requester": "host-test", "capability": "youtube_automation",
            "operation": op, "permissions": perms or ["youtube.read"],
            "input": inp or {}, **extra}


async def main_async() -> None:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=_APP),
                               base_url="http://testserver")

    # ════════════════════ 1. manifiesto (§16) ═══════════════════════
    print("── 1. manifiesto del arnés")
    r = await client.get("/api/harness/v1/manifest")
    m = r.json()
    check("manifest 200", r.status_code == 200)
    check("identidad", m.get("harness") == "youtube-harness"
          and m.get("contract_version") == "1.0")
    check("19 operaciones registradas", len(m.get("operations", [])) == 19,
          str(len(m.get("operations", []))))
    check("niveles de riesgo", m.get("risk_levels") ==
          ["LOW", "MEDIUM", "HIGH", "CRITICAL"])
    check("destructivas = delete+cleanup",
          sorted(m.get("destructive_operations", [])) ==
          ["youtube.cleanup", "youtube.delete"])
    check("transportes declarados", m.get("supported_transports") == ["http"])
    check("sin secretos en manifiesto",
          not any("secret" in k or "token" in k or "api_key" in k
                  for k in m.keys()))
    check("cada operación declara permiso",
          all(o.get("required_permission") for o in m["operations"]))
    r = await client.get("/api/harness/v1/manifest?knowledge=true")
    mk = r.json()
    check("knowledge embebible", mk.get("knowledge", {}).get(
        "knowledge_version") == "1.0")
    check("equivalencia legacy informada",
          mk.get("legacy_equivalence", {}).get("legacy_worker") ==
          "VÓRTICE (services/agent.py)")

    # ═══════════════ 2. validación estricta del contrato (§7) ═══════
    print("── 2. validación estricta (nada silencioso)")
    r = await _post(client, json={"contract_version": "9.9",
                                  "execution_id": "exec-2a-000001",
                                  "requester": "t",
                                  "capability": "youtube_automation",
                                  "operation": "youtube.list_projects"})
    check("versión de contrato ajena → 400 CONTRACT_VERSION",
          r.status_code == 400
          and r.json()["detail"]["error"]["code"] == "CONTRACT_VERSION")
    bad = _req("x", "youtube.list_projects")  # execution_id demasiado corto
    r = await _post(client, json=bad)
    check("execution_id corto → 400",
          r.status_code == 400
          and r.json()["detail"]["error"]["code"] == "EXECUTION_ID")
    bad = _req("exec-2b-000001", "youtube.list_projects")
    bad["capability"] = "otra"
    r = await _post(client, json=bad)
    check("capability ajena → 400", r.status_code == 400
          and r.json()["detail"]["error"]["code"] == "CAPABILITY")
    bad = _req("exec-2c-000001", "youtube.list_projects")
    bad["permissions"] = ["permiso raro"]
    r = await _post(client, json=bad)
    check("permiso con formato inválido → 400", r.status_code == 400
          and r.json()["detail"]["error"]["code"] == "PERMISSIONS")
    bad = _req("exec-2d-000001", "youtube.list_projects",
               metadata={"api_key": "filtrada"})
    r = await _post(client, json=bad)
    check("metadata sensible → 400 METADATA_SENSIBLE", r.status_code == 400
          and r.json()["detail"]["error"]["code"] == "METADATA_SENSIBLE")
    r = await _post(client, json=_req("exec-2e-000001", "youtube.no_existe"))
    check("operación desconocida → 404 estructurado",
          r.status_code == 404
          and r.json()["detail"]["error"]["code"] == "OPERATION_UNKNOWN")

    # ═══════════════════ 3. permisos (§13/§18) ══════════════════════
    print("── 3. permisos y destructivas")
    r = await _post(client, json=_req("exec-3a-000001", "youtube.create"))
    b = r.json()
    check("sin permiso declarado → BLOCKED PERMISSION_MISSING",
          b["status"] == "BLOCKED"
          and b["errors"][0]["code"] == "PERMISSION_MISSING")
    r = await _post(client, json=_req("exec-3b-000001", "youtube.create",
                                      perms=["youtube.admin"],
                                      inp={"idea": "batería admin"}))
    check("youtube.admin expande → create ACCEPTED",
          r.json()["status"] == "ACCEPTED")
    r = await _post(client, json=_req("exec-3c-000001", "youtube.delete",
                                      perms=["youtube.production.launch"],
                                      inp={"project_id": "0" * 12}))
    b = r.json()
    check("destructiva sin youtube.destroy → BLOCKED",
          b["status"] == "BLOCKED"
          and b["errors"][0]["code"] == "PERMISSION_MISSING")
    # scopes de credencial (fail-closed)
    _prev = os.environ.get("HARNESS_ALLOWED_PERMISSIONS")
    os.environ["HARNESS_ALLOWED_PERMISSIONS"] = "youtube.read"
    try:
        r = await _post(client, json=_req(
            "exec-3d-000001", "youtube.create",
            perms=["youtube.production.create"],
            inp={"idea": "fuera de scope"}))
        b = r.json()
        check("scope de credencial excluyente → BLOCKED "
              "PERMISSION_NOT_GRANTED",
              b["status"] == "BLOCKED"
              and b["errors"][0]["code"] == "PERMISSION_NOT_GRANTED")
    finally:
        if _prev is None:
            os.environ.pop("HARNESS_ALLOWED_PERMISSIONS", None)
        else:
            os.environ["HARNESS_ALLOWED_PERMISSIONS"] = _prev
    r = await _post(client, json=_req(
        "exec-3e-000001", "youtube.list_projects",
        perms=["youtube.read"]))
    check("scope concedido sigue funcionando",
          r.json()["status"] == "ACCEPTED")

    # ═══════════ 4. ciclo real sobre la fábrica (create→status) ═════
    print("── 4. ciclo real create → estado → libro")
    r = await _post(client, json=_req("exec-4a-000001", "youtube.create",
                                      perms=["youtube.production.create"],
                                      inp={"idea": "proyecto del arnés",
                                           "format": "short"}))
    b = r.json()
    pid = (b.get("outputs", {}).get("project") or {}).get("project_id")
    check("create → ACCEPTED con project_id",
          b["status"] == "ACCEPTED" and bool(pid))
    check("create NO lanza pipeline (sin job_id)",
          b.get("job_id") is None)
    r = await _post(client, json=_req("exec-4a-000001", "youtube.create",
                                      perms=["youtube.production.create"],
                                      inp={"idea": "proyecto del arnés",
                                           "format": "short"}))
    b2 = r.json()
    check("mismo execution_id → replay idempotente",
          b2.get("project_id") == pid
          and b2.get("metadata", {}).get("replayed") is True)
    r = await client.get("/api/harness/v1/executions/exec-4a-000001")
    check("GET /executions/{id} 200", r.status_code == 200
          and r.json().get("operation") == "youtube.create")
    r = await client.get("/api/harness/v1/executions/nadie")
    check("GET /executions desconocida → 404", r.status_code == 404)
    r = await _post(client, json=_req("exec-4b-000001", "youtube.project_status",
                                      inp={"project_id": pid}))
    b3 = r.json()
    check("project_status normaliza draft→ACCEPTED",
          b3["outputs"].get("status") == "ACCEPTED"
          and b3["outputs"].get("internal_status") == "draft")
    check("resultado abstracto, sin columnas SQLite crudas",
          "status" in b3["outputs"] and "meta" not in b3["outputs"])

    # ═══════════════ 5. validación de Production JSON (§13) ═════════
    print("── 5. validate_production / submit_production")
    from services import production_json as pj
    ejemplo = pj.spec([])["ejemplo"]
    r = await _post(client, json=_req("exec-5a-000001",
                                      "youtube.validate_production",
                                      inp={"production_json": ejemplo}))
    b4 = r.json()
    check("ejemplo canónico → válido (ACCEPTED)",
          b4["status"] == "ACCEPTED" and b4["outputs"]["valid"] is True)
    r = await _post(client, json=_req("exec-5b-000001",
                                      "youtube.validate_production",
                                      inp={"production_json": {"x": 1}}))
    b5 = r.json()
    check("payload roto → BLOCKED + código VALIDATION",
          b5["status"] == "BLOCKED"
          and b5["outputs"]["errors"][0]["code"] == "VALIDATION")
    r = await _post(client, json=_req("exec-5c-000001",
                                      "youtube.submit_production",
                                      perms=["youtube.production.create"],
                                      inp={"production_json": ejemplo}))
    b6 = r.json()
    check("submit sin launch → proyecto draft aceptado",
          b6["status"] == "ACCEPTED" and bool(b6.get("project_id")))
    pid2 = b6.get("project_id")
    r = await _post(client, json=_req("exec-5d-000001", "youtube.project_status",
                                      inp={"project_id": pid2}))
    check("proyecto ingerido visible y normalizado",
          r.json()["outputs"].get("status") == "ACCEPTED")

    # ═══════════════ 6. errores honestos de recursos ════════════════
    print("── 6. recursos inexistentes / conflictos")
    r = await _post(client, json=_req("exec-6a-000001", "youtube.project_status",
                                      inp={"project_id": "f" * 12}))
    b7 = r.json()
    check("proyecto inexistente → FAILED NOT_FOUND",
          b7["status"] == "FAILED"
          and b7["errors"][0]["code"] == "NOT_FOUND")
    r = await _post(client, json=_req("exec-6b-000001", "youtube.delete",
                                      perms=["youtube.destroy"],
                                      inp={"project_id": "f" * 12}))
    check("delete inexistente → FAILED NOT_FOUND",
          r.json()["errors"][0]["code"] == "NOT_FOUND")
    bad_pid = _req("exec-6c-000001", "youtube.project_status",
                   inp={"project_id": "../../etc"})
    r = await _post(client, json=bad_pid)
    check("project_id no canónico → BLOCKED (C1 intacto)",
          r.json()["status"] == "BLOCKED")

    # ═══════════════════ 7. estados externos (§9) ═══════════════════
    print("── 7. normalización de estados")
    check("draft→ACCEPTED", hc.normalize_status("draft") == "ACCEPTED")
    check("queued→QUEUED", hc.normalize_status("queued") == "QUEUED")
    check("scripting/images/tts/align/render→RUNNING",
          all(hc.normalize_status(s) == "RUNNING"
              for s in ("scripting", "images", "tts", "align", "render")))
    check("subtitles→VERIFYING",
          hc.normalize_status("subtitles") == "VERIFYING")
    check("ready→READY · published→PUBLISHED",
          hc.normalize_status("ready") == "READY"
          and hc.normalize_status("published") == "PUBLISHED")
    check("failed→FAILED", hc.normalize_status("failed") == "FAILED")
    check("failed+recuperable→RECOVERABLE",
          hc.normalize_status("failed", recoverable=True) == "RECOVERABLE")
    check("flow done→READY · dead→FAILED · claimed→RUNNING",
          hc.normalize_status("done", kind="flow") == "READY"
          and hc.normalize_status("dead", kind="flow") == "FAILED"
          and hc.normalize_status("claimed", kind="flow") == "RUNNING")
    check("job cancelled→CANCELLED",
          hc.normalize_status("cancelled", kind="job") == "CANCELLED")
    check("desconocido→WAITING (honesto)",
          hc.normalize_status("no-se") == "WAITING")

    # ═══════════════ 8. equivalencia legacy VÓRTICE (§12) ═══════════
    print("── 8. puente legacy VÓRTICE → arnés")
    check("delete_project → youtube.delete (destructiva)",
          VORTICE_ACTION_TO_OPERATION["delete_project"] == "youtube.delete"
          and hcap.OPERATIONS["youtube.delete"].destructive)
    check("create_video → youtube.create",
          VORTICE_ACTION_TO_OPERATION["create_video"] == "youtube.create")
    rep = equivalence_report()
    check("toda operación mapeada existe en el registro",
          all(i["operation_exists"] for i in rep["covered_by_harness"]))
    check("capacidad de producir/recuperar/QA/publicar cubierta",
          {"youtube.create", "youtube.launch", "youtube.recover",
           "youtube.video_qa", "youtube.publish"}
          <= set(hcap.OPERATIONS.keys()))

    # ═══════════ 9. herencia de seguridad SIN bypass (§18) ══════════
    print("── 9. seguridad heredada (auth + csrf)")
    r = await client.post("/api/harness/v1/execute", json=_req(
        "exec-9a-000001", "youtube.list_projects"),
        headers={"Origin": "https://malicioso.example"})
    check("Origin externo + POST → 403 (csrf_guard heredado)",
          r.status_code == 403)
    _key = "harness-battery-key-123"
    _security._key = _key
    try:
        r = await client.get("/api/harness/v1/manifest")
        check("auth activa: manifest SIN clave → 401", r.status_code == 401)
        r = await client.get("/api/harness/v1/manifest",
                             headers={"X-API-Key": _key})
        check("auth activa: manifest CON clave → 200", r.status_code == 200)
        r = await _post(client, json=_req("exec-9b-000001",
                                          "youtube.list_projects"),
                        headers={"X-API-Key": _key})
        check("auth activa: execute CON clave → 200",
              r.status_code == 200
              and r.json()["status"] == "ACCEPTED")
        r = await client.get("/api/harness/v1/health")
        check("health del arnés también protegida", r.status_code == 401)
    finally:
        _security.reload()

    # ═══════════════════════ 10. health ═════════════════════════════
    print("── 10. health")
    r = await client.get("/api/harness/v1/health")
    h = r.json()
    check("health ok + checks.database", r.status_code == 200
          and h.get("ok") is True and h["checks"]["database"] is True)

    # ═════════ 11. envelope de publicación — regresión G-01 (P3-B) ═══
    # G-01: op_publish no incluía external_status → _final_status
    # devolvía FAILED para un publish EXITOSO. Tras el parche el éxito
    # se reporta PUBLISHED (estado canónico §9) y el fallo auténtico
    # sigue siendo FAILED + errors[] + recovery (camino AdapterError).
    print("── 11. envelope publish: éxito real ≠ FAILED (G-01)")
    from services import youtube_publish as _ypub
    _orig_configured, _orig_upload = _ypub.configured, _ypub.upload
    try:
        # proyecto A: publicación exitosa simulada (sin red, sin YouTube)
        r = await _post(client, json=_req("exec-11a-000001", "youtube.create",
                                          perms=["youtube.production.create"],
                                          inp={"idea": "publish ok G-01",
                                               "format": "short"}))
        pid_a = (r.json().get("outputs", {}).get("project") or {})
        pid_a = pid_a.get("project_id")
        db.update_project(pid_a, video_url="videos/g01-ok.mp4")
        _ypub.configured = lambda: True
        _ypub.upload = lambda *a, **k: "g01vid1234"
        r = await _post(client, json=_req(
            "exec-11a-000002", "youtube.publish",
            perms=["youtube.publish"], inp={"project_id": pid_a}))
        b = r.json()
        check("publish exitoso → envelope PUBLISHED (G-01 corregido)",
              b["status"] == "PUBLISHED", f"status={b.get('status')!r}")
        check("envelope PUBLISHED sin errors[]",
              b["status"] == "PUBLISHED" and not b.get("errors"))
        check("outputs traen youtube_id + url + external_status",
              b["outputs"].get("youtube_id") == "g01vid1234"
              and b["outputs"].get("external_status") == "PUBLISHED"
              and str(b["outputs"].get("url", "")).startswith(
                  "https://youtube.com/watch?v="))
        _pa = db.get_project(pid_a)
        check("BD: proyecto published + youtube_id (estado real intacto)",
              _pa["status"] == "published"
              and _pa["youtube_id"] == "g01vid1234")
        r = await _post(client, json=_req(
            "exec-11a-000002", "youtube.publish",
            perms=["youtube.publish"], inp={"project_id": pid_a}))
        b2 = r.json()
        check("replay del ledger conserva el éxito (metadata.replayed)",
              b2.get("status") == "PUBLISHED"
              and b2.get("metadata", {}).get("replayed") is True)
        r = await _post(client, json=_req(
            "exec-11a-000003", "youtube.publish",
            perms=["youtube.publish"], inp={"project_id": pid_a}))
        b3 = r.json()
        check("re-publish del mismo proyecto → CONFLICT (idempotencia)",
              b3["status"] == "FAILED"
              and b3["errors"][0]["code"] == "CONFLICT")

        # proyecto B: fallo auténtico del proveedor (upload lanza)
        r = await _post(client, json=_req("exec-11b-000001", "youtube.create",
                                          perms=["youtube.production.create"],
                                          inp={"idea": "publish fail G-01",
                                               "format": "short"}))
        pid_b = (r.json().get("outputs", {}).get("project") or {})
        pid_b = pid_b.get("project_id")
        db.update_project(pid_b, video_url="videos/g01-fail.mp4")

        def _boom(*a, **k):
            raise RuntimeError("quotaExceeded simulada (fixture)")
        _ypub.upload = _boom
        r = await _post(client, json=_req(
            "exec-11b-000002", "youtube.publish",
            perms=["youtube.publish"], inp={"project_id": pid_b}))
        bf = r.json()
        check("fallo auténtico → FAILED con errors[]",
              bf["status"] == "FAILED"
              and bf["errors"][0]["code"] == "PROVIDER_FAILURE")
        check("fallo auténtico → recovery.recoverable (hint recover/doctor)",
              bf.get("recovery", {}).get("recoverable") is True)
        _pb = db.get_project(pid_b)
        check("BD: fallo NO publica ni marca youtube_id",
              _pb["status"] != "published" and not _pb.get("youtube_id"))
        check("éxito y fallo son distinguibles por envelope",
              b["status"] == "PUBLISHED" and bf["status"] == "FAILED"
              and bool(bf["errors"]) and not b["errors"])
    finally:
        _ypub.configured, _ypub.upload = _orig_configured, _orig_upload

    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main_async())
    print(f"\n═══ {_OK} OK · {_FAIL} fallos ═══")
    sys.exit(1 if _FAIL else 0)
