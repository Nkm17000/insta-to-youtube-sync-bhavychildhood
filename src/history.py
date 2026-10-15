import datetime as dt
import json
import os
import tempfile
import threading

_LOCK = threading.Lock()

class HistoryManager:
    """One file per channel; one channel's result never changes another's history."""
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            self.save({})

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, data):
        directory = os.path.dirname(self.path) or "."
        fd, temp = tempfile.mkstemp(prefix=".history-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.remove(temp)

    def status(self, media_id):
        return self.load().get(media_id, {})

    def eligible(self, video, retry_hours=24):
        entry = self.status(video["id"])
        if not entry:
            return True
        status = entry.get("status", "")
        if status == "SKIPPED_NO_MEDIA":
            try:
                stamp = dt.datetime.fromisoformat(entry["updated_at"])
                if stamp.tzinfo:
                    now = dt.datetime.now(dt.timezone.utc)
                else:
                    now = dt.datetime.now()
                return (now - stamp).total_seconds() >= retry_hours * 3600
            except (KeyError, ValueError, TypeError):
                return True
        # Success, duplicate, and upload failures are terminal unless manually reset.
        return False

    def mark(self, media_id, status, title="", youtube_id="", error=""):
        with _LOCK:
            data = self.load()
            data[media_id] = {
                "status": status,
                "title": title,
                "youtube_id": youtube_id,
                "error": str(error)[:1000],
                "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            self.save(data)

    def summary(self):
        data = self.load()
        counts = {}
        for item in data.values():
            status = item.get("status", "UNKNOWN")
            counts[status] = counts.get(status, 0) + 1
        return counts
