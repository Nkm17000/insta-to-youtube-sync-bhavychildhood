# Instagram → multi-channel YouTube uploader

Uploads the oldest eligible Instagram Reel to each configured, enabled YouTube channel. Every channel has a separate history file and separate OAuth credentials.

## Key behavior

- `config/channels.json` is the source of truth for channel enablement. `enabled: false` means no upload attempt for that channel.
- Each enabled channel must have `id`, actual `channel_id`, `env_prefix`, and its own `{PREFIX}_CLIENT_ID`, `{PREFIX}_CLIENT_SECRET`, and `{PREFIX}_REFRESH_TOKEN` environment variables.
- Credentials are intentionally **not** inherited from shared `YOUTUBE_CLIENT_ID` / `YOUTUBE_REFRESH_TOKEN` variables.
- History is stored separately in `data/channel_history/<id>.json`. Upload success/failure for one channel does not update another channel's history.
- The app does not call YouTube to list channels, inspect playlists, or check duplicates. It selects an Instagram candidate, refreshes the Instagram media URL, downloads and validates the complete local file, and only then creates the YouTube client and calls `videos.insert` to upload.
- If no candidate can be downloaded, no YouTube API request is made for that channel.
- An upload failure is recorded as `FAILED_YOUTUBE` for that channel and is not automatically retried. `SKIPPED_NO_MEDIA` entries can be retried after `SKIPPED_RETRY_HOURS`.
- The workflow is scheduled/manual only; a code push will not accidentally trigger uploads.

## Important YouTube channel identity note

The YouTube Data API chooses the target channel from the Google account represented by the OAuth refresh token. `channel_id` in the JSON is used as the configured channel identity/history label; it cannot force an OAuth token to upload to that channel. For every config entry, create the refresh token while signed into the intended YouTube channel's Google account, and set `channel_id` to that account's channel ID. Since this design avoids pre-upload YouTube API calls, it does not make a `channels.list` call to verify that mapping.

## Setup

1. Copy `.env.example` values into local environment variables or GitHub Actions repository secrets.
2. Update `config/channels.json` with real channel IDs. Set `enabled` to `true` only for channels you want to process.
3. Generate a distinct refresh token for each channel using `python get_refresh_token.py`; use that channel's OAuth client credentials and Google account.
4. Install dependencies: `pip install -r requirements.txt`.
5. Run: `python -m src.main`.

## Enable or disable a channel

Edit `config/channels.json`:

```json
{
  "id": "example_channel",
  "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx",
  "env_prefix": "YT3",
  "enabled": true,
  "privacy": "private",
  "category_id": "24",
  "made_for_kids": false,
  "tags": ["reels"]
}
```

Add `YT3_CLIENT_ID`, `YT3_CLIENT_SECRET`, and `YT3_REFRESH_TOKEN` to the environment. A disabled channel is ignored even if credentials are present.

## History operations

History files use Instagram media IDs as keys and statuses such as `UPLOADED`, `FAILED_YOUTUBE`, and `SKIPPED_NO_MEDIA`. To intentionally retry a terminal item, edit/remove that Instagram ID from only the desired channel's JSON history file. Never copy one channel's history over another's.

## Limitations

Because no pre-upload YouTube API calls are made, the program does not automatically check for duplicates already present on YouTube and cannot independently verify that an OAuth token maps to the configured `channel_id`. Keep channel credentials correctly mapped. YouTube's `videos.insert` upload call may still incur API quota and channel upload limits.
