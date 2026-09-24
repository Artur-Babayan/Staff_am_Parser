import fcntl
import multiprocessing
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import requests

import parser


def hold_lock(lock_path, ready, release):
    with open(lock_path, "w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        ready.set()
        release.wait(timeout=10)


def response(status_code, payload=None, text=""):
    result = Mock(status_code=status_code, headers={}, text=text)
    result.json.return_value = payload if payload is not None else {}
    return result


class TelegramRetryTests(unittest.TestCase):
    job = {
        "id": 123,
        "title": "Python Developer",
        "companiesStruct": {"title": "Example"},
        "url": "https://example.test/123",
    }

    @patch("parser.time.sleep")
    @patch("parser.requests.post")
    def test_rate_limit_uses_retry_after(self, post, sleep):
        post.side_effect = [
            response(429, {"parameters": {"retry_after": 9}}),
            response(200, {"ok": True}),
        ]
        self.assertTrue(parser.send_telegram_notification(42, self.job))
        sleep.assert_called_once_with(9.0)

    @patch("parser.time.sleep")
    @patch("parser.requests.post")
    def test_server_errors_use_exponential_backoff(self, post, sleep):
        post.side_effect = [response(503), response(502), response(200, {"ok": True})]
        self.assertTrue(parser.send_telegram_notification(42, self.job))
        self.assertEqual([call.args for call in sleep.call_args_list], [(2,), (4,)])

    @patch("parser.time.sleep")
    @patch("parser.requests.post")
    def test_network_error_is_retried(self, post, sleep):
        post.side_effect = [requests.Timeout("timeout"), response(200, {"ok": True})]
        self.assertTrue(parser.send_telegram_notification(42, self.job))
        sleep.assert_called_once_with(2)

    @patch("parser.time.sleep")
    @patch("parser.requests.post")
    def test_client_error_is_not_retried(self, post, sleep):
        post.return_value = response(403, {"ok": False}, "Forbidden")
        self.assertFalse(parser.send_telegram_notification(42, self.job))
        post.assert_called_once()
        sleep.assert_not_called()


class ParserFlowTests(unittest.TestCase):
    def test_partial_failures_do_not_stop_run(self):
        jobs = [{"id": 1, "title": "One"}, {"id": 2, "title": "Two"}]
        records = {10: [
            {"id": 1, "keyword": "bad", "initialized": 1},
            {"id": 2, "keyword": "good", "initialized": 1},
        ]}

        def collect(session, build_id, key_word, sort_by):
            if key_word == "bad":
                raise RuntimeError("keyword failed")
            return jobs

        with patch("parser.db.get_all_user_ids", return_value=[10]), \
             patch("parser.db.load_all_filter_records", return_value=records), \
             patch("parser.get_build_id", return_value="build"), \
             patch("parser.collect_jobs_for_keyword", side_effect=collect), \
             patch("parser.db.get_seen_job_ids", return_value=set()), \
             patch("parser.send_telegram_notification", side_effect=[RuntimeError("send failed"), True]) as send, \
             patch("parser.db.mark_job_seen") as mark_seen, \
             patch("parser.send_fresh_menu", new=AsyncMock()), \
             patch("parser.db.cleanup_old_seen_jobs"), \
             patch("parser.requests.Session"), patch("parser.time.sleep"):
            self.assertEqual(parser.run_parser(), 0)

        self.assertEqual(send.call_count, 2)
        mark_seen.assert_called_once_with(10, 2)

    def test_systemic_failure_returns_nonzero(self):
        with patch("parser.db.get_all_user_ids", side_effect=RuntimeError("database unavailable")):
            self.assertEqual(parser.run_parser(), 1)


class ParserLockTests(unittest.TestCase):
    def test_second_process_is_skipped_and_lock_is_released(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = os.path.join(temp_dir, "parser.lock")
            ready = multiprocessing.Event()
            release = multiprocessing.Event()
            process = multiprocessing.Process(target=hold_lock, args=(lock_path, ready, release))
            process.start()
            self.assertTrue(ready.wait(timeout=5))
            try:
                with patch("parser.PARSER_LOCK_FILE", lock_path), \
                     patch("parser.run_parser", return_value=77) as run:
                    self.assertEqual(parser.main(), 0)
                    run.assert_not_called()
            finally:
                release.set()
                process.join(timeout=5)

            self.assertEqual(process.exitcode, 0)
            with patch("parser.PARSER_LOCK_FILE", lock_path), \
                 patch("parser.run_parser", return_value=77):
                self.assertEqual(parser.main(), 77)


if __name__ == "__main__":
    unittest.main()
