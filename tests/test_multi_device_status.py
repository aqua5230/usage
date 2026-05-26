import json
import os
import shutil
import tempfile
import unittest

import usage_client


class TestMultiDeviceStatus(unittest.TestCase):

    def setUp(self) -> None:
        # Create a temporary directory to act as ~/.claude
        self.temp_dir = tempfile.mkdtemp()
        self.old_status_file = usage_client.STATUS_FILE
        self.old_legacy_status_file = usage_client.LEGACY_STATUS_FILE
        self.old_tt_status_file = usage_client.TT_STATUS_FILE

        # Patch paths to point inside the temp dir
        usage_client.STATUS_FILE = os.path.join(
            self.temp_dir, "usage-status.json"
        )
        usage_client.LEGACY_STATUS_FILE = os.path.join(
            self.temp_dir, "usag-status.json"
        )
        usage_client.TT_STATUS_FILE = os.path.join(
            self.temp_dir, "tt-status.json"
        )

        # Mock os.path.expanduser to return our temp_dir when looking for ~/.claude
        self.old_expanduser = os.path.expanduser
        os.path.expanduser = lambda path: self.temp_dir if path == "~/.claude" else path  # type: ignore[assignment]

    def tearDown(self) -> None:
        # Restore paths
        usage_client.STATUS_FILE = self.old_status_file
        usage_client.LEGACY_STATUS_FILE = self.old_legacy_status_file
        usage_client.TT_STATUS_FILE = self.old_tt_status_file
        os.path.expanduser = self.old_expanduser
        shutil.rmtree(self.temp_dir)

    def test_selects_latest_by_received_ts(self) -> None:
        # Create local status file (older)
        local_data = {
            "rate_limits": {"five_hour": {"used_percentage": 20}},
            "_received_at_ts": 1000.0,
        }
        with open(usage_client.STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(local_data, f)

        # Create remote status file (newer)
        remote_path = os.path.join(self.temp_dir, "usage-status-remote.json")
        remote_data = {
            "rate_limits": {"five_hour": {"used_percentage": 50}},
            "_received_at_ts": 2000.0,
        }
        with open(remote_path, "w", encoding="utf-8") as f:
            json.dump(remote_data, f)

        result = usage_client._read_status_file()
        assert result is not None
        data, path, mtime = result
        self.assertEqual(path, remote_path)
        self.assertEqual(data["rate_limits"]["five_hour"]["used_percentage"], 50)

    def test_falls_back_to_mtime(self) -> None:
        # Create local status file (older)
        local_path = usage_client.STATUS_FILE
        local_data = {"rate_limits": {"five_hour": {"used_percentage": 30}}}
        with open(local_path, "w", encoding="utf-8") as f:
            json.dump(local_data, f)

        # Set mtime of local file to be old
        os.utime(local_path, (1000.0, 1000.0))

        # Create remote status file (newer)
        remote_path = os.path.join(self.temp_dir, "usage-status-remote.json")
        remote_data = {"rate_limits": {"five_hour": {"used_percentage": 60}}}
        with open(remote_path, "w", encoding="utf-8") as f:
            json.dump(remote_data, f)

        # Set mtime of remote file to be new
        os.utime(remote_path, (2000.0, 2000.0))

        result = usage_client._read_status_file()
        assert result is not None
        data, path, mtime = result
        self.assertEqual(path, remote_path)
        self.assertEqual(data["rate_limits"]["five_hour"]["used_percentage"], 60)

    def test_prefers_active_rate_limit_over_newer_expired_one(self) -> None:
        import time
        now = time.time()

        # Create local status file (older timestamp, but resets_at is in the future - active)
        local_path = usage_client.STATUS_FILE
        local_data = {
            "rate_limits": {
                "five_hour": {
                    "used_percentage": 30,
                    "resets_at": now + 3600
                }
            },
            "_received_at_ts": now - 100
        }
        with open(local_path, "w", encoding="utf-8") as f:
            json.dump(local_data, f)

        # Create remote status file (newer timestamp, but resets_at is in the past - expired)
        remote_path = os.path.join(self.temp_dir, "usage-status-remote.json")
        remote_data = {
            "rate_limits": {
                "five_hour": {
                    "used_percentage": 10,
                    "resets_at": now - 100
                }
            },
            "_received_at_ts": now - 10
        }
        with open(remote_path, "w", encoding="utf-8") as f:
            json.dump(remote_data, f)

        result = usage_client._read_status_file()
        assert result is not None
        data, path, mtime = result
        self.assertEqual(path, local_path)
        self.assertEqual(data["rate_limits"]["five_hour"]["used_percentage"], 30)


if __name__ == "__main__":
    unittest.main()
