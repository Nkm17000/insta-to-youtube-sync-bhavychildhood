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
- `playlist_id`: explicit playlist ID (the value after `list=` in a playlist URL). Channel 1 uses `PLN_W_X8ML6AU`; channel 2 uses `PLDIFVPTnQdbM`.
- `playlist_title`: descriptive label for the configured playlist.
- `playlist_env_prefix`: OAuth credential prefix for the account that owns/manages that channel’s playlist. Channel 1 uses `YT1`; channel 2 uses `YT2`.
- `playlist_owner_channel_id`: expected owner channel ID, checked before playlist operations.
- `playlist_required`: if true, playlist resolution must succeed before any upload begins.
- `max_items_per_run`: maximum eligible items attempted for that channel each run.

Do not enable the second sample channel until its channel ID and all `YT2_*` secrets are correct. Set `privacy` intentionally; `private` can explain why an upload is not visible publicly.

### Playlist configuration

Each channel has its own playlist ID and its own playlist-manager OAuth account in the supplied config:

```json
"playlist_id": "PLN_W_X8ML6AU",
"playlist_env_prefix": "YT1",
"playlist_owner_channel_id": "UCh7Mjux-jmT8ywtrs-ZFxDg",
"playlist_required": true
```

The authenticated YouTube channel must own that playlist, and its OAuth refresh token must have YouTube Data API permissions to read playlists and insert playlist items. If the playlist is owned by another channel, configure the credentials for the channel that owns the playlist and its matching channel ID. For an exact ID-based configuration, set `playlist_id` to the value after `list=` in the playlist URL.

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
- `data/channel_history/trailers_bollywood_main.json`: history for Trailers Bollywood only.
- `data/channel_history/bhavychildhood_main.json`: history for Bhavy Childhood only.
- A successful record includes `youtube_video_url`, `youtube_channel_title`, `youtube_channel_id`, `privacy_status`, and `playlist_url` if it was added.
- `SKIPPED_NO_MEDIA`: API did not return a media URL after re-query; retried after `SKIPPED_RETRY_HOURS`.
- `FAILED`: processing/upload failed; retried on the next run.
- `UPLOADED`: video upload succeeded. Check `playlist_url` to confirm the playlist target; if insertion fails, `playlist_error` is saved and the next run retries.

## 7. Common reasons a video appears missing

1. Check the exact `youtube_video_url` in the history JSON.
2. Confirm the `youtube_channel_title` and `youtube_channel_id` recorded in the history.
3. Check `privacy_status`: private/unlisted videos will not be publicly discoverable.
4. Check YouTube Studio → Content on the verified channel and allow time for processing.
5. Check `playlist_url` and `playlist_error` separately; upload and playlist insertion are distinct API operations. Previously uploaded history entries are automatically backfilled when possible.
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

## Parallel per-channel jobs and upload-limit handling

- GitHub Actions builds a matrix from every `enabled: true` entry in `config/channels.json`. Each enabled channel runs in its own parallel job and sets `CHANNEL_CONFIG_ID`, so a failure in one channel cannot stop the other channel's job.
- Per-channel histories are written to `data/channel_history/<config-id>.json`. The workflow collects each channel's history artifact and commits all changed histories once after every channel job finishes, avoiding concurrent Git pushes.
- If YouTube returns `uploadLimitExceeded`, the current channel records `FAILED_UPLOAD_LIMIT` and stops making further upload attempts for that channel in that run. It does not create a permanent or day-long block; pending items are eligible on the next scheduled/manual run. The other channel runs in a separate matrix job and continues independently. YouTube must lift its channel-level limit before a new upload can succeed.
- Each channel uses its own playlist-manager OAuth credentials: YT1 manages channel 1 playlist `PLN_W_X8ML6AU`; YT2 manages channel 2 playlist `PLDIFVPTnQdbM`. The `playlist_owner_channel_id` setting verifies the expected account before playlist operations.
- Required GitHub secrets: `IG_USER_ID`, `IG_ACCESS_TOKEN`, `YT1_CLIENT_ID`, `YT1_CLIENT_SECRET`, `YT1_REFRESH_TOKEN`, `YT2_CLIENT_ID`, `YT2_CLIENT_SECRET`, and `YT2_REFRESH_TOKEN`. A channel job skips/fails independently if its credentials are missing or point to the wrong YouTube channel.



### Separate per-channel playlist behavior

`trailers_bollywood_main` (YT1) uploads to its channel and targets `https://www.youtube.com/playlist?list=PLN_W_X8ML6AU` using YT1 OAuth. `bhavychildhood_main` (YT2) uploads to its channel and targets `https://www.youtube.com/playlist?list=PLDIFVPTnQdbM` using YT2 OAuth. The workflow logs a confirmed playlist insertion or a specific failure, retries short-lived YouTube API errors, and backfills videos previously uploaded but missing from the relevant channel playlist on later runs. A video may appear under the YouTube Shorts tab and still also belong to a playlist; Shorts classification is separate from playlist membership.

The YouTube description template for both channels appends the Smart Learning Lab Instagram, Bhavy Childhood Instagram, both YouTube channel links, Facebook page, EduApp, and the source Instagram permalink.


## Retry behavior (updated)

Items that have not successfully uploaded are retried on every workflow run, including items previously marked `FAILED`, `SKIPPED_NO_MEDIA`, or `SKIPPED_UNSUPPORTED_MEDIA`. This removes the timed/deferred skip behavior for pending items. Items already marked `UPLOADED` are still skipped intentionally to prevent duplicate uploads to YouTube. Items whose media is still unavailable or whose format cannot be processed will remain unuploaded until Instagram exposes usable media or the format becomes supported.


## Upload-limit handling (updated)

The workflow does not mark a channel as blocked for the rest of the day and does not skip later runs because a previous run reached YouTube's upload limit. If YouTube returns `uploadLimitExceeded`, the current item is recorded as `FAILED_UPLOAD_LIMIT` and further upload attempts stop for that channel in the current run to avoid repeated rejected requests. Pending items are retried on the next scheduled/manual run; successfully uploaded items remain protected from duplicate uploads. The other channel's job is independent. YouTube may still reject a later retry until its channel-level upload limit clears.
