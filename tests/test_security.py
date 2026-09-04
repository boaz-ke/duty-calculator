import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app import db


def _expire_lockout(db_path: Path, ip: str) -> None:
    past = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
    with db.connect(db_path) as conn:
        conn.execute(
            "UPDATE login_attempts SET locked_until = ? WHERE ip = ?", (past, ip)
        )


class LoginLockoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vdc-security-"))
        self.db_path = self.tmp / "test.sqlite3"
        db.init_db(self.db_path)

    def test_three_failures_trigger_30_minute_lockout(self):
        self.assertIsNone(db.login_lockout_remaining(self.db_path, "10.0.0.1"))
        for _ in range(2):
            outcome = db.record_failed_login(self.db_path, "10.0.0.1")
            self.assertFalse(outcome["triggered"])
            self.assertIsNone(outcome["lockout_seconds"])

        outcome = db.record_failed_login(self.db_path, "10.0.0.1")
        self.assertTrue(outcome["triggered"])
        self.assertEqual(outcome["lockout_seconds"], 30 * 60)
        remaining = db.login_lockout_remaining(self.db_path, "10.0.0.1")
        self.assertIsNotNone(remaining)
        self.assertLessEqual(remaining, 30 * 60)
        self.assertGreater(remaining, 29 * 60)

    def test_lockout_escalates_per_ip(self):
        ip = "10.0.0.2"
        for _ in range(3):
            db.record_failed_login(self.db_path, ip)
        remaining = db.login_lockout_remaining(self.db_path, ip)
        self.assertIsNotNone(remaining)
        self.assertLessEqual(remaining, 30 * 60)
        self.assertGreater(remaining, 29 * 60)

        _expire_lockout(self.db_path, ip)
        for _ in range(2):
            outcome = db.record_failed_login(self.db_path, ip)
            self.assertFalse(outcome["triggered"])
        outcome = db.record_failed_login(self.db_path, ip)
        self.assertTrue(outcome["triggered"])
        self.assertEqual(outcome["lockout_seconds"], 24 * 60 * 60)

        _expire_lockout(self.db_path, ip)
        for _ in range(2):
            outcome = db.record_failed_login(self.db_path, ip)
            self.assertFalse(outcome["triggered"])
        outcome = db.record_failed_login(self.db_path, ip)
        self.assertTrue(outcome["triggered"])
        self.assertEqual(outcome["lockout_seconds"], 7 * 24 * 60 * 60)

    def test_successful_sign_in_resets_the_failure_window(self):
        ip = "10.0.0.3"
        for _ in range(2):
            db.record_failed_login(self.db_path, ip)
        db.clear_login_attempts(self.db_path, ip)

        for _ in range(2):
            outcome = db.record_failed_login(self.db_path, ip)
            self.assertFalse(outcome["triggered"])
        outcome = db.record_failed_login(self.db_path, ip)
        self.assertTrue(outcome["triggered"])
        self.assertEqual(outcome["lockout_seconds"], 30 * 60)


if __name__ == "__main__":
    unittest.main()
