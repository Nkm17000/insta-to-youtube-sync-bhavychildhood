import requests, time

class InstagramFetcher:
    def __init__(self, user_id, access_token):
        self.user_id = user_id
        self.token = access_token

    def get_all_reels(self, max_fetch=1000):
        url = f"https://graph.facebook.com/v20.0/{self.user_id}/media"
        params = {"fields": "id,caption,media_type,media_url,permalink,timestamp", "access_token": self.token, "limit": 50}
        all_videos = []
        next_url = url
        first = True
        print("[Instagram] Fetching all reels...")
        while next_url and len(all_videos) < max_fetch:
            res = requests.get(next_url, params=params if first else None, timeout=30).json()
            first = False
            if 'error' in res:
                raise Exception(f"IG Error: {res['error']}")
            for item in res.get('data', []):
                if item.get('media_type') in ['VIDEO','REELS']:
                    all_videos.append(item)
            next_url = res.get('paging', {}).get('next')
            if not next_url: break
            time.sleep(0.3)
        all_videos.sort(key=lambda x: x.get('timestamp',''))
        print(f"[Instagram] Total: {len(all_videos)}")
        return all_videos

    def fetch_media_url(self, media_id):
        # ONLY Instagram API - no YouTube API
        url = f"https://graph.facebook.com/v20.0/{media_id}"
        params = {"fields": "id,media_type,media_url,permalink", "access_token": self.token}
        try:
            res = requests.get(url, params=params, timeout=30).json()
            if 'error' in res:
                print(f"[Instagram] {media_id} -> No media_url, error: {res['error'].get('message')}")
                return None
            mu = res.get('media_url')
            if mu:
                print(f"[Instagram] {media_id} -> media_url OK ({mu[:60]}...)")
            else:
                print(f"[Instagram] {media_id} -> No media_url (expired/deleted)")
            return mu
        except Exception as e:
            print(f"[Instagram] {media_id} -> Exception fetching media_url: {e}")
            return None

    def download_video(self, media_url, dest_path):
        print(f"[Instagram] Downloading from {media_url[:80]}...")
        r = requests.get(media_url, stream=True, timeout=180)
        r.raise_for_status()
        total = 0
        with open(dest_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
                    total += len(chunk)
        print(f"[Instagram] Downloaded {total} bytes")
        return dest_path
