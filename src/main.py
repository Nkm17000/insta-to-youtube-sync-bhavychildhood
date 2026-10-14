import os, re
from src.config import Config
from src.instagram import InstagramFetcher
from src.youtube import YouTubeChannel, ChannelLimitError, QuotaError
from src.history import HistoryManager, PlaylistManager, CounterManager

def clean_title(caption, bhavy_number):
    if not caption or caption.strip()=="": return f"bhavy{bhavy_number}"
    first=caption.split('\n')[0].strip()
    no_hash=re.sub(r'#\S+', '', first).strip()
    no_hash=re.sub(r'\s+', ' ', no_hash).strip()
    if len(no_hash)<3 or first.startswith('#'): return f"bhavy{bhavy_number}"
    return no_hash[:95]

def run():
    print("="*70)
    print("FINAL V10 - OLDEST FIRST, RETRY SKIPPED_NO_MEDIA WITH FRESH URL")
    print("="*70)
    print("Flow:")
    print("  1. Fetch IG oldest first (sorted by timestamp asc)")
    print("  2. History check - skip duplicates, but retry SKIPPED_NO_MEDIA after 24h with fresh media_url")
    print("  3. Instagram media_url refresh - ONLY Instagram API, NO YouTube API")
    print("  4. Only after valid media_url, call YouTube API and check playlist duplicate")
    print("="*70)

    os.makedirs(Config.TEMP_DIR, exist_ok=True)
    os.makedirs("data", exist_ok=True)

    history=HistoryManager(Config.HISTORY_FILE)
    playlist_mgr=PlaylistManager(Config.PLAYLIST_FILE)
    counter_mgr=CounterManager(Config.COUNTER_FILE, history)

    # STEP 1: Instagram fetch oldest first - No YouTube API
    print("\n[STEP 1] Fetching Instagram - Oldest first - No YouTube API")
    ig=InstagramFetcher(Config.IG_USER_ID, Config.IG_ACCESS_TOKEN)
    all_videos=ig.get_all_reels()

    # STEP 2: History filter oldest first, with retry for SKIPPED_NO_MEDIA - No YouTube API
    print(f"\n[STEP 2] Filtering history - Oldest first - Retry SKIPPED_NO_MEDIA after {Config.SKIPPED_RETRY_HOURS}h - No YouTube API")
    to_check=history.filter_new(all_videos, retry_hours=Config.SKIPPED_RETRY_HOURS)

    if not to_check:
        print("\n[RESULT] No videos to check - all uploaded or recent SKIPPED")
        return

    # STEP 3: Find valid media_url oldest first, refresh latest - ONLY Instagram API
    print(f"\n[STEP 3] Finding valid video with fresh media_url - Oldest first - ONLY Instagram API, NO YouTube API")
    print(f"[STEP 3] Checking {len(to_check)} videos oldest first, will refresh media_url for SKIPPED_NO_MEDIA")

    candidate=None
    candidate_media_url=None

    for idx, video in enumerate(to_check):
        insta_id=video['id']
        ts=video.get('timestamp')
        print(f"\n[STEP 3] {idx+1}/{len(to_check)}: {insta_id} @ {ts} (oldest first)")

        # Fetch fresh latest media_url (refresh)
        media_url=ig.fetch_media_url(insta_id)

        if not media_url:
            # If SKIPPED_NO_MEDIA, keep it as SKIPPED but allow retry later
            # If never tried, mark as SKIPPED_NO_MEDIA now, but it will be retryable after 24h
            print(f"  -> No media_url (expired) - Marking SKIPPED_NO_MEDIA, will retry after {Config.SKIPPED_RETRY_HOURS}h with fresh refresh")
            history.mark(insta_id, "SKIPPED_NO_MEDIA", f"skipped_{insta_id}", "none")
            continue
        else:
            print(f"  -> FOUND valid media_url (refreshed latest) - Will upload this oldest valid video")
            candidate=video
            candidate_media_url=media_url
            break

    if not candidate:
        print("\n[RESULT] No valid video with fresh media_url found - all expired")
        print("[RESULT] Will retry SKIPPED_NO_MEDIA after 24h with new refresh")
        valid, skipped, failed, total=history.count()
        print(f"[RESULT] History: valid={valid}, skipped={skipped}, failed={failed}, total={total}")
        return

    print("\n" + "="*70)
    print(f"[STEP 3] DECIDED oldest valid video: {candidate['id']} @ {candidate.get('timestamp')}")
    print(f"  Permalink: {candidate.get('permalink')}")
    print(f"  Fresh media_url refreshed OK")
    print(f"  Now calling YouTube API for first time")
    print("="*70)

    # STEP 4: YouTube API - First call
    print("\n[STEP 4] Loading YouTube channels - First YouTube API call")
    channels_cfg=Config.load_channels()
    channels=[]
    for cfg in channels_cfg:
        try:
            ch=YouTubeChannel(cfg)
            channels.append(ch)
        except Exception as e:
            print(f"Failed {cfg['id']}: {e}")

    if not channels:
        print("[ERROR] No channels")
        return

    # Get next bhavy number
    # Need playlist titles to check existing bhavy numbers
    # Will check after getting playlist

    next_bhavy=counter_mgr.get_next()
    print(f"\n[STEP 4] Initial next bhavy: bhavy{next_bhavy}")

    channel_index=(next_bhavy-1)%len(channels) if channels else 0
    channels_ordered=channels[channel_index:]+channels[:channel_index]

    uploaded=False
    for ch in channels_ordered:
        if ch.exhausted:
            print(f"[{ch.id}] Skipped exhausted")
            continue

        print(f"\n--- Trying Channel: {ch.id} ({ch.channel_name}) ---")

        playlist_id=playlist_mgr.get(ch.playlist_title, ch.id)
        if not playlist_id:
            try:
                playlist_id=ch.get_or_create_playlist(ch.playlist_title, Config.PLAYLIST_DESC, Config.PRIVACY)
                playlist_mgr.save(ch.playlist_title, ch.id, playlist_id)
            except (ChannelLimitError, QuotaError) as e:
                print(f"[{ch.id}] Playlist failed: {e}")
                continue

        print(f"Playlist: https://www.youtube.com/playlist?list={playlist_id}")

        existing_videos=ch.list_playlist_videos(playlist_id)
        existing_titles=[v['title'] for v in existing_videos]

        next_bhavy=counter_mgr.get_next(youtube_titles=existing_titles)
        print(f"[STEP 4] Recalculated next bhavy after playlist check: bhavy{next_bhavy}")

        title=clean_title(candidate.get('caption',''), next_bhavy)
        is_bhavy=title.lower().startswith('bhavy')
        used_num=next_bhavy if is_bhavy else None
        if is_bhavy:
            next_bhavy+=1

        # Duplicate check by permalink and title
        is_dup, dup_info=ch.check_duplicate(playlist_id, candidate.get('permalink'), title)
        if is_dup:
            print(f"DUPLICATE found - marking {candidate['id']} as duplicate, skipping YouTube upload")
            history.mark(candidate['id'], f"DUPLICATE_SKIPPED_{dup_info['videoId']}", title, ch.id)
            if used_num:
                counter_mgr.save(used_num)
            # Don't try same YouTube video again, but try next Instagram video? For this run, stop and next run will try next
            # Requirement: if error don't run same youtube video but if SKIPPED_NO_MEDIA can refresh and retry
            # Duplicate is not error, so we should try next Instagram video in same run? Let's try next
            print(f"Trying next oldest Instagram video instead of same YouTube duplicate")
            continue

        temp_file=f"{Config.TEMP_DIR}/{candidate['id']}.mp4"
        description=f"""{candidate.get('caption','')}

Original: {candidate.get('permalink')}
Instagram ID: {candidate['id']}
Created: {candidate.get('timestamp')}
Playlist: https://www.youtube.com/playlist?list={playlist_id}
Channel: {ch.channel_name}
#bhavychildhood #bhavy #trailersbollywood
Oldest first - Fresh media_url refreshed
"""

        try:
            print(f"[Run] Downloading using fresh media_url")
            ig.download_video(candidate_media_url, temp_file)

            yt_id=ch.upload_video(temp_file, title, description, tags=["trailers bollywood", f"bhavy{used_num}" if used_num else "kids"], privacy=Config.PRIVACY)

            try:
                ch.add_to_playlist(playlist_id, yt_id)
            except Exception as e:
                print(f"Playlist add failed but video uploaded: {e}")

            history.mark(candidate['id'], yt_id, title, ch.id)
            if used_num:
                counter_mgr.save(used_num)

            print("\n" + "="*70)
            print(f"SUCCESS! Oldest video {candidate['id']} @ {candidate.get('timestamp')} -> https://youtu.be/{yt_id} as {title}")
            print(f"Channel: {ch.channel_name}")
            print("="*70)
            uploaded=True
            break

        except (ChannelLimitError, QuotaError) as e:
            print(f"[{ch.id}] Limit hit: {e}, trying next channel")
            # Don't mark as failed, try next channel
            continue
        except Exception as e:
            print(f"FAILED YouTube upload for {candidate['id']}: {e}")
            # Requirement: if error don't run same youtube video again
            print(f"Marking {candidate['id']} as FAILED_YOUTUBE so same video won't be retried for YouTube error")
            history.mark(candidate['id'], f"FAILED_YOUTUBE_{str(e)[:50]}", title, ch.id)
            if used_num:
                counter_mgr.save(used_num)
            import traceback; traceback.print_exc()
            break
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    if not uploaded:
        print("\n[RESULT] Failed to upload")
    else:
        valid, skipped, failed, total=history.count()
        print("\n" + "="*70)
        print(f"FINAL SUMMARY: IG Total {len(all_videos)} | History total {total} (valid={valid}, skipped={skipped}, failed={failed}) | Uploaded this run: 1")
        print(f"Next bhavy: bhavy{counter_mgr.get_next()}")
        print(f"SKIPPED_NO_MEDIA will be retried after {Config.SKIPPED_RETRY_HOURS}h with fresh media_url refresh")
        print("="*70)

if __name__=="__main__":
    run()
