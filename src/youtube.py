from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

class ChannelLimitError(Exception):
    def __init__(self, msg, channel_id):
        super().__init__(msg)
        self.channel_id = channel_id

class QuotaError(Exception):
    def __init__(self, msg, channel_id):
        super().__init__(msg)
        self.channel_id = channel_id

class YouTubeChannel:
    """Single class for all channels - no duplicate code"""
    def __init__(self, config):
        self.id = config['id']
        self.playlist_title = config['playlist_title']
        self.env_prefix = config['env_prefix']

        creds = Credentials(
            None,
            refresh_token=config['refresh_token'],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=config['client_id'],
            client_secret=config['client_secret'],
            scopes=[
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube"
            ]
        )
        self.youtube = build('youtube', 'v3', credentials=creds)
        self.exhausted = False
        self.channel_name = self.id
        self.youtube_channel_id = "unknown"

        # Get actual channel name
        try:
            res = self.youtube.channels().list(part="snippet", mine=True).execute()
            if res.get('items'):
                self.channel_name = res['items'][0]['snippet']['title']
                self.youtube_channel_id = res['items'][0]['id']
        except Exception:
            pass

        print(f"[{self.id}] Ready -> Channel: '{self.channel_name}' ({self.youtube_channel_id})")

    def get_or_create_playlist(self, title, description, privacy="public"):
        try:
            res = self.youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
            for item in res.get('items', []):
                if item['snippet']['title'].lower() == title.lower():
                    print(f"[{self.id}] Found playlist: {item['id']}")
                    return item['id']
        except HttpError as e:
            txt = str(e).lower()
            if 'uploadlimit' in txt:
                raise ChannelLimitError(str(e), self.id)
            if 'quota' in txt:
                raise QuotaError(str(e), self.id)

        print(f"[{self.id}] Creating playlist: {title}")
        body = {
            "snippet": {"title": title, "description": description},
            "status": {"privacyStatus": privacy}
        }
        try:
            res = self.youtube.playlists().insert(part="snippet,status", body=body).execute()
            return res['id']
        except HttpError as e:
            txt = str(e).lower()
            if 'uploadlimit' in txt:
                raise ChannelLimitError(str(e), self.id)
            if 'quota' in txt:
                raise QuotaError(str(e), self.id)
            raise

    def add_to_playlist(self, playlist_id, video_id):
        if video_id.startswith("SKIPPED"):
            return
        body = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id}
            }
        }
        try:
            self.youtube.playlistItems().insert(part="snippet", body=body).execute()
            print(f"[{self.id}] Added {video_id} to playlist")
        except HttpError as e:
            txt = str(e).lower()
            if 'uploadlimit' in txt:
                raise ChannelLimitError(str(e), self.id)
            if 'quota' in txt:
                raise QuotaError(str(e), self.id)

    def upload_video(self, file_path, title, description, tags=[], privacy="public"):
        if self.exhausted:
            raise ChannelLimitError(f"Channel {self.id} exhausted", self.id)

        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags[:15],
                "categoryId": "24"
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False
            }
        }
        media = MediaFileUpload(file_path, mimetype='video/mp4', resumable=True)
        try:
            request = self.youtube.videos().insert(part="snippet,status", body=body, media_body=media)
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    print(f"[{self.id}] Upload {int(status.progress()*100)}% - {title}")
            print(f"[{self.id}] SUCCESS: {response['id']} - {title}")
            return response['id']
        except HttpError as e:
            txt = str(e).lower()
            if 'uploadlimit' in txt:
                self.exhausted = True
                raise ChannelLimitError(f"Channel {self.id} daily upload limit (15/day) hit: {e}", self.id)
            if any(x in txt for x in ['quota', 'exceeded', 'rate limit']):
                self.exhausted = True
                raise QuotaError(f"Channel {self.id} quota exceeded: {e}", self.id)
            raise
