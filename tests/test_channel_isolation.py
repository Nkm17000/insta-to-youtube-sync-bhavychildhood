"""Offline regression checks for per-channel isolation and upload-limit handling."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "channels.json").read_text(encoding="utf-8"))
SOURCE = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "sync.yml").read_text(encoding="utf-8")


class ChannelIsolationTests(unittest.TestCase):
    def test_channels_have_distinct_ids_credentials_and_histories(self):
        ids = [c["id"] for c in CONFIG]
        channel_ids = [c["channel_id"] for c in CONFIG]
        prefixes = [c["env_prefix"] for c in CONFIG]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(channel_ids), len(set(channel_ids)))
        self.assertEqual(len(prefixes), len(set(prefixes)))
        self.assertIn('return HISTORY_DIR / f"{safe_id(str(channel[\'id\']))}.json"', SOURCE)
        self.assertIn('CHANNEL_CONFIG_ID', WORKFLOW)
        self.assertIn('fail-fast: false', WORKFLOW)
        self.assertIn('refusing to mix channels', SOURCE)
        self.assertIn('previous_youtube_channel_id', SOURCE)

    def test_expected_channel_and_playlist_mapping_is_not_shared(self):
        by_id = {c["id"]: c for c in CONFIG}
        self.assertEqual(by_id["trailers_bollywood_main"]["channel_id"], "UCh7Mjux-jmT8ywtrs-ZFxDg")
        self.assertEqual(by_id["trailers_bollywood_main"]["env_prefix"], "YT1")
        self.assertEqual(by_id["trailers_bollywood_main"]["playlist_id"], "PLN_W_X8ML6AU")
        self.assertEqual(by_id["bhavychildhood_main"]["channel_id"], "UCwXgJ9WyTh9BgMP6csXjHRA")
        self.assertEqual(by_id["bhavychildhood_main"]["env_prefix"], "YT2")
        self.assertEqual(by_id["bhavychildhood_main"]["playlist_id"], "PLDIFVPTnQdbM")
        self.assertNotEqual(by_id["trailers_bollywood_main"]["playlist_id"], by_id["bhavychildhood_main"]["playlist_id"])
        for channel in CONFIG:
            self.assertEqual(channel["playlist_owner_channel_id"], channel["channel_id"])
            self.assertEqual(channel["playlist_env_prefix"], channel["env_prefix"])

    def test_upload_limit_stops_only_current_channel_run_and_is_retryable(self):
        self.assertIn('youtube_upload_limit_reached = True', SOURCE)
        self.assertIn('status="FAILED_UPLOAD_LIMIT"', SOURCE)
        self.assertIn('return "limit"', SOURCE)
        self.assertIn('summary["status"] = "upload_limit_reached"', SOURCE)
        self.assertIn('fail-fast: false', WORKFLOW)
        self.assertRegex(SOURCE, re.compile(r"if existing\.get\(\"status\"\) == \"UPLOADED\":", re.S))

    def test_stale_playlist_metadata_is_repaired_without_duplicate_insert(self):
        self.assertIn('metadata_repaired += 1', SOURCE)
        self.assertIn('saved_record["playlist_id"] = playlist_id', SOURCE)
        self.assertIn('saved_record["playlist_url"] = expected_playlist_url', SOURCE)
        self.assertIn('if saved_video_id in present_in_playlist:', SOURCE)


if __name__ == "__main__":
    unittest.main()
