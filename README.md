# Instagram to YouTube multi-channel sync

A GitHub Actions project that fetches Instagram professional-account media, refreshes media metadata immediately before downloading, and uploads ready videos to independently configured YouTube channels. Each channel has its own history file and errors in one channel do not stop the next channel.

## Important notes

- This is a complete replacement template based on the run log provided, not a patch against unseen original source files. The Instagram API caller now supports both Graph API hosts and reports actionable details if both reject the request.
- Instagram Graph API access requires a supported professional Instagram account, correct permissions, a valid access token, and an API version supported by your Meta app. Set `IG_GRAPH_API_VERSION` to a currently supported version for your app.
- A metadata refresh can get a fresh URL only while Instagram still exposes the media to the API. It cannot restore deleted media or bypass permissions.
- YouTube uploads are uploaded to the channel authenticated by the channel-specific OAuth refresh token. The program verifies `channels.list(mine=true)` against `channel_id` before uploading.
- YouTube playlists are optional. Set `playlist_id` per channel to add videos after upload. A video upload and playlist insertion are separate API calls.
- If privacy is `private`, you will only see the video while signed in to the owning account. `unlisted` videos do not normally appear in channel browse/search. `public` videos may still take time to process or appear.
- The program never claims a playlist was updated unless `playlistItems.insert` succeeds.
- History records the YouTube video ID, URL, verified channel, privacy, playlist outcome, timestamps, and errors.

## Repository layout

```text
.
├── .github/workflows/sync.yml
├── config/channels.json
├── data/channel_history/        # generated per-channel history
├── src/main.py
├── requirements.txt
└── .env.example
```

## 1. Set up Instagram API credentials

In Meta developer settings, configure the Instagram Graph API for the professional Instagram account. The token needs permission to read the account's media. Add repository secrets:

- `IG_USER_ID`: Instagram professional account ID (not the username)
- `IG_ACCESS_TOKEN`: access token for that account

Optionally add repository variables `IG_GRAPH_API_VERSION` and `IG_API_MODE`. `IG_API_MODE` accepts `auto`, `facebook_login`, or `instagram_login`. `auto` tries `graph.facebook.com` first, then tries `graph.instagram.com` once if the first host returns Graph API error code 2500 (unknown path). If you know which login product issued your token, set the matching mode explicitly. Set the API version to one currently supported by your Meta app.

## 2. Set up each YouTube channel

Create OAuth credentials in Google Cloud for YouTube Data API v3 and obtain an offline refresh token for the Google account that controls the target YouTube channel. The refresh token must be created with offline access and authorized for the scopes needed by this project (`youtube.upload`, `youtube.readonly`, `youtube`). During refresh, the script reuses the token’s existing grant instead of trying to request new scopes. If Google still returns `invalid_scope`, generate a new refresh token using the same OAuth Client ID/Secret and grant those YouTube scopes, then update the matching GitHub secret.

Add GitHub repository secrets for every configured `env_prefix`. For `YT1`, add:

- `YT1_CLIENT_ID`
- `YT1_CLIENT_SECRET`
- `YT1_REFRESH_TOKEN`

For `YT2`, add:

- `YT2_CLIENT_ID`
- `YT2_CLIENT_SECRET`
- `YT2_REFRESH_TOKEN`

Each refresh token must authenticate the intended channel. The program verifies the OAuth destination against the configured `channel_id` and skips that channel if they do not match. If a brand account/channel is involved, ensure OAuth authorization selected the correct channel.

## 3. Configure channels

Edit `config/channels.json`. For each channel:

- `id`: unique internal identifier; used for the history filename.
- `channel_id`: actual YouTube channel ID, typically starts with `UC`.
- `env_prefix`: prefix used to read the channel's OAuth secrets.
- `enabled`: `true` or `false`.
- `privacy`: `public`, `unlisted`, or `private`.
- `playlist_id`: playlist ID (the value after `list=` in a playlist URL), or empty string.
- `playlist_required`: if true, record `UPLOADED_PLAYLIST_FAILED` if adding to the playlist fails or no playlist is configured.
- `max_items_per_run`: maximum eligible items attempted for that channel each run.

Do not enable the second sample channel until its channel ID and all `YT2_*` secrets are correct. Set `privacy` intentionally; `private` can explain why an upload is not visible publicly.

### Playlist example

