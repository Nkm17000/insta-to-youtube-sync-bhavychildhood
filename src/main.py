import os
import re
import traceback
import json

from src.config import Config
from src.history import HistoryManager
from src.instagram import InstagramFetcher
from src.youtube import YouTubeChannel

def clean_title(caption, fallback):
    first = (caption or "").splitlines()[0].strip() if caption else ""
    first = re.sub(r"#\S+", "", first)
    first = re.sub(r"\s+", " ", first).strip()
    if len(first) < 3 or (caption or "").strip().startswith("#"):
        first = fallback
    return first[:100]

def prepare_video(ig, candidates, history, retry_hours, temp_dir, channel_id):
    """Find and fully download the oldest usable candidate before any YouTube API request."""
    for video in candidates:
        media_id = video.get("id")
        if not media_id or not history.eligible(video, retry_hours):
            continue
        print(f"[{channel_id}] Checking oldest eligible Instagram item {media_id}")
        url = ig.fetch_media_url(media_id)  # Instagram API only
        if not url:
            history.mark(media_id, "SKIPPED_NO_MEDIA", error="Instagram media URL unavailable")
            print(f"[{channel_id}] No media URL; retry eligible after {retry_hours}h")
            continue

        path = os.path.join(temp_dir, f"{channel_id}_{media_id}.mp4")
        try:
            ig.download_video(url, path)
            if not os.path.isfile(path) or os.path.getsize(path) == 0:
                raise RuntimeError("Downloaded file is empty")
            return video, path
        except Exception as exc:
            if os.path.exists(path):
                os.remove(path)
            print(f"[{channel_id}] Download failed for {media_id}: {exc}")
            # Download failures are retryable; keep them separate from YouTube failures.
            history.mark(media_id, "SKIPPED_NO_MEDIA", error=f"Download failed: {exc}")
    return None, None

def migrate_legacy_history(history, cfg):
    """Import matching records from the former shared history without mixing channels."""
    legacy_path = "data/uploaded_history.json"
    if not os.path.isfile(legacy_path) or history.load():
        return
    try:
        with open(legacy_path, encoding="utf-8") as f:
            legacy = json.load(f)
    except (OSError, ValueError):
        return
    matches = 0
    for media_id, entry in legacy.items():
        if entry.get("channel") not in {cfg["id"], cfg["channel_id"]}:
            continue
        old_id = str(entry.get("youtube_id", ""))
        if old_id.startswith("SKIPPED_NO_MEDIA"):
            status = "SKIPPED_NO_MEDIA"
        elif old_id.startswith("SKIPPED"):
            status = "DUPLICATE_SKIPPED"
        elif old_id.startswith("FAILED"):
            status = "FAILED_YOUTUBE"
        else:
            status = "UPLOADED"
        history.mark(media_id, status, title=entry.get("title", ""), youtube_id=old_id)
        matches += 1
    if matches:
        print(f"[Migration:{cfg['id']}] Imported {matches} matching records from legacy history")

def run():
    if not Config.IG_USER_ID or not Config.IG_ACCESS_TOKEN:
        raise RuntimeError("IG_USER_ID and IG_ACCESS_TOKEN must be set")
    if Config.PRIVACY not in {"private", "unlisted", "public"}:
        raise RuntimeError("YOUTUBE_PRIVACY_STATUS must be private, unlisted, or public")

    os.makedirs(Config.TEMP_DIR, exist_ok=True)
    channels = Config.load_channels()
    if not channels:
        print("[Run] No enabled channels with complete credentials. Nothing uploaded.")
        return

    # Fetching and choosing source videos is independent of YouTube.
    ig = InstagramFetcher(Config.IG_USER_ID, Config.IG_ACCESS_TOKEN)
    videos = ig.get_all_reels()
    if not videos:
        print("[Run] No Instagram videos found.")
        return

    for cfg in channels:
        channel_key = cfg["id"]
        history = HistoryManager(cfg["history_file"])
        migrate_legacy_history(history, cfg)
        print(f"\n{'='*70}\n[Channel {channel_key}] configured YouTube channel ID: {cfg['channel_id']}")
        print(f"[Channel {channel_key}] independent history: {cfg['history_file']}")
        print(f"[Channel {channel_key}] current history: {history.summary()}")

        # Candidate selection + fresh URL + complete local download all happen before
        # constructing the YouTube client or making any YouTube API request.
        candidate, file_path = prepare_video(
            ig, videos, history, Config.SKIPPED_RETRY_HOURS, Config.TEMP_DIR, channel_key
        )
        if not candidate:
            print(f"[Channel {channel_key}] No eligible, downloadable video. No YouTube API called.")
            continue

        title = clean_title(candidate.get("caption", ""), f"video-{candidate['id']}")
        description = (
            f"{candidate.get('caption', '')}\n\n"
            f"Original Instagram: {candidate.get('permalink', '')}\n"
            f"Instagram media ID: {candidate['id']}\n"
            f"Created: {candidate.get('timestamp', '')}\n"
        )
        print(f"[Channel {channel_key}] READY: {candidate['id']} -> {title}")
        print(f"[Channel {channel_key}] File size: {os.path.getsize(file_path)} bytes")
        print(f"[Channel {channel_key}] First and only YouTube API operation will be videos.insert upload.")

        try:
            # No channels.list, playlist.list, duplicate lookup, or other YouTube calls.
            youtube = YouTubeChannel(cfg)
            video_id = youtube.upload_video(
                file_path,
                title,
                description,
                tags=cfg.get("tags", ["Instagram", "Reels"]),
            )
            history.mark(candidate["id"], "UPLOADED", title=title, youtube_id=video_id)
            print(f"[Channel {channel_key}] SUCCESS https://youtu.be/{video_id}")
        except Exception as exc:
            # Failure is channel-specific; other channels continue normally.
            history.mark(candidate["id"], "FAILED_YOUTUBE", title=title, error=exc)
            print(f"[Channel {channel_key}] Upload failed; recorded only in this channel's history: {exc}")
            traceback.print_exc()
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)

    print("\n[Run] Finished. Per-channel history summaries:")
    for cfg in channels:
        print(f"  {cfg['id']}: {HistoryManager(cfg['history_file']).summary()}")

if __name__ == "__main__":
    run()
