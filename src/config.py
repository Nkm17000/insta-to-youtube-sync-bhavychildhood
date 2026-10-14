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
        print("[Config] Loading channels...")
        try:
            with open(Config.CHANNELS_CONFIG, 'r') as f: channels = json.load(f)
        except: channels = [{"id": "trailers_bollywood_main", "env_prefix": "YT1", "enabled": True, "playlist_title": Config.PLAYLIST_TITLE}]
        valid=[]
        for ch in channels:
            prefix=ch.get("env_prefix")
            if not prefix: continue
            enabled=ch.get("enabled", True)
            raw=os.getenv(f"{prefix}_ENABLED")
            if raw is not None and raw.strip()!="":
                enabled=raw.strip().lower() in ['true','1','yes','enabled','on']
            if not enabled: continue
            cid=os.getenv(f"{prefix}_CLIENT_ID") or os.getenv("YOUTUBE_CLIENT_ID")
            csec=os.getenv(f"{prefix}_CLIENT_SECRET") or os.getenv("YOUTUBE_CLIENT_SECRET")
            rtok=os.getenv(f"{prefix}_REFRESH_TOKEN") or os.getenv("YOUTUBE_REFRESH_TOKEN")
            if not (cid and csec and rtok and cid.strip() and csec.strip() and rtok.strip()): continue
            ch['client_id']=cid.strip(); ch['client_secret']=csec.strip(); ch['refresh_token']=rtok.strip()
            ch['playlist_title']=ch.get('playlist_title', Config.PLAYLIST_TITLE)
            valid.append(ch)
        print(f"[Config] Loaded {len(valid)} channel(s)")
        return valid
