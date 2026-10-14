import os, json
from dotenv import load_dotenv
load_dotenv()

class Config:
    IG_USER_ID = os.getenv("IG_USER_ID")
    IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")
    PLAYLIST_TITLE = os.getenv("YOUTUBE_PLAYLIST_TITLE", "trailers bollywood")
    PLAYLIST_DESC = os.getenv("YOUTUBE_PLAYLIST_DESCRIPTION", "All videos")
    PRIVACY = os.getenv("YOUTUBE_PRIVACY_STATUS", "public")
    VIDEOS_PER_RUN = int(os.getenv("VIDEOS_PER_RUN", "1"))

    HISTORY_FILE = "data/uploaded_history.json"
    PLAYLIST_FILE = "data/playlist_info.json"
    COUNTER_FILE = "data/bhavy_counter.json"
    TEMP_DIR = "data/temp"
    CHANNELS_CONFIG = "config/channels.json"

    @staticmethod
    def load_channels():
        print("="*70)
        print("[Config] Loading YouTube channels...")
        print(f"[Config] VIDEOS_PER_RUN from env: {os.getenv('VIDEOS_PER_RUN', 'not set -> default 1')} => Using: {Config.VIDEOS_PER_RUN}")
        print(f"[Config] PLAYLIST_TITLE: {Config.PLAYLIST_TITLE}")
        print(f"[Config] PRIVACY: {Config.PRIVACY}")
        print("="*70)

        try:
            with open(Config.CHANNELS_CONFIG, 'r') as f:
                channels = json.load(f)
        except FileNotFoundError:
            print(f"[Config] {Config.CHANNELS_CONFIG} not found, using default")
            channels = [{"id": "trailers_bollywood_main", "env_prefix": "YT1", "enabled": True, "playlist_title": Config.PLAYLIST_TITLE}]

        valid = []
        for ch in channels:
            prefix = ch.get("env_prefix")
            if not prefix:
                print(f"[Config] Skipping {ch.get('id')}: no env_prefix")
                continue

            # FIXED: empty string should not be treated as disabled
            enabled = ch.get("enabled", True)
            env_enabled_raw = os.getenv(f"{prefix}_ENABLED")
            if env_enabled_raw is not None and env_enabled_raw.strip() != "":
                env_enabled = env_enabled_raw.strip().lower()
                enabled = env_enabled in ['true','1','yes','enabled','on']
                print(f"[Config] Channel {ch['id']} enabled override from env {prefix}_ENABLED={env_enabled_raw} -> {enabled}")
            else:
                print(f"[Config] Channel {ch['id']} enabled from config file: {enabled} (env {prefix}_ENABLED not set or empty)")

            if not enabled:
                print(f"[Config] -> Skipping disabled channel {ch['id']}")
                continue

            client_id = os.getenv(f"{prefix}_CLIENT_ID") or os.getenv("YOUTUBE_CLIENT_ID")
            client_secret = os.getenv(f"{prefix}_CLIENT_SECRET") or os.getenv("YOUTUBE_CLIENT_SECRET")
            refresh_token = os.getenv(f"{prefix}_REFRESH_TOKEN") or os.getenv("YOUTUBE_REFRESH_TOKEN")

            has_id = bool(client_id and client_id.strip())
            has_secret = bool(client_secret and client_secret.strip())
            has_refresh = bool(refresh_token and refresh_token.strip())

            print(f"[Config] Checking {ch['id']} ({prefix}_*): CLIENT_ID={'SET' if has_id else 'MISSING'}, CLIENT_SECRET={'SET' if has_secret else 'MISSING'}, REFRESH_TOKEN={'SET' if has_refresh else 'MISSING'}")

            if not (has_id and has_secret and has_refresh):
                print(f"[Config] -> Skipping {ch['id']}: missing credentials")
                continue

            ch['client_id'] = client_id.strip()
            ch['client_secret'] = client_secret.strip()
            ch['refresh_token'] = refresh_token.strip()
            ch['playlist_title'] = ch.get('playlist_title', Config.PLAYLIST_TITLE)
            valid.append(ch)
            print(f"[Config] -> Loaded channel {ch['id']} OK")

        if not valid and os.getenv("YOUTUBE_CLIENT_ID"):
            print("[Config] Using fallback YOUTUBE_* single channel")
            valid.append({
                "id": "default_channel",
                "env_prefix": "YOUTUBE",
                "client_id": os.getenv("YOUTUBE_CLIENT_ID"),
                "client_secret": os.getenv("YOUTUBE_CLIENT_SECRET"),
                "refresh_token": os.getenv("YOUTUBE_REFRESH_TOKEN"),
                "playlist_title": Config.PLAYLIST_TITLE
            })

        print("="*70)
        print(f"[Config] FINAL: Loaded {len(valid)} channel(s): {[c['id'] for c in valid]}")
        print(f"[Config] Mode: {Config.VIDEOS_PER_RUN} video(s) per run")
        for i, c in enumerate(valid):
            print(f"[Config]   {i+1}. {c['id']} ({c['env_prefix']}) -> Playlist '{c['playlist_title']}'")
        print("="*70)
        return valid
