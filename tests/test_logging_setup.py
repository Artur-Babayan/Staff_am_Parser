import logging
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import logging_setup


class LoggingSetupTests(unittest.TestCase):
    def test_privacy_filter_redacts_user_identifiers(self):
        record = logging.LogRecord(
            "test", logging.INFO, __file__, 1,
            "Failed for chat_id=%s", (123456789,), None,
        )
        logging_setup._PrivacyFilter().filter(record)
        self.assertEqual(record.getMessage(), "Failed for chat_id=<redacted>")

        record = logging.LogRecord(
            "test", logging.INFO, __file__, 1,
            "New user registered: 123456789 (@private_user)", (), None,
        )
        logging_setup._PrivacyFilter().filter(record)
        self.assertEqual(record.getMessage(), "New user registered: <redacted>")

    def test_only_expired_matching_archives_are_deleted(self):
        with tempfile.TemporaryDirectory() as archive_dir, \
             patch("logging_setup.LOG_ARCHIVE_DIR", archive_dir):
            expired = os.path.join(archive_dir, "parser_old.log.gz")
            current = os.path.join(archive_dir, "parser_current.log.gz")
            unrelated = os.path.join(archive_dir, "bot_old.log.gz")
            for path in (expired, current, unrelated):
                open(path, "wb").close()
            old_time = time.time() - (logging_setup.ARCHIVE_RETENTION_DAYS + 1) * 86400
            os.utime(expired, (old_time, old_time))
            os.utime(unrelated, (old_time, old_time))

            logging_setup._delete_expired_archives("parser")

            self.assertFalse(os.path.exists(expired))
            self.assertTrue(os.path.exists(current))
            self.assertTrue(os.path.exists(unrelated))


if __name__ == "__main__":
    unittest.main()
