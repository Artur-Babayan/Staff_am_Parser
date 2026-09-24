"""
Shared logging setup used by both parser.py and bot.py.

Rotation behavior:
    - The active log file (e.g. parser.log) grows normally.
    - Once it reaches MAX_LOG_SIZE_BYTES (10 MB by default), logging's
      RotatingFileHandler renames it and starts a fresh empty file.
    - We hook into that rotation (via a custom namer + rotator) so the
      rotated-out file is moved into a LogArchive/ subfolder and gzip
      compressed, instead of sitting next to the active log as a plain
      .log.1, .log.2, etc.

Result: parser.log stays small and current; old data lives compressed
in LogArchive/parser_20260723_153000.log.gz style filenames.
"""

import os
import re
import gzip
import shutil
import logging
import logging.handlers
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_ARCHIVE_DIR = os.path.join(BASE_DIR, "LogArchive")

MAX_LOG_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
# Must be >= 1: Python's RotatingFileHandler only rotates at all when
# backupCount > 0 (see logging.handlers source). We still don't accumulate
# numbered .log.1/.log.2 files because our custom namer/rotator below
# intercepts every rotation and moves the file into LogArchive/ as .gz
# instead of leaving it next to the active log.
BACKUP_COUNT = 1
ARCHIVE_RETENTION_DAYS = 30


class _PrivacyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        message = re.sub(r"chat_id=-?\d+", "chat_id=<redacted>", message)
        message = re.sub(
            r"New user registered: -?\d+ \(@[^)]*\)",
            "New user registered: <redacted>",
            message,
        )
        record.msg = message
        record.args = ()
        return True


def _delete_expired_archives(log_basename: str) -> None:
    if not os.path.isdir(LOG_ARCHIVE_DIR):
        return
    cutoff = datetime.now().timestamp() - timedelta(days=ARCHIVE_RETENTION_DAYS).total_seconds()
    prefix = f"{log_basename}_"
    for filename in os.listdir(LOG_ARCHIVE_DIR):
        if not filename.startswith(prefix) or not filename.endswith(".log.gz"):
            continue
        path = os.path.join(LOG_ARCHIVE_DIR, filename)
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except FileNotFoundError:
            pass


def _gzip_and_archive_rotator(source: str, dest: str):
    """
    Called by RotatingFileHandler instead of its default os.rename.
    Compresses `source` into a .gz file inside LogArchive/ and removes
    the uncompressed temporary file RotatingFileHandler created.
    """
    os.makedirs(LOG_ARCHIVE_DIR, exist_ok=True)

    archive_name = os.path.basename(dest) + ".gz"
    archive_path = os.path.join(LOG_ARCHIVE_DIR, archive_name)

    with open(source, "rb") as f_in, gzip.open(archive_path, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    os.remove(source)
    _delete_expired_archives(os.path.splitext(os.path.basename(source))[0])


def _archive_namer(default_name: str) -> str:
    """
    Called by RotatingFileHandler to decide the rotated file's name before
    the rotator runs. default_name is normally something like
    'parser.log.1' - we replace it with a timestamped name so multiple
    rotations don't collide and archives sort naturally by date.
    """
    base_log_name = default_name.rsplit(".", 1)[0]  # strip the '.1' suffix
    log_basename = os.path.splitext(os.path.basename(base_log_name))[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return os.path.join(os.path.dirname(base_log_name), f"{log_basename}_{timestamp}.log")


def get_logger(name: str, log_filename: str) -> logging.Logger:
    """
    Returns a configured logger that:
      - writes to `log_filename` in BASE_DIR
      - also prints to stdout
      - rotates + gzip-archives into LogArchive/ once the file hits 10 MB
    Safe to call multiple times (won't duplicate handlers).
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    log_path = os.path.join(BASE_DIR, log_filename)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=MAX_LOG_SIZE_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.namer = _archive_namer
    file_handler.rotator = _gzip_and_archive_rotator
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_PrivacyFilter())
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(_PrivacyFilter())
    logger.addHandler(stream_handler)

    return logger