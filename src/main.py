from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

import requests
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "channels.json"
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "channel_history"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly",
          "https://www.googleapis.com/auth/youtube"]
LOGGER = logging.getLogger("insta_youtube_sync")


class UploadLimitExceeded(RuntimeError):
    """Raised when YouTube rejects uploads because the channel/account limit is reached."""


def is_upload_limit_error(exc: BaseException) -> bool:
    """Recognize YouTube's uploadLimitExceeded response, including resumable-upload wrappers."""
    details = str(exc).lower()
    return "uploadlimitexceeded" in details or "exceeded the number of videos they may upload" in details


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def upload_limit_day() -> str:
    """Calendar day used for daily upload-limit suppression (India local time)."""
    return datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(DATA_DIR / "last_run.log", encoding="utf-8")],
    )


def load_config() -> list[dict[str, Any]]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing config file: {CONFIG_PATH}")
    with CONFIG_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("config/channels.json must contain a JSON array.")
    ids = set()
    for ch in data:
        for key in ("id", "channel_id", "env_prefix", "enabled"):
            if key not in ch:
                raise ValueError(f"Channel entry missing required key: {key}")
        if ch["id"] in ids:
            raise ValueError(f"Duplicate channel config id: {ch['id']}")
        ids.add(ch["id"])
    return data


def credentials_for(channel: dict[str, Any]) -> Credentials:
    prefix = str(channel["env_prefix"])
    client_id = os.getenv(f"{prefix}_CLIENT_ID", "").strip()
    client_secret = os.getenv(f"{prefix}_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv(f"{prefix}_REFRESH_TOKEN", "").strip()
    missing = [name for name, value in [
        (f"{prefix}_CLIENT_ID", client_id),
        (f"{prefix}_CLIENT_SECRET", client_secret),
        (f"{prefix}_REFRESH_TOKEN", refresh_token),
    ] if not value]
    if missing:
        raise RuntimeError("Missing YouTube credential secret(s): " + ", ".join(missing))
    # A refresh token is bound to the scopes granted during its original OAuth consent.
    # Sending a new/expanded scopes list during refresh can cause Google's
    # `invalid_scope` error. Leave scopes unset here so the refresh request uses the
    # token's existing grant; re-authorize the token if that grant lacks permissions.
    creds = Credentials(
        token=None, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id, client_secret=client_secret
    )
    try:
        creds.refresh(GoogleAuthRequest())
    except RefreshError as exc:
        message = str(exc)
        if "invalid_scope" in message.lower():
            raise RuntimeError(
                f"Google OAuth refresh failed for {prefix}_REFRESH_TOKEN with invalid_scope. "
                "The refresh token may have been issued with incompatible OAuth scopes or a different OAuth client. "
                "Create a new offline refresh token using the same Client ID/Client Secret configured here and "
                "grant YouTube Data API access (youtube.upload, youtube.readonly, and youtube). "
                "Update the matching GitHub Actions secret, then rerun. Do not share the token publicly."
            ) from exc
        raise RuntimeError(
            f"Google OAuth refresh failed for channel prefix {prefix}: {message}. "
            "Check the client ID, client secret, refresh token, and OAuth consent grant."
        ) from exc
    return creds


def youtube_service(channel: dict[str, Any]):
    creds = credentials_for(channel)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def verify_youtube_channel(youtube, expected_channel_id: str) -> tuple[str, str]:
    """Confirm which YouTube channel the OAuth credentials actually control."""
    response = youtube.channels().list(part="id,snippet", mine=True, maxResults=10).execute()
    items = response.get("items", [])
    if not items:
        raise RuntimeError("YouTube credentials returned no channel for channels.list(mine=true).")
    actual_ids = [item.get("id", "") for item in items]
    if expected_channel_id not in actual_ids:
        details = ", ".join(
            f'{item.get("snippet", {}).get("title", "(untitled)")} ({item.get("id", "no-id")})'
            for item in items
        )
        raise RuntimeError(
            f"OAuth credentials do not control configured channel {expected_channel_id}. "
            f"Authenticated channel(s): {details}. Fix the refresh token/client credentials."
        )
    item = next(item for item in items if item.get("id") == expected_channel_id)
    return item.get("id", ""), item.get("snippet", {}).get("title", "(untitled)")


_ACTIVE_IG_HOST: str | None = None
_IG_HOST_FALLBACK_ATTEMPTED = False


def _api_version() -> str:
    version = os.getenv("IG_GRAPH_API_VERSION", "v23.0").strip()
    if not version:
        version = "v23.0"
    return version if version.startswith("v") else "v" + version


def _configured_ig_mode() -> str:
    mode = os.getenv("IG_API_MODE", "auto").strip().lower() or "auto"
    if mode not in {"auto", "facebook_login", "instagram_login"}:
        raise RuntimeError("IG_API_MODE must be auto, facebook_login, or instagram_login.")
    return mode


def graph_base(host: str | None = None) -> str:
    """Return the Graph API base URL for the configured Instagram login method."""
    global _ACTIVE_IG_HOST
    if host is None and _ACTIVE_IG_HOST:
        host = _ACTIVE_IG_HOST
    if host is None:
        mode = _configured_ig_mode()
        host = "graph.instagram.com" if mode == "instagram_login" else "graph.facebook.com"
    return f"https://{host}/{_api_version()}"


def _instagram_request(host: str, path: str, params: dict[str, Any], token: str,
                       timeout: int) -> tuple[requests.Response, dict[str, Any]]:
    response = requests.get(
        f"https://{host}/{_api_version()}/{path.lstrip('/')}",
        params={**params, "access_token": token}, timeout=timeout,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:500]}
    return response, payload


