# FINAL FIXED - Trailers Bollywood - Single Video Per Run - Heavy Logs

## Fixed Issues:
1. **Skipped disabled channel** - Fixed empty env handling (YT2_ENABLED empty no longer disables)
2. **Wrong channel name trailers bollywood** - This IS your target channel, token is correct
3. **History 0** - You deleted history file when unzipping fresh project. Restore from old repo or it will re-upload from bhavy1
4. **No media_url expired** - Added fresh fetch right before download, heavy logs
5. **Added heavy logs**: token remaining, channel stats, playlist URLs, quota, channel limits

## Project Structure:
```
.
├── .github/workflows/sync.yml
├── src/
│   ├── config.py      - Loads channels, logs each token SET/MISSING, VIDEOS_PER_RUN from config default 1
│   ├── history.py     - Prevents duplicates, logs history counts
│   ├── instagram.py   - Fetches fresh media_url before download, logs pages
│   ├── youtube.py     - Single class, logs channel name, stats, quota, channel limit, token status
│   └── main.py        - Single video per run, rotates channels, heavy logs
├── config/channels.json
├── data/
│   ├── uploaded_history.json  - Prevents duplicates
│   ├── playlist_info.json
│   ├── bhavy_counter.json
│   └── temp/
├── get_refresh_token.py - Only CLIENT_ID+SECRET
```

## Logs Added:
- Config: VIDEOS_PER_RUN from env, each channel SET/MISSING, enabled status
- History: Total IG, Already uploaded, New, Last 5 IDs, Next to upload
- Instagram: Page by page fetch count, fresh media_url fetch, download size
- YouTube: Channel name, Channel ID, stats, playlist list, upload progress %, SUCCESS URL, token status, exhausted reason, remaining quota explanation
- Main: Plan, rotation order, per video try each channel, final summary with token remaining, channel limit reset time

## Why SKIP no media_url?
Instagram media_url expires quickly. Old reels (2023) may not have media_url via API anymore.
Code now marks as SKIPPED_NO_MEDIA and moves to next video - won't retry same ID again.

## How to restore history to avoid duplicates:
Copy data/uploaded_history.json from previous repo backup, or run:
```bash
# If you have YouTube playlist, we can rebuild history from it
# Or manually set bhavy_counter.json to 12 if you uploaded 12
```

## VIDEOS_PER_RUN from config:
- Env var VIDEOS_PER_RUN, default 1
- Set in GitHub Secrets or workflow env: VIDEOS_PER_RUN=1
- If not set, defaults to 1

## Token remaining / quota:
- Quota: 10k per GCP project per day, each upload ~1600 quota = 6 uploads per project
- Channel limit: 15 per YouTube channel per day, resets 12:30 PM IST
- Different Gmail = different channel = separate 15/day
- Logs show exhausted reason, uploaded today count, reset time

## Setup:
1. Unzip, push to GitHub
2. Secrets: IG_USER_ID, IG_ACCESS_TOKEN, YT1_*, YT2_*
3. Workflow runs 1 video per run, 4x/day
