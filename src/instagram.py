import requests, time

class InstagramFetcher:
    def __init__(self, user_id, access_token):
        self.user_id = user_id
        self.access_token = access_token
        print(f"[Instagram] Initialized with user_id={user_id[:5]}...")

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
        page = 0

        print("[Instagram] Fetching all reels/videos...")
        print(f"[Instagram] API URL: {url}")
        while next_url and len(all_videos) < max_fetch:
            page += 1
            print(f"[Instagram] Fetching page {page}, total so far: {len(all_videos)}")
            try:
                res = requests.get(next_url, params=params if first else None, timeout=30).json()
            except Exception as e:
                print(f"[Instagram] Request failed page {page}: {e}")
                break
            first = False
            if 'error' in res:
                print(f"[Instagram] API Error: {res['error']}")
                raise Exception(f"Instagram API Error: {res['error']}")
            data = res.get('data', [])
            videos_in_page = [x for x in data if x.get('media_type') in ['VIDEO','REELS']]
            all_videos.extend(videos_in_page)
            print(f"[Instagram] Page {page}: got {len(data)} items, {len(videos_in_page)} videos, total videos now {len(all_videos)}")
            next_url = res.get('paging', {}).get('next')
            if not next_url:
                print("[Instagram] No more pages")
                break
            time.sleep(0.5)

        all_videos.sort(key=lambda x: x.get('timestamp',''))
        print(f"[Instagram] FINAL Total videos: {len(all_videos)}")
        if all_videos:
            print(f"[Instagram] Oldest: {all_videos[0]['id']} @ {all_videos[0].get('timestamp')}")
            print(f"[Instagram] Newest: {all_videos[-1]['id']} @ {all_videos[-1].get('timestamp')}")
        return all_videos

    def fetch_fresh_media_url(self, media_id):
        print(f"[Instagram] Fetching fresh media_url for {media_id}")
        url = f"https://graph.facebook.com/v20.0/{media_id}"
        params = {"fields": "id,media_type,media_url,permalink", "access_token": self.access_token}
        try:
            res = requests.get(url, params=params, timeout=30).json()
            if 'error' in res:
                print(f"[Instagram] Failed to fetch media_url for {media_id}: {res['error']}")
                return None
            media_url = res.get('media_url')
            if media_url:
                print(f"[Instagram] Got fresh media_url for {media_id}: {media_url[:80]}...")
            else:
                print(f"[Instagram] No media_url in response for {media_id}: {res}")
            return media_url
        except Exception as e:
            print(f"[Instagram] Exception fetching media_url for {media_id}: {e}")
            return None

    def download_video(self, media_id, media_url_fallback, dest_path):
        # Always try to get fresh URL first to avoid expired
        fresh_url = self.fetch_fresh_media_url(media_id)
        media_url = fresh_url or media_url_fallback

        if not media_url:
            raise Exception(f"No media_url for {media_id} - Instagram says expired or deleted (API returned None)")

        print(f"[Instagram] Downloading {media_id} to {dest_path}")
        print(f"[Instagram] Using media_url: {media_url[:120]}...")

        try:
            r = requests.get(media_url, stream=True, timeout=180)
            if r.status_code != 200:
                print(f"[Instagram] Download HTTP {r.status_code}: {r.text[:200]}")
                # If fallback was used and failed, try fresh one more time
                if media_url == media_url_fallback and fresh_url is None:
                    print("[Instagram] Retrying with fresh fetch...")
                    fresh_url2 = self.fetch_fresh_media_url(media_id)
                    if fresh_url2 and fresh_url2 != media_url:
                        print("[Instagram] Retrying with new URL")
                        r = requests.get(fresh_url2, stream=True, timeout=180)
            r.raise_for_status()
            total = 0
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk)
                        total += len(chunk)
            print(f"[Instagram] Downloaded {total} bytes to {dest_path}")
            return dest_path
        except requests.exceptions.HTTPError as e:
            if '403' in str(e) or '401' in str(e) or 'expired' in str(e).lower():
                raise Exception(f"No media_url for {media_id} - expired (HTTP {e})")
            raise