def instagram_get(path: str, params: dict[str, Any], timeout: int = 40) -> dict[str, Any]:
    """Call Instagram Graph API. In auto mode, try the alternate host on path error 2500.

    The Facebook Login and Instagram Login products use different Graph API hosts. A token
    valid for one product may not work against the other, so auto mode tries the alternate
    host only when the first response indicates an unknown path (code 2500).
    """
    global _ACTIVE_IG_HOST, _IG_HOST_FALLBACK_ATTEMPTED
    token = os.getenv("IG_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing IG_ACCESS_TOKEN.")

    mode = _configured_ig_mode()
    if _ACTIVE_IG_HOST:
        first_host = _ACTIVE_IG_HOST
    elif mode == "instagram_login":
        first_host = "graph.instagram.com"
    else:
        first_host = "graph.facebook.com"

    response, payload = _instagram_request(first_host, path, params, token, timeout)
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    code = error.get("code")

    if (response.status_code >= 400 or "error" in payload) and mode == "auto" and code == 2500 and not _IG_HOST_FALLBACK_ATTEMPTED:
        _IG_HOST_FALLBACK_ATTEMPTED = True
        alternate_host = "graph.instagram.com" if first_host == "graph.facebook.com" else "graph.facebook.com"
        LOGGER.warning(
            "[Instagram] API returned path error 2500 from %s; trying alternate host %s once. "
            "This can happen when the token was issued for a different Instagram API login product.",
            first_host, alternate_host,
        )
        alt_response, alt_payload = _instagram_request(alternate_host, path, params, token, timeout)
        alt_error = alt_payload.get("error", {}) if isinstance(alt_payload, dict) else {}
        if alt_response.status_code < 400 and "error" not in alt_payload:
            _ACTIVE_IG_HOST = alternate_host
            LOGGER.info("[Instagram] API host selected successfully: %s", alternate_host)
            response, payload = alt_response, alt_payload
            error = {}
        else:
            first_message = error.get("message", response.text[:300])
            alt_message = alt_error.get("message", alt_response.text[:300])
            raise RuntimeError(
                "Instagram Graph API rejected the media path on both supported hosts. "
                f"{first_host}: HTTP {response.status_code}, code {code}, {first_message}. "
                f"{alternate_host}: HTTP {alt_response.status_code}, code {alt_error.get('code', 'unknown')}, {alt_message}. "
                "Check that IG_USER_ID is the Instagram Professional Account ID for Facebook Login, "
                "or set IG_API_MODE=instagram_login for an Instagram Login token. Also verify token type, "
                "account linkage, permissions, and API version. Do not print or share the access token."
            )
    elif response.status_code >= 400 or "error" in payload:
        message = error.get("message", response.text[:300])
        raise RuntimeError(
            f"Instagram Graph API error via {first_host} (HTTP {response.status_code}, "
            f"code {code if code is not None else 'unknown'}): {message}. "
            "If using an Instagram Login token, set IG_API_MODE=instagram_login; "
            "if using Facebook Login, confirm IG_USER_ID is the Instagram Professional Account ID."
        )
    else:
        _ACTIVE_IG_HOST = first_host
    return payload


def fetch_instagram_items() -> list[dict[str, Any]]:
    user_id = os.getenv("IG_USER_ID", "").strip()
    if not user_id:
        raise RuntimeError("Missing IG_USER_ID.")
    fields = "id,media_type,media_url,permalink,timestamp,caption,thumbnail_url"
    payload = instagram_get(f"{user_id}/media", {"fields": fields, "limit": 100})
    items: list[dict[str, Any]] = []
    while True:
        items.extend(payload.get("data", []))
        next_url = payload.get("paging", {}).get("next")
        if not next_url:
            break
        # Use the returned paging URL as-is; it already contains Graph API paging parameters.
        response = requests.get(next_url, timeout=40)
        try:
            payload = response.json()
        except ValueError:
            raise RuntimeError("Instagram paging response was not valid JSON.")
        if response.status_code >= 400 or "error" in payload:
            raise RuntimeError(
                "Instagram paging failed: "
                f"{payload.get('error', {}).get('message', response.text[:300])}. "
                "Confirm the selected IG_API_MODE matches the token type and that the token has media-read permissions."
            )
    # Oldest first, to preserve the existing project's processing behavior.
    items.sort(key=lambda x: x.get("timestamp", ""))
    return items


def refresh_media_metadata(item: dict[str, Any]) -> dict[str, Any]:
    """Re-query Instagram by media ID immediately before download; do not reuse a stale URL."""
    media_id = str(item.get("id", ""))
    if not media_id:
        raise RuntimeError("Instagram item has no media ID.")
    fields = "id,media_type,media_url,permalink,timestamp,caption,thumbnail_url"
    try:
        refreshed = instagram_get(media_id, {"fields": fields})
        merged = {**item, **refreshed}
        if merged.get("media_url"):
            LOGGER.info("[Instagram] %s -> Fresh media_url OK (refreshed latest)", media_id)
        else:
            LOGGER.warning("[Instagram] %s -> No media_url after refresh (unavailable/unsupported/permissions)", media_id)
        return merged
    except Exception as exc:
        LOGGER.warning("[Instagram] %s -> Metadata refresh failed: %s", media_id, exc)
        # Return original metadata only if it still has a URL; otherwise caller will defer it.
        return item


def history_path(channel: dict[str, Any]) -> Path:
    return HISTORY_DIR / f"{safe_id(str(channel['id']))}.json"


def _history_record_id(record: Any, fallback_id: Any = None) -> str:
    """Get an Instagram media ID from current or legacy history record shapes."""
    if isinstance(record, str):
        return record.strip() or str(fallback_id or "")
    if isinstance(record, dict):
        for key in ("instagram_media_id", "media_id", "instagram_id", "id"):
            candidate = record.get(key)
            if candidate is not None and str(candidate).strip():
                return str(candidate).strip()
    return str(fallback_id or "").strip()


