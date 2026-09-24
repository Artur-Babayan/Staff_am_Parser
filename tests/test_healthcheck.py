import os
import tempfile
import unittest
from unittest.mock import patch

import db
import healthcheck


class HealthcheckTests(unittest.TestCase):
    def test_healthy_configuration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = os.path.join(temp_dir, "health.db")
            with patch("db.DB_FILE", database), patch.dict(os.environ, {"TOKEN": "test"}):
                db.init_db()
                result = healthcheck.run_checks()
        self.assertTrue(result["ok"])

    def test_missing_token_is_unhealthy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = os.path.join(temp_dir, "health.db")
            with patch("db.DB_FILE", database), patch.dict(os.environ, {}, clear=True), \
                 patch("healthcheck.load_dotenv"):
                db.init_db()
                result = healthcheck.run_checks()
        self.assertFalse(result["ok"])
        self.assertFalse(result["checks"]["token_configured"])


if __name__ == "__main__":
    unittest.main()
