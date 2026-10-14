import json, os, datetime

class HistoryManager:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, 'w') as f:
                json.dump({}, f)
            print(f"[History] Created new history file: {path}")
        else:
            print(f"[History] Using existing history file: {path}")

    def load(self):
        with open(self.path, 'r') as f:
            try:
                data = json.load(f)
                return data
            except Exception as e:
                print(f"[History] Failed to load history: {e}, returning empty")
                return {}

    def count_valid(self):
        data = self.load()
        valid = len([v for v in data.values() if not str(v.get('youtube_id','')).startswith('SKIPPED')])
        skipped = len(data) - valid
        return valid, skipped, len(data)

    def filter_new_videos(self, all_videos):
        data = self.load()
        uploaded_ids = set(data.keys())
        valid, skipped, total = self.count_valid()

        new_videos = [v for v in all_videos if v['id'] not in uploaded_ids]

        print("="*70)
        print("[History] DUPLICATE CHECK")
        print(f"  Total Instagram videos fetched: {len(all_videos)}")
        print(f"  History file total entries: {total} (valid={valid}, skipped={skipped})")
        print(f"  Already uploaded IDs: {len(uploaded_ids)}")
        print(f"  New videos to upload: {len(new_videos)}")
        if total > 0:
            print(f"  Last 5 uploaded: {list(data.keys())[-5:]}")
        if len(new_videos) == 0:
            print("  -> All videos already synced, no duplicates will be uploaded")
        else:
            print(f"  -> Next to upload: {new_videos[0]['id']} (oldest new)")
        print("="*70)
        return new_videos

    def mark_uploaded(self, insta_id, yt_id, title, channel_id):
        data = self.load()
        data[insta_id] = {
            "youtube_id": yt_id,
            "title": title,
            "channel": channel_id,
            "date": datetime.datetime.now().isoformat()
        }
        with open(self.path, 'w') as f:
            json.dump(data, f, indent=2)
        valid, skipped, total = self.count_valid()
        print(f"[History] Marked {insta_id} as uploaded -> {yt_id} on {channel_id}")
        print(f"[History] History now: total={total}, valid={valid}, skipped={skipped}")

class PlaylistManager:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, 'w') as f:
                json.dump({}, f)

    def load(self):
        with open(self.path, 'r') as f:
            try:
                return json.load(f)
            except:
                return {}

    def get(self, playlist_title, channel_id):
        key = f"{channel_id}::{playlist_title}"
        data = self.load()
        pid = data.get(key)
        if pid:
            print(f"[Playlist] Found existing playlist for {channel_id}::{playlist_title}: {pid}")
        else:
            print(f"[Playlist] No existing playlist for {channel_id}::{playlist_title}, will create")
        return pid

    def save(self, playlist_title, channel_id, playlist_id):
        data = self.load()
        key = f"{channel_id}::{playlist_title}"
        data[key] = playlist_id
        with open(self.path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"[Playlist] Saved playlist {playlist_id} for {channel_id}::{playlist_title}")

class CounterManager:
    def __init__(self, path, history_manager):
        self.path = path
        self.history = history_manager
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, 'w') as f:
                json.dump({"bhavy_counter": 0}, f)
            print(f"[Counter] Created new counter file: {path}")

    def get_next(self):
        valid, skipped, total = self.history.count_valid()
        try:
            with open(self.path, 'r') as f:
                file_count = json.load(f).get('bhavy_counter', 0)
        except:
            file_count = 0
        next_num = max(file_count, valid) + 1
        print(f"[Counter] Next bhavy: bhavy{next_num} (file_counter={file_count}, history_valid={valid})")
        return next_num

    def save(self, used_number):
        with open(self.path, 'w') as f:
            json.dump({"bhavy_counter": used_number}, f, indent=2)
        print(f"[Counter] Saved counter: {used_number}")
