#!/usr/bin/env python3
"""
INT-089 · Telemetría por llamada HF (ZeroGPU) + endpoint hf-status.

Cubre los 3 frentes de la tarea:
  A. Registro por llamada — cada intento contra un Space de Hugging Face
     (lipsync audio-driven INT-072 y video-to-video INT-075) deja UN
     registro en hf_telemetry.json dentro de la carpeta del proyecto:
     timestamp, segundos_solicitados, segundos_restantes (parseados del
     mensaje real de cuota ZeroGPU), éxito/fallo, motor, space, duración,
     timeout y mensaje de error.
  B. Endpoint — GET /api/projects/{pid}/hf-status devuelve el último
     registro del proyecto (workspace INT-086 primero, output/<pid> legacy
     como respaldo) con conveniencias cuota_agotada / segundos_restantes
     para que la UI anticipe fallos por cuota ANTES de ejecutar.
  C. Cableado — video.py pasa project_dir=tel_dir (workspace si existe,
     legacy como respaldo); la telemetría JAMÁS rompe el pipeline.

Método: unit de parseo/escritura, llamadas simuladas con monkeypatch
(sin red), API REAL con TestClient y contratos de fuente congelados.

Dual-mode: pytest y script directo.
"""
import asyncio
import json
import shutil
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
import main  # noqa: E402
from services import avatar_motion, hf_telemetry  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

OK, FAIL = 0, 0

MSG_CUOTA = ("You have exceeded your GPU quota "
             "(60s requested / 42s left. Try again in 18s)")


def check(nombre: str, cond: bool, extra: str = ""):
    global OK, FAIL
    ok = bool(cond)
    FAIL += 0 if ok else 1
    OK += 1 if ok else 0
    print(f"{'✓' if ok else '✗'} {nombre}" + (f" — {extra}" if extra and not ok else ""))
    if not ok:
        raise AssertionError(nombre + (f" — {extra}" if extra else ""))


# ── A1 · parseo del mensaje de cuota ZeroGPU ─────────────────────────────
def test_parse_cuota():
    check("mensaje real de ZeroGPU → (60, 42)",
          hf_telemetry.parse_cuota(MSG_CUOTA) == (60, 42))
    check("variante corta → (33, 21)",
          hf_telemetry.parse_cuota("quota exceeded (33s requested / 21s left)") == (33, 21))
    check("con decimales → enteros",
          hf_telemetry.parse_cuota("12.5s requested / 3.5s left") == (12, 3))
    check("error sin cuota → (None, None)",
          hf_telemetry.parse_cuota("Connection error") == (None, None))
    check("cadena vacía → (None, None)",
          hf_telemetry.parse_cuota("") == (None, None))


# ── A2 · sidecar por proyecto: escribir, leer, recortar ──────────────────
def test_record_y_sidecar(tmp_path):
    e = hf_telemetry.record("v2v", "ByteDance/LatentSync", False, error=MSG_CUOTA,
                            project_dir=tmp_path, timeout_s=300.0, duracion_s=8.41)
    sc = tmp_path / "hf_telemetry.json"
    check("sidecar creado en la carpeta del proyecto", sc.is_file())
    check("campos del registro completos",
          e["motor"] == "v2v" and e["space"] == "ByteDance/LatentSync"
          and e["exito"] is False and e["cuota_agotada"] is True
          and e["segundos_solicitados"] == 60 and e["segundos_restantes"] == 42
          and e["timeout_s"] == 300.0 and e["duracion_s"] == 8.41
          and "T" in e["timestamp"] and "GPU quota" in e["error"])
    on_disk = json.loads(sc.read_text(encoding="utf-8"))
    check("el registro queda persistido en el JSON", on_disk and on_disk[-1] == e)
    for i in range(3):
        hf_telemetry.record("v2v", f"space/{i}", True, project_dir=tmp_path)
    check("last_record devuelve el ÚLTIMO registro",
          hf_telemetry.last_record(tmp_path)["space"] == "space/2")
    check("history(n) respeta el corte", len(hf_telemetry.history(tmp_path, 2)) == 2)
    for i in range(60):
        hf_telemetry.record("lipsync_hf", f"s/{i}", True, project_dir=tmp_path)
    data = json.loads(sc.read_text(encoding="utf-8"))
    check("recorte FIFO a 50 entradas", len(data) == 50 and data[-1]["space"] == "s/59")
    check("exito sin error → cuota_agotada False",
          hf_telemetry.record("v2v", "x", True, project_dir=tmp_path)["cuota_agotada"] is False)


def test_record_failsafe_no_rompe(tmp_path):
    muro = tmp_path / "es_un_archivo.txt"
    muro.write_text("no soy directorio", encoding="utf-8")
    # project_dir que no puede alojar el sidecar → igualmente devuelve el entry
    e = hf_telemetry.record("v2v", "s", True, project_dir=muro)
    check("escritura imposible NO lanza y devuelve el entry",
          e["exito"] is True and e["motor"] == "v2v")
    check("last_record sobre sidecar inexistente → None",
          hf_telemetry.last_record(tmp_path / "no_existe") is None)


