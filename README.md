# FINAL PROJECT - Insta to YouTube Sync - From Scratch

## Requirements Met:
1. **No duplicate uploads**: `data/uploaded_history.json` tracks every Instagram ID ever uploaded. Filtered BEFORE download/upload.
2. **Multiple channels**: Different Gmail = separate 15/day limits. Config in `config/channels.json` + env YT1_, YT2_
3. **Single video at a time**: `VIDEOS_PER_RUN=1` - Only 1 video per GitHub Action run
4. **No duplicate code**: Single `YouTubeChannel` class used for all channels

## Project Structure:
```
insta-to-youtube-sync/
├── .github/workflows/sync.yml      # Runs 4x/day, 1 video per run
├── src/
│   ├── __init__.py
│   ├── config.py                   # Loads channels from env
│   ├── instagram.py                # Fetch reels
│   ├── youtube.py                  # Single class for all channels (no duplicate code)
│   ├── history.py                  # HistoryManager, PlaylistManager, CounterManager
│   └── main.py                     # Main logic: 1 video, rotate channels
├── config/
│   └── channels.json               # Channel list (YT1, YT2)
├── data/
│   ├── uploaded_history.json       # HISTORY - prevents duplicates
│   ├── playlist_info.json          # Playlist IDs per channel
│   ├── bhavy_counter.json          # bhavy counter
│   └── temp/                       # Temp downloads
├── get_refresh_token.py            # Generate refresh token (only CLIENT_ID/SECRET needed)
├── requirements.txt
├── .env.example
└── .gitignore
```

## How History Prevents Duplicates:
- Before any upload: `new_videos = [v for v in all if v.id not in history]`
- After upload: `history.mark_uploaded(insta_id, yt_id, title, channel_id)`
- Committed to git: `data/uploaded_history.json` saved after each run

## How Multi-Channel Works:
- Channel 1: YT1_* secrets, Gmail1, bhavychildhood channel, 15/day
- Channel 2: YT2_* secrets, Different Gmail, new channel, 15/day
- Total 30/day
- Rotation: bhavy number % channel count = which channel uploads next

## Setup From Scratch:

1. **Instagram**: Get IG_USER_ID and long-lived token
2. **YouTube**: For each Gmail/channel:
   - Create GCP Project, enable YouTube Data API v3
   - Create OAuth Desktop client
   - Run `python get_refresh_token.py` -> Enter CLIENT_ID/SECRET -> Login with that Gmail -> Get REFRESH_TOKEN
   - Save as YT1_* or YT2_*

3. **GitHub Secrets**: Add:
   - IG_USER_ID, IG_ACCESS_TOKEN
   - YT1_CLIENT_ID, YT1_CLIENT_SECRET, YT1_REFRESH_TOKEN, YT1_ENABLED=true
   - YT2_CLIENT_ID, YT2_CLIENT_SECRET, YT2_REFRESH_TOKEN, YT2_ENABLED=true

4. **Push**: `git push` -> Workflow runs -> Uploads 1 video

## Daily Limits:
- Single channel: 15 uploads/day (YouTube channel limit)
- With 2 channels (different Gmail): 30/day
- Workflow: 4 runs/day * 1 video = 4/day safe

## Commands:
```bash
pip install -r requirements.txt
python get_refresh_token.py  # Generate token
python -m src.main           # Upload 1 video
```
