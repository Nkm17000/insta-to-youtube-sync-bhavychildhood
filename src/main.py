import os, re
from src.config import Config
from src.instagram import InstagramFetcher
from src.youtube import YouTubeChannel, ChannelLimitError, QuotaError
from src.history import HistoryManager, PlaylistManager, CounterManager

def clean_title(caption, bhavy_number):
    if not caption or caption.strip()=="": return f"bhavy{bhavy_number}"
    first = caption.split('\n')[0].strip()
    no_hash = re.sub(r'#\S+', '', first).strip()
    no_hash = re.sub(r'\s+', ' ', no_hash).strip()
    if len(no_hash)<3 or first.startswith('#'): return f"bhavy{bhavy_number}"
    return no_hash[:95]

def run():
    print("="*70)
    print("FINAL v8 - NO YT API UNTIL VIDEO DECIDED - HISTORY CHECK FIRST")
    print("="*70)
    print(f"VIDEOS_PER_RUN: {Config.VIDEOS_PER_RUN} (from env, default 1)")
    print("Flow: 1. Fetch IG -> 2. Check history (no duplicates) -> 3. Check IG media_url valid -> 4. Only then call YouTube API")
    print("="*70)

    os.makedirs(Config.TEMP_DIR, exist_ok=True)
    os.makedirs("data", exist_ok=True)

    history = HistoryManager(Config.HISTORY_FILE)
    playlist_mgr = PlaylistManager(Config.PLAYLIST_FILE)
    counter_mgr = CounterManager(Config.COUNTER_FILE, history)

    # STEP 1: Fetch Instagram - No YouTube API yet
    print("\n[STEP 1] Fetching Instagram videos - No YouTube API called yet")
    ig = InstagramFetcher(Config.IG_USER_ID, Config.IG_ACCESS_TOKEN)
    all_videos = ig.get_all_reels()

    # STEP 2: Check history - No YouTube API yet, skip duplicates
    print("\n[STEP 2] Checking history to avoid duplicates - No YouTube API called yet")
    new_videos = history.filter_new(all_videos)
    if not new_videos:
        print("\n[RESULT] All videos already uploaded - no new video, no YouTube API needed")
        return

    print(f"\n[STEP 2] Found {len(new_videos)} new videos not in history")

    # STEP 3: Find first video with valid media_url - ONLY Instagram API, no YouTube API yet
    print("\n[STEP 3] Finding which video has valid media_url - ONLY Instagram API, NO YouTube API yet")
    print(f"[STEP 3] Will check up to {len(new_videos)} new videos for valid media_url")

    candidate_video = None
    candidate_media_url = None

    for idx, video in enumerate(new_videos):
        insta_id = video['id']
        print(f"\n[STEP 3] Checking {idx+1}/{len(new_videos)}: {insta_id} (timestamp: {video.get('timestamp')})")
        # Check if already in history (double check)
        if insta_id in history.load():
            print(f"  -> SKIP duplicate (already in history)")
            continue

        # Fetch fresh media_url - Instagram API only
        media_url = ig.fetch_media_url(insta_id)

        if not media_url:
            print(f"  -> SKIP {insta_id}: No media_url (expired/deleted) - marking as SKIPPED in history")
            # Mark as skipped so we don't check again next run - still history tracking
            history.mark(insta_id, "SKIPPED_NO_MEDIA", f"skipped_{insta_id}", "none")
            continue
        else:
            print(f"  -> FOUND valid video: {insta_id} has media_url, will upload this one")
            candidate_video = video
            candidate_media_url = media_url
            break

    if not candidate_video:
        print("\n[RESULT] No valid video with media_url found among new videos")
        print("[RESULT] All new videos expired or deleted - no YouTube API called")
        valid, skipped, total = history.count()
        print(f"[RESULT] History: valid={valid}, skipped={skipped}, total={total}")
        return

    # STEP 4: Now we have decided which video to post - NOW call YouTube API
    print("\n" + "="*70)
    print(f"[STEP 4] DECIDED to upload: {candidate_video['id']}")
    print(f"  Caption: {candidate_video.get('caption','')[:80]}")
    print(f"  Permalink: {candidate_video.get('permalink')}")
    print(f"  Media URL valid: Yes")
    print(f"  Now calling YouTube API for first time")
    print("="*70)

    # Load channels - YouTube API token validation happens here (first YouTube API call)
    print("\n[STEP 4] Loading YouTube channels - First YouTube API call")
    channels_cfg = Config.load_channels()
    if not channels_cfg:
        print("[ERROR] No channels")
        return

    channels = []
    for cfg in channels_cfg:
        try:
            ch = YouTubeChannel(cfg)
            channels.append(ch)
        except Exception as e:
            print(f"Failed init {cfg['id']}: {e}")

    if not channels:
        print("[ERROR] No valid channels")
        return

    next_bhavy = counter_mgr.get_next()
    print(f"\n[STEP 4] Will upload as bhavy{next_bhavy}")

    # Rotate channels
    channel_index = (next_bhavy - 1) % len(channels)
    channels_ordered = channels[channel_index:] + channels[:channel_index]

    print(f"[STEP 4] Channel order: {[c.id for c in channels_ordered]}")

    uploaded = False
    for ch in channels_ordered:
        if ch.exhausted:
            print(f"[{ch.id}] Skipped exhausted")
            continue

        print(f"\n--- Uploading to Channel: {ch.id} ({ch.channel_name}) ---")

        # Get playlist - YouTube API
        playlist_id = playlist_mgr.get(ch.playlist_title, ch.id)
        if not playlist_id:
            try:
                playlist_id = ch.get_or_create_playlist(ch.playlist_title, Config.PLAYLIST_DESC, Config.PRIVACY)
                playlist_mgr.save(ch.playlist_title, ch.id, playlist_id)
            except (ChannelLimitError, QuotaError) as e:
                print(f"[{ch.id}] Playlist failed: {e}, trying next channel")
                continue

        print(f"Playlist: https://www.youtube.com/playlist?list={playlist_id}")

        temp_file = f"{Config.TEMP_DIR}/{candidate_video['id']}.mp4"
        title = clean_title(candidate_video.get('caption',''), next_bhavy)
        is_bhavy = title.lower().startswith('bhavy')
        used_num = next_bhavy if is_bhavy else None

        description = f"""{candidate_video.get('caption','')}

Original: {candidate_video.get('permalink')}
Playlist: https://www.youtube.com/playlist?list={playlist_id}
Channel: {ch.channel_name}
#bhavychildhood #bhavy #trailersbollywood
Single video per run - No duplicates - YouTube API called only after video decided
"""

        try:
            # Download using already validated media_url
            print(f"[Run] Downloading Instagram video (media_url already validated)")
            ig.download_video(candidate_media_url, temp_file)

            # Upload - YouTube API
            yt_id = ch.upload_video(temp_file, title, description, tags=["trailers bollywood", f"bhavy{used_num}" if used_num else "kids"], privacy=Config.PRIVACY)

            try:
                ch.add_to_playlist(playlist_id, yt_id)
            except Exception as e:
                print(f"Playlist add failed but video uploaded: {e}")

            history.mark(candidate_video['id'], yt_id, title, ch.id)
            if used_num:
                counter_mgr.save(used_num)

            print("\n" + "="*70)
            print(f"SUCCESS! Uploaded {candidate_video['id']} -> https://youtu.be/{yt_id}")
            print(f"Title: {title} (bhavy{used_num})")
            print(f"Channel: {ch.channel_name} ({ch.id})")
            print(f"Playlist: https://www.youtube.com/playlist?list={playlist_id}")
            print("="*70)
            uploaded = True
            break

        except (ChannelLimitError, QuotaError) as e:
            print(f"[{ch.id}] Limit hit: {e}, trying next channel")
            continue
        except Exception as e:
            print(f"FAILED: {e}")
            import traceback; traceback.print_exc()
            break
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    if not uploaded:
        print("\n[RESULT] Failed to upload - all channels exhausted or error")
        print("Wait until 12:30 PM IST reset for channel limit (15/day)")
    else:
        valid, skipped, total = history.count()
        print("\n" + "="*70)
        print("FINAL SUMMARY")
        print(f"IG Total: {len(all_videos)} | History total: {total} (valid={valid}, skipped={skipped}) | Uploaded this run: 1")
        print(f"Next bhavy: bhavy{counter_mgr.get_next()}")
        print(f"History file prevents duplicates - no YouTube API called until video decided")
        print("="*70)

if __name__ == "__main__":
    run()
