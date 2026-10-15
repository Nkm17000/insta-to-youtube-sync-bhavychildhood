import json
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    IG_USER_ID = os.getenv("IG_USER_ID", "").strip()
    IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN", "").strip()
    PRIVACY = os.getenv("YOUTUBE_PRIVACY_STATUS", "public").strip().lower()
    SKIPPED_RETRY_HOURS = int(os.getenv("SKIPPED_RETRY_HOURS", "24"))
    TEMP_DIR = os.getenv("TEMP_DIR", "data/temp")
    CHANNELS_CONFIG = os.getenv("CHANNELS_CONFIG", "config/channels.json")
    HISTORY_DIR = os.getenv("HISTORY_DIR", "data/channel_history")

    @classmethod
    def load_channels(cls):
        with open(cls.CHANNELS_CONFIG, encoding="utf-8") as f:
            configs = json.load(f)
        enabled = []
        for item in configs:
            if not item.get("enabled", False):
                print(f"[Config] {item.get('id', '<missing>')}: disabled")
                continue
            channel_id = str(item.get("channel_id", "")).strip()
            prefix = str(item.get("env_prefix", "")).strip()
            if not item.get("id") or not channel_id or not prefix:
                print(f"[Config] Skipping invalid channel config: {item.get('id', '<missing>')} (id, channel_id, env_prefix required)")
                continue
            # No shared credential fallback: channel isolation is intentional.
            client_id = os.getenv(f"{prefix}_CLIENT_ID", "").strip()
            client_secret = os.getenv(f"{prefix}_CLIENT_SECRET", "").strip()
            refresh_token = os.getenv(f"{prefix}_REFRESH_TOKEN", "").strip()
            if not all((client_id, client_secret, refresh_token)):
                print(f"[Config] {item['id']}: enabled but credentials missing; skipping")
                continue
            enabled.append({
                **item,
                "channel_id": channel_id,
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "privacy": item.get("privacy", cls.PRIVACY),
                "history_file": os.path.join(cls.HISTORY_DIR, f"{item['id']}.json"),
            })
        print(f"[Config] {len(enabled)} enabled channel(s) with complete credentials")
        return enabled
