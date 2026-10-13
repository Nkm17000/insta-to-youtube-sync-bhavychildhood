import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    IG_USER_ID = os.getenv("IG_USER_ID")
    IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")
    YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")
    YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
    YOUTUBE_REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN")
    YOUTUBE_PRIVACY = os.getenv("YOUTUBE_PRIVACY_STATUS", "public")
    YOUTUBE_PLAYLIST_TITLE = os.getenv("YOUTUBE_PLAYLIST_TITLE", "bhavychildhood")
    YOUTUBE_PLAYLIST_DESCRIPTION = os.getenv("YOUTUBE_PLAYLIST_DESCRIPTION", "All videos from Instagram @bhavychildhood - Auto synced | bhavy series")
    HISTORY_FILE = "data/uploaded_history.json"
    PLAYLIST_FILE = "data/playlist_info.json"
    COUNTER_FILE = "data/bhavy_counter.json"
    TEMP_DIR = "data/temp"
