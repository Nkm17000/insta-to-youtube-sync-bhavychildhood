import os, re, time
from src.config import Config
from src.instagram import InstagramFetcher
from src.youtube import YouTubeUploader, QuotaExceededException
from src.history import HistoryManager, PlaylistManager, CounterManager

def clean_title(caption, bhavy_number):
    """
    If caption has title, use it. If empty/only hashtags, use bhavy{number}
    """
    if not caption or caption.strip() == "":
        return f"bhavy{bhavy_number}"

    # Remove hashtags and get first line
    first_line = caption.split('\n')[0].strip()
    first_line_no_hash = re.sub(r'#\S+', '', first_line).strip()
    first_line_no_hash = re.sub(r'\s+', ' ', first_line_no_hash).strip()

    # If after removing hashtags nothing left or only emojis/symbols or too short
    if len(first_line_no_hash) < 3:
        return f"bhavy{bhavy_number}"

    # If title is just hashtags originally
    if first_line.startswith('#'):
        return f"bhavy{bhavy_number}"

    # Use cleaned title but limit
    return first_line_no_hash[:95]

def run():
    print("=== Insta -> YouTube FINAL SYNC ===")
    print("Mode: Upload until quota finishes + bhavy1, bhavy2 fallback")
    os.makedirs(Config.TEMP_DIR, exist_ok=True)
    os.makedirs("data", exist_ok=True)

    history = HistoryManager(Config.HISTORY_FILE)
    playlist_mgr = PlaylistManager(Config.PLAYLIST_FILE)
    counter_mgr = CounterManager(Config.COUNTER_FILE, history)

    ig = InstagramFetcher(Config.IG_USER_ID, Config.IG_ACCESS_TOKEN)
    yt = YouTubeUploader()

    # 1. Get or create playlist
    playlist_title = Config.YOUTUBE_PLAYLIST_TITLE
    playlist_id = playlist_mgr.get_playlist_id(playlist_title)
    try:
        if not playlist_id:
            playlist_id = yt.get_or_create_playlist(playlist_title, Config.YOUTUBE_PLAYLIST_DESCRIPTION)
            playlist_mgr.save_playlist_id(playlist_title, playlist_id)
        else:
            # Verify still exists, if not recreate
            try:
                playlist_id = yt.get_or_create_playlist(playlist_title, Config.YOUTUBE_PLAYLIST_DESCRIPTION)
                playlist_mgr.save_playlist_id(playlist_title, playlist_id)
            except QuotaExceededException:
                print("Quota exceeded while checking playlist, using cached ID")
    except QuotaExceededException as q:
        print(f"Quota exceeded at playlist step: {q}")
        print("Using cached playlist ID if available")
        if not playlist_id:
            print("No cached playlist ID and quota exceeded - stopping")
            return

    print(f"Playlist URL: https://www.youtube.com/playlist?list={playlist_id}")

    # 2. Fetch ALL videos
    all_videos = ig.get_all_reels(max_fetch=1000)
    print(f"Total to process: {len(all_videos)}")

    # 3. Get starting bhavy number
    next_bhavy = counter_mgr.get_next_bhavy_number()
    print(f"Starting bhavy number: bhavy{next_bhavy}")

    uploaded_this_run = 0
    skipped = 0
    quota_hit = False

    for idx, video in enumerate(all_videos):
        insta_id = video['id']
        if history.is_uploaded(insta_id):
            skipped += 1
            # Ensure old videos are also in playlist (if quota left)
            try:
                existing = history.load().get(insta_id)
                if existing and existing.get('youtube_id'):
                    yt.add_video_to_playlist(playlist_id, existing['youtube_id'])
            except QuotaExceededException:
                print("Quota hit while adding old videos to playlist, stopping add-to-playlist")
                break
            except Exception as e:
                print(f"Could not add old video {insta_id} to playlist: {e}")
            continue

        print(f"\n[{idx+1}/{len(all_videos)}] Processing {insta_id} - {video.get('timestamp')}")
        temp_file = f"{Config.TEMP_DIR}/{insta_id}.mp4"
        
        # Determine title
        raw_caption = video.get('caption', '')
        title = clean_title(raw_caption, next_bhavy)
        
        # If we used bhavy fallback, increment for next
        is_bhavy_fallback = title.lower().startswith('bhavy')
        if is_bhavy_fallback:
            used_number = next_bhavy
            next_bhavy += 1
        else:
            used_number = None

        description = f"""{raw_caption}

Original: {video.get('permalink')}

Playlist: https://www.youtube.com/playlist?list={playlist_id}

#bhavychildhood #bhavy #kids #shorts #fun
Auto synced from Instagram
"""

        try:
            # Download
            print(f"  Downloading...")
            ig.download_video(video['media_url'], temp_file)

            # Upload
            print(f"  Uploading as '{title}'...")
            yt_id = yt.upload(temp_file, title, description, tags=["bhavychildhood", f"bhavy{used_number}" if used_number else "bhavychildhood", "kids", "shorts"])

            # Add to playlist
            try:
                yt.add_video_to_playlist(playlist_id, yt_id)
            except QuotaExceededException:
                print("Quota exceeded during add-to-playlist, but video is uploaded. Saving history and continuing to stop.")
                history.mark_uploaded(insta_id, yt_id, title)
                if used_number:
                    counter_mgr.increment_and_save(used_number)
                uploaded_this_run += 1
                quota_hit = True
                break

            # Save history + counter
            history.mark_uploaded(insta_id, yt_id, title)
            if used_number:
                counter_mgr.increment_and_save(used_number)

            uploaded_this_run += 1
            print(f"  SUCCESS: {title} -> https://youtu.be/{yt_id}")

            # Small delay to avoid rate limit
            time.sleep(2)

        except QuotaExceededException as qe:
            print(f"\n*** QUOTA EXCEEDED - STOPPING GRACEFULLY ***")
            print(f"Error: {qe}")
            print(f"Uploaded this run: {uploaded_this_run}")
            print(f"Remaining videos will be uploaded in next run (GitHub Action daily or next manual run)")
            quota_hit = True
            break
        except Exception as e:
            print(f"  FAILED {insta_id}: {e}")
            import traceback
            traceback.print_exc()
            continue
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    print("\n=== FINAL SUMMARY ===")
    print(f"Total Instagram videos: {len(all_videos)}")
    print(f"Already uploaded (skipped): {skipped}")
    print(f"New uploaded this run: {uploaded_this_run}")
    print(f"Quota hit: {quota_hit}")
    print(f"Next bhavy number will be: bhavy{next_bhavy}")
    print(f"Playlist: https://www.youtube.com/playlist?list={playlist_id}")
    if quota_hit:
        print("NOTE: Quota finished - run again tomorrow or after quota reset (midnight PST) to continue")
    else:
        print("All videos synced!")

if __name__ == "__main__":
    run()
