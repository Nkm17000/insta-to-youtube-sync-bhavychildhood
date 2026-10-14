# FINAL v8 - No YouTube API until video decided

## Requirement:
- If video not posted yet, post it, if duplicate skip and look for next
- Until decide which video to post, don't call any YouTube API
- Use history to check posted

## Flow (YouTube API called ONLY in STEP 4):
1. STEP 1: Fetch Instagram (Instagram API only)
2. STEP 2: Check history file data/uploaded_history.json - skip duplicates (No YouTube API)
3. STEP 3: For each new video, fetch Instagram media_url to check if valid (Instagram API only) - if expired, mark SKIPPED_NO_MEDIA in history and try next
4. STEP 4: Only after deciding valid video, load YouTube channels and call YouTube API (playlist, upload)

## Logs:
- STEP 1,2,3 show "No YouTube API called yet"
- STEP 4 shows "Now calling YouTube API for first time"

## VIDEOS_PER_RUN from config:
- Env VIDEOS_PER_RUN, default 1
- Set in workflow env: VIDEOS_PER_RUN=1

## History prevents duplicates:
- data/uploaded_history.json tracks every insta_id
- Filtered before any YouTube API

## Project Structure:
Same as before, but main.py restructured.

## How to restore history if deleted:
If data/uploaded_history.json empty, it will re-upload from start and try expired videos.
Restore from backup or set bhavy_counter.

## Token remaining logs:
- YouTubeChannel logs channel name, ID, stats
- Logs exhausted reason, uploaded today
- Channel limit 15/day per channel, quota 10k per project
