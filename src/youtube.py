from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

class QuotaExceededException(Exception):
    def __init__(self, msg, token_id=None, is_channel_limit=False):
        super().__init__(msg); self.token_id = token_id; self.is_channel_limit = is_channel_limit

class YouTubeToken:
    def __init__(self, token_config):
        self.token_id = token_config['id']
        creds = Credentials(None, refresh_token=token_config['refresh_token'], token_uri="https://oauth2.googleapis.com/token",
            client_id=token_config['client_id'], client_secret=token_config['client_secret'],
            scopes=["https://www.googleapis.com/auth/youtube.upload","https://www.googleapis.com/auth/youtube"])
        self.youtube = build('youtube', 'v3', credentials=creds)
        self.exhausted = False
        print(f"[{self.token_id}] Token ready")

    def get_or_create_playlist(self, title, description, privacy="public"):
        try:
            req = self.youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
            for item in req.get('items', []):
                if item['snippet']['title'].lower() == title.lower(): return item['id']
        except HttpError as e:
            if 'uploadlimit' in str(e).lower() or 'quota' in str(e).lower():
                raise QuotaExceededException(str(e), self.token_id, is_channel_limit='uploadlimit' in str(e).lower())
        body = {"snippet": {"title": title, "description": description}, "status": {"privacyStatus": privacy}}
        try:
            res = self.youtube.playlists().insert(part="snippet,status", body=body).execute()
            return res['id']
        except HttpError as e:
            raise QuotaExceededException(str(e), self.token_id, is_channel_limit='uploadlimit' in str(e).lower())

    def add_to_playlist(self, playlist_id, video_id):
        if video_id.startswith("SKIPPED"): return None
        body = {"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}
        try:
            self.youtube.playlistItems().insert(part="snippet", body=body).execute()
            print(f"[{self.token_id}] Added to playlist: {video_id}")
        except HttpError as e:
            if 'uploadlimit' in str(e).lower() or 'quota' in str(e).lower():
                raise QuotaExceededException(str(e), self.token_id, is_channel_limit='uploadlimit' in str(e).lower())

    def upload(self, file_path, title, description, tags=[], privacy="public"):
        body = {"snippet": {"title": title[:100], "description": description[:5000], "tags": tags[:15], "categoryId": "24"}, "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
        media = MediaFileUpload(file_path, mimetype='video/mp4', resumable=True)
        try:
            request = self.youtube.videos().insert(part="snippet,status", body=body, media_body=media)
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status: print(f"[{self.token_id}] Upload {int(status.progress()*100)}% - {title}")
            print(f"[{self.token_id}] SUCCESS: {response['id']}")
            return response['id']
        except HttpError as e:
            txt = str(e).lower()
            if any(x in txt for x in ['quota','exceeded','uploadlimit','rate limit']):
                raise QuotaExceededException(str(e), self.token_id, is_channel_limit='uploadlimit' in txt)
            raise

class SingleChannelMultiTokenManager:
    def __init__(self, tokens_config):
        self.tokens = [YouTubeToken(t) for t in tokens_config]
        self.current_idx = 0
    def get_active_token(self):
        while self.current_idx < len(self.tokens):
            tok = self.tokens[self.current_idx]
            if not tok.exhausted: return tok
            self.current_idx += 1
        return None
    def upload_with_rotation(self, file_path, title, description, tags=[], privacy="public"):
        while True:
            token = self.get_active_token()
            if not token: raise QuotaExceededException("All tokens exhausted", "ALL", is_channel_limit=True)
            try:
                vid = token.upload(file_path, title, description, tags, privacy)
                return vid, token.token_id, token
            except QuotaExceededException as qe:
                if qe.is_channel_limit:
                    print(f"Channel limit hit - all tokens for same channel blocked")
                    raise
                else:
                    print(f"[{token.token_id}] Quota hit, rotating...")
                    continue
