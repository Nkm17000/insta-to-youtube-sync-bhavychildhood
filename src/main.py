import os, re, time, json
from src.config import Config
from src.instagram import InstagramFetcher
from src.youtube import YouTubeChannel, ChannelLimitError, QuotaError
from src.history import HistoryManager, PlaylistManager, CounterManager

def clean_title(caption, bhavy_number):
    if not caption or caption.strip() == "":
        return f"bhavy{bhavy_number}"
    first_line = caption.split('\n')[0].strip()
    no_hash = re.sub(r'#\S+', '', first_line).strip()
    no_hash = re.sub(r'\s+', ' ', no_hash).strip()
    if len(no_hash) < 3 or first_line.startswith('#'):
        return f"bhavy{bhavy_number}"
    return no_hash[:95]

def run():
    print("="*70)
    print("FINAL PROJECT - SINGLE VIDEO PER RUN - MULTI-CHANNEL - NO DUPLICATES")
    print("="*70)
    print(f"Mode: {Config.VIDEOS_PER_RUN} video per run | History tracking enabled | Multi-channel")

    os.makedirs(Config.TEMP_DIR, exist_ok=True)
    os.makedirs("data", exist_ok=True)

    # Init managers (history prevents duplicates)
    history = HistoryManager(Config.HISTORY_FILE)
    playlist_mgr = PlaylistManager(Config.PLAYLIST_FILE)
    counter_mgr = CounterManager(Config.COUNTER_FILE, history)

    # Load channels (different Gmail = separate limits)
    channels_cfg = Config.load_channels()
    if not channels_cfg:
        print("ERROR: No channels configured. Add YT1_*, YT2_* secrets")
        return

    channels = []
    for cfg in channels_cfg:
        try:
            ch = YouTubeChannel(cfg)
            channels.append(ch)
        except Exception as e:
            print(f"Failed to init channel {cfg['id']}: {e}")

    if not channels:
        print("No valid channels")
        return

    # Instagram
    ig = InstagramFetcher(Config.IG_USER_ID, Config.IG_ACCESS_TOKEN)
    all_videos = ig.get_all_reels(max_fetch=1000)

    # Filter already uploaded - CRITICAL to prevent duplicates
    new_videos = history.filter_new_videos(all_videos)
    if not new_videos:
        print("\nAll videos already uploaded - nothing new. No duplicate upload.")
        return

    # SINGLE VIDEO PER RUN
    video = new_videos[0]  # Only first new video
    next_bhavy = counter_mgr.get_next()
    print(f"\n[Run] Will upload 1 video: {video['id']} as bhavy{next_bhavy} to one of {len(channels)} channel(s)")

    # Find available channel (round-robin, skip exhausted)
    # Use counter to rotate channels: bhavy number % channel count
    channel_index = (next_bhavy - 1) % len(channels)
    # Try channels in rotation order
    channels_ordered = channels[channel_index:] + channels[:channel_index]

    uploaded = False
    for ch in channels_ordered:
        if ch.exhausted:
            print(f"[{ch.id}] Skipped - exhausted today")
            continue

        print(f"\n--- Trying Channel: {ch.id} ({ch.channel_name}) ---")
        playlist_id = playlist_mgr.get(ch.playlist_title, ch.id)
        if not playlist_id:
            try:
                playlist_id = ch.get_or_create_playlist(ch.playlist_title, Config.PLAYLIST_DESC, Config.PRIVACY)
                playlist_mgr.save(ch.playlist_title, ch.id, playlist_id)
            except (ChannelLimitError, QuotaError) as e:
                print(f"[{ch.id}] Cannot create playlist: {e} - trying next channel")
                ch.exhausted = True
                continue

        print(f"Playlist: https://www.youtube.com/playlist?list={playlist_id}")

        temp_file = f"{Config.TEMP_DIR}/{video['id']}.mp4"
        raw_caption = video.get('caption','')
        title = clean_title(raw_caption, next_bhavy)
        is_bhavy = title.lower().startswith('bhavy')
        used_num = next_bhavy if is_bhavy else None

        description = f"""{raw_caption}

Original: {video.get('permalink')}
Playlist: https://www.youtube.com/playlist?list={playlist_id}
Channel: {ch.channel_name}
#bhavychildhood #bhavy
Auto synced - Single video per run - No duplicates
"""

        try:
            ig.download_video(video['id'], video.get('media_url'), temp_file)
            yt_id = ch.upload_video(temp_file, title, description, tags=["bhavychildhood", f"bhavy{used_num}" if used_num else "kids"], privacy=Config.PRIVACY)
            try:
                ch.add_to_playlist(playlist_id, yt_id)
            except (ChannelLimitError, QuotaError):
                print(f"Playlist add hit limit, but video uploaded: https://youtu.be/{yt_id}")

            history.mark_uploaded(video['id'], yt_id, title, ch.id)
            if used_num:
                counter_mgr.save(used_num)

            print(f"\n=== SUCCESS ===")
            print(f"Video: {video['id']} -> https://youtu.be/{yt_id}")
            print(f"Title: {title}")
            print(f"Channel: {ch.channel_name} ({ch.id})")
            print(f"Playlist: https://www.youtube.com/playlist?list={playlist_id}")
            print(f"Next run will upload bhavy{next_bhavy+1 if is_bhavy else next_bhavy} (no duplicates)")

            uploaded = True
            break

        except (ChannelLimitError, QuotaError) as e:
            print(f"[{ch.id}] Limit hit: {e} - trying next channel")
            ch.exhausted = True
            continue
        except Exception as e:
            if 'No media_url' in str(e):
                print(f"SKIP {video['id']}: no media_url (expired)")
                history.mark_uploaded(video['id'], "SKIPPED_NO_MEDIA", title, ch.id)
                if used_num:
                    counter_mgr.save(used_num)
                uploaded = True
                break
            print(f"FAILED {video['id']} on {ch.id}: {e}")
            import traceback; traceback.print_exc()
            break
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    if not uploaded:
        print("\n=== FAILED ===")
        print("All channels exhausted today (15/day each). Wait until 12:30 PM IST reset.")
        print("No video uploaded this run, will retry next run - no duplicates created.")
    else:
        print(f"\n=== SUMMARY ===")
        print(f"IG Total: {len(all_videos)} | Already: {len(all_videos)-len(new_videos)} | Uploaded this run: 1")
        print(f"Next bhavy: bhavy{counter_mgr.get_next()}")
        for ch in channels:
            pl_id = playlist_mgr.get(ch.playlist_title, ch.id)
            if pl_id:
                print(f"  {ch.id}: https://www.youtube.com/playlist?list={pl_id} (exhausted={ch.exhausted})")

if __name__ == "__main__":
    run()