# ── A3 · telemetría integrada en las cadenas HF (sin red) ────────────────
def test_lipsync_hf_registra_intento_a_intento(tmp_path, monkeypatch):
    img = tmp_path / "avatar.png"; img.write_bytes(b"\x89PNG fake")
    aud = tmp_path / "voz.wav"; aud.write_bytes(b"RIFF fake")
    out = tmp_path / "out.mp4"

    def fake_call(space_id, img_p, aud_p, out_p):
        if space_id == "fake/uno":
            raise RuntimeError(MSG_CUOTA)
        Path(out_p).write_bytes(b"mp4 fake")
        return Path(out_p)

    monkeypatch.setattr(avatar_motion, "hf_space_list", lambda: ["fake/uno", "fake/dos"])
    monkeypatch.setattr(avatar_motion, "_call_hf_lipsync_gradio", fake_call)

    p, space = asyncio.run(avatar_motion.lipsync_liveportrait_hf(
        img, aud, out, project_dir=tmp_path))
    check("failover termina en el 2º Space", space == "fake/dos" and p.is_file())
    data = json.loads((tmp_path / "hf_telemetry.json").read_text(encoding="utf-8"))
    check("UN registro por llamada: 2 intentos → 2 entradas", len(data) == 2)
    r0, r1 = data
    check("intento 1: fallo con cuota parseada",
          r0["space"] == "fake/uno" and r0["exito"] is False
          and r0["cuota_agotada"] is True and r0["segundos_solicitados"] == 60
          and r0["segundos_restantes"] == 42 and r0["motor"] == "lipsync_hf")
    check("intento 2: éxito con duración medida",
          r1["space"] == "fake/dos" and r1["exito"] is True
          and r1["cuota_agotada"] is False and r1["duracion_s"] is not None)


def test_v2v_registra_y_fail_open(tmp_path, monkeypatch):
    vid = tmp_path / "base.mp4"; vid.write_bytes(b"mp4 fake")
    aud = tmp_path / "voz.mp3"; aud.write_bytes(b"mp3 fake")
    out = tmp_path / "lipsync.mp4"

    def fake_wav(audio_path, out_wav):
        Path(out_wav).write_bytes(b"RIFF fake"); return Path(out_wav)

    def fake_call(space_id, video_p, audio_w, out_p):
        raise RuntimeError(f"{space_id}: GPU quota (30s requested / 5s left)")

    monkeypatch.setattr(avatar_motion, "_to_wav_mono16k", fake_wav)
    monkeypatch.setattr(avatar_motion, "_call_hf_v2v_gradio", fake_call)
    monkeypatch.setattr(avatar_motion, "v2v_space_list",
                        lambda: ["ByteDance/LatentSync", "akhaliq/Wav2Lip"])

    res = asyncio.run(avatar_motion.lipsync_video_to_video(
        vid, aud, out, project_dir=tmp_path))
    check("fail-open: ok=False con video original copiado",
          res["ok"] is False and res["fallback"] is True and out.is_file())
    data = json.loads((tmp_path / "hf_telemetry.json").read_text(encoding="utf-8"))
    check("2 Spaces intentados → 2 registros de fallo", len(data) == 2)
    check("último registro con cuota ZeroGPU parseada",
          data[-1]["motor"] == "v2v" and data[-1]["cuota_agotada"] is True
          and data[-1]["segundos_solicitados"] == 30
          and data[-1]["segundos_restantes"] == 5
          and data[-1]["space"] == "akhaliq/Wav2Lip")

    # variante de éxito en el 2º Space
    def call_mixed(space_id, video_p, audio_w, out_p):
        if space_id == "ByteDance/LatentSync":
            raise RuntimeError("401 sin token")
        shutil.copy(video_p, out_p); return Path(out_p)

    monkeypatch.setattr(avatar_motion, "_call_hf_v2v_gradio", call_mixed)
    res2 = asyncio.run(avatar_motion.lipsync_video_to_video(
        vid, aud, tmp_path / "out2.mp4", project_dir=tmp_path))
    check("éxito en el 2º Space → ok=True", res2["ok"] is True
          and res2["space"] == "akhaliq/Wav2Lip")
    data = json.loads((tmp_path / "hf_telemetry.json").read_text(encoding="utf-8"))
    check("el último registro ahora es de éxito",
          data[-1]["exito"] is True and data[-1]["cuota_agotada"] is False)


# ── B · endpoint GET /api/projects/{pid}/hf-status ───────────────────────
@pytest.fixture
def client():
    return TestClient(main.app)


