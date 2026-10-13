# Final - Upload Until Quota + bhavy1,bhavy2 fallback

Features:
- Fetches ALL Instagram videos via pagination (not just last 10)
- Sorts oldest first -> bhavy1 = oldest
- If caption empty or only hashtags -> uses bhavy1, bhavy2, bhavy3 incremental
- Counter saved in data/bhavy_counter.json + scans history for max bhavy number
- Uploads until YouTube quota (10k units ~ 6 videos) is exceeded, then stops gracefully
- GitHub Action runs 4x daily to finish all videos fast
- All progress committed back to repo

Setup same as before, secrets same.
