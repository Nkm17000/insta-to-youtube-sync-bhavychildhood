from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

class ChannelLimitError(Exception):
    def __init__(self, msg, channel_id): super().__init__(msg); self.channel_id=channel_id
class QuotaError(Exception):
    def __init__(self, msg, channel_id): super().__init__(msg); self.channel_id=channel_id

class YouTubeChannel:
    def __init__(self, config):
        self.id=config['id']
        self.playlist_title=config['playlist_title']
        creds=Credentials(None, refresh_token=config['refresh_token'], token_uri="https://oauth2.googleapis.com/token",
            client_id=config['client_id'], client_secret=config['client_secret'],
            scopes=["https://www.googleapis.com/auth/youtube.upload","https://www.googleapis.com/auth/youtube"])
        self.youtube=build('youtube','v3', credentials=creds)
        self.exhausted=False; self.exhausted_reason=None
        self.channel_name=self.id; self.youtube_channel_id="unknown"; self.uploaded_today=0
        try:
            res=self.youtube.channels().list(part="snippet", mine=True).execute()
            if res.get('items'):
                self.channel_name=res['items'][0]['snippet']['title']
                self.youtube_channel_id=res['items'][0]['id']
        except: pass
        print(f"[YouTube:{self.id}] Ready -> '{self.channel_name}'")

    def list_playlist_videos(self, playlist_id):
        print(f"[YouTube:{self.id}] Listing playlist {playlist_id} to avoid duplicate bhavy2")
        videos=[]
        next_token=None
        try:
            while True:
                req=self.youtube.playlistItems().list(part="snippet,contentDetails", playlistId=playlist_id, maxResults=50, pageToken=next_token).execute()
                for item in req.get('items', []):
                    videos.append({"title":item['snippet']['title'],"description":item['snippet'].get('description',''),"videoId":item['contentDetails']['videoId']})
                next_token=req.get('nextPageToken')
                if not next_token: break
            print(f"[YouTube:{self.id}] Playlist has {len(videos)} videos")
            return videos
        except Exception as e:
            print(f"[YouTube:{self.id}] List failed: {e}")
            return []

    def check_duplicate(self, playlist_id, insta_permalink, candidate_title):
        existing=self.list_playlist_videos(playlist_id)
        for v in existing:
            if insta_permalink and insta_permalink in v['description']:
                print(f"[YouTube:{self.id}] DUPLICATE by permalink: {insta_permalink} already in {v['videoId']}")
                return True, v
            if v['title'].lower().strip()==candidate_title.lower().strip():
                print(f"[YouTube:{self.id}] DUPLICATE by title: '{candidate_title}' already exists")
                return True, v
        print(f"[YouTube:{self.id}] No duplicate for '{candidate_title}'")
        return False, None

    def get_or_create_playlist(self, title, description, privacy="public"):
        print(f"[YouTube:{self.id}] Checking/creating playlist '{title}' - YouTube API call")
        try:
            res=self.youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
            for item in res.get('items', []):
                if item['snippet']['title'].lower()==title.lower():
                    print(f"[YouTube:{self.id}] Found playlist {item['id']}")
                    return item['id']
        except HttpError as e:
            txt=str(e).lower()
            if 'uploadlimit' in txt: raise ChannelLimitError(str(e), self.id)
            if 'quota' in txt: raise QuotaError(str(e), self.id)
        print(f"[YouTube:{self.id}] Creating playlist '{title}'")
        body={"snippet":{"title":title,"description":description},"status":{"privacyStatus":privacy}}
        res=self.youtube.playlists().insert(part="snippet,status", body=body).execute()
        return res['id']

    def add_to_playlist(self, playlist_id, video_id):
        if video_id.startswith("SKIPPED") or video_id.startswith("FAILED"): return
        body={"snippet":{"playlistId":playlist_id,"resourceId":{"kind":"youtube#video","videoId":video_id}}}
        self.youtube.playlistItems().insert(part="snippet", body=body).execute()
        print(f"[YouTube:{self.id}] Added {video_id} to playlist")

    def upload_video(self, file_path, title, description, tags=[], privacy="public"):
        print(f"[YouTube:{self.id}] Uploading '{title}' - YouTube API upload")
        body={"snippet":{"title":title[:100],"description":description[:5000],"tags":tags[:15],"categoryId":"24"},"status":{"privacyStatus":privacy,"selfDeclaredMadeForKids":False}}
        media=MediaFileUpload(file_path, mimetype='video/mp4', resumable=True)
        try:
            request=self.youtube.videos().insert(part="snippet,status", body=body, media_body=media)
            response=None
            while response is None:
                status, response=request.next_chunk()
                if status: print(f"[YouTube:{self.id}] Upload {int(status.progress()*100)}%")
            vid=response['id']
            self.uploaded_today+=1
            print(f"[YouTube:{self.id}] SUCCESS {vid} -> https://youtu.be/{vid}")
            return vid
        except HttpError as e:
            txt=str(e).lower()
            if 'uploadlimit' in txt:
                self.exhausted=True; self.exhausted_reason=str(e)
                raise ChannelLimitError(str(e), self.id)
            if 'quota' in txt or 'exceeded' in txt:
                self.exhausted=True; self.exhausted_reason=str(e)
                raise QuotaError(str(e), self.id)
            raise
