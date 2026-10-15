from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests
from google.auth.transport.requests import Request as GoogleAuthRequest
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


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


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
    creds = Credentials(
        token=None, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id, client_secret=client_secret, scopes=SCOPES
    )
    creds.refresh(GoogleAuthRequest())
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


def load_history(channel: dict[str, Any]) -> dict[str, Any]:
    path = history_path(channel)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return {"channel_id": channel["channel_id"], "items": {}}
    try:
        with path.open(encoding="utf-8") as f:
            value = json.load(f)
        if not isinstance(value, dict) or not isinstance(value.get("items"), dict):
            raise ValueError("Unexpected history format")
        return value
    except Exception as exc:
        # Never silently overwrite a damaged history file.
        raise RuntimeError(f"Cannot read history {path}: {exc}") from exc


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


def download_video(url: str, media_id: str, download_dir: Path) -> Path:
    download_dir.mkdir(parents=True, exist_ok=True)
    destination = download_dir / f"instagram-{safe_id(media_id)}.mp4"
    partial = destination.with_suffix(".mp4.part")
    with requests.get(url, stream=True, timeout=(30, 180), allow_redirects=True) as response:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "text/html" in content_type or "application/json" in content_type:
            raise RuntimeError(f"Instagram media URL returned non-video content type: {content_type}")
        size = 0
        with partial.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    size += len(chunk)
        if size < 10_000:
            raise RuntimeError(f"Downloaded file is too small to be a valid video ({size} bytes).")
    partial.replace(destination)
    LOGGER.info("[Instagram] Downloaded %d bytes", destination.stat().st_size)
    return destination


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


def add_to_playlist(youtube, video_id: str, playlist_id: str) -> None:
    youtube.playlistItems().insert(
        part="snippet",
        body={"snippet": {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        }},
    ).execute()
    LOGGER.info("[YouTube] Added video %s to playlist %s", video_id, playlist_id)


