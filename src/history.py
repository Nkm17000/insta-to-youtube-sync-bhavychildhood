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
        data=self.load()
        valid=len([v for v in data.values() if not str(v.get('youtube_id','')).startswith('SKIPPED')])
        skipped=len(data)-valid
        return valid, skipped, len(data)

    def is_uploaded(self, insta_id):
        return insta_id in self.load()

    def filter_new(self, all_videos):
        data=self.load()
        uploaded=set(data.keys())
        new=[v for v in all_videos if v['id'] not in uploaded]
        valid, skipped, total=self.count()
        print(f"[History] Total IG: {len(all_videos)} | History total: {total} (valid={valid}, skipped={skipped}) | New: {len(new_videos) if 'new_videos' in locals() else len(new)}")
        # Actually need new_videos variable
        print(f"[History] New videos not in history: {len(new)}")
        if total>0:
            print(f"[History] Last 5: {list(data.keys())[-5:]}")
        return new

    def mark(self, insta_id, yt_id, title, channel_id):
        data=self.load()
        data[insta_id]={"youtube_id":yt_id,"title":title,"channel":channel_id,"date":datetime.datetime.now().isoformat()}
        with open(self.path, 'w') as f: json.dump(data, f, indent=2)
        print(f"[History] Marked {insta_id} -> {yt_id} ({title}) on {channel_id}")

class PlaylistManager:
    def __init__(self, path):
        self.path=path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, 'w') as f: json.dump({}, f)
    def load(self):
        try:
            with open(self.path,'r') as f: return json.load(f)
        except: return {}
    def get(self, title, channel_id):
        return self.load().get(f"{channel_id}::{title}")
    def save(self, title, channel_id, pid):
        data=self.load()
        data[f"{channel_id}::{title}"]=pid
        with open(self.path,'w') as f: json.dump(data,f,indent=2)

class CounterManager:
    def __init__(self, path, history):
        self.path=path
        self.history=history
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path,'w') as f: json.dump({"bhavy_counter":0}, f)
    def get_next(self, youtube_existing_titles=None):
        valid,_,_=self.history.count()
        try:
            with open(self.path,'r') as f: file_c=json.load(f).get("bhavy_counter",0)
        except: file_c=0

        # Also check YouTube existing bhavy numbers to avoid duplicate bhavy2
        max_youtube_bhavy=0
        if youtube_existing_titles:
            import re
            for t in youtube_existing_titles:
                m=re.search(r'bhavy(\d+)', str(t).lower())
                if m:
                    try:
                        num=int(m.group(1))
                        max_youtube_bhavy=max(max_youtube_bhavy, num)
                    except: pass

        nxt=max(file_c, valid, max_youtube_bhavy)+1
        print(f"[Counter] Next bhavy: bhavy{nxt} (file={file_c}, history_valid={valid}, youtube_max_bhavy={max_youtube_bhavy})")
        return nxt
    def save(self, n):
        with open(self.path,'w') as f: json.dump({"bhavy_counter":n}, f, indent=2)
        print(f"[Counter] Saved {n}")
