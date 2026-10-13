from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from src.config import Config

class QuotaExceededException(Exception):
    pass

class YouTubeUploader:
    def __init__(self):
        if not Config.YOUTUBE_REFRESH_TOKEN:
            raise Exception("Missing YOUTUBE_REFRESH_TOKEN")
        creds = Credentials(
            None,
            refresh_token=Config.YOUTUBE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=Config.YOUTUBE_CLIENT_ID,
            client_secret=Config.YOUTUBE_CLIENT_SECRET,
            scopes=[
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube"
            ]
        )
        self.youtube = build('youtube', 'v3', credentials=creds)

    def get_or_create_playlist(self, title, description=""):
        print(f"Checking for playlist: {title}")
        try:
            req = self.youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
            for item in req.get('items', []):
                if item['snippet']['title'].lower() == title.lower():
                    print(f"Found existing playlist: {item['id']}")
                    return item['id']
        except HttpError as e:
            if any(x in str(e).lower() for x in ['quota','exceeded','uploadlimit']):
                raise QuotaExceededException(str(e))

        print(f"Creating new playlist: {title}")
        body = {
            "snippet": {"title": title, "description": description or f"Playlist {title} - bhavy series"},
            "status": {"privacyStatus": Config.YOUTUBE_PRIVACY}
        }
        try:
            res = self.youtube.playlists().insert(part="snippet,status", body=body).execute()
            print(f"Created playlist: {res['id']}")
            return res['id']
        except HttpError as e:
            if any(x in str(e).lower() for x in ['quota','exceeded','uploadlimit']):
                raise QuotaExceededException(str(e))
            raise

    def add_video_to_playlist(self, playlist_id, video_id):
        if video_id.startswith("SKIPPED"):
            return None
        body = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id}
            }
        }
        try:
            res = self.youtube.playlistItems().insert(part="snippet", body=body).execute()
            print(f"Added to playlist: {video_id}")
            return res['id']
        except HttpError as e:
            msg = str(e).lower()
            if any(x in msg for x in ['quota','exceeded','uploadlimit']):
                raise QuotaExceededException(str(e))
            if 'already' in msg or 'duplicate' in msg:
                print(f"Video {video_id} already in playlist")
                return None
            print(f"Failed to add to playlist: {e}")
            return None

    def upload(self, file_path, title, description, tags=[]):
        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags[:15],
                "categoryId": "24"
            },
            "status": {
                "privacyStatus": Config.YOUTUBE_PRIVACY,
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
                    print(f"  Upload {int(status.progress()*100)}%")
            print(f"Upload OK: {response['id']} - {title}")
            return response['id']
        except HttpError as e:
            err_text = str(e).lower()
            if any(x in err_text for x in ['quota','exceeded','uploadlimit','rate limit']):
                print(f"!!! YOUTUBE LIMIT EXCEEDED: {e}")
                raise QuotaExceededException(str(e))
            else:
                raise
