import os, re, time
from src.config import Config
from src.instagram import InstagramFetcher
from src.youtube import SingleChannelMultiTokenManager, QuotaExceededException
from src.history import HistoryManager, PlaylistManager, CounterManager, UsageTracker

def clean_title(caption, bhavy_number):
    if not caption or caption.strip() == "": return f"bhavy{bhavy_number}"
    first_line = caption.split('\n')[0].strip()
    no_hash = re.sub(r'#\S+', '', first_line).strip()
    no_hash = re.sub(r'\s+', ' ', no_hash).strip()
    if len(no_hash) < 3 or first_line.startswith('#'): return f"bhavy{bhavy_number}"
    return no_hash[:95]

def run():
    print("=== FINAL v5 - ONE VIDEO PER RUN - SINGLE CHANNEL MULTI-TOKEN ===")
    print(f"Mode: {Config.VIDEOS_PER_RUN} video per run to avoid limit")
    os.makedirs(Config.TEMP_DIR, exist_ok=True)
    os.makedirs("data", exist_ok=True)

    history = HistoryManager(Config.HISTORY_FILE)
    playlist_mgr = PlaylistManager(Config.PLAYLIST_FILE)
    counter_mgr = CounterManager(Config.COUNTER_FILE, history)
    usage = UsageTracker(Config.USAGE_FILE)

    tokens = Config.load_youtube_tokens()
    if not tokens:
        print("No tokens found - add YT1_* secrets")
        return
    yt_manager = SingleChannelMultiTokenManager(tokens)

    ig = InstagramFetcher(Config.IG_USER_ID, Config.IG_ACCESS_TOKEN)
    all_videos = ig.get_all_reels(max_fetch=1000)

    # Filter already uploaded - CRITICAL to save quota
    new_videos = history.filter_new_videos(all_videos)
    if not new_videos:
        print("All synced! Nothing new.")
        return

    next_bhavy = counter_mgr.get_next_bhavy_number()
    print(f"Next bhavy: bhavy{next_bhavy} | Playlist: {Config.YOUTUBE_PLAYLIST_TITLE}")

    # Get single playlist for same channel
    playlist_id = playlist_mgr.get_playlist_id(Config.YOUTUBE_PLAYLIST_TITLE)
    if not playlist_id:
        for tok in yt_manager.tokens:
            try:
                playlist_id = tok.get_or_create_playlist(Config.YOUTUBE_PLAYLIST_TITLE, Config.YOUTUBE_PLAYLIST_DESCRIPTION, Config.YOUTUBE_PRIVACY)
                playlist_mgr.save_playlist_id(Config.YOUTUBE_PLAYLIST_TITLE, playlist_id)
                print(f"Playlist: {playlist_id}")
                break
            except QuotaExceededException:
                continue
    if not playlist_id:
        print("Could not get playlist - all tokens exhausted")
        return
    print(f"Playlist URL: https://www.youtube.com/playlist?list={playlist_id}")

    # ONE VIDEO AT A TIME
    videos_to_upload = new_videos[:Config.VIDEOS_PER_RUN]
    print(f"\nUploading {len(videos_to_upload)} video(s) this run (ONE at a time mode)...")

    uploaded = 0
    for idx, video in enumerate(videos_to_upload):
        insta_id = video['id']
        print(f"\n[{idx+1}/{len(videos_to_upload)}] {insta_id}")
        temp_file = f"{Config.TEMP_DIR}/{insta_id}.mp4"
        raw_caption = video.get('caption','')
        title = clean_title(raw_caption, next_bhavy)
        is_bhavy = title.lower().startswith('bhavy')
        used_num = next_bhavy if is_bhavy else None
        if is_bhavy: next_bhavy += 1

        description = f"""{raw_caption}

Original: {video.get('permalink')}
Playlist: https://www.youtube.com/playlist?list={playlist_id}
#bhavychildhood #bhavy
"""
        try:
            print(f"  Downloading...")
            ig.download_video(video['id'], video.get('media_url'), temp_file)
            print(f"  Uploading as '{title}'...")
            yt_id, token_used, token_obj = yt_manager.upload_with_rotation(temp_file, title, description, tags=["bhavychildhood", f"bhavy{used_num}" if used_num else "kids"], privacy=Config.YOUTUBE_PRIVACY)
            try:
                token_obj.add_to_playlist(playlist_id, yt_id)
            except QuotaExceededException as qe:
                if qe.is_channel_limit:
                    print("Channel limit during playlist add, but video uploaded OK")
            history.mark_uploaded(insta_id, yt_id, title, token_used)
            if used_num: counter_mgr.increment_and_save(used_num)
            usage.record(token_used, success=True)
            uploaded += 1
            print(f"  DONE: https://youtu.be/{yt_id} via {token_used}")
            # ONE VIDEO DONE - STOP (important for one-at-a-time mode)
            break

        except QuotaExceededException as qe:
            usage.record(qe.token_id if qe.token_id != "ALL" else "ALL", success=False, is_channel_limit=qe.is_channel_limit)
            if qe.is_channel_limit:
                print(f"\n*** CHANNEL DAILY LIMIT HIT - STOPPING ***")
                print(f"Wait until 12:30 PM IST tomorrow. This run uploaded {uploaded} video.")
            else:
                print(f"\n*** QUOTA EXHAUSTED - STOPPING ***")
            break
        except Exception as e:
            if 'No media_url' in str(e):
                print(f"  SKIP no media: {insta_id}")
                history.mark_uploaded(insta_id, "SKIPPED_NO_MEDIA", title, "NONE")
                if used_num: counter_mgr.increment_and_save(used_num)
                uploaded += 1
                break
            print(f"  FAILED: {e}")
            import traceback; traceback.print_exc()
            break
        finally:
            if os.path.exists(temp_file): os.remove(temp_file)

    print(f"\n=== SUMMARY - ONE VIDEO PER RUN ===")
    print(f"IG Total: {len(all_videos)} | Already: {len(all_videos)-len(new_videos)} | Uploaded this run: {uploaded}")
    print(f"Next run will upload: bhavy{next_bhavy}")
    print(f"Playlist: https://www.youtube.com/playlist?list={playlist_id}")
    print(f"\nThis mode uploads 1 video per GitHub Action run, safe for quota.")

if __name__ == "__main__":
    run()
