"""
YOUTUBE AUTOMATION v2.0 — Autopublicación en YouTube
OAuth de escritorio con retorno LOOPBACK (Google retiró el flujo OOB
"urn:ietf:wg:oauth:2.0:oob" → hoy responde Error 400 invalid_request).
El navegador vuelve a http://127.0.0.1:<PORT>/api/publish/callback, donde
el propio servidor intercambia el código y guarda el token.
Opcional: se activa solo si el usuario coloca client_secret.json en backend/data/.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import PORT, YT_CLIENT_SECRET, YT_TOKEN_FILE

log = logging.getLogger("publish")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]


def redirect_uri() -> str:
    """URI de retorno OAuth. Debe estar registrada EXACTAMENTE igual en
    Google Cloud Console → Credenciales → URIs de redirección autorizadas."""
    return (os.getenv("GOOGLE_REDIRECT_URI", "").strip()
            or f"http://127.0.0.1:{PORT}/api/publish/callback")


def configured() -> bool:
    return Path(YT_CLIENT_SECRET).exists()


def has_token() -> bool:
    return Path(YT_TOKEN_FILE).exists()


def build_auth_url() -> str | None:
    """Genera URL de consentimiento con retorno loopback (sin OOB)."""
    if not configured():
        return None
    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(
            YT_CLIENT_SECRET, scopes=SCOPES,
            redirect_uri=redirect_uri())
        auth_url, _ = flow.authorization_url(
            access_type="offline", include_granted_scopes="true", prompt="consent")
        return auth_url
    except Exception as e:  # noqa: BLE001
        log.error("auth url error: %s", e)
        return None


def exchange_code(code: str) -> bool:
    if not configured():
        return False
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(
        YT_CLIENT_SECRET, scopes=SCOPES, redirect_uri=redirect_uri())
    flow.fetch_token(code=code)
    creds = flow.credentials
    tok = Path(YT_TOKEN_FILE)
    tok.write_text(creds.to_json())
    tok.chmod(0o600)  # v2.19: el token da acceso a la cuenta — 0600
    return True


def _credentials():
    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_file(YT_TOKEN_FILE, SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        tok = Path(YT_TOKEN_FILE)
        tok.write_text(creds.to_json())
        tok.chmod(0o600)  # v2.19: idem
    return creds


# v2.19 · tope temporal del upload (§reintentos: timeout explícito). Antes
# el bucle next_chunk() era ILIMITADO: un cuelgue de red dejaba el job de
# publicación colgado para siempre.
UPLOAD_TIMEOUT_S = 30 * 60


def upload(video_path: str, title: str, description: str = "",
           tags: list[str] | None = None, private: bool = True,
           publish_at: str | None = None,
           progress_cb=None) -> str:
    """Sube el video y devuelve el video_id de YouTube."""
    if not configured():
        raise RuntimeError("Falta backend/data/client_secret.json (ver README §Publicar)")
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = _credentials()
    yt = build("youtube", "v3", credentials=creds)

    body: dict = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": (tags or [])[:30],
            "categoryId": "24",  # Entertainment
        },
        "status": {
            "privacyStatus": "private" if (private or publish_at) else "public",
            "selfDeclaredMadeForKids": False,
        },
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at  # ISO-8601 UTC

    media = MediaFileUpload(video_path, chunksize=8 * 1024 * 1024, resumable=True,
                            mimetype="video/mp4")
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    import time as _time
    t0 = _time.monotonic()
    response = None
    while response is None:
        if _time.monotonic() - t0 > UPLOAD_TIMEOUT_S:
            raise TimeoutError(
                f"upload de YouTube excedió {UPLOAD_TIMEOUT_S}s sin terminar "
                "(resumable session colgada) — reintentar")
        status, response = request.next_chunk()
        if status and progress_cb:
            progress_cb(int(status.progress() * 100))

    return response["id"]
