import os, re, time
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
    print("FINAL FIXED FULL LOGS - SINGLE VIDEO PER RUN - MULTI-CHANNEL")
    print("="*70)
    print(f"VIDEOS_PER_RUN env: {os.getenv('VIDEOS_PER_RUN','not set -> default 1')} => Using: {Config.VIDEOS_PER_RUN}")
    print(f"Channel: trailers bollywood (your target)")
    print("="*70)

    os.makedirs(Config.TEMP_DIR, exist_ok=True)
    os.makedirs("data", exist_ok=True)

    # History - prevents duplicates
    history = HistoryManager(Config.HISTORY_FILE)
    playlist_mgr = PlaylistManager(Config.PLAYLIST_FILE)
    counter_mgr = CounterManager(Config.COUNTER_FILE, history)

    # Load channels with detailed logs
    channels_cfg = Config.load_channels()
    if not channels_cfg:
        print("\n[ERROR] No channels configured!")
        print("Add YT1_* secrets in GitHub: YT1_CLIENT_ID, YT1_CLIENT_SECRET, YT1_REFRESH_TOKEN, YT1_ENABLED=true")
        return

    channels = []
    print("\n" + "="*70)
    print("[Init] Initializing YouTube channels...")
    for cfg in channels_cfg:
        try:
            print(f"[Init] -> Initializing {cfg['id']}...")
            ch = YouTubeChannel(cfg)
            channels.append(ch)
            ch.log_token_status()
        except Exception as e:
            print(f"[Init] Failed to init channel {cfg['id']}: {e}")
            import traceback; traceback.print_exc()

    print(f"[Init] Total channels ready: {len(channels)}")
    if not channels:
        print("[ERROR] No valid channels after init")
        return
    print("="*70 + "\n")

    # Instagram fetch
    try:
        ig = InstagramFetcher(Config.IG_USER_ID, Config.IG_ACCESS_TOKEN)
        all_videos = ig.get_all_reels(max_fetch=1000)
    except Exception as e:
        print(f"[ERROR] Instagram fetch failed: {e}")
        import traceback; traceback.print_exc()
        return

    # Filter new - prevents duplicates
    new_videos = history.filter_new_videos(all_videos)
    if not new_videos:
        print("\n[Run] All videos already uploaded - nothing new. No duplicates.")
        valid, skipped, total = history.count_valid()
        print(f"[Run] History: valid={valid}, skipped={skipped}, total={total}")
        print(f"[Run] Next bhavy would be: bhavy{counter_mgr.get_next()}")
        return

    # SINGLE VIDEO PER RUN
    videos_to_upload = new_videos[:Config.VIDEOS_PER_RUN]
    next_bhavy = counter_mgr.get_next()

    print("\n" + "="*70)
    print(f"[Run] PLAN: Upload {len(videos_to_upload)} video(s) this run (VIDEOS_PER_RUN={Config.VIDEOS_PER_RUN})")
    print(f"[Run] Next bhavy number: bhavy{next_bhavy}")
    print(f"[Run] Available channels: {len(channels)}")
    for i, ch in enumerate(channels):
        print(f"  {i+1}. {ch.id} -> {ch.channel_name} (ID: {ch.youtube_channel_id}) - exhausted={ch.exhausted}")
    print(f"[Run] Videos to upload this run:")
    for i, v in enumerate(videos_to_upload):
        print(f"  {i+1}. {v['id']} - {v.get('timestamp')} - {v.get('caption','')[:50]}")
    print("="*70 + "\n")

    uploaded_count = 0
    channel_index = (next_bhavy - 1) % len(channels) if channels else 0
    channels_ordered = channels[channel_index:] + channels[:channel_index] if channels else []

    print(f"[Run] Channel rotation: starting from index {channel_index} (based on bhavy{next_bhavy})")
    print(f"[Run] Order: {[c.id for c in channels_ordered]}")

    for video_idx, video in enumerate(videos_to_upload):
        insta_id = video['id']
        print("\n" + "="*70)
        print(f"[Upload {video_idx+1}/{len(videos_to_upload)}] Instagram ID: {insta_id}")
        print(f"  Permalink: {video.get('permalink')}")
        print(f"  Timestamp: {video.get('timestamp')}")
        print(f"  Caption: {video.get('caption','')[:100]}")
        print("="*70)

        title = clean_title(video.get('caption',''), next_bhavy)
        is_bhavy = title.lower().startswith('bhavy')
        used_num = next_bhavy if is_bhavy else None
        if is_bhavy:
            next_bhavy += 1

        # Try each channel until one succeeds
        success = False
        for ch in channels_ordered:
            if ch.exhausted:
                print(f"[{ch.id}] Skipped - exhausted (reason: {ch.exhausted_reason})")
                continue

            print(f"\n--- Trying Channel: {ch.id} ({ch.channel_name}) ---")
            ch.log_token_status()

            playlist_id = playlist_mgr.get(ch.playlist_title, ch.id)
            if not playlist_id:
                try:
                    playlist_id = ch.get_or_create_playlist(ch.playlist_title, Config.PLAYLIST_DESC, Config.PRIVACY)
                    playlist_mgr.save(ch.playlist_title, ch.id, playlist_id)
                except (ChannelLimitError, QuotaError) as e:
                    print(f"[{ch.id}] Playlist creation failed: {e} - trying next channel")
                    continue
                except Exception as e:
                    print(f"[{ch.id}] Playlist error: {e} - trying next channel")
                    continue

            print(f"[Run] Playlist URL: https://www.youtube.com/playlist?list={playlist_id}")

            temp_file = f"{Config.TEMP_DIR}/{insta_id}.mp4"
            description = f"""{video.get('caption','')}

Original: {video.get('permalink')}
Playlist: https://www.youtube.com/playlist?list={playlist_id}
Channel: {ch.channel_name}
#bhavychildhood #bhavy #trailersbollywood
Single video per run - No duplicates
"""

            try:
                print(f"[Run] Downloading Instagram video...")
                ig.download_video(video['id'], video.get('media_url'), temp_file)

                file_size = os.path.getsize(temp_file) if os.path.exists(temp_file) else 0
                print(f"[Run] Downloaded file size: {file_size} bytes ({file_size/1024/1024:.2f} MB)")

                print(f"[Run] Uploading to YouTube as '{title}'...")
                yt_id = ch.upload_video(temp_file, title, description, tags=["trailers bollywood", "bhavychildhood", f"bhavy{used_num}" if used_num else "kids"], privacy=Config.PRIVACY)

                try:
                    ch.add_to_playlist(playlist_id, yt_id)
                except (ChannelLimitError, QuotaError) as e:
                    print(f"[Run] Playlist add hit limit but video uploaded OK: https://youtu.be/{yt_id}")

                history.mark_uploaded(insta_id, yt_id, title, ch.id)
                if used_num:
                    counter_mgr.save(used_num)

                print(f"\n[Run] SUCCESS! Uploaded {insta_id} -> https://youtu.be/{yt_id}")
                print(f"[Run] Channel: {ch.channel_name} ({ch.id})")
                uploaded_count += 1
                success = True
                break

            except (ChannelLimitError, QuotaError) as e:
                print(f"[{ch.id}] Limit hit: {e}")
                print(f"[{ch.id}] Trying next channel for same video...")
                continue
            except Exception as e:
                err_str = str(e)
                print(f"[Run] FAILED {insta_id} on {ch.id}: {e}")
                if 'No media_url' in err_str or 'expired' in err_str.lower():
                    print(f"[Run] Instagram media_url expired for {insta_id} - marking as SKIPPED_NO_MEDIA")
                    history.mark_uploaded(insta_id, "SKIPPED_NO_MEDIA", title, ch.id)
                    if used_num:
                        counter_mgr.save(used_num)
                    uploaded_count += 1
                    success = True
                    break
                import traceback; traceback.print_exc()
                break
            finally:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    print(f"[Run] Cleaned temp file {temp_file}")

        if not success:
            print(f"\n[Run] FAILED to upload {insta_id} - all channels exhausted or error")
            print("[Run] Stopping run - will retry next scheduled run")
            break

        # If VIDEOS_PER_RUN=1, we upload only 1 video per run total
        if Config.VIDEOS_PER_RUN == 1:
            print(f"\n[Run] VIDEOS_PER_RUN=1, so stopping after 1 video (single video per run requirement)")
            break

        time.sleep(2)

    print("\n" + "="*70)
    print("FINAL SUMMARY - HEAVY LOGS")
    print("="*70)
    valid, skipped, total = history.count_valid()
    print(f"Instagram Total: {len(all_videos)}")
    print(f"History Total: {total} (valid={valid}, skipped={skipped})")
    print(f"Already uploaded before this run: {len(all_videos)-len(new_videos)}")
    print(f"Uploaded this run: {uploaded_count}")
    print(f"Next bhavy number: bhavy{counter_mgr.get_next()}")
    print("")
    print("Token/Channel Status:")
    for ch in channels:
        pl_id = playlist_mgr.get(ch.playlist_title, ch.id)
        pl_url = f"https://www.youtube.com/playlist?list={pl_id}" if pl_id else "Not created yet"
        print(f"  - {ch.id}:")
        print(f"      Name: {ch.channel_name}")
        print(f"      YouTube Channel ID: {ch.youtube_channel_id}")
        print(f"      Env prefix: {ch.env_prefix}")
        print(f"      Exhausted: {ch.exhausted} (reason: {ch.exhausted_reason})")
        print(f"      Uploaded today this run: {ch.uploaded_today}")
        print(f"      Playlist: {pl_url}")
        print(f"      Remaining quota: Unlimited if different Gmail, but channel limit 15/day per channel")
        if ch.exhausted and 'limit' in str(ch.exhausted_reason).lower():
            print(f"      -> Channel daily limit hit (15/day). Reset ~12:30 PM IST tomorrow. Use different Gmail channel for more.")
    print("")
    print("History file: data/uploaded_history.json prevents duplicates")
    print("Next run will upload next new video (no duplicates)")
    print("="*70)

if __name__ == "__main__":
    run()
