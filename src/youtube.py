from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import time

class ChannelLimitError(Exception):
    def __init__(self, msg, channel_id):
        super().__init__(msg)
        self.channel_id = channel_id
        self.is_channel_limit = True

class QuotaError(Exception):
    def __init__(self, msg, channel_id):
        super().__init__(msg)
        self.channel_id = channel_id
        self.is_channel_limit = False

class YouTubeChannel:
    def __init__(self, config):
        self.id = config['id']
        self.playlist_title = config['playlist_title']
        self.env_prefix = config['env_prefix']

        print(f"[YouTube:{self.id}] Initializing with prefix {self.env_prefix}...")

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
        self.exhausted_reason = None
        self.channel_name = self.id
        self.youtube_channel_id = "unknown"
        self.uploaded_today = 0

        try:
            res = self.youtube.channels().list(part="snippet,statistics", mine=True).execute()
            if res.get('items'):
                snippet = res['items'][0]['snippet']
                stats = res['items'][0].get('statistics', {})
                self.channel_name = snippet['title']
                self.youtube_channel_id = res['items'][0]['id']
                print(f"[YouTube:{self.id}] Ready -> Channel: '{self.channel_name}' (ID: {self.youtube_channel_id})")
                print(f"[YouTube:{self.id}] Channel stats: videos={stats.get('videoCount')}, subs={stats.get('subscriberCount')}")
            else:
                print(f"[YouTube:{self.id}] No channel found for token")
        except Exception as e:
            print(f"[YouTube:{self.id}] Failed to get channel info: {e}")
            # Still consider ready, token might be valid

    def log_token_status(self):
        print(f"[YouTube:{self.id}] Token Status:")
        print(f"  Channel ID: {self.youtube_channel_id}")
        print(f"  Channel Name: {self.channel_name}")
        print(f"  Playlist Title: {self.playlist_title}")
        print(f"  Exhausted: {self.exhausted} (reason: {self.exhausted_reason})")
        print(f"  Uploaded today in this run: {self.uploaded_today}")
        print(f"  Env prefix: {self.env_prefix}")

    def get_or_create_playlist(self, title, description, privacy="public"):
        print(f"[YouTube:{self.id}] Checking playlist '{title}'...")
        try:
            res = self.youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
            items = res.get('items', [])
            print(f"[YouTube:{self.id}] Found {len(items)} existing playlists")
            for item in items:
                t = item['snippet']['title']
                pid = item['id']
                print(f"  - Playlist: '{t}' -> {pid}")
                if t.lower() == title.lower():
                    print(f"[YouTube:{self.id}] MATCH found playlist '{title}': {pid} -> https://www.youtube.com/playlist?list={pid}")
                    return pid
        except HttpError as e:
            txt = str(e).lower()
            print(f"[YouTube:{self.id}] Error listing playlists: {e}")
            if 'uploadlimit' in txt or 'quota' in txt:
                self.exhausted = True
                self.exhausted_reason = str(e)
                if 'uploadlimit' in txt:
                    raise ChannelLimitError(str(e), self.id)
                else:
                    raise QuotaError(str(e), self.id)

        print(f"[YouTube:{self.id}] Creating new playlist: '{title}' (privacy={privacy})")
        body = {
            "snippet": {"title": title, "description": description},
            "status": {"privacyStatus": privacy}
        }
        try:
            res = self.youtube.playlists().insert(part="snippet,status", body=body).execute()
            pid = res['id']
            print(f"[YouTube:{self.id}] Created playlist '{title}': {pid}")
            return pid
        except HttpError as e:
            txt = str(e).lower()
            print(f"[YouTube:{self.id}] Failed to create playlist: {e}")
            self.exhausted = True
            self.exhausted_reason = str(e)
            if 'uploadlimit' in txt:
                raise ChannelLimitError(str(e), self.id)
            if 'quota' in txt or 'exceeded' in txt:
                raise QuotaError(str(e), self.id)
            raise

    def add_to_playlist(self, playlist_id, video_id):
        if video_id.startswith("SKIPPED"):
            print(f"[YouTube:{self.id}] Skipping playlist add for SKIPPED video {video_id}")
            return
        print(f"[YouTube:{self.id}] Adding video {video_id} to playlist {playlist_id}")
        body = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id}
            }
        }
        try:
            self.youtube.playlistItems().insert(part="snippet", body=body).execute()
            print(f"[YouTube:{self.id}] Added {video_id} to playlist {playlist_id}")
        except HttpError as e:
            print(f"[YouTube:{self.id}] Failed to add to playlist: {e}")
            txt = str(e).lower()
            if 'uploadlimit' in txt:
                raise ChannelLimitError(str(e), self.id)
            if 'quota' in txt:
                raise QuotaError(str(e), self.id)

    def upload_video(self, file_path, title, description, tags=[], privacy="public"):
        if self.exhausted:
            raise ChannelLimitError(f"Channel {self.id} already marked exhausted: {self.exhausted_reason}", self.id)

        print(f"[YouTube:{self.id}] Starting upload:")
        print(f"  File: {file_path}")
        print(f"  Title: {title}")
        print(f"  Description length: {len(description)}")
        print(f"  Tags: {tags}")
        print(f"  Privacy: {privacy}")
        print(f"  Channel: {self.channel_name} ({self.youtube_channel_id})")

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
            last_progress = 0
            while response is None:
                status, response = request.next_chunk()
                if status:
                    prog = int(status.progress()*100)
                    if prog != last_progress and prog % 20 == 0:
                        print(f"[YouTube:{self.id}] Upload progress: {prog}% - {title}")
                        last_progress = prog

            video_id = response['id']
            self.uploaded_today += 1
            print(f"[YouTube:{self.id}] SUCCESS! Video ID: {video_id}")
            print(f"[YouTube:{self.id}] URL: https://youtu.be/{video_id}")
            print(f"[YouTube:{self.id}] Title: {title}")
            print(f"[YouTube:{self.id}] Channel: {self.channel_name}")
            print(f"[YouTube:{self.id}] Uploaded today (this run): {self.uploaded_today}")
            return video_id

        except HttpError as e:
            txt = str(e).lower()
            print(f"[YouTube:{self.id}] Upload FAILED: {e}")
            print(f"[YouTube:{self.id}] Error text: {txt[:500]}")
            if 'uploadlimit' in txt:
                print(f"[YouTube:{self.id}] *** CHANNEL DAILY LIMIT HIT (15/day) ***")
                print(f"[YouTube:{self.id}] This is per YouTube channel, not per token. Different Gmail = separate limit.")
                print(f"[YouTube:{self.id}] Reset time: ~12:30 PM IST next day (midnight PST)")
                self.exhausted = True
                self.exhausted_reason = f"Channel limit: {e}"
                raise ChannelLimitError(f"Channel {self.id} daily upload limit hit: {e}", self.id)
            if any(x in txt for x in ['quota', 'exceeded', 'rate limit', 'userRateLimitExceeded']):
                print(f"[YouTube:{self.id}] *** QUOTA EXCEEDED (10k units/day per GCP project) ***")
                print(f"[YouTube:{self.id}] Each upload costs ~1600 quota. 6 uploads per project per day max.")
                print(f"[YouTube:{self.id}] Use different GCP project / different Gmail to get more quota.")
                self.exhausted = True
                self.exhausted_reason = f"Quota: {e}"
                raise QuotaError(f"Channel {self.id} quota exceeded: {e}", self.id)
            raise