def _normalize_history(value: Any, channel: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize known legacy history layouts without discarding uploaded markers.

    Returns None only when no recognizable history structure is present.
    """
    channel_id = str(channel["channel_id"])
    normalized: dict[str, Any] = {"channel_id": channel_id, "items": {}}
    if isinstance(value, dict) and isinstance(value.get("items"), dict):
        normalized.update({k: v for k, v in value.items() if k != "items"})
        normalized["channel_id"] = channel_id
        normalized["items"] = {
            str(media_id): record if isinstance(record, dict) else {"status": "UPLOADED" if record else "UNKNOWN"}
            for media_id, record in value["items"].items() if str(media_id).strip()
        }
        return normalized

    # Older versions sometimes saved the list of uploaded IDs under a named key.
    if isinstance(value, dict):
        for key in ("uploaded_ids", "uploaded", "processed_ids", "completed_ids", "media_ids"):
            entries = value.get(key)
            if isinstance(entries, list):
                for entry in entries:
                    media_id = _history_record_id(entry)
                    if media_id:
                        rec = entry if isinstance(entry, dict) else {}
                        normalized["items"][media_id] = {**rec, "instagram_media_id": media_id,
                                                          "status": "UPLOADED" if key in ("uploaded_ids", "uploaded", "completed_ids") else "PROCESSED"}
        # Some old formats stored a list of records directly in "items", or under history/records.
        for key in ("items", "history", "records"):
            entries = value.get(key)
            if isinstance(entries, list):
                for entry in entries:
                    media_id = _history_record_id(entry)
                    if media_id:
                        rec = dict(entry) if isinstance(entry, dict) else {}
                        status = str(rec.get("status", "UNKNOWN")).upper()
                        if status in {"SUCCESS", "DONE", "COMPLETE", "COMPLETED"}:
                            status = "UPLOADED"
                        rec.update(instagram_media_id=media_id, status=status)
                        normalized["items"][media_id] = rec
        # Legacy top-level mapping: media ID -> record/status.
        reserved = {"channel_id", "channel", "uploaded_ids", "uploaded", "processed_ids",
                    "completed_ids", "media_ids", "items", "history", "records", "version", "updated_at"}
        for media_id, record in value.items():
            if media_id in reserved or not str(media_id).strip():
                continue
            if isinstance(record, dict):
                rec = dict(record)
                status = str(rec.get("status", "UNKNOWN")).upper()
                if status in {"SUCCESS", "DONE", "COMPLETE", "COMPLETED"}:
                    status = "UPLOADED"
                rec.update(instagram_media_id=str(media_id), status=status)
                normalized["items"][str(media_id)] = rec
            elif isinstance(record, str) and record.upper() in {"UPLOADED", "SUCCESS", "DONE", "COMPLETE", "COMPLETED"}:
                normalized["items"][str(media_id)] = {"instagram_media_id": str(media_id), "status": "UPLOADED"}
        if normalized["items"]:
            return normalized

    # Older history files were occasionally just a list of uploaded IDs/records.
    if isinstance(value, list):
        for entry in value:
            media_id = _history_record_id(entry)
            if not media_id:
                continue
            if isinstance(entry, dict):
                rec = dict(entry)
                status = str(rec.get("status", "UPLOADED")).upper()
                if status in {"SUCCESS", "DONE", "COMPLETE", "COMPLETED"}:
                    status = "UPLOADED"
                rec.update(instagram_media_id=media_id, status=status)
            else:
                rec = {"instagram_media_id": media_id, "status": "UPLOADED"}
            normalized["items"][media_id] = rec
        return normalized
    return None


def load_history(channel: dict[str, Any]) -> dict[str, Any]:
    path = history_path(channel)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return {"channel_id": channel["channel_id"], "items": {}}
    try:
        with path.open(encoding="utf-8") as f:
            value = json.load(f)
    except Exception as exc:
        # Keep the original file intact; a malformed history must not be silently replaced.
        raise RuntimeError(f"Cannot parse history JSON {path}: {exc}") from exc

    normalized = _normalize_history(value, channel)
    if normalized is not None:
        if not (isinstance(value, dict) and isinstance(value.get("items"), dict)):
            backup = path.with_name(path.name + ".legacy-backup")
            if not backup.exists():
                backup.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            LOGGER.warning("[History] Migrated legacy history format for channel %s; preserved original at %s",
                           channel["id"], backup.name)
            save_history(channel, normalized)
        return normalized

    # Unknown but valid JSON: preserve it and proceed with a clean history so this channel
    # does not block all remaining videos. Warn loudly because unknown data may contain upload markers.
    backup = path.with_name(path.name + ".unrecognized-backup")
    if not backup.exists():
        backup.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    LOGGER.error("[History] Unrecognized history format for channel %s. Original preserved at %s. "
                 "Starting a new history; verify prior uploads to avoid duplicates.", channel["id"], backup.name)
    fresh = {"channel_id": str(channel["channel_id"]), "items": {}}
    save_history(channel, fresh)
    return fresh


def save_history(channel: dict[str, Any], history: dict[str, Any]) -> None:
    path = history_path(channel)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def should_retry(record: dict[str, Any], retry_hours: int) -> bool:
    status = record.get("status")
    if status == "UPLOADED":
        return False
    last = record.get("last_attempt_at")
    if not last:
        return True
    try:
        attempted = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return True
    return utc_now() - attempted >= timedelta(hours=retry_hours)


def download_remote_asset(url: str, media_id: str, download_dir: Path, *, kind: str) -> Path:
    """Download a refreshed Instagram asset to a temporary local file."""
    download_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".mp4" if kind == "video" else ".image"
    destination = download_dir / f"instagram-{safe_id(media_id)}{suffix}"
    partial = destination.with_suffix(destination.suffix + ".part")
    with requests.get(url, stream=True, timeout=(30, 180), allow_redirects=True) as response:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "text/html" in content_type or "application/json" in content_type:
            raise RuntimeError(f"Instagram media URL returned non-media content type: {content_type}")
        size = 0
        with partial.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    size += len(chunk)
        if size < 2_000:
            raise RuntimeError(f"Downloaded asset is too small to be valid ({size} bytes).")
    partial.replace(destination)
    LOGGER.info("[Instagram] Downloaded %d bytes for %s", destination.stat().st_size, media_id)
    return destination


def convert_image_to_video(image_path: Path, media_id: str, download_dir: Path) -> Path:
    """Turn a still image into an 8-second MP4 with letterboxing, ready for YouTube."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed; install ffmpeg to convert Instagram images to MP4.")
    try:
        duration = max(3, min(60, int(os.getenv("IMAGE_VIDEO_DURATION_SECONDS", "8"))))
    except ValueError:
        duration = 8
    output = download_dir / f"instagram-{safe_id(media_id)}-image-video.mp4"
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", str(image_path), "-t", str(duration),
        "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        "-r", "30", "-an", "-c:v", "libx264", "-preset", "veryfast",
        "-movflags", "+faststart", str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=240)
    if result.returncode != 0 or not output.exists() or output.stat().st_size < 10_000:
        detail = (result.stderr or result.stdout or "ffmpeg produced no output")[-1200:]
        raise RuntimeError(f"Image-to-video conversion failed for {media_id}: {detail}")
    LOGGER.info("[Media] Converted Instagram image %s into %s (%d seconds)",
                media_id, output.name, duration)
    return output


def prepare_upload_media(item: dict[str, Any], media_id: str, download_dir: Path) -> tuple[Path | None, str]:
    """Return (video_path, outcome); images are converted to MP4, videos downloaded directly."""
    media_type = str(item.get("media_type", "")).upper()
    if media_type == "VIDEO":
        media_url = item.get("media_url")
        if not media_url:
            return None, "NO_MEDIA"
        return download_remote_asset(str(media_url), media_id, download_dir, kind="video"), "VIDEO"
    if media_type == "IMAGE":
        # Prefer media_url; thumbnail_url is a fallback when Instagram omits media_url.
        image_url = item.get("media_url") or item.get("thumbnail_url")
        if not image_url:
            return None, "NO_MEDIA"
        image_path = download_remote_asset(str(image_url), media_id, download_dir, kind="image")
        try:
            video_path = convert_image_to_video(image_path, media_id, download_dir)
        finally:
            try:
                image_path.unlink(missing_ok=True)
            except OSError:
                pass
        return video_path, "IMAGE_CONVERTED"
    return None, "UNSUPPORTED"


