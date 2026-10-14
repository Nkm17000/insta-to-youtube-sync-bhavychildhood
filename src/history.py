import json, os, datetime

class HistoryManager:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, 'w') as f: json.dump({}, f)

    def load(self):
        try:
            with open(self.path, 'r') as f: return json.load(f)
        except: return {}

    def count(self):
        data = self.load()
        valid = len([v for v in data.values() if not str(v.get('youtube_id','')).startswith('SKIPPED')])
        skipped = len(data) - valid
        return valid, skipped, len(data)

    def filter_new(self, all_videos):
        data = self.load()
        uploaded_ids = set(data.keys())
        new_videos = [v for v in all_videos if v['id'] not in uploaded_ids]
        valid, skipped, total = self.count()
        print("="*70)
        print("[History] CHECKING DUPLICATES - No YouTube API called yet")
        print(f"  Total Instagram: {len(all_videos)}")
        print(f"  History total: {total} (valid={valid}, skipped={skipped})")
        print(f"  Already uploaded IDs: {len(uploaded_ids)}")
        print(f"  New (not in history): {len(new_videos)}")
        if total>0:
            print(f"  Last uploaded IDs: {list(data.keys())[-5:]}")
        print("="*70)
        return new_videos

    def mark(self, insta_id, yt_id, title, channel_id):
        data = self.load()
        data[insta_id] = {"youtube_id": yt_id, "title": title, "channel": channel_id, "date": datetime.datetime.now().isoformat()}
        with open(self.path, 'w') as f: json.dump(data, f, indent=2)
        print(f"[History] Marked {insta_id} -> {yt_id} on {channel_id}")

class PlaylistManager:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, 'w') as f: json.dump({}, f)
    def load(self):
        try:
            with open(self.path, 'r') as f: return json.load(f)
        except: return {}
    def get(self, title, channel_id):
        return self.load().get(f"{channel_id}::{title}")
    def save(self, title, channel_id, pid):
        data = self.load()
        data[f"{channel_id}::{title}"] = pid
        with open(self.path, 'w') as f: json.dump(data, f, indent=2)

class CounterManager:
    def __init__(self, path, history):
        self.path = path
        self.history = history
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, 'w') as f: json.dump({"bhavy_counter": 0}, f)
    def get_next(self):
        valid, _, _ = self.history.count()
        try:
            with open(self.path, 'r') as f: file_c = json.load(f).get("bhavy_counter", 0)
        except: file_c = 0
        nxt = max(file_c, valid) + 1
        print(f"[Counter] Next bhavy: bhavy{nxt} (file={file_c}, history_valid={valid})")
        return nxt
    def save(self, n):
        with open(self.path, 'w') as f: json.dump({"bhavy_counter": n}, f, indent=2)