def test_endpoint_hf_status(client):
    from services import hf_telemetry as hft

    r = client.post("/api/projects", json={"mode": "idea",
                                           "idea": "video de prueba hf-status"})
    check("POST /api/projects → 200", r.status_code == 200)
    p = r.json()
    pid, ws = p["id"], Path(p["workspace"])
    try:
        res = client.get(f"/api/projects/{pid}/hf-status")
        check("hf-status → 200", res.status_code == 200)
        j = res.json()
        check("sin llamadas aún → telemetria None y sin cuota",
              j["ok"] is True and j["telemetria"] is None
              and j["cuota_agotada"] is False and j["segundos_restantes"] is None)

        hft.record("v2v", "ByteDance/LatentSync", False, error=MSG_CUOTA,
                   project_dir=ws)
        res = client.get(f"/api/projects/{pid}/hf-status")
        j = res.json()
        check("último registro del workspace expuesto",
              j["telemetria"] and j["telemetria"]["space"] == "ByteDance/LatentSync")
        check("conveniencia cuota_agotada + segundos_restantes",
              j["cuota_agotada"] is True and j["segundos_restantes"] == 42)
        check("origen apunta al hf_telemetry.json del workspace",
              j["origen"].endswith("hf_telemetry.json") and "projects" in j["origen"])

        # respaldo legacy: sin sidecar en el workspace se lee output/<pid>/
        (ws / "hf_telemetry.json").unlink()
        import config as _cfg
        legacy_dir = _cfg.OUTPUT_DIR / pid  # el recorder crea la carpeta si falta
        hft.record("lipsync_hf", "fake/legacy", True, project_dir=legacy_dir)
        res = client.get(f"/api/projects/{pid}/hf-status")
        j = res.json()
        check("fallback legacy output/<pid> cuando el workspace no tiene datos",
              j["telemetria"] and j["telemetria"]["space"] == "fake/legacy"
              and "output" in j["origen"])
    finally:
        client.delete(f"/api/projects/{pid}")

    check("proyecto eliminado → 404",
          client.get(f"/api/projects/{pid}/hf-status").status_code == 404)
    check("pid traversal → 400 (nunca 500)",
          client.get("/api/projects/..%2Fetc/hf-status").status_code in (400, 404))


# ── C · contratos de fuente del cableado ─────────────────────────────────
def test_wiring_fuentes():
    vid = (BACKEND / "pipeline" / "video.py").read_text(encoding="utf-8")
    am = (BACKEND / "services" / "avatar_motion.py").read_text(encoding="utf-8")
    mn = (BACKEND / "main.py").read_text(encoding="utf-8")
    ht = (BACKEND / "services" / "hf_telemetry.py").read_text(encoding="utf-8")
    check("video.py calcula tel_dir (workspace INT-086 si existe, legacy respaldo)",
          "tel_dir = _ws if (_ws and _ws.is_dir()) else proj_dir" in vid
          and "project_workspace.workspace_path(project)" in vid)
    check("video.py pasa project_dir a lipsync_video_to_video",
          "project_dir=tel_dir" in vid)
    check("avatar_motion registra en las DOS cadenas HF (4 puntos)",
          am.count("hf_telemetry.record(") == 4
          and '"v2v"' in am and '"lipsync_hf"' in am)
    check("lipsync_video_to_video y lipsync_liveportrait_hf aceptan project_dir",
          am.count("project_dir: Path | str | None = None") == 3)
    check("endpoint hf-status registrado", '/api/projects/{pid}/hf-status"' in mn
          and "cuota_agotada" in mn)
    check("telemetría nunca lanza (best-effort documentado)",
          "jamás romper el pipeline" in ht or "jamás romper el render" in ht)
    check("el sidecar recorta FIFO a 50", "_MAX_RECORDS = 50" in ht)


# ── contrato de versión (cadena INT-080) ─────────────────────────────────
def test_version():
    check("APP_VERSION 2.44.0 (INT-080: bump por cambio funcional)",
          config.APP_VERSION == "2.44.0")


if __name__ == "__main__":  # modo script directo
    import tempfile
    _ok = True
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _td = None
            try:
                import inspect as _ins
                _params = _ins.signature(_fn).parameters
                _kwargs = {}
                if "client" in _params:
                    _kwargs["client"] = TestClient(main.app)
                if "tmp_path" in _params:
                    _td = tempfile.TemporaryDirectory()
                    _kwargs["tmp_path"] = Path(_td.name)
                if "monkeypatch" in _params:
                    from pytest import MonkeyPatch
                    _kwargs["monkeypatch"] = MonkeyPatch()
                _fn(**_kwargs)
            except Exception as _e:  # noqa: BLE001
                _ok = False
                print(f"✗ {_name}: {_e}")
            finally:
                if _td is not None:
                    _td.cleanup()
    print(f"\n{'OK' if _ok else 'FALLOS'} — {OK} checks · {FAIL} fallos")
    sys.exit(0 if _ok else 1)
