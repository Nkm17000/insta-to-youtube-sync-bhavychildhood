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
    print("FINAL V9 - FIX DUPLICATE BHAVY2 - Triple duplicate check")
    print("="*70)
    print("Flow: History check -> Instagram media_url valid check -> YouTube playlist duplicate check -> Upload")
    print("="*70)

    os.makedirs(Config.TEMP_DIR, exist_ok=True)
    os.makedirs("data", exist_ok=True)

    history=HistoryManager(Config.HISTORY_FILE)
    playlist_mgr=PlaylistManager(Config.PLAYLIST_FILE)
    counter_mgr=CounterManager(Config.COUNTER_FILE, history)

    # STEP 1: Instagram fetch - No YT API
    print("\n[STEP 1] Fetching Instagram - No YouTube API")
    ig=InstagramFetcher(Config.IG_USER_ID, Config.IG_ACCESS_TOKEN)
    all_videos=ig.get_all_reels()

    # STEP 2: History filter - No YT API
    print("\n[STEP 2] Checking history file for duplicates - No YouTube API")
    data=history.load()
    uploaded_ids=set(data.keys())
    new_videos=[v for v in all_videos if v['id'] not in uploaded_ids]
    valid, skipped, total=history.count()
    print(f"[History] IG Total: {len(all_videos)} | History total: {total} (valid={valid}, skipped={skipped}) | New: {len(new_videos)}")

    if not new_videos:
        print("[RESULT] No new videos - all in history")
        return

    # STEP 3: Find valid media_url - Only Instagram API
    print("\n[STEP 3] Finding valid Instagram video with media_url - Only Instagram API, No YouTube API")
    candidate=None
    candidate_media_url=None

    for idx, video in enumerate(new_videos):
        insta_id=video['id']
        print(f"\n[STEP 3] Checking {idx+1}/{len(new_videos)}: {insta_id}")
        if history.is_uploaded(insta_id):
            print(f"  SKIP duplicate in history")
            continue
        mu=ig.fetch_media_url(insta_id)
        if not mu:
            print(f"  SKIP no media_url -> mark SKIPPED")
            history.mark(insta_id, "SKIPPED_NO_MEDIA", f"skipped_{insta_id}", "none")
            continue
        else:
            print(f"  FOUND valid: {insta_id}")
            candidate=video
            candidate_media_url=mu
            break

    if not candidate:
        print("\n[RESULT] No valid Instagram video found")
        return

    print("\n" + "="*70)
    print(f"[STEP 3] DECIDED to upload: {candidate['id']} permalink {candidate.get('permalink')}")
    print("Now calling YouTube API for first time")
    print("="*70)

    # STEP 4: Load channels - First YouTube API
    print("\n[STEP 4] Loading YouTube channels - First YouTube API call")
    channels_cfg=Config.load_channels()
    channels=[]
    for cfg in channels_cfg:
        try:
            ch=YouTubeChannel(cfg)
            channels.append(ch)
        except Exception as e:
            print(f"Failed init {cfg['id']}: {e}")

    if not channels:
        print("[ERROR] No channels")
        return

    # Get existing YouTube titles to avoid duplicate bhavy numbers
    # Need playlist ID first, so we will check after getting playlist

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

        # Get playlist
        playlist_id=playlist_mgr.get(ch.playlist_title, ch.id)
        if not playlist_id:
            try:
                playlist_id=ch.get_or_create_playlist(ch.playlist_title, Config.PLAYLIST_DESC, Config.PRIVACY)
                playlist_mgr.save(ch.playlist_title, ch.id, playlist_id)
            except (ChannelLimitError, QuotaError) as e:
                print(f"[{ch.id}] Playlist failed: {e}")
                continue

        print(f"Playlist: https://www.youtube.com/playlist?list={playlist_id}")

        # CRITICAL: List existing videos in playlist to avoid duplicate bhavy2
        existing_videos=ch.list_playlist_videos(playlist_id)
        existing_titles=[v['title'] for v in existing_videos]

        # Recalculate next bhavy based on YouTube existing titles to avoid duplicate bhavy2
        next_bhavy=counter_mgr.get_next(youtube_existing_titles=existing_titles)
        print(f"[STEP 4] Recalculated next bhavy after checking YouTube playlist: bhavy{next_bhavy} (playlist has {len(existing_titles)} videos)")

        title=clean_title(candidate.get('caption',''), next_bhavy)
        is_bhavy=title.lower().startswith('bhavy')
        used_num=next_bhavy if is_bhavy else None
        if is_bhavy:
            next_bhavy+=1

        # Triple duplicate check: history + playlist permalink + title
        print(f"\n[Duplicate Check] Checking if {candidate['id']} already uploaded")
        print(f"  History check: {candidate['id']} in history? {history.is_uploaded(candidate['id'])}")

        is_dup, dup_info=ch.check_duplicate(playlist_id, candidate.get('permalink'), title)
        if is_dup:
            print(f"  DUPLICATE FOUND in YouTube playlist! Title '{title}' or permalink already exists")
            print(f"  Marking {candidate['id']} as duplicate in history to avoid future uploads")
            history.mark(candidate['id'], f"DUPLICATE_SKIPPED_{dup_info['videoId']}", title, ch.id)
            if used_num:
                counter_mgr.save(used_num)
            print(f"  Skipping this video and trying next Instagram video (no YouTube upload)")
            # Try next Instagram video
            # For simplicity, break and let next run handle next video
            # But to avoid infinite loop, we will continue to next channel or next run
            continue

        print(f"  No duplicate - safe to upload as '{title}'")

        temp_file=f"{Config.TEMP_DIR}/{candidate['id']}.mp4"
        description=f"""{candidate.get('caption','')}

Original: {candidate.get('permalink')}
Instagram ID: {candidate['id']}
Playlist: https://www.youtube.com/playlist?list={playlist_id}
Channel: {ch.channel_name}
#bhavychildhood #bhavy #trailersbollywood
Single video per run - Triple duplicate check
"""

        try:
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
            print(f"SUCCESS! {candidate['id']} -> https://youtu.be/{yt_id} as {title}")
            print(f"Channel: {ch.channel_name}")
            print(f"Playlist: https://www.youtube.com/playlist?list={playlist_id}")
            print("="*70)
            uploaded=True
            break

        except (ChannelLimitError, QuotaError) as e:
            print(f"[{ch.id}] Limit hit: {e}")
            continue
        except Exception as e:
            print(f"FAILED: {e}")
            import traceback; traceback.print_exc()
            break
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    if not uploaded:
        print("\n[RESULT] Failed to upload - all channels exhausted or duplicate found")
    else:
        valid, skipped, total=history.count()
        print("\n" + "="*70)
        print(f"FINAL SUMMARY: IG Total {len(all_videos)} | History total {total} (valid={valid}, skipped={skipped}) | Uploaded this run: 1")
        print(f"Next bhavy: bhavy{counter_mgr.get_next()}")
        print("="*70)

if __name__=="__main__":
    run()