def fetch_carousel_children(media_id: str) -> list[dict[str, Any]]:
    """Fetch carousel children, including child videos and images."""
    fields = "id,media_type,media_url,permalink,timestamp,caption,thumbnail_url"
    payload = instagram_get(f"{media_id}/children", {"fields": fields, "limit": 100})
    children = list(payload.get("data", []))
    while payload.get("paging", {}).get("next"):
        next_url = payload["paging"]["next"]
        response = requests.get(next_url, timeout=40)
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Instagram carousel paging response was not valid JSON.") from exc
        if response.status_code >= 400 or "error" in payload:
            err = payload.get("error", {}) if isinstance(payload, dict) else {}
            raise RuntimeError(f"Instagram carousel paging failed: {err.get('message', response.text[:300])}")
        children.extend(payload.get("data", []))
    LOGGER.info("[Instagram] Carousel %s has %d child item(s)", media_id, len(children))
    return children


def build_title(item: dict[str, Any], channel: dict[str, Any]) -> str:
    caption = re.sub(r"\s+", " ", str(item.get("caption") or "")).strip()
    prefix = str(channel.get("title_prefix", "")).strip()
    # Keep title within YouTube's 100-character limit.
    base = caption.splitlines()[0].strip() if caption else f"Instagram Reel {item.get('id', '')}"
    title = f"{prefix} {base}".strip() if prefix else base
    if len(title) > 100:
        title = title[:97].rstrip() + "..."
    return title


def build_description(item: dict[str, Any], channel: dict[str, Any]) -> str:
    caption = str(item.get("caption") or "").strip()
    permalink = str(item.get("permalink") or "")
    template = str(channel.get("description_template", "{caption}\n\nSource Instagram: {permalink}"))
    try:
        return template.format(caption=caption, permalink=permalink, media_id=item.get("id", ""))
    except (KeyError, ValueError):
        return f"{caption}\n\nSource Instagram: {permalink}".strip()


def upload_video(youtube, item: dict[str, Any], channel: dict[str, Any],
                 video_path: Path) -> str:
    privacy = str(channel.get("privacy") or os.getenv("YOUTUBE_PRIVACY_STATUS", "private")).lower()
    if privacy not in {"private", "unlisted", "public"}:
        raise ValueError(f"Invalid privacy setting {privacy!r}; use private, unlisted, or public.")
    body = {
        "snippet": {
            "title": build_title(item, channel),
            "description": build_description(item, channel),
            "tags": list(channel.get("tags", []))[:500],
            "categoryId": str(channel.get("category_id", "24")),
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": bool(channel.get("made_for_kids", False)),
        },
    }
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            LOGGER.info("[YouTube] Upload progress: %.0f%%", status.progress() * 100)
    video_id = response.get("id")
    if not video_id:
        raise RuntimeError(f"YouTube upload returned no video ID: {response}")
    LOGGER.info("[YouTube] Upload complete: https://youtu.be/%s (privacy=%s)", video_id, privacy)
    return video_id


def resolve_playlist_id(youtube, channel: dict[str, Any]) -> str:
    """Resolve a configured playlist ID or exact playlist title owned by this channel."""
    configured_id = str(channel.get("playlist_id", "")).strip()
    if configured_id and configured_id != "${BHAVYCHILDHOOD_PLAYLIST_ID}":
        return configured_id
    title = str(channel.get("playlist_title", "")).strip()
    if not title:
        if channel.get("playlist_required", False):
            raise RuntimeError(
                f"Channel {channel.get('id')} requires a playlist, but playlist_id/playlist_title is not configured."
            )
        return ""

    matches = []
    page_token = None
    while True:
        response = youtube.playlists().list(
            part="id,snippet", mine=True, maxResults=50, pageToken=page_token
        ).execute()
        for playlist in response.get("items", []):
            playlist_title = str(playlist.get("snippet", {}).get("title", "")).strip()
            if playlist_title.casefold() == title.casefold():
                matches.append(playlist)
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    if not matches:
        raise RuntimeError(
            f"Required playlist '{title}' was not found among playlists owned by authenticated channel. "
            "No videos were uploaded. Check the playlist name and YouTube OAuth permissions."
        )
    if len(matches) > 1:
        details = ", ".join(
            f"{m.get('snippet', {}).get('title', title)} ({m.get('id', 'no-id')})" for m in matches
        )
        raise RuntimeError(
            f"More than one owned playlist exactly matches '{title}': {details}. "
            "Set playlist_id explicitly in config/channels.json to avoid choosing the wrong playlist."
        )
    playlist_id = str(matches[0].get("id", "")).strip()
    if not playlist_id:
        raise RuntimeError(f"Playlist '{title}' was found but YouTube returned no playlist ID.")
    LOGGER.info("[YouTube] Resolved required playlist '%s': https://www.youtube.com/playlist?list=%s", title, playlist_id)
    return playlist_id


def playlist_video_ids(youtube, playlist_id: str) -> set[str]:
    """Return video IDs already present in the playlist to make backfill idempotent."""
    video_ids: set[str] = set()
    page_token = None
    while True:
        response = youtube.playlistItems().list(
            part="snippet,contentDetails", playlistId=playlist_id, maxResults=50, pageToken=page_token
        ).execute()
        for item in response.get("items", []):
            video_id = (item.get("contentDetails", {}).get("videoId")
                        or item.get("snippet", {}).get("resourceId", {}).get("videoId"))
            if video_id:
                video_ids.add(str(video_id))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return video_ids


def add_to_playlist(youtube, video_id: str, playlist_id: str) -> None:
    """Add a video to the configured playlist, retrying short-lived YouTube API failures.

    Shorts are still normal YouTube videos for playlist purposes. A video appearing in
    the Shorts tab does not mean it cannot also be in a playlist.
    """
    body = {"snippet": {
        "playlistId": playlist_id,
        "resourceId": {"kind": "youtube#video", "videoId": video_id},
    }}
    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        try:
            response = youtube.playlistItems().insert(part="snippet", body=body).execute()
            returned_playlist = str(response.get("snippet", {}).get("playlistId", "")).strip()
            returned_video = str(
                response.get("snippet", {}).get("resourceId", {}).get("videoId", "")
            ).strip()
            if returned_playlist and returned_playlist != playlist_id:
                raise RuntimeError(
                    f"YouTube inserted video {video_id} into unexpected playlist {returned_playlist}; "
                    f"expected {playlist_id}."
                )
            if returned_video and returned_video != video_id:
                raise RuntimeError(
                    f"YouTube returned unexpected video ID {returned_video}; expected {video_id}."
                )
            LOGGER.info(
                "[YouTube] PLAYLIST INSERT CONFIRMED: video=%s playlist=%s url=https://www.youtube.com/playlist?list=%s",
                video_id, playlist_id, playlist_id,
            )
            return
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            message = str(exc).lower()
            transient = status in {404, 409, 429, 500, 502, 503, 504} or any(
                token in message for token in ("videonotfound", "processingfailure", "backenderror")
            )
            if not transient or attempt == max_attempts:
                LOGGER.error(
                    "[YouTube] PLAYLIST INSERT FAILED: video=%s playlist=%s attempt=%d/%d status=%s error=%s",
                    video_id, playlist_id, attempt, max_attempts, status, exc,
                )
                raise
            delay = min(2 ** attempt, 10)
            LOGGER.warning(
                "[YouTube] Playlist insert not ready yet for video=%s playlist=%s; retry %d/%d in %ds: %s",
                video_id, playlist_id, attempt + 1, max_attempts, delay, exc,
            )
            time.sleep(delay)


