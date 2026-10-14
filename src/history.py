import json, os, re, datetime
class HistoryManager:
    def __init__(self, path):
        self.path = path; os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, 'w') as f: json.dump({}, f)
    def load(self):
        with open(self.path, 'r') as f:
            try: return json.load(f)
            except: return {}
    def filter_new_videos(self, all_videos):
        uploaded_ids = set(self.load().keys())
        new_videos = [v for v in all_videos if v['id'] not in uploaded_ids]
        print(f"Already uploaded: {len(uploaded_ids)} | New to upload: {len(new_videos)} | Total IG: {len(all_videos)}")
        return new_videos
    def mark_uploaded(self, insta_id, yt_id, title, token_id="TOKEN1"):
        data = self.load()
        data[insta_id] = {"youtube_id": yt_id, "title": title, "token": token_id, "date": datetime.date.today().isoformat()}
        with open(self.path, 'w') as f: json.dump(data, f, indent=2)

class PlaylistManager:
    def __init__(self, path):
        self.path = path; os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, 'w') as f: json.dump({}, f)
    def load(self):
        with open(self.path, 'r') as f:
            try: return json.load(f)
            except: return {}
    def get_playlist_id(self, title): return self.load().get(title)
    def save_playlist_id(self, title, playlist_id):
        data = self.load(); data[title] = playlist_id
        with open(self.path, 'w') as f: json.dump(data, f, indent=2)

class CounterManager:
    def __init__(self, path, history_manager):
        self.path = path; self.history = history_manager
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, 'w') as f: json.dump({"bhavy_counter": 0}, f)
    def get_next_bhavy_number(self):
        try:
            with open(self.path, 'r') as f: file_counter = json.load(f).get("bhavy_counter", 0)
        except: file_counter = 0
        max_from_history = 0
        for info in self.history.load().values():
            m = re.search(r'bhavy\s*[-_]*\s*(\d+)', info.get("title",""), re.IGNORECASE)
            if m:
                try: n = int(m.group(1)); max_from_history = max(max_from_history, n)
                except: pass
        return max(file_counter, max_from_history) + 1
    def increment_and_save(self, used_number):
        with open(self.path, 'w') as f: json.dump({"bhavy_counter": used_number}, f, indent=2)

class UsageTracker:
    def __init__(self, path):
        self.path = path; os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, 'w') as f: json.dump({}, f)
    def load(self):
        with open(self.path, 'r') as f:
            try: return json.load(f)
            except: return {}
    def record(self, token_id, success=True, is_channel_limit=False):
        data = self.load(); today = datetime.date.today().isoformat()
        if today not in data: data[today] = {}
        if token_id not in data[today]: data[today][token_id] = {"uploads_success": 0, "uploads_failed": 0, "channel_limit_hit": False}
        if success: data[today][token_id]["uploads_success"] += 1
        else:
            data[today][token_id]["uploads_failed"] += 1
            if is_channel_limit: data[today][token_id]["channel_limit_hit"] = True
        with open(self.path, 'w') as f: json.dump(data, f, indent=2)
