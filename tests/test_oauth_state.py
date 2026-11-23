"""
AUDITORÍA MULTI-FUENTE 2026-11 — state CSRF del OAuth de YouTube (regresión).

El flujo loopback anterior aceptaba CUALQUIER ?code= en
/api/publish/callback: un atacante podía iniciar el consentimiento con SU
propio client_id, obtener un código válido y colárselo al navegador de la
víctima contra el loopback local (login CSRF → el canal enlazado es el del
atacante). Ahora build_auth_url() emite un state aleatorio
(secrets.token_urlsafe(32)), single-use con TTL de 10 min, que
exchange_code() exige intacto; callback y /publish/exchange lo reenvían.

TODO con DOBLES (fake google_auth_oauthlib inyectado en sys.modules):
hermético, sin red, sin credenciales reales, sin paquete instalado.
"""
import json
import sys
import time
import types
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))


# ── doble de google_auth_oauthlib.flow.Flow (sin red, sin paquete real) ────
class _FakeFlow:
    last: "_FakeFlow | None" = None

    def __init__(self):
        self.redirect_uri = None
        self.scopes = None
        self.secret_path = None
        self.code = None
        self.credentials = None

    @classmethod
    def from_client_secrets_file(cls, path, scopes, redirect_uri):
        f = cls()
        f.secret_path = str(path)
        f.scopes = list(scopes)
        f.redirect_uri = redirect_uri
        cls.last = f
        return f

    def authorization_url(self, **kw):
        st = kw.get("state") or "fake-state"
        return f"https://accounts.google.com/o/oauth2/v2/auth?state={st}", st

    def fetch_token(self, code=None):
        self.code = code
        self.credentials = types.SimpleNamespace(
            to_json=lambda: json.dumps({"refresh_token": "1//fake", "code": code}))


def _install_fake_flow(monkeypatch) -> None:
    pkg = types.ModuleType("google_auth_oauthlib")
    flow_mod = types.ModuleType("google_auth_oauthlib.flow")
    flow_mod.Flow = _FakeFlow
    pkg.flow = flow_mod
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib", pkg)
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", flow_mod)


@pytest.fixture()
def pub(monkeypatch, tmp_path):
    """services.youtube_publish con rutas falsas, states limpios y Flow doble."""
    _install_fake_flow(monkeypatch)
    secret = tmp_path / "client_secret.json"
    secret.write_text('{"installed": {"client_id": "x", "client_secret": "y"}}',
                      encoding="utf-8")
    import services.youtube_publish as yt
    monkeypatch.setattr(yt, "YT_CLIENT_SECRET", str(secret))
    monkeypatch.setattr(yt, "YT_TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setattr(yt, "_pending_states", {})
    return yt


# ── 1 · emisión ────────────────────────────────────────────────────────────
def test_auth_url_emite_state_aleatorio_registrado(pub):
    url, state = pub.build_auth_url()
    assert url and state
    assert len(state) >= 40  # token_urlsafe(32) ≈ 43 chars
    assert state in pub._pending_states  # registrado con TTL
    assert pub._pending_states[state] > time.monotonic()
    assert state in url  # el state viaja en la URL de consentimiento


def test_dos_auth_urls_emiten_states_distintos(pub):
    _, s1 = pub.build_auth_url()
    _, s2 = pub.build_auth_url()
    assert s1 != s2


# ── 2 · validación single-use / alterado / expirado ────────────────────────
def test_validate_state_single_use(pub):
    _, state = pub.build_auth_url()
    assert pub.validate_state(state) is True   # 1.ª vez: válido y se consume
    assert pub.validate_state(state) is False  # 2.ª vez: ya consumido


def test_validate_state_alterado(pub):
    _, state = pub.build_auth_url()
    assert pub.validate_state(state + "x") is False
    assert pub.validate_state("attacker-controlled-state") is False
    # el legítimo sigue pendiente (el atacante no lo gastó)
    assert pub.validate_state(state) is True


def test_validate_state_expirado(pub):
    _, state = pub.build_auth_url()
    pub._pending_states[state] = time.monotonic() - 1  # expiró hace 1 s
    assert pub.validate_state(state) is False


def test_validate_state_vacio(pub):
    assert pub.validate_state("") is False


# ── 3 · exchange_code exige state ──────────────────────────────────────────
def test_exchange_sin_state_rechazado(pub, tmp_path):
    with pytest.raises(ValueError, match="CSRF"):
        pub.exchange_code("4/0AxxS-fake-code")
    assert not Path(pub.YT_TOKEN_FILE).exists()  # sin token escrito


def test_exchange_con_state_legitimo_guarda_token(pub):
    _, state = pub.build_auth_url()
    assert pub.exchange_code("4/0AxxS-fake-code", state) is True
    tok = Path(pub.YT_TOKEN_FILE)
    assert tok.exists()
    assert tok.read_text(encoding="utf-8").startswith("{")
    if sys.platform != "win32":
        assert (tok.stat().st_mode & 0o777) == 0o600  # permiso 0600 (v2.19, POSIX)
    # el state se consumió: reusarlo para otro código es rechazado
    with pytest.raises(ValueError, match="CSRF"):
        pub.exchange_code("4/otro-codigo", state)


# ── 4 · endpoints HTTP (ASGI, httpx) ───────────────────────────────────────
def _client():
    import httpx
    import main as _main
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=_main.app),
                             base_url="http://testserver")


