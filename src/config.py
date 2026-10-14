import os, json
from dotenv import load_dotenv
load_dotenv()
class Config:
    IG_USER_ID = os.getenv("IG_USER_ID")
    IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")
    YOUTUBE_PLAYLIST_TITLE = os.getenv("YOUTUBE_PLAYLIST_TITLE", "bhavychildhood")
    YOUTUBE_PLAYLIST_DESCRIPTION = os.getenv("YOUTUBE_PLAYLIST_DESCRIPTION", "All videos from Instagram @bhavychildhood")
    YOUTUBE_PRIVACY = os.getenv("YOUTUBE_PRIVACY_STATUS", "public")
    HISTORY_FILE = "data/uploaded_history.json"
    PLAYLIST_FILE = "data/playlist_info.json"
    COUNTER_FILE = "data/bhavy_counter.json"
    USAGE_FILE = "data/token_usage.json"
    
    TEMP_DIR = "data/temp"
    ACCOUNTS_CONFIG = "config/youtube_accounts.json"
    VIDEOS_PER_RUN = int(os.getenv("VIDEOS_PER_RUN", "1"))  # ONE video at a time
    @staticmethod
    def load_youtube_tokens():
        try:
            with open(Config.ACCOUNTS_CONFIG, 'r') as f: tokens = json.load(f)
        except: tokens = [{"id": "TOKEN1", "enabled": True, "env_prefix": "YT1"}]
        enabled = []
        for t in tokens:
            env_prefix = t.get("env_prefix", t.get("id"))
            enabled_flag = t.get("enabled", True)
            env_enabled = os.getenv(f"{env_prefix}_ENABLED")
            if env_enabled is not None: enabled_flag = env_enabled.lower() in ['true','1','yes','enabled']
            if not enabled_flag: continue
            client_id = os.getenv(f"{env_prefix}_CLIENT_ID") or os.getenv("YOUTUBE_CLIENT_ID")
            client_secret = os.getenv(f"{env_prefix}_CLIENT_SECRET") or os.getenv("YOUTUBE_CLIENT_SECRET")
            refresh_token = os.getenv(f"{env_prefix}_REFRESH_TOKEN") or os.getenv("YOUTUBE_REFRESH_TOKEN")
            if not (client_id and client_secret and refresh_token): continue
            t['client_id'] = client_id; t['client_secret'] = client_secret; t['refresh_token'] = refresh_token
            enabled.append(t)
        if not enabled and os.getenv("YOUTUBE_CLIENT_ID"):
            enabled.append({"id": "DEFAULT", "env_prefix": "YOUTUBE", "client_id": os.getenv("YOUTUBE_CLIENT_ID"), "client_secret": os.getenv("YOUTUBE_CLIENT_SECRET"), "refresh_token": os.getenv("YOUTUBE_REFRESH_TOKEN")})
        print(f"Loaded {len(enabled)} tokens: {[a['id'] for a in enabled]} | Mode: {Config.VIDEOS_PER_RUN} video(s) per run")
        return enabled