A playlist URL like `https://www.youtube.com/playlist?list=PLxxxxxxxx` has playlist ID `PLxxxxxxxx`. Set:

```json
"playlist_id": "PLxxxxxxxx",
"playlist_required": true
```

The authenticated account must have permission to add videos to that playlist.

## 4. GitHub Actions

Workflow triggers:
- push to `main`, except changes only under `data/**` or Markdown files;
- manual run via **Actions → Instagram to YouTube channel sync → Run workflow**;
- scheduled runs at `01:00, 07:00, 13:00, 19:00 UTC`.

If your default branch is `master`, change `main` in `.github/workflows/sync.yml`. GitHub Actions schedule uses UTC. Ensure Actions are enabled in repository settings. The workflow needs `contents: write` to commit history/log files.

## 5. Run locally (optional)

```bash
python -m venv .venv
# Windows PowerShell:
.venv\\Scripts\\Activate.ps1
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
# Set the environment variables from .env.example in your shell.
python -u -m src.main
```

The program does not automatically load `.env`; export the variables in your shell or configure them as GitHub Actions secrets. Never commit real tokens or client secrets.

## 6. Where to see results

- `data/last_run.log`: latest run log.
- `data/channel_history/<channel-id>.json`: per-channel history.
- A successful record includes `youtube_video_url`, `youtube_channel_title`, `youtube_channel_id`, `privacy_status`, and `playlist_url` if it was added.
- `SKIPPED_NO_MEDIA`: API did not return a media URL after re-query; retried after `SKIPPED_RETRY_HOURS`.
- `FAILED`: processing/upload failed; retried on the next run.
- `UPLOADED`: upload succeeded (and playlist insertion succeeded if configured).
- `UPLOADED_PLAYLIST_FAILED`: video upload succeeded but playlist insertion failed; check `playlist_error`.

## 7. Common reasons a video appears missing

1. Check the exact `youtube_video_url` in the history JSON.
2. Confirm the `youtube_channel_title` and `youtube_channel_id` recorded in the history.
3. Check `privacy_status`: private/unlisted videos will not be publicly discoverable.
4. Check YouTube Studio → Content on the verified channel and allow time for processing.
5. Check `playlist_url` and `playlist_error` separately; uploading does not automatically select a playlist.
6. If `channels.list(mine=true)` returns the wrong channel, replace that channel's OAuth refresh token with one authorized for the intended channel.

## 8. Security and behavior

- Never commit access tokens or OAuth secrets.
- Instagram media URLs are treated as temporary and re-fetched before download.
- Per-channel histories prevent duplicate uploads for already uploaded Instagram media IDs.
- A media ID that lacks a fresh URL is retried after the configured retry interval.
- YouTube API failures are logged and do not stop processing other channels.


## Media handling and upload limits

- Instagram `VIDEO` items (including Reels returned as videos) are prioritized first, followed by `CAROUSEL_ALBUM`, then still `IMAGE` items. Items remain oldest-first within each type.
- Still images are downloaded and converted into silent 1280x720 MP4 videos using `ffmpeg`; the default duration is 8 seconds. Set `IMAGE_VIDEO_DURATION_SECONDS` to a value from 3 to 60 if you want a different duration. This can be configured as a workflow environment value or repository variable/secret if you wire it into the workflow.
- Carousel albums are expanded through the Instagram `children` endpoint. Each child video is uploaded as a video; each child image is converted to an MP4. Child history is tracked separately from the carousel parent so an already-uploaded child is not uploaded again if another child fails or the run limit is reached.
- If Instagram returns no usable `media_url` for a video, the item is marked `SKIPPED_NO_MEDIA` and retried after `SKIPPED_RETRY_HOURS` (default 24). For still images, `thumbnail_url` is used as a fallback if `media_url` is absent. A missing/expired URL cannot be repaired by guessing a different URL; the script refreshes the metadata before trying again.
- `MAX_ITEMS_PER_RUN` / channel `max_items_per_run` limits upload attempts, not metadata checks or skipped images/unsupported items. Skipped items do not consume the upload limit. Videos are prepared locally before the YouTube upload API is called.
- Logs include per-run upload attempts/successes, image conversions, carousel child count, missing media, failures, channel destination, and YouTube URL. Uploads are still subject to Instagram API access, media availability, YouTube API limits, and rights to republish the content.

