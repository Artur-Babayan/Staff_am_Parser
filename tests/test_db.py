import os
import tempfile
import unittest
from unittest.mock import patch

import db


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        self.db_patch = patch("db.DB_FILE", self.db_path)
        self.db_patch.start()
        db.init_db()
        db.ensure_user(1)
        db.ensure_user(2)

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_database_configuration_and_cleanup_index(self):
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], 10000)
            indexes = {row[1] for row in conn.execute("PRAGMA index_list(seen_jobs)")}
        self.assertIn("idx_seen_jobs_seen_at", indexes)

    def test_filter_validation_duplicate_and_limit(self):
        self.assertEqual(db.add_filter(1, "   ")[0], "empty")
        self.assertEqual(db.add_filter(1, "x" * 51)[0], "too_long")
        self.assertEqual(db.add_filter(1, " Python ")[0], "added")
        self.assertEqual(db.add_filter(1, "python")[0], "duplicate")
        for number in range(2, db.MAX_FILTERS_PER_USER + 1):
            self.assertEqual(db.add_filter(1, f"filter-{number}")[0], "added")
        self.assertEqual(db.add_filter(1, "one-too-many")[0], "limit")

    def test_baseline_and_owner_safe_removal(self):
        db.add_filter(1, "Python")
        record = db.load_filter_records(1)[0]
        self.assertEqual(record["initialized"], 0)
        self.assertTrue(db.initialize_filter(1, record["id"], [10, 11, None]))
        self.assertEqual(db.get_seen_job_ids(1, [10, 11, 12]), {10, 11})
        self.assertFalse(db.remove_filter_by_id(2, record["id"])[0])
        self.assertTrue(db.remove_filter_by_id(1, record["id"])[0])

    def test_seen_jobs_are_loaded_in_large_batches(self):
        now = db._now()
        with db.get_connection() as conn:
            conn.executemany(
                "INSERT INTO seen_jobs (chat_id, job_id, seen_at) VALUES (?, ?, ?)",
                [(1, job_id, now) for job_id in range(1, 1801)],
            )
        requested = list(range(1, 2001)) + [1, None]
        self.assertEqual(db.get_seen_job_ids(1, requested), set(range(1, 1801)))

    def test_transaction_rolls_back_on_exception(self):
        with self.assertRaises(RuntimeError):
            with db.get_connection() as conn:
                conn.execute("INSERT INTO users (chat_id, created_at) VALUES (99, 'now')")
                raise RuntimeError("force rollback")
        self.assertIsNone(db.get_user_info(99))


if __name__ == "__main__":
    unittest.main()
