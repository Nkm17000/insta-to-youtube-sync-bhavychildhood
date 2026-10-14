import os, json
from dotenv import load_dotenv
load_dotenv()

class Config:
    IG_USER_ID = os.getenv("IG_USER_ID")
    IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")
    PLAYLIST_TITLE = os.getenv("YOUTUBE_PLAYLIST_TITLE", "bhavychildhood")
    PLAYLIST_DESC = os.getenv("YOUTUBE_PLAYLIST_DESCRIPTION", "All videos from Instagram @bhavychildhood")
    PRIVACY = os.getenv("YOUTUBE_PRIVACY_STATUS", "public")
    VIDEOS_PER_RUN = int(os.getenv("VIDEOS_PER_RUN", "1"))  # SINGLE VIDEO PER RUN

    HISTORY_FILE = "data/uploaded_history.json"
    PLAYLIST_FILE = "data/playlist_info.json"
    COUNTER_FILE = "data/bhavy_counter.json"
    TEMP_DIR = "data/temp"
    CHANNELS_CONFIG = "config/channels.json"

    @staticmethod
    def load_channels():
        try:
            with open(Config.CHANNELS_CONFIG, 'r') as f:
                channels = json.load(f)
        except:
            channels = [{"id": "channel_old", "env_prefix": "YT1", "enabled": True, "playlist_title": Config.PLAYLIST_TITLE}]

        valid = []
        for ch in channels:
            prefix = ch.get("env_prefix")
            if not prefix:
                continue
            enabled = ch.get("enabled", True)
            env_enabled = os.getenv(f"{prefix}_ENABLED")
            if env_enabled is not None:
                enabled = env_enabled.lower() in ['true','1','yes','enabled']
            if not enabled:
                print(f"Skipping disabled channel {ch['id']}")
                continue

            client_id = os.getenv(f"{prefix}_CLIENT_ID") or os.getenv("YOUTUBE_CLIENT_ID")
            client_secret = os.getenv(f"{prefix}_CLIENT_SECRET") or os.getenv("YOUTUBE_CLIENT_SECRET")
            refresh_token = os.getenv(f"{prefix}_REFRESH_TOKEN") or os.getenv("YOUTUBE_REFRESH_TOKEN")

            if not (client_id and client_secret and refresh_token):
                print(f"Skipping {ch['id']}: missing {prefix}_CLIENT_ID/SECRET/REFRESH_TOKEN")
                continue

            ch['client_id'] = client_id
            ch['client_secret'] = client_secret
            ch['refresh_token'] = refresh_token
            ch['playlist_title'] = ch.get('playlist_title', Config.PLAYLIST_TITLE)
            valid.append(ch)

        # Fallback to single default if nothing
        if not valid and os.getenv("YOUTUBE_CLIENT_ID"):
            valid.append({
                "id": "default_channel",
                "env_prefix": "YOUTUBE",
                "client_id": os.getenv("YOUTUBE_CLIENT_ID"),
                "client_secret": os.getenv("YOUTUBE_CLIENT_SECRET"),
                "refresh_token": os.getenv("YOUTUBE_REFRESH_TOKEN"),
                "playlist_title": Config.PLAYLIST_TITLE
            })

        print(f"Loaded {len(valid)} channel(s): {[c['id'] for c in valid]} | Mode: {Config.VIDEOS_PER_RUN} video per run")
        return valid