def process_channel(channel: dict[str, Any], items: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    channel_key = str(channel["id"])
    configured_channel_id = str(channel["channel_id"])
    LOGGER.info("=" * 70)
    LOGGER.info("[Channel %s] configured YouTube channel ID: %s", channel_key, configured_channel_id)
    history = load_history(channel)
    LOGGER.info("[Channel %s] independent history: %s", channel_key, history_path(channel).relative_to(ROOT))
    counts: dict[str, int] = {}
    for record in history["items"].values():
        status = record.get("status", "UNKNOWN") if isinstance(record, dict) else "UNKNOWN"
        counts[status] = counts.get(status, 0) + 1
    LOGGER.info("[Channel %s] current history: %s", channel_key, counts)

    youtube = youtube_service(channel)
    actual_id, actual_title = verify_youtube_channel(youtube, configured_channel_id)
    LOGGER.info("[Channel %s] OAuth verified destination: %s (%s)", channel_key, actual_title, actual_id)
    summary["youtube_channel_id"] = actual_id
    summary["youtube_channel_title"] = actual_title

    # Playlist management can use a different OAuth account from the upload destination.
    # This lets each channel upload independently while the playlist owner (YT1) adds every
    # successful public video to the one shared bhavychildhood playlist.
    playlist_env_prefix = str(channel.get("playlist_env_prefix", channel.get("env_prefix", ""))).strip()
    upload_env_prefix = str(channel.get("env_prefix", "")).strip()
    playlist_youtube = youtube
    if playlist_env_prefix and playlist_env_prefix != upload_env_prefix:
        playlist_account = {**channel, "env_prefix": playlist_env_prefix}
        playlist_youtube = youtube_service(playlist_account)
        expected_playlist_owner = str(channel.get("playlist_owner_channel_id", "")).strip()
        if expected_playlist_owner:
            owner_id, owner_title = verify_youtube_channel(playlist_youtube, expected_playlist_owner)
            LOGGER.info("[Channel %s] Playlist manager verified: %s (%s)", channel_key, owner_title, owner_id)

    # Resolve and validate the required playlist BEFORE any video upload API call.
    playlist_id = resolve_playlist_id(playlist_youtube, channel)
    LOGGER.info(
        "[Channel %s] REQUIRED PLAYLIST TARGET: title=%s id=%s manager_prefix=%s; "
        "Shorts classification does not prevent playlist membership.",
        channel_key, channel.get("playlist_title", "bhavychildhood"), playlist_id,
        playlist_env_prefix or upload_env_prefix,
    )
    summary["playlist_id"] = playlist_id or ""
    summary["playlist_url"] = f"https://www.youtube.com/playlist?list={playlist_id}" if playlist_id else ""
    present_in_playlist: set[str] = set()
    if playlist_id:
        LOGGER.info("[Channel %s] All new and previously uploaded videos will target playlist: https://www.youtube.com/playlist?list=%s",
                    channel_key, playlist_id)
        present_in_playlist = playlist_video_ids(playlist_youtube, playlist_id)
        # Backfill all videos already marked uploaded in this channel's history.
        # This repairs earlier runs where upload succeeded but playlist insertion was never configured.
        backfilled = 0
        backfill_failed = 0
        for history_key, saved_record in history["items"].items():
            if not isinstance(saved_record, dict) or saved_record.get("status") != "UPLOADED":
                continue
            saved_video_id = str(saved_record.get("youtube_video_id", "")).strip()
            if not saved_video_id or saved_video_id in present_in_playlist:
                continue
            try:
                add_to_playlist(playlist_youtube, saved_video_id, playlist_id)
                present_in_playlist.add(saved_video_id)
                saved_record["playlist_id"] = playlist_id
                saved_record["playlist_url"] = f"https://www.youtube.com/playlist?list={playlist_id}"
                saved_record.pop("playlist_error", None)
                saved_record["updated_at"] = iso_now()
                history["items"][history_key] = saved_record
                backfilled += 1
                summary["playlist_backfilled_video_ids"].append(saved_video_id)
            except Exception as playlist_exc:
                saved_record["playlist_error"] = str(playlist_exc)
                saved_record["updated_at"] = iso_now()
                history["items"][history_key] = saved_record
                backfill_failed += 1
                summary["playlist_add_failed_video_ids"].append(saved_video_id)
                LOGGER.exception("[Channel %s] Could not add previous upload %s to required playlist %s",
                                 channel_key, saved_video_id, playlist_id)
        if backfilled or backfill_failed:
            save_history(channel, history)
        LOGGER.info("[Channel %s] Playlist backfill complete: added=%d failed=%d already_present=%d",
                    channel_key, backfilled, backfill_failed, len(present_in_playlist))

    retry_hours = int(os.getenv("SKIPPED_RETRY_HOURS", "24"))
    max_upload_attempts = max(1, int(channel.get("max_items_per_run", os.getenv("MAX_ITEMS_PER_RUN", "20"))))
    download_dir = ROOT / os.getenv("DOWNLOAD_DIR", "downloads")
    upload_attempts = 0
    run_stats = {"uploads_succeeded": 0, "upload_attempts": 0, "images_converted": 0,
                 "carousel_children_seen": 0, "no_media": 0, "unsupported": 0,
                 "failed": 0, "skipped_already_uploaded": 0, "deferred_by_retry": 0}
    stop_for_limit = False

    def process_asset(asset: dict[str, Any], history_key: str, *, parent_id: str | None = None) -> str:
        """Process one video/image. Returns uploaded, skipped, failed, or limit."""
        nonlocal upload_attempts, stop_for_limit
        asset_id = str(asset.get("id", ""))
        if not asset_id:
            run_stats["unsupported"] += 1
            return "skipped"
        existing = history["items"].get(history_key, {})
        if not isinstance(existing, dict):
            existing = {}
        if existing.get("status") == "UPLOADED":
            run_stats["skipped_already_uploaded"] += 1
            return "skipped"
        # Old versions marked still images and carousel parents unsupported. Revisit those
        # immediately now that image-to-video and carousel-child handling are supported.
        current_type = str(asset.get("media_type", "")).upper()
        legacy_unsupported_now_supported = (
            existing.get("status") == "SKIPPED_UNSUPPORTED_MEDIA"
            and current_type in {"IMAGE", "VIDEO", "CAROUSEL_ALBUM"}
        )
        if not legacy_unsupported_now_supported and not should_retry(existing, retry_hours):
            run_stats["deferred_by_retry"] += 1
            return "skipped"

        now = iso_now()
        record = {**existing, "instagram_media_id": asset_id, "last_attempt_at": now,
                  "attempt_count": int(existing.get("attempt_count", 0)) + 1,
                  "instagram_permalink": asset.get("permalink", ""),
                  "instagram_timestamp": asset.get("timestamp", "")}
        if parent_id:
            record["instagram_parent_media_id"] = parent_id
        video_path: Path | None = None
        try:
            item = refresh_media_metadata(asset)
            media_type = str(item.get("media_type", "")).upper()
            # Some API responses omit media_type on refresh; retain the original value.
            if not media_type:
                media_type = str(asset.get("media_type", "")).upper()
                item["media_type"] = media_type
            if media_type not in {"VIDEO", "IMAGE"}:
                record.update(status="SKIPPED_UNSUPPORTED_MEDIA", last_error=f"Unsupported media_type: {media_type or 'missing'}",
                              retry_after_hours=retry_hours, updated_at=iso_now())
                history["items"][history_key] = record
                save_history(channel, history)
                run_stats["unsupported"] += 1
                LOGGER.info("[Channel %s] Unsupported media type %s for Instagram item %s", channel_key, media_type or "(missing)", asset_id)
                return "skipped"

            # If the upload-attempt cap is reached, continue skipping metadata-only items but do not
            # download/convert another eligible asset. Its history is left unchanged for the next run.
            if upload_attempts >= max_upload_attempts:
                stop_for_limit = True
                return "limit"

            video_path, outcome = prepare_upload_media(item, asset_id, download_dir)
            if outcome == "NO_MEDIA" or video_path is None:
                record.update(status="SKIPPED_NO_MEDIA", last_error="Instagram returned no usable media_url/thumbnail_url after refresh",
                              retry_after_hours=retry_hours, updated_at=iso_now())
                history["items"][history_key] = record
                save_history(channel, history)
                run_stats["no_media"] += 1
                LOGGER.warning("[Channel %s] No usable media URL for %s (%s); retry eligible after %s hours",
                               channel_key, asset_id, media_type, retry_hours)
                return "skipped"
            if outcome == "IMAGE_CONVERTED":
                run_stats["images_converted"] += 1

            LOGGER.info("[Channel %s] READY: Instagram %s (%s) -> %s", channel_key, asset_id, outcome, video_path.name)
            LOGGER.info("[Channel %s] File size: %d bytes", channel_key, video_path.stat().st_size)
            upload_attempts += 1
            run_stats["upload_attempts"] += 1
            # First upload-related YouTube API call happens only after the complete MP4 is ready.
            video_id = upload_video(youtube, item, channel, video_path)
            video_url = f"https://youtu.be/{video_id}"
            record.update(status="UPLOADED", youtube_video_id=video_id, youtube_video_url=video_url,
                          youtube_channel_id=actual_id, youtube_channel_title=actual_title,
                          privacy_status=channel.get("privacy", os.getenv("YOUTUBE_PRIVACY_STATUS", "private")),
                          playlist_id=None, playlist_url=None, last_error=None, uploaded_at=iso_now(),
                          source_media_type=media_type, image_converted=(outcome == "IMAGE_CONVERTED"),
                          updated_at=iso_now())
            if playlist_id:
                try:
                    if video_id not in present_in_playlist:
                        add_to_playlist(playlist_youtube, video_id, playlist_id)
                        present_in_playlist.add(video_id)
                    record["playlist_id"] = playlist_id
                    record["playlist_url"] = f"https://www.youtube.com/playlist?list={playlist_id}"
                    record.pop("playlist_error", None)
                    LOGGER.info(
                        "[Channel %s] PLAYLIST SUCCESS: video=%s playlist=%s",
                        channel_key, video_id, record["playlist_url"],
                    )
                except Exception as playlist_exc:
                    # Preserve the successful upload in history; next run retries playlist insertion.
                    record["playlist_error"] = str(playlist_exc)
                    LOGGER.exception("[Channel %s] Video uploaded but required playlist insertion failed; it will be retried next run",
                                     channel_key)
            history["items"][history_key] = record
            save_history(channel, history)
            run_stats["uploads_succeeded"] += 1
            summary["uploaded_video_ids"].append(video_id)
            summary["uploaded_video_urls"].append(video_url)
            if record.get("playlist_error"):
                summary["playlist_add_failed_video_ids"].append(video_id)
            elif playlist_id:
                summary["playlist_added_video_ids"].append(video_id)
            LOGGER.info("[Channel %s] SUCCESS %s", channel_key, video_url)
            LOGGER.info("[Channel %s] YouTube channel: %s (%s)", channel_key, actual_title, actual_id)
            LOGGER.info("[Channel %s] Instagram source: %s (%s)", channel_key, asset_id, media_type)
            if outcome == "IMAGE_CONVERTED":
                LOGGER.info("[Channel %s] Upload type: image converted to MP4", channel_key)
            if record.get("playlist_url"):
                LOGGER.info("[Channel %s] Playlist: %s", channel_key, record["playlist_url"])
            else:
                LOGGER.info("[Channel %s] Playlist: not configured / not added", channel_key)
            return "uploaded"
        except Exception as exc:
            if is_upload_limit_error(exc):
                # Do not keep trying: YouTube will reject every subsequent upload until its
                # account/channel upload allowance resets or is otherwise resolved.
                record.update(status="FAILED_UPLOAD_LIMIT", last_error=str(exc), updated_at=iso_now())
                history["items"][history_key] = record
                save_history(channel, history)
                LOGGER.critical(
                    "[Channel %s] YouTube upload limit reached for Instagram item %s. "
                    "Stopping the entire workflow immediately; no further YouTube uploads will be attempted.",
                    channel_key, asset_id,
                )
                raise UploadLimitExceeded(
                    f"YouTube returned uploadLimitExceeded for channel {channel_key}; stopped immediately."
                ) from exc
            run_stats["failed"] += 1
            LOGGER.exception("[Channel %s] FAILED for Instagram item %s: %s", channel_key, asset_id, exc)
            record.update(status="FAILED", last_error=str(exc), updated_at=iso_now())
            history["items"][history_key] = record
            save_history(channel, history)
            return "failed"
        finally:
            if video_path and video_path.exists():
                try:
                    video_path.unlink()
                except OSError:
                    LOGGER.warning("Could not remove temporary video file %s", video_path)

    # Prioritize actual videos/reels, then carousels, then still images. Preserve oldest-first
    # order within each type. Skipped items do not consume the upload-attempt limit.
    priority = {"VIDEO": 0, "CAROUSEL_ALBUM": 1, "IMAGE": 2}
    ordered_items = sorted(items, key=lambda x: (priority.get(str(x.get("media_type", "")).upper(), 3),
                                                 str(x.get("timestamp", ""))))
    for original in ordered_items:
        media_id = str(original.get("id", ""))
        if not media_id:
            continue
        if stop_for_limit:
            LOGGER.info("[Channel %s] Reached max upload attempts per run=%s", channel_key, max_upload_attempts)
            break
        original_type = str(original.get("media_type", "")).upper()
        if original_type != "CAROUSEL_ALBUM":
            process_asset(original, media_id)
            continue

        # A carousel parent has multiple child assets. Each child gets its own history key so
        # uploaded children are never uploaded again if a later child fails or the run limit hits.
        parent_existing = history["items"].get(media_id, {})
        if isinstance(parent_existing, dict) and parent_existing.get("status") == "UPLOADED":
            continue
        parent_status = parent_existing.get("status") if isinstance(parent_existing, dict) else None
        legacy_unsupported_carousel = parent_status == "SKIPPED_UNSUPPORTED_MEDIA"
        pending_carousel = parent_status == "PENDING_CAROUSEL_CHILDREN"
        if (not legacy_unsupported_carousel and not pending_carousel
                and isinstance(parent_existing, dict) and not should_retry(parent_existing, retry_hours)):
            run_stats["deferred_by_retry"] += 1
            continue
        try:
            parent = refresh_media_metadata(original)
            children = fetch_carousel_children(media_id)
            if not children:
                record = {**(parent_existing if isinstance(parent_existing, dict) else {}),
                          "instagram_media_id": media_id, "status": "SKIPPED_NO_MEDIA",
                          "last_attempt_at": iso_now(), "last_error": "Carousel returned no child items",
                          "retry_after_hours": retry_hours, "updated_at": iso_now()}
                history["items"][media_id] = record
                save_history(channel, history)
                run_stats["no_media"] += 1
                LOGGER.warning("[Channel %s] Carousel %s has no accessible children; retry after %s hours",
                               channel_key, media_id, retry_hours)
                continue
            parent_caption = parent.get("caption", original.get("caption", ""))
            parent_permalink = parent.get("permalink", original.get("permalink", ""))
            completed_all = True
            for child in children:
                if stop_for_limit:
                    completed_all = False
                    break
                child = {**child}
                child.setdefault("caption", parent_caption)
                child.setdefault("permalink", parent_permalink)
                child_id = str(child.get("id", ""))
                if not child_id:
                    run_stats["unsupported"] += 1
                    continue
                run_stats["carousel_children_seen"] += 1
                child_key = f"{media_id}::{child_id}"
                result = process_asset(child, child_key, parent_id=media_id)
                if result == "limit":
                    completed_all = False
                    break
            parent_record = {**(parent_existing if isinstance(parent_existing, dict) else {}),
                             "instagram_media_id": media_id,
                             "status": "PROCESSED_CAROUSEL" if completed_all else "PENDING_CAROUSEL_CHILDREN",
                             "child_count": len(children), "last_attempt_at": iso_now(), "updated_at": iso_now()}
            history["items"][media_id] = parent_record
            save_history(channel, history)
        except UploadLimitExceeded:
            # Never swallow a hard upload-limit stop inside carousel processing.
            raise
        except Exception as exc:
            run_stats["failed"] += 1
            LOGGER.exception("[Channel %s] Could not process carousel %s: %s", channel_key, media_id, exc)
            existing_parent = parent_existing if isinstance(parent_existing, dict) else {}
            history["items"][media_id] = {**existing_parent, "instagram_media_id": media_id,
                "status": "FAILED", "last_attempt_at": iso_now(), "last_error": str(exc), "updated_at": iso_now()}
            save_history(channel, history)

    counts = {}
    for record in history["items"].values():
        status = record.get("status", "UNKNOWN") if isinstance(record, dict) else "UNKNOWN"
        counts[status] = counts.get(status, 0) + 1
    LOGGER.info("[Channel %s] Final history summary: %s", channel_key, counts)
    LOGGER.info("[Channel %s] Run summary: %s", channel_key, run_stats)
    LOGGER.info("[Channel %s] Upload attempts this run: %d/%d", channel_key, upload_attempts, max_upload_attempts)
    summary["status"] = "upload_limit_reached" if stop_for_limit else "completed"
    summary["uploads_succeeded"] = len(summary["uploaded_video_ids"])
    summary["run_stats"] = run_stats


def log_final_run_summary(summaries: list[dict[str, Any]], overall_status: str) -> None:
    """Print an easy-to-scan per-channel result, including YouTube video IDs."""
    LOGGER.info("=" * 80)
    LOGGER.info("[FINAL STATUS] Overall run status: %s", overall_status.upper())
    if not summaries:
        LOGGER.info("[FINAL STATUS] No channel runs were attempted.")
    for item in summaries:
        LOGGER.info(
            "[FINAL STATUS] Channel config=%s | status=%s | YouTube channel=%s (%s) | "
            "uploaded successfully this run=%d | playlist=%s",
            item.get("channel_config_id", "unknown"), item.get("status", "not_started"),
            item.get("youtube_channel_title", "not verified"), item.get("youtube_channel_id", "unknown"),
            len(item.get("uploaded_video_ids", [])), item.get("playlist_url") or "not configured",
        )
        video_ids = item.get("uploaded_video_ids", [])
        video_urls = item.get("uploaded_video_urls", [])
        if video_ids:
            LOGGER.info("[FINAL STATUS] Newly uploaded video IDs: %s", ", ".join(video_ids))
            for video_id, video_url in zip(video_ids, video_urls):
                LOGGER.info("[FINAL STATUS] Video: ID=%s URL=%s", video_id, video_url)
        else:
            LOGGER.info("[FINAL STATUS] Newly uploaded video IDs: none")
        LOGGER.info(
            "[FINAL STATUS] Newly uploaded videos successfully in playlist=%d (%s); "
            "old videos backfilled=%d (%s); playlist additions failed=%d (%s)",
            len(item.get("playlist_added_video_ids", [])),
            ", ".join(item.get("playlist_added_video_ids", [])) or "none",
            len(item.get("playlist_backfilled_video_ids", [])),
            ", ".join(item.get("playlist_backfilled_video_ids", [])) or "none",
            len(item.get("playlist_add_failed_video_ids", [])),
            ", ".join(item.get("playlist_add_failed_video_ids", [])) or "none",
        )
        if item.get("error"):
            LOGGER.info("[FINAL STATUS] Channel error: %s", item["error"])
        if item.get("run_stats"):
            LOGGER.info("[FINAL STATUS] Processing stats: %s", item["run_stats"])
    LOGGER.info("=" * 80)


def main() -> int:
    setup_logging()
    summaries: list[dict[str, Any]] = []
    overall_status = "failed"
    try:
        configured_channels = load_config()
        target_id = os.getenv("CHANNEL_CONFIG_ID", "").strip()
        if target_id:
            matches = [ch for ch in configured_channels if str(ch.get("id")) == target_id]
            if not matches:
                raise RuntimeError(f"CHANNEL_CONFIG_ID={target_id!r} does not exist in config/channels.json")
            channels = matches
            LOGGER.info("[Run] Isolated channel job selected: %s", target_id)
        else:
            # Local/manual runs without CHANNEL_CONFIG_ID still process all enabled channels.
            channels = configured_channels
            LOGGER.warning("[Run] CHANNEL_CONFIG_ID is not set; processing enabled channels in this process. "
                           "GitHub Actions uses one isolated job per channel.")

        enabled = [ch for ch in channels if bool(ch.get("enabled", False))]
        for ch in channels:
            summaries.append({
                "channel_config_id": str(ch.get("id", "unknown")),
                "status": "disabled" if not ch.get("enabled", False) else "not_started",
                "youtube_channel_id": str(ch.get("channel_id", "unknown")),
                "youtube_channel_title": "not verified",
                "playlist_id": "", "playlist_url": "",
                "uploaded_video_ids": [], "uploaded_video_urls": [],
                "playlist_added_video_ids": [], "playlist_backfilled_video_ids": [],
                "playlist_add_failed_video_ids": [],
            })
        if not enabled:
            LOGGER.warning("[Config] No enabled YouTube channels selected for this job.")
            overall_status = "no_enabled_channels"
            return 0

        # Suppress only the channel that hit uploadLimitExceeded, through the rest of the
        # current Asia/Kolkata calendar day. Each channel has its own history and marker.
        eligible: list[dict[str, Any]] = []
        summary_by_id = {entry["channel_config_id"]: entry for entry in summaries}
        today = upload_limit_day()
        for ch in enabled:
            summary = summary_by_id[str(ch["id"])]
            try:
                history = load_history(ch)
                blocked_day = str(history.get("upload_limit_blocked_day", ""))
                if blocked_day == today:
                    summary["status"] = "skipped_upload_limit_blocked_today"
                    summary["error"] = (f"This channel reached YouTube's upload limit earlier today ({today}, Asia/Kolkata); "
                                         "skipping it until the next local day.")
                    LOGGER.warning("[Channel %s] %s", ch["id"], summary["error"])
                    continue
                if blocked_day and blocked_day != today:
                    history.pop("upload_limit_blocked_day", None)
                    history.pop("upload_limit_error", None)
                    save_history(ch, history)
                    LOGGER.info("[Channel %s] Previous upload-limit block expired (%s); retrying on %s.",
                                ch["id"], blocked_day, today)
                eligible.append(ch)
            except Exception as exc:
                summary["status"] = "failed"
                summary["error"] = str(exc)
                LOGGER.exception("[Channel %s] Could not check per-channel upload-limit state", ch["id"])

        if not eligible:
            overall_status = "all_channels_skipped_or_failed"
            return 1 if any(x.get("status") == "failed" for x in summaries) else 0

        ig_user_id = os.getenv("IG_USER_ID", "").strip()
        if not ig_user_id or not os.getenv("IG_ACCESS_TOKEN", "").strip():
            raise RuntimeError("IG_USER_ID and IG_ACCESS_TOKEN must be configured.")

        # Fetch Instagram list once per isolated job. Jobs run independently in GitHub Actions,
        # so a channel failure cannot stop or cancel another channel's job.
        LOGGER.info("[Instagram] Fetching media list...")
        items = fetch_instagram_items()
        LOGGER.info("[Instagram] Total: %d sorted oldest first", len(items))
        if items:
            LOGGER.info("[Instagram] Oldest: %s @ %s", items[0].get("id"), items[0].get("timestamp"))
            LOGGER.info("[Instagram] Newest: %s @ %s", items[-1].get("id"), items[-1].get("timestamp"))

        for ch in eligible:
            summary = summary_by_id[str(ch.get("id", "unknown"))]
            prefix = str(ch.get("env_prefix", ""))
            missing = [f"{prefix}_{suffix}" for suffix in
                       ("CLIENT_ID", "CLIENT_SECRET", "REFRESH_TOKEN") if not os.getenv(f"{prefix}_{suffix}")]
            if missing:
                message = ", ".join(missing)
                summary["status"] = "skipped_missing_credentials"
                summary["error"] = f"Missing credentials: {message}"
                LOGGER.error("[Config] %s enabled but missing credentials: %s; skipping this channel only",
                             ch.get("id"), message)
                continue
            LOGGER.info("[Config] %s: enabled", ch["id"])
            summary["status"] = "running"
            try:
                process_channel(ch, items, summary)
            except UploadLimitExceeded as exc:
                # Persist the suppression marker in THIS channel's independent history. Other
                # matrix jobs are unaffected and continue processing their own channel.
                summary["status"] = "upload_limit_reached"
                summary["error"] = str(exc)
                try:
                    history = load_history(ch)
                    history["upload_limit_blocked_day"] = upload_limit_day()
                    history["upload_limit_error"] = str(exc)
                    save_history(ch, history)
                    LOGGER.critical("[Channel %s] Marked blocked for the remainder of %s (Asia/Kolkata).",
                                    ch["id"], history["upload_limit_blocked_day"])
                except Exception:
                    LOGGER.exception("[Channel %s] Could not persist upload-limit suppression marker", ch["id"])
                # Do not return: in local multi-channel runs, continue to the next channel.
                continue
            except Exception as exc:
                summary["status"] = "failed"
                summary["error"] = str(exc)
                LOGGER.exception("[Channel %s] Channel failed; other channels will continue", ch["id"])

        overall_status = "completed_with_errors" if any(
            item.get("status") in {"failed", "skipped_missing_credentials", "upload_limit_reached"}
            for item in summaries
        ) else "completed"
        LOGGER.info("[Run] Finished channel job.")
        return 1 if overall_status == "completed_with_errors" else 0
    except Exception as exc:
        LOGGER.exception("[Run] Fatal error")
        overall_status = f"fatal_error: {exc}"
        return 1
    finally:
        log_final_run_summary(summaries, overall_status)


if __name__ == "__main__":
    raise SystemExit(main())
