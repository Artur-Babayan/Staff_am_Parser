import os
import re
import time
import json
import asyncio
import logging
import requests
from dotenv import load_dotenv
from telegram import Bot

from filters_store import load_filters
from keyboards import main_menu_keyboard

load_dotenv()

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

HOME_PAGE_URL = "https://staff.am/am/jobs"
DATA_ENDPOINT_TEMPLATE = "https://staff.am/_next/data/{build_id}/am/jobs.json"
JOB_URL_TEMPLATE = "https://staff.am/{lang}/job/{slug}"
TELEGRAM_SEND_PHOTO_URL = "https://api.telegram.org/bot{token}/sendPhoto"
TELEGRAM_SEND_MESSAGE_URL = "https://api.telegram.org/bot{token}/sendMessage"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEEN_JOBS_FILE = os.path.join(BASE_DIR, "seen_jobs.json")
LOG_FILE = os.path.join(BASE_DIR, "parser.log")

URL_LANG = "ru"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = False

if not logger.handlers:
    _formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    _file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    _file_handler.setFormatter(_formatter)
    logger.addHandler(_file_handler)

    _stream_handler = logging.StreamHandler()
    _stream_handler.setFormatter(_formatter)
    logger.addHandler(_stream_handler)


def get_build_id(session: requests.Session) -> str:
    resp = session.get(HOME_PAGE_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    match = re.search(r'"buildId":"([^"]+)"', resp.text)
    if not match:
        raise RuntimeError(
            "Could not find buildId on the page. The site may have changed its structure."
        )
    return match.group(1)


def fetch_jobs(session: requests.Session, build_id: str, key_word: str, sort_by: int = 2, page: int = 1):
    url = DATA_ENDPOINT_TEMPLATE.format(build_id=build_id)
    params = {"key_word": key_word, "sort_by": sort_by}
    if page and page > 1:
        params["page"] = page

    request_headers = dict(HEADERS)
    request_headers["x-nextjs-data"] = "1"
    request_headers["Referer"] = f"https://staff.am/am/jobs?key_word={key_word}&sort_by={sort_by}"

    resp = session.get(url, headers=request_headers, params=params, timeout=15)
    logger.info(f"[{key_word} / page {page}] status: {resp.status_code}")

    if resp.status_code == 404:
        raise RuntimeError("404 - build_id is likely stale. Will refetch on next run.")

    resp.raise_for_status()

    if not resp.text.strip():
        raise ValueError("Server returned an empty response body.")

    return resp.json()


def build_job_url(job: dict, lang: str = URL_LANG) -> str:
    slug = job.get("slug")
    if isinstance(slug, dict):
        slug_val = slug.get(lang) or slug.get("en") or slug.get("am")
    else:
        slug_val = slug

    if not slug_val:
        return ""
    return JOB_URL_TEMPLATE.format(lang=lang, slug=slug_val)


def collect_jobs_for_keyword(session: requests.Session, build_id: str, key_word: str, sort_by: int = 2, max_pages: int = 20, delay: float = 0.5):
    keyword_jobs = []
    page = 1
    seen_ids = set()

    logger.info(f"--- Collecting jobs for keyword: {key_word} ---")

    while page <= max_pages:
        data = fetch_jobs(session, build_id, key_word=key_word, sort_by=sort_by, page=page)
        payload = data.get("pageProps", data) if isinstance(data, dict) else data
        jobs = payload.get("jobs") if isinstance(payload, dict) else None

        if jobs is None:
            logger.warning(f"Could not find job list for '{key_word}'.")
            break
        if not jobs:
            logger.info(f"Empty page - no more jobs for '{key_word}'.")
            break

        new_jobs = [j for j in jobs if j.get("id") not in seen_ids]
        if not new_jobs:
            logger.info(f"No new jobs on this page - end of list for '{key_word}'.")
            break

        for j in new_jobs:
            j["url"] = build_job_url(j)
            seen_ids.add(j.get("id"))

        keyword_jobs.extend(new_jobs)
        logger.info(f"Page {page}: fetched {len(new_jobs)} new jobs (total for '{key_word}': {len(keyword_jobs)})")

        page += 1
        time.sleep(delay)

    return keyword_jobs


def collect_all_jobs(session: requests.Session, build_id: str, key_words: list, sort_by: int = 2):
    all_jobs = []
    seen_ids = set()

    for key_word in key_words:
        jobs_for_keyword = collect_jobs_for_keyword(session, build_id, key_word=key_word, sort_by=sort_by)

        new_jobs = [j for j in jobs_for_keyword if j.get("id") not in seen_ids]
        for j in new_jobs:
            seen_ids.add(j.get("id"))
        all_jobs.extend(new_jobs)

        logger.info(f"=== Total for '{key_word}': {len(jobs_for_keyword)} jobs ({len(new_jobs)} new for combined list) ===")

    return all_jobs


def load_seen_ids() -> set:
    if not os.path.exists(SEEN_JOBS_FILE):
        return set()
    try:
        with open(SEEN_JOBS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data) if isinstance(data, list) else set()
    except (json.JSONDecodeError, ValueError):
        return set()


def save_seen_ids(ids: set):
    with open(SEEN_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(ids), f, ensure_ascii=False, indent=2)


def get_job_title(job: dict, lang: str = URL_LANG) -> str:
    title = job.get("title")
    if isinstance(title, dict):
        result = title.get(lang) or title.get("en") or title.get("am")
        if result:
            return result
    elif title:
        return title

    logger.debug(f"Could not resolve title for job id={job.get('id')}. Title value: {title!r}")
    return "No title"


def get_company_title(job: dict, lang: str = URL_LANG) -> str:
    company = job.get("companiesStruct") or {}
    title = company.get("title")
    if isinstance(title, dict):
        result = title.get(lang) or title.get("en") or title.get("am")
        if result:
            return result
    elif title:
        return title

    logger.debug(f"Could not resolve company for job id={job.get('id')}. companiesStruct: {company!r}")
    return "Company not specified"


def get_profile_image(job: dict) -> str:
    company = job.get("companiesStruct") or {}
    return company.get("profile_image") or ""


def send_telegram_notification(job: dict):
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("TOKEN or CHAT_ID not found in .env file.")

    title = get_job_title(job)
    company = get_company_title(job)
    image_url = get_profile_image(job)
    url = job.get("url", "")

    caption = f"{title}\n{company}\n{url}"

    if image_url:
        resp = requests.post(
            TELEGRAM_SEND_PHOTO_URL.format(token=TOKEN),
            data={"chat_id": CHAT_ID, "photo": image_url, "caption": caption},
            timeout=15,
        )
    else:
        resp = requests.post(
            TELEGRAM_SEND_MESSAGE_URL.format(token=TOKEN),
            data={"chat_id": CHAT_ID, "text": caption},
            timeout=15,
        )

    if resp.status_code != 200:
        logger.error(f"Failed to send Telegram notification for job {job.get('id')}: {resp.status_code} {resp.text}")
    else:
        logger.info(f"Sent to Telegram: {title} ({company})")


async def send_fresh_menu():
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("TOKEN or CHAT_ID not found in .env file.")

    bot = Bot(token=TOKEN)
    await bot.send_message(
        chat_id=CHAT_ID,
        text="Menu:",
        reply_markup=main_menu_keyboard(),
    )


def main():
    logger.info("=" * 60)
    logger.info("Parser run started")

    key_words = load_filters()
    if not key_words:
        logger.warning("Filter list is empty (filters.json). Nothing to parse, exiting.")
        return

    logger.info(f"Current filters: {key_words}")

    session = requests.Session()

    logger.info("Fetching current build_id...")
    build_id = get_build_id(session)
    logger.info(f"build_id: {build_id}")

    jobs = collect_all_jobs(session, build_id, key_words=key_words, sort_by=2)

    seen_ids = load_seen_ids()
    new_jobs = [j for j in jobs if j.get("id") not in seen_ids]

    logger.info(f"Total jobs found: {len(jobs)}. New (not yet sent): {len(new_jobs)}.")

    for job in new_jobs:
        send_telegram_notification(job)
        seen_ids.add(job.get("id"))
        time.sleep(1)

    save_seen_ids(seen_ids)

    if new_jobs:
        asyncio.run(send_fresh_menu())

    logger.info("Parser run finished")


if __name__ == "__main__":
    main()