import json
import os
import sqlite3

from dotenv import load_dotenv

import db


def run_checks() -> dict:
    load_dotenv()
    checks = {
        "token_configured": bool(os.getenv("TOKEN")),
        "database": False,
        "database_writable": os.access(os.path.dirname(db.DB_FILE), os.W_OK),
    }
    try:
        with db.get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        checks["database"] = {"users", "filters", "seen_jobs"}.issubset(tables)
    except sqlite3.Error:
        checks["database"] = False
    return {"ok": all(checks.values()), "checks": checks}


def main() -> int:
    result = run_checks()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
