import requests, time

class InstagramFetcher:
    def __init__(self, user_id, access_token):
        self.user_id = user_id
        self.access_token = access_token

    def get_all_reels(self, max_fetch=1000):
        url = f"https://graph.facebook.com/v20.0/{self.user_id}/media"
        params = {
            "fields": "id,caption,media_type,media_url,permalink,timestamp",
            "access_token": self.access_token,
            "limit": 50
        }
        all_videos = []
        next_url = url
        first = True

        print("[Instagram] Fetching all reels/videos...")
        while next_url and len(all_videos) < max_fetch:
            res = requests.get(next_url, params=params if first else None).json()
            first = False
            if 'error' in res:
                raise Exception(f"Instagram API Error: {res['error']}")
            for item in res.get('data', []):
                if item.get('media_type') in ['VIDEO', 'REELS']:
                    all_videos.append(item)
            print(f"  Fetched {len(all_videos)} so far...")
            next_url = res.get('paging', {}).get('next')
            if not next_url:
                break
            time.sleep(0.3)

        all_videos.sort(key=lambda x: x.get('timestamp',''))
        print(f"[Instagram] Total videos: {len(all_videos)}")
        return all_videos

    def download_video(self, media_id, media_url_fallback, dest_path):
        media_url = media_url_fallback
        if not media_url:
            # Try to fetch media_url
            url = f"https://graph.facebook.com/v20.0/{media_id}"
            params = {"fields": "media_url", "access_token": self.access_token}
            res = requests.get(url, params=params).json()
            media_url = res.get('media_url')

        if not media_url:
            raise Exception(f"No media_url for {media_id} (expired or deleted)")

        print(f"  Downloading {media_id}...")
        r = requests.get(media_url, stream=True, timeout=180)
        r.raise_for_status()
        with open(dest_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
        return dest_path
