import requests
import time

class InstagramFetcher:
    def __init__(self, user_id, access_token):
        self.user_id = user_id
        self.token = access_token

    def get_all_reels(self, max_fetch=1000):
        url = f"https://graph.facebook.com/v20.0/{self.user_id}/media"
        params = {
            "fields": "id,caption,media_type,media_url,permalink,timestamp,thumbnail_url",
            "access_token": self.token,
            "limit": 50
        }
        all_videos = []
        next_url = url
        first = True
        
        print("Fetching ALL Instagram videos...")
        while next_url and len(all_videos) < max_fetch:
            try:
                if first:
                    res = requests.get(next_url, params=params).json()
                    first = False
                else:
                    res = requests.get(next_url).json()

                if 'error' in res:
                    raise Exception(f"Instagram API Error: {res['error']}")

                for item in res.get('data', []):
                    if item.get('media_type') in ['VIDEO', 'REELS']:
                        all_videos.append(item)

                print(f"  Fetched {len(all_videos)} videos so far...")
                next_url = res.get('paging', {}).get('next')
                if not next_url:
                    break
                time.sleep(0.5)
            except Exception as e:
                print(f"Pagination error: {e}")
                break

        all_videos.sort(key=lambda x: x.get('timestamp', ''))
        print(f"Total Instagram videos found: {len(all_videos)}")
        return all_videos

    def get_media_url(self, media_id):
        url = f"https://graph.facebook.com/v20.0/{media_id}"
        params = {
            "fields": "id,media_type,media_url,permalink",
            "access_token": self.token
        }
        res = requests.get(url, params=params).json()
        if 'error' in res:
            print(f"Could not get media_url for {media_id}: {res['error']}")
            return None
        return res.get('media_url')

    def download_video(self, media_id, media_url_fallback, dest_path):
        media_url = media_url_fallback
        if not media_url:
            print(f"  media_url missing, fetching for {media_id}...")
            media_url = self.get_media_url(media_id)
        
        if not media_url:
            raise Exception(f"No media_url for {media_id}")

        r = requests.get(media_url, stream=True, timeout=120)
        r.raise_for_status()
        with open(dest_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
        return dest_path