def test_auth_url_endpoint_devuelve_state(pub, monkeypatch):
    import asyncio
    import main as _main
    monkeypatch.setattr(_main.youtube_publish, "YT_CLIENT_SECRET", pub.YT_CLIENT_SECRET)
    monkeypatch.setattr(_main.youtube_publish, "_pending_states", pub._pending_states)
    async def _run():
        async with _client() as c:
            return await c.get("/api/publish/auth-url")
    r = asyncio.run(_run())
    assert r.status_code == 200
    body = r.json()
    assert body["url"] and len(body["state"]) >= 40


def test_callback_rechaza_state_alterado(pub, monkeypatch, tmp_path):
    import asyncio
    import main as _main
    monkeypatch.setattr(_main.youtube_publish, "YT_CLIENT_SECRET", pub.YT_CLIENT_SECRET)
    monkeypatch.setattr(_main.youtube_publish, "YT_TOKEN_FILE", pub.YT_TOKEN_FILE)
    monkeypatch.setattr(_main.youtube_publish, "_pending_states", pub._pending_states)
    async def _run():
        async with _client() as c:
            return await c.get("/api/publish/callback?code=4/attacker&state=evil-state")
    r = asyncio.run(_run())
    assert r.status_code == 400
    assert "CSRF" in r.text
    assert not Path(pub.YT_TOKEN_FILE).exists()  # NADA se intercambió


def test_callback_con_state_valido_conecta(pub, monkeypatch):
    import asyncio
    import main as _main
    monkeypatch.setattr(_main.youtube_publish, "YT_CLIENT_SECRET", pub.YT_CLIENT_SECRET)
    monkeypatch.setattr(_main.youtube_publish, "YT_TOKEN_FILE", pub.YT_TOKEN_FILE)
    monkeypatch.setattr(_main.youtube_publish, "_pending_states", pub._pending_states)
    _, state = pub.build_auth_url()
    async def _run():
        async with _client() as c:
            return await c.get(f"/api/publish/callback?code=4/fake&state={state}")
    r = asyncio.run(_run())
    assert r.status_code == 200
    assert "Canal conectado" in r.text
    assert Path(pub.YT_TOKEN_FILE).exists()


def test_exchange_endpoint_sin_state_400(pub, monkeypatch):
    import asyncio
    import main as _main
    monkeypatch.setattr(_main.youtube_publish, "YT_CLIENT_SECRET", pub.YT_CLIENT_SECRET)
    monkeypatch.setattr(_main.youtube_publish, "YT_TOKEN_FILE", pub.YT_TOKEN_FILE)
    monkeypatch.setattr(_main.youtube_publish, "_pending_states", pub._pending_states)
    async def _run():
        async with _client() as c:
            return await c.post("/api/publish/exchange", json={"code": "4/abc"})
    r = asyncio.run(_run())
    assert r.status_code == 400
    assert "CSRF" in r.json()["detail"]


def test_exchange_endpoint_con_state_valido(pub, monkeypatch):
    import asyncio
    import main as _main
    monkeypatch.setattr(_main.youtube_publish, "YT_CLIENT_SECRET", pub.YT_CLIENT_SECRET)
    monkeypatch.setattr(_main.youtube_publish, "YT_TOKEN_FILE", pub.YT_TOKEN_FILE)
    monkeypatch.setattr(_main.youtube_publish, "_pending_states", pub._pending_states)
    _, state = pub.build_auth_url()
    async def _run():
        async with _client() as c:
            return await c.post("/api/publish/exchange",
                                json={"code": "4/fake", "state": state})
    r = asyncio.run(_run())
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert Path(pub.YT_TOKEN_FILE).exists()
