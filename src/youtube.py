from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

class YouTubeChannel:
    """Creates the YouTube client only when a prepared file is ready to upload."""
    def __init__(self, config):
        creds = Credentials(
            None,
            refresh_token=config["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            scopes=["https://www.googleapis.com/auth/youtube.upload"],
        )
        self.config = config
        # build() itself is local; no API request is made until upload_video().
        self.youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    def upload_video(self, file_path, title, description, tags=None):
        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": (tags or [])[:15],
                "categoryId": str(self.config.get("category_id", "24")),
            },
            "status": {
                "privacyStatus": self.config.get("privacy", "public"),
                "selfDeclaredMadeForKids": bool(self.config.get("made_for_kids", False)),
            },
        }
        request = self.youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=MediaFileUpload(file_path, mimetype="video/mp4", resumable=True),
        )
        response = None
        while response is None:
            progress, response = request.next_chunk()
            if progress:
                print(f"[YouTube:{self.config['id']}] Upload {int(progress.progress() * 100)}%")
        return response["id"]

def is_quota_or_limit_error(exc):
    text = str(exc).lower()
    return isinstance(exc, HttpError) and any(
        marker in text for marker in ("quotaexceeded", "uploadlimitexceeded", "dailylimitexceeded")
    )
