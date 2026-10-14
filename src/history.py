import json, os, re, datetime

class HistoryManager:
    """Prevents duplicate uploads - tracks every Instagram ID ever uploaded"""
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

    def is_uploaded(self, insta_id):
        return insta_id in self.load()

    def filter_new_videos(self, all_videos):
        uploaded = self.load()
        uploaded_ids = set(uploaded.keys())
        new_videos = [v for v in all_videos if v['id'] not in uploaded_ids]
        print(f"[History] Total IG: {len(all_videos)} | Already uploaded: {len(uploaded_ids)} | New: {len(new_videos)}")
        if uploaded_ids and len(new_videos) == 0:
            print("[History] All videos already synced - no duplicates will be uploaded")
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
        print(f"[History] Marked {insta_id} as uploaded -> {yt_id} on {channel_id}")

class PlaylistManager:
    """One playlist per channel - no duplicates"""
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
        return self.load().get(key)

    def save(self, playlist_title, channel_id, playlist_id):
        data = self.load()
        key = f"{channel_id}::{playlist_title}"
        data[key] = playlist_id
        with open(self.path, 'w') as f:
            json.dump(data, f, indent=2)

class CounterManager:
    """bhavy number counter - no repeats"""
    def __init__(self, path, history_manager):
        self.path = path
        self.history = history_manager
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, 'w') as f:
                json.dump({"bhavy_counter": 0}, f)

    def get_next(self):
        hist = self.history.load()
        # Count only valid uploads (not SKIPPED)
        valid_count = len([v for v in hist.values() if not str(v.get('youtube_id','')).startswith('SKIPPED')])
        try:
            with open(self.path, 'r') as f:
                file_count = json.load(f).get('bhavy_counter', 0)
        except:
            file_count = 0
        next_num = max(file_count, valid_count) + 1
        print(f"[Counter] Next bhavy number: bhavy{next_num} (file={file_count}, history_valid={valid_count})")
        return next_num

    def save(self, used_number):
        with open(self.path, 'w') as f:
            json.dump({"bhavy_counter": used_number}, f, indent=2)
