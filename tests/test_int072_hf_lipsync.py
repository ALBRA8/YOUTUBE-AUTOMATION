#!/usr/bin/env python3
"""
BATERÍA DE TESTS — INT-072 · Lip-Sync & Face Animation vía HF Spaces ($0.00)

Valida el conector `lipsync_liveportrait_hf` + integración fail-open en
`render_avatar_animation` + normalización 9:16 (1080x1920):

1. Firma de las funciones existentes PRESERVADA (contrato de la spec INT-072).
2. Cadena de Spaces audio-driven por defecto y parsing de AVATAR_HF_SPACES.
3. Fail-open: si `gradio_client`/los Spaces fallan → motor local determinista
   (`lipsync_musetalk_local`) responde OK (jamás rompe el render).
4. Camino feliz HF: fake de gradio_client que devuelve un MP4 real →
   engine="liveportrait_hf" + salida normalizada a 1080x1920 (FFmpeg REAL).
5. Normalización 9:16: cuadrado 512x512 → 1080x1920 cover+crop centrado,
   idempotente en segunda pasada.
6. `_extract_video_from_result`: str / dict(video=) / tupla anidada / error.
7. engine="musetalk" explícito NO toca red; engine="hf" explícito SÍ propaga.

Sin red: los Spaces se simulan con un fake de `gradio_client` inyectado en
sys.modules (el import es perezoso dentro de `_call_hf_lipsync_gradio`).
FFmpeg/ffprobe son reales (baratos: clips de 0.5-1 s).
"""
from __future__ import annotations

import asyncio
import inspect
import struct
import subprocess
import sys
import types
import wave
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from services import avatar_motion as am  # noqa: E402


# ── helpers de fixtures ──────────────────────────────────────────────────
def _tiny_image(tmp_path: Path) -> Path:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (64, 64), (40, 40, 60))
    d = ImageDraw.Draw(img)
    d.ellipse([18, 16, 46, 50], fill=(225, 190, 160))
    p = tmp_path / "face.png"
    img.save(p)
    return p


def _tiny_wav(tmp_path: Path, seconds: float = 0.6) -> Path:
    """WAV 16-bit PCM 16 kHz con amplitud variable (envolvente hablada)."""
    sr = 16000
    n = int(sr * seconds)
    frames = bytearray()
    for i in range(n):
        t = i / sr
        s = int(12000 * max(0.0, __import__("math").sin(t * 2 * 3.1415 * 220)) *
                (0.5 + 0.5 * __import__("math").sin(t * 7.0)))
        frames += struct.pack("<h", s)
    p = tmp_path / "voice.wav"
    with wave.open(str(p), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(frames))
    return p