def process_channel(channel: dict[str, Any], items: list[dict[str, Any]]) -> None:
    channel_key = str(channel["id"])
    configured_channel_id = str(channel["channel_id"])
    LOGGER.info("=" * 70)
    LOGGER.info("[Channel %s] configured YouTube channel ID: %s", channel_key, configured_channel_id)
    history = load_history(channel)
    LOGGER.info("[Channel %s] independent history: %s", channel_key, history_path(channel).relative_to(ROOT))
    counts: dict[str, int] = {}
    for record in history["items"].values():
        status = record.get("status", "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1
    LOGGER.info("[Channel %s] current history: %s", channel_key, counts)

    youtube = youtube_service(channel)
    actual_id, actual_title = verify_youtube_channel(youtube, configured_channel_id)
    LOGGER.info("[Channel %s] OAuth verified destination: %s (%s)", channel_key, actual_title, actual_id)

    retry_hours = int(os.getenv("SKIPPED_RETRY_HOURS", "24"))
    max_items = int(channel.get("max_items_per_run", os.getenv("MAX_ITEMS_PER_RUN", "20")))
    download_dir = ROOT / os.getenv("DOWNLOAD_DIR", "downloads")
    processed_this_run = 0

    for original in items:
        media_id = str(original.get("id", ""))
        if not media_id:
            continue
        existing = history["items"].get(media_id, {})
        if existing.get("status") == "UPLOADED":
            continue
        if not should_retry(existing, retry_hours):
            continue
        if processed_this_run >= max_items:
            LOGGER.info("[Channel %s] Reached max_items_per_run=%s", channel_key, max_items)
            break
        processed_this_run += 1
        LOGGER.info("[Channel %s] Checking Instagram item %s", channel_key, media_id)
        now = iso_now()
        record = {**existing, "instagram_media_id": media_id, "last_attempt_at": now,
                  "attempt_count": int(existing.get("attempt_count", 0)) + 1,
                  "instagram_permalink": original.get("permalink", ""),
                  "instagram_timestamp": original.get("timestamp", "")}
        video_path = None
        try:
            item = refresh_media_metadata(original)
            media_type = str(item.get("media_type", ""))
            if media_type != "VIDEO":
                record.update(status="SKIPPED_UNSUPPORTED_MEDIA", last_error=f"Unsupported media_type: {media_type}",
                              updated_at=iso_now())
                history["items"][media_id] = record
                save_history(channel, history)
                LOGGER.info("[Channel %s] Skip unsupported media type %s", channel_key, media_type)
                continue
            media_url = item.get("media_url")
            if not media_url:
                record.update(status="SKIPPED_NO_MEDIA", last_error="Instagram returned no media_url after refresh",
                              retry_after_hours=retry_hours, updated_at=iso_now())
                history["items"][media_id] = record
                save_history(channel, history)
                LOGGER.warning("[Channel %s] No media URL; retry eligible after %s hours", channel_key, retry_hours)
                continue

            LOGGER.info("[Instagram] Downloading video...")
            video_path = download_video(str(media_url), media_id, download_dir)
            LOGGER.info("[Channel %s] READY: %s -> %s", channel_key, media_id, video_path.name)
            LOGGER.info("[Channel %s] File size: %s bytes", channel_key, video_path.stat().st_size)
            # First upload-related YouTube API call occurs only after the video is downloaded and validated.
            video_id = upload_video(youtube, item, channel, video_path)
            video_url = f"https://youtu.be/{video_id}"
            record.update(status="UPLOADED", youtube_video_id=video_id, youtube_video_url=video_url,
                          youtube_channel_id=actual_id, youtube_channel_title=actual_title,
                          privacy_status=channel.get("privacy", os.getenv("YOUTUBE_PRIVACY_STATUS", "private")),
                          playlist_id=None, playlist_url=None, last_error=None, uploaded_at=iso_now(),
                          updated_at=iso_now())
            playlist_id = str(channel.get("playlist_id", "")).strip()
            if playlist_id:
                try:
                    add_to_playlist(youtube, video_id, playlist_id)
                    record["playlist_id"] = playlist_id
                    record["playlist_url"] = f"https://www.youtube.com/playlist?list={playlist_id}"
                except Exception as playlist_exc:
                    record["playlist_error"] = str(playlist_exc)
                    LOGGER.exception("[Channel %s] Video uploaded but playlist insertion failed", channel_key)
                    # The video itself is already uploaded. Keep status UPLOADED so a later
                    # run never uploads a duplicate merely because playlist insertion failed.
            elif channel.get("playlist_required", False):
                record["playlist_error"] = "playlist_required=true but playlist_id is empty"
                LOGGER.error("[Channel %s] Video uploaded, but playlist is required and no playlist_id is configured", channel_key)
            history["items"][media_id] = record
            save_history(channel, history)
            LOGGER.info("[Channel %s] SUCCESS %s", channel_key, video_url)
            LOGGER.info("[Channel %s] YouTube channel: %s (%s)", channel_key, actual_title, actual_id)
            if record.get("playlist_url"):
                LOGGER.info("[Channel %s] Playlist: %s", channel_key, record["playlist_url"])
            else:
                LOGGER.info("[Channel %s] Playlist: not configured / not added", channel_key)
        except Exception as exc:
            LOGGER.exception("[Channel %s] FAILED for Instagram item %s: %s", channel_key, media_id, exc)
            record.update(status="FAILED", last_error=str(exc), updated_at=iso_now())
            history["items"][media_id] = record
            save_history(channel, history)
        finally:
            if video_path and video_path.exists():
                try:
                    video_path.unlink()
                except OSError:
                    LOGGER.warning("Could not remove temporary video file %s", video_path)

    counts = {}
    for record in history["items"].values():
        status = record.get("status", "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1
    LOGGER.info("[Channel %s] Final history summary: %s", channel_key, counts)


def main() -> int:
    setup_logging()
    try:
        channels = load_config()
        enabled = [ch for ch in channels if bool(ch.get("enabled", False))]
        if not enabled:
            LOGGER.warning("[Config] No enabled YouTube channels.")
            return 0
        ig_user_id = os.getenv("IG_USER_ID", "").strip()
        if not ig_user_id or not os.getenv("IG_ACCESS_TOKEN", "").strip():
            raise RuntimeError("IG_USER_ID and IG_ACCESS_TOKEN must be configured.")
        # Fetch list once, then refresh each item's metadata again just before processing.
        LOGGER.info("[Instagram] Fetching media list (oldest first sorting after fetch)...")
        items = fetch_instagram_items()
        LOGGER.info("[Instagram] Total: %d sorted oldest first", len(items))
        if items:
            LOGGER.info("[Instagram] Oldest: %s @ %s", items[0].get("id"), items[0].get("timestamp"))
            LOGGER.info("[Instagram] Newest: %s @ %s", items[-1].get("id"), items[-1].get("timestamp"))
        for ch in channels:
            if not ch.get("enabled", False):
                LOGGER.info("[Config] %s: disabled", ch.get("id"))
                continue
            prefix = str(ch.get("env_prefix", ""))
            missing = [f"{prefix}_{suffix}" for suffix in
                       ("CLIENT_ID", "CLIENT_SECRET", "REFRESH_TOKEN") if not os.getenv(f"{prefix}_{suffix}")]
            if missing:
                LOGGER.error("[Config] %s enabled but missing credentials: %s; skipping this channel only",
                             ch.get("id"), ", ".join(missing))
                continue
            LOGGER.info("[Config] %s: enabled", ch["id"])
            try:
                process_channel(ch, items)
            except Exception:
                LOGGER.exception("[Channel %s] Channel failed; continuing to other channels", ch["id"])
        LOGGER.info("[Run] Finished.")
        return 0
    except Exception:
        LOGGER.exception("[Run] Fatal error")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
