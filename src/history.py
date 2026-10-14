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

    def save(self, data):
        with open(self.path, 'w') as f: json.dump(data, f, indent=2)

    def count(self):
        data=self.load()
        valid=len([v for v in data.values() if not str(v.get('youtube_id','')).startswith('SKIPPED') and not str(v.get('youtube_id','')).startswith('FAILED')])
        skipped=len([v for v in data.values() if str(v.get('youtube_id','')).startswith('SKIPPED')])
        failed=len([v for v in data.values() if str(v.get('youtube_id','')).startswith('FAILED')])
        return valid, skipped, failed, len(data)

    def is_retryable_skipped(self, entry, retry_hours=24):
        # SKIPPED_NO_MEDIA can be retried after retry_hours
        yt_id=entry.get('youtube_id','')
        if not yt_id.startswith('SKIPPED_NO_MEDIA'):
            return False
        date_str=entry.get('date')
        try:
            last_time=datetime.datetime.fromisoformat(date_str)
            now=datetime.datetime.now()
            diff=(now-last_time).total_seconds()/3600
            return diff>=retry_hours
        except:
            return True

    def filter_new(self, all_videos, retry_hours=24):
        data=self.load()
        new=[]
        retry_candidates=[]
        for v in all_videos:
            insta_id=v['id']
            if insta_id not in data:
                new.append(v)
            else:
                entry=data[insta_id]
                yt_id=entry.get('youtube_id','')
                # If SKIPPED_NO_MEDIA and old enough, allow retry
                if yt_id.startswith('SKIPPED_NO_MEDIA') and self.is_retryable_skipped(entry, retry_hours):
                    print(f"[History] Retry candidate: {insta_id} was SKIPPED_NO_MEDIA at {entry.get('date')} -> retry after {retry_hours}h, will refresh media_url")
                    retry_candidates.append(v)
                # FAILED_YOUTUBE should NOT be retried same video (your requirement)
                elif yt_id.startswith('FAILED'):
                    print(f"[History] Skipping FAILED {insta_id} (YouTube error, don't retry same video)")
                    continue
                # Valid uploaded or recent SKIPPED -> skip
                else:
                    if yt_id.startswith('SKIPPED'):
                        print(f"[History] Skipping recent SKIPPED {insta_id} (retry after {retry_hours}h)")
                    continue

        # Combine new + retry candidates, sorted by timestamp oldest first
        combined=new+retry_candidates
        combined.sort(key=lambda x: x.get('timestamp',''))

        valid, skipped, failed, total=self.count()
        print("="*70)
        print("[History] OLDEST FIRST - No YouTube API yet")
        print(f"  IG Total: {len(all_videos)} | History total: {total} (valid={valid}, skipped={skipped}, failed={failed})")
        print(f"  New (never tried): {len(new)}")
        print(f"  Retryable SKIPPED_NO_MEDIA (expired, will refresh media_url): {len(retry_candidates)}")
        print(f"  Combined to check (oldest first): {len(combined)}")
        if combined:
            print(f"  Oldest to try: {combined[0]['id']} @ {combined[0].get('timestamp')}")
            print(f"  Newest in list: {combined[-1]['id']} @ {combined[-1].get('timestamp')}")
        print("="*70)
        return combined

    def mark(self, insta_id, yt_id, title, channel_id):
        data=self.load()
        data[insta_id]={"youtube_id":yt_id,"title":title,"channel":channel_id,"date":datetime.datetime.now().isoformat()}
        self.save(data)
        print(f"[History] Marked {insta_id} -> {yt_id} ({title})")

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
    def get_next(self, youtube_titles=None):
        valid,_,_,_=self.history.count()
        try:
            with open(self.path,'r') as f: file_c=json.load(f).get("bhavy_counter",0)
        except: file_c=0
        max_yt=0
        if youtube_titles:
            import re
            for t in youtube_titles:
                m=re.search(r'bhavy(\d+)', str(t).lower())
                if m:
                    try: max_yt=max(max_yt, int(m.group(1)))
                    except: pass
        nxt=max(file_c, valid, max_yt)+1
        print(f"[Counter] Next bhavy: bhavy{nxt} (file={file_c}, history_valid={valid}, youtube_max={max_yt})")
        return nxt
    def save(self, n):
        with open(self.path,'w') as f: json.dump({"bhavy_counter":n}, f, indent=2)