def _tiny_square_mp4(tmp_path: Path, size: int = 64) -> Path:
    """MP4 cuadrado REAL (ffmpeg lavfi): color + audio sine, 0.5 s @12fps."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "hf_out.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"smptebars=s={size}x{size}:rate=12:duration=0.5",
        "-f", "lavfi", "-i", "sine=frequency=300:duration=0.5",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "64k", "-shortest",
        str(p),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return p


def _video_dims(p: Path) -> tuple[int, int]:
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(p)],
        capture_output=True, text=True, check=True)
    w, h = res.stdout.strip().split(",")[:2]
    return int(w), int(h)


class _FakeClient:
    """Fake de gradio_client.Client configurable por clase."""
    behavior = "ok"          # ok | raise
    result_factory = None    # callable(space_id, out_hint) -> valor devuelto
    calls: list = []

    def __init__(self, space_id, hf_token=None, verbose=False):
        self.space_id = space_id
        type(self).calls.append((space_id, hf_token is not None))

    def predict(self, **kwargs):
        if type(self).behavior == "raise":
            raise RuntimeError("fake: Space caído (simulado)")
        return type(self).result_factory(self.space_id, kwargs)


def _fake_gradio_module(behavior: str, result_factory=None):
    mod = types.ModuleType("gradio_client")
    _FakeClient.behavior = behavior
    _FakeClient.result_factory = result_factory
    _FakeClient.calls = []
    mod.Client = _FakeClient

    def handle_file(path, **kw):
        return {"path": str(path), "meta": {"_fake": True}}
    mod.handle_file = handle_file
    return mod


@pytest.fixture
def fake_gradio():
    """Inyecta/retira sys.modules['gradio_client'] (higiene garantizada)."""
    saved = sys.modules.get("gradio_client")
    holder = {"mod": None}

    def install(behavior: str, result_factory=None):
        holder["mod"] = _fake_gradio_module(behavior, result_factory)
        sys.modules["gradio_client"] = holder["mod"]
        return _FakeClient

    yield install
    if saved is not None:
        sys.modules["gradio_client"] = saved
    elif holder["mod"] is not None and sys.modules.get("gradio_client") is holder["mod"]:
        sys.modules.pop("gradio_client", None)


@pytest.fixture(autouse=True)
def _hf_on():
    """Garantiza AVATAR_HF_ENABLED=1 durante la batería (canon guard lo restaura)."""
    import config as cfg
    old = getattr(cfg, "AVATAR_HF_ENABLED", True)
    cfg.AVATAR_HF_ENABLED = True
    yield
    cfg.AVATAR_HF_ENABLED = old


# ── 1. contrato: firmas preservadas ──────────────────────────────────────
def test_signatures_preserved():
    sig = inspect.signature(am.render_avatar_animation)
    assert list(sig.parameters) == [
        "image_path", "output_video", "audio_path", "duration_sec", "engine"]
    assert sig.parameters["audio_path"].default is None
    assert sig.parameters["duration_sec"].default == 4.0
    assert sig.parameters["engine"].default == "auto"

    sig_lp = inspect.signature(am.animate_liveportrait_local)
    assert list(sig_lp.parameters) == ["image_path", "output_video", "duration_sec", "fps"]
    sig_mt = inspect.signature(am.lipsync_musetalk_local)
    assert list(sig_mt.parameters) == ["image_path", "audio_path", "output_video", "fps"]


def test_new_exports_exist():
    for name in ("lipsync_liveportrait_hf", "normalize_vertical_916",
                 "hf_space_list", "hf_lipsync_enabled"):
        assert hasattr(am, name), f"falta {name}"


# ── 2. cadena de Spaces ──────────────────────────────────────────────────
def test_default_space_chain():
    import config as cfg
    old = cfg.AVATAR_HF_SPACES
    try:
        cfg.AVATAR_HF_SPACES = am._AVATAR_HF_SPACES_DEFAULT
        chain = am.hf_space_list()
        assert chain == [
            "fffiloni/EchoMimic", "ZJYang/AniPortrait_official",
            "fffiloni/echomimic-v2"]
    finally:
        cfg.AVATAR_HF_SPACES = old


def test_space_list_parsing_tolerant():
    import config as cfg
    old = cfg.AVATAR_HF_SPACES
    try:
        cfg.AVATAR_HF_SPACES = " a/b , c/d,,  "
        assert am.hf_space_list() == ["a/b", "c/d"]
        cfg.AVATAR_HF_SPACES = ""
        # vacío → cae al default (la cadena verificada viva)
        assert am.hf_space_list() == [
            "fffiloni/EchoMimic", "ZJYang/AniPortrait_official",
            "fffiloni/echomimic-v2"]
    finally:
        cfg.AVATAR_HF_SPACES = old


# ── 3. fail-open a motor local ───────────────────────────────────────────
def test_fail_open_to_local_engine(tmp_path, fake_gradio):
    fake_gradio("raise")
    img, wav = _tiny_image(tmp_path), _tiny_wav(tmp_path)
    out = tmp_path / "out_failopen.mp4"

    res = asyncio.run(am.render_avatar_animation(img, out, audio_path=wav, engine="auto"))
    assert res["ok"] is True
    assert res["engine"] == "musetalk"
    assert res["type"] == "lipsync_speaking"
    assert Path(res["video_path"]).is_file()


def test_engine_local_never_touches_network(tmp_path, fake_gradio):
    install = fake_gradio("raise")  # si alguien lo llama, explota
    img, wav = _tiny_image(tmp_path), _tiny_wav(tmp_path)
    res = asyncio.run(am.render_avatar_animation(
        img, tmp_path / "out_local.mp4", audio_path=wav, engine="musetalk"))
    assert res["ok"] is True and res["engine"] == "musetalk"
    assert _FakeClient.calls == []  # ni un intento de red


def test_engine_hf_explicit_propagates(tmp_path, fake_gradio):
    fake_gradio("raise")
    img, wav = _tiny_image(tmp_path), _tiny_wav(tmp_path)
    with pytest.raises(RuntimeError):
        asyncio.run(am.render_avatar_animation(
            img, tmp_path / "out_hf.mp4", audio_path=wav, engine="hf"))


# ── 4. camino feliz HF + normalización 9:16 real ─────────────────────────
def test_hf_success_and_916_normalization(tmp_path, fake_gradio):
    mp4 = _tiny_square_mp4(tmp_path / "hfsrc")
    fake_gradio("ok", result_factory=lambda space, kw: str(mp4))
    img, wav = _tiny_image(tmp_path), _tiny_wav(tmp_path)
    out = tmp_path / "out_hf.mp4"

    res = asyncio.run(am.render_avatar_animation(img, out, audio_path=wav, engine="auto"))
    assert res["ok"] is True
    assert res["engine"] == "liveportrait_hf"
    assert res["space"] == "fffiloni/EchoMimic"  # primero de la cadena
    assert res["fallback"] is False
    assert _FakeClient.calls and _FakeClient.calls[0][0] == "fffiloni/EchoMimic"
    assert _video_dims(Path(res["video_path"])) == (1080, 1920)  # FFmpeg REAL


def test_failover_to_second_space(tmp_path, fake_gradio):
    """Primer Space caído → el segundo responde (failover de cadena)."""
    import config as cfg
    old = cfg.AVATAR_HF_SPACES
    cfg.AVATAR_HF_SPACES = "space-roto/A,fffiloni/EchoMimic"
    try:
        mp4 = _tiny_square_mp4(tmp_path / "hfsrc2")

        def _factory(space_id, kw):
            if space_id == "space-roto/A":
                raise RuntimeError("fake: primer Space caído")
            return str(mp4)
        fake_gradio("ok", result_factory=_factory)
        img, wav = _tiny_image(tmp_path), _tiny_wav(tmp_path)
        p, space_used = asyncio.run(am.lipsync_liveportrait_hf(img, wav, tmp_path / "fo.mp4"))
        assert space_used == "fffiloni/EchoMimic"
        assert [c[0] for c in _FakeClient.calls] == ["space-roto/A", "fffiloni/EchoMimic"]
    finally:
        cfg.AVATAR_HF_SPACES = old


# ── 5. normalización 9:16 (FFmpeg real) ──────────────────────────────────
def test_normalize_square_to_916(tmp_path):
    src = _tiny_square_mp4(tmp_path, size=256)
    out = am.normalize_vertical_916(src, 1080, 1920)
    assert out == src  # sobrescribe in situ
    assert _video_dims(src) == (1080, 1920)


def test_normalize_idempotent(tmp_path):
    src = _tiny_square_mp4(tmp_path, size=256)
    am.normalize_vertical_916(src, 1080, 1920)
    mtime = src.stat().st_mtime_ns
    am.normalize_vertical_916(src, 1080, 1920)  # 2ª pasada: ya está en 9:16
    assert src.stat().st_mtime_ns == mtime  # no re-encodificó


def test_normalize_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        am.normalize_vertical_916(tmp_path / "nope.mp4")


# ── 6. extracción de video de la respuesta ───────────────────────────────
def test_extract_video_shapes(tmp_path):
    real = _tiny_square_mp4(tmp_path / "x")
    assert am._extract_video_from_result(str(real)) == real
    assert am._extract_video_from_result({"video": str(real)}) == real
    assert am._extract_video_from_result({"value": {"path": str(real)}}) == real
    assert am._extract_video_from_result([None, {"video": str(real)}]) == real
    with pytest.raises(RuntimeError):
        am._extract_video_from_result({"nope": 1})
    with pytest.raises(FileNotFoundError):
        am._extract_video_from_result(str(tmp_path / "fantasma.mp4"))
    with pytest.raises(RuntimeError):
        am._extract_video_from_result(3.14)


# ── 7. HF deshabilitado por config ───────────────────────────────────────
def test_hf_disabled_goes_local(tmp_path, fake_gradio):
    import config as cfg
    fake_gradio("raise")
    old = cfg.AVATAR_HF_ENABLED
    cfg.AVATAR_HF_ENABLED = False
    try:
        img, wav = _tiny_image(tmp_path), _tiny_wav(tmp_path)
        res = asyncio.run(am.render_avatar_animation(
            img, tmp_path / "out_dis.mp4", audio_path=wav, engine="auto"))
        assert res["engine"] == "musetalk"
        assert _FakeClient.calls == []  # ni intentó
    finally:
        cfg.AVATAR_HF_ENABLED = old


def test_no_audio_uses_facial_loop(tmp_path):
    img = _tiny_image(tmp_path)
    res = asyncio.run(am.render_avatar_animation(
        img, tmp_path / "loop.mp4", duration_sec=0.6))
    assert res["ok"] is True
    assert res["engine"] == "liveportrait"
    assert res["type"] == "facial_motion_loop"
    assert Path(res["video_path"]).is_file()
