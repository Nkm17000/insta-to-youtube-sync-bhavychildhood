# FINAL V9 - Fix duplicate bhavy2 in screenshot

## Your screenshot issue:
Playlist trailers bollywood shows bhavy2 twice (0:16 video) - duplicate upload.

## Root cause:
1. data/uploaded_history.json empty {} every run (fresh zip)
2. So Already uploaded: 0 -> thinks bhavy2 new every time
3. Uploads same Instagram ID again

## Fix v9 - Triple duplicate protection:
1. History file check: insta_id in history.json? Skip
2. YouTube playlist check: List all videos in playlist, check if Instagram permalink already in description OR title bhavy2 already exists
3. Counter check: Next bhavy number calculated from max(file_counter, history_valid, youtube_max_bhavy) to avoid bhavy2 duplicate

## Code changes:
- src/youtube.py: Added list_playlist_videos() and check_duplicate()
- src/history.py: CounterManager.get_next() now also checks youtube_existing_titles
- src/main.py: Before upload, lists playlist videos and checks duplicate

## How to fix existing duplicate bhavy2 in playlist:
1. Go to YouTube Studio -> trailers bollywood channel -> Content
2. Delete duplicate bhavy2 (keep one)
3. Restore history file: Copy old uploaded_history.json with 12 entries from backup, or set bhavy_counter to correct number
4. Push v9 code

## VIDEOS_PER_RUN from config default 1:
VIDEOS_PER_RUN env, default 1

## Logs:
- [History] check no YouTube API
- [Instagram] media_url check only Instagram API
- [YouTube] Only after deciding video, calls YouTube API
- Duplicate check logs: "DUPLICATE FOUND by permalink" or "No duplicate"
