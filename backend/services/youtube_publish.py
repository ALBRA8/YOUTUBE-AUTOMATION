"""
YOUTUBE AUTOMATION v2.0 — Autopublicación en YouTube
OAuth de escritorio (flujo installed-app) con token persistente.
Opcional: se activa solo si el usuario coloca client_secret.json en backend/data/.
"""
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import YT_CLIENT_SECRET, YT_TOKEN_FILE

log = logging.getLogger("publish")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]


def configured() -> bool:
    return Path(YT_CLIENT_SECRET).exists()


def has_token() -> bool:
    return Path(YT_TOKEN_FILE).exists()


def build_auth_url() -> str | None:
    """Genera URL de consentimiento (para mostrarla en el dashboard)."""
    if not configured():
        return None
    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(
            YT_CLIENT_SECRET, scopes=SCOPES,
            redirect_uri="urn:ietf:wg:oauth:2.0:oob")
        flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
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
        YT_CLIENT_SECRET, scopes=SCOPES, redirect_uri="urn:ietf:wg:oauth:2.0:oob")
    flow.fetch_token(code=code)
    creds = flow.credentials
    Path(YT_TOKEN_FILE).write_text(creds.to_json())
    return True


def _credentials():
    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_file(YT_TOKEN_FILE, SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        Path(YT_TOKEN_FILE).write_text(creds.to_json())
    return creds


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

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and progress_cb:
            progress_cb(int(status.progress() * 100))

    return response["id"]
