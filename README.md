# FINAL V10 - Oldest first, Retry SKIPPED_NO_MEDIA with fresh URL

## Your requirements:
1. Upload oldest video first (Instagram created descending older) so no media expire
2. If error then don't run same youtube video
3. If SKIPPED_NO_MEDIA due to expire media then refresh latest media url and try to post that again

## Flow:
1. Fetch IG all reels, sort by timestamp ASC (oldest first) - No YT API
2. History check: 
   - New videos (never tried)
   - SKIPPED_NO_MEDIA retryable after 24h (SKIPPED_RETRY_HOURS env) -> will refresh latest media_url and try again
   - FAILED_YOUTUBE -> don't retry same video (your requirement)
   - Valid uploaded -> skip
   Combined sorted oldest first
3. For each video oldest first, fetch fresh media_url (refresh latest) - ONLY Instagram API, No YT API
   - If no media_url: mark SKIPPED_NO_MEDIA with current date, will be retried after 24h
   - If media_url OK: decide this video, break
4. Only after deciding valid video with fresh media_url, call YouTube API
   - Check playlist duplicate by permalink and title bhavy2
   - Upload
   - If YouTube error: mark FAILED_YOUTUBE so same video won't be retried (requirement)
   - If success: mark valid

## Why no video uploaded before?
Your history had 30 SKIPPED_NO_MEDIA - all old videos expired. Code marked them permanent, so no retry.
Now v10: SKIPPED_NO_MEDIA retryable after 24h with fresh refresh.

## How to clean history:
Keep only 2 valid bhavy2, bhavy3, delete 30 SKIPPED entries, set bhavy_counter=3, commit.

## VIDEOS_PER_RUN from config default 1:
Env VIDEOS_PER_RUN, default 1

## SKIPPED_RETRY_HOURS:
Env SKIPPED_RETRY_HOURS, default 24h. After 24h, SKIPPED_NO_MEDIA will be retried with fresh media_url refresh.

## Oldest first:
all_videos.sort(key=lambda x: x.get('timestamp','')) -> oldest first
to_check sorted oldest first

## Logs:
- STEP 1,2,3 No YouTube API
- STEP 3 shows oldest first check
- STEP 3 shows refresh latest media_url
- STEP 4 calls YouTube API
