import json, os, re

class HistoryManager:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, 'w') as f: json.dump({}, f)

    def load(self):
        with open(self.path, 'r') as f:
            try: return json.load(f)
            except: return {}

    def is_uploaded(self, insta_id):
        return insta_id in self.load()

    def mark_uploaded(self, insta_id, yt_id, title):
        data = self.load()
        data[insta_id] = {"youtube_id": yt_id, "title": title}
        with open(self.path, 'w') as f:
            json.dump(data, f, indent=2)

class PlaylistManager:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, 'w') as f: json.dump({}, f)
    
    def load(self):
        with open(self.path, 'r') as f:
            try: return json.load(f)
            except: return {}

    def get_playlist_id(self, title):
        return self.load().get(title)

    def save_playlist_id(self, title, playlist_id):
        data = self.load()
        data[title] = playlist_id
        with open(self.path, 'w') as f:
            json.dump(data, f, indent=2)

class CounterManager:
    def __init__(self, path, history_manager):
        self.path = path
        self.history = history_manager
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, 'w') as f: json.dump({"bhavy_counter": 0}, f)

    def get_next_bhavy_number(self):
        try:
            with open(self.path, 'r') as f:
                data = json.load(f)
                file_counter = data.get("bhavy_counter", 0)
        except:
            file_counter = 0

        max_from_history = 0
        history_data = self.history.load()
        for info in history_data.values():
            title = info.get("title", "")
            m = re.search(r'bhavy\s*[-_]*\s*(\d+)', title, re.IGNORECASE)
            if m:
                try:
                    n = int(m.group(1))
                    if n > max_from_history:
                        max_from_history = n
                except: pass

        next_num = max(file_counter, max_from_history) + 1
        return next_num

    def increment_and_save(self, used_number):
        with open(self.path, 'w') as f:
            json.dump({"bhavy_counter": used_number}, f, indent=2)
