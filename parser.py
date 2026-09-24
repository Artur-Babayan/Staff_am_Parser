import os
import re
import sys
import time
import asyncio
import requests
from dotenv import load_dotenv
from telegram import Bot

import db
from keyboards import main_menu_keyboard
from logging_setup import get_logger

load_dotenv()

TOKEN = os.getenv("TOKEN")

HOME_PAGE_URL = "https://staff.am/am/jobs"
DATA_ENDPOINT_TEMPLATE = "https://staff.am/_next/data/{build_id}/am/jobs.json"
JOB_URL_TEMPLATE = "https://staff.am/{lang}/job/{slug}"
TELEGRAM_SEND_PHOTO_URL = "https://api.telegram.org/bot{token}/sendPhoto"
TELEGRAM_SEND_MESSAGE_URL = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_MAX_ATTEMPTS = 4
TELEGRAM_BACKOFF_SECONDS = 2

URL_LANG = "am"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

logger = get_logger(__name__, "parser.log")


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
    seen_ids_this_run = set()

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

        valid_jobs = []
        for j in jobs:
            job_id = j.get("id")
            if job_id is None:
                logger.warning(f"Skipping a job with no id for keyword '{key_word}': {j.get('title')!r}")
                continue
            valid_jobs.append(j)

        new_jobs = [j for j in valid_jobs if j.get("id") not in seen_ids_this_run]
        if not new_jobs:
            logger.info(f"No new jobs on this page - end of list for '{key_word}'.")
            break

        for j in new_jobs:
            j["url"] = build_job_url(j)
            seen_ids_this_run.add(j.get("id"))

        keyword_jobs.extend(new_jobs)
        logger.info(f"Page {page}: fetched {len(new_jobs)} jobs (total for '{key_word}': {len(keyword_jobs)})")

        page += 1
        time.sleep(delay)

    return keyword_jobs


def get_job_title(job: dict, lang: str = URL_LANG) -> str:
    title = job.get("title")
    if isinstance(title, dict):
        result = title.get(lang) or title.get("en") or title.get("am")
        if result:
            return result
    elif title:
        return title
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
    return "Company not specified"


def get_profile_image(job: dict) -> str:
    company = job.get("companiesStruct") or {}
    return company.get("profile_image") or ""


def _telegram_retry_delay(resp: requests.Response, attempt: int) -> float:
    try:
        retry_after = resp.json().get("parameters", {}).get("retry_after")
        if retry_after is not None:
            return max(float(retry_after), 0)
    except (ValueError, TypeError, AttributeError):
        pass

    retry_after_header = resp.headers.get("Retry-After")
    if retry_after_header is not None:
        try:
            return max(float(retry_after_header), 0)
        except ValueError:
            pass
    return TELEGRAM_BACKOFF_SECONDS * (2 ** (attempt - 1))


def send_telegram_notification(chat_id: int, job: dict):
    if not TOKEN:
        raise RuntimeError("TOKEN not found in .env file.")

    title = get_job_title(job)
    company = get_company_title(job)
    image_url = get_profile_image(job)
    url = job.get("url", "")
    caption = f"{title}\n{company}\n{url}"

    if image_url:
        endpoint = TELEGRAM_SEND_PHOTO_URL
        data = {"chat_id": chat_id, "photo": image_url, "caption": caption}
    else:
        endpoint = TELEGRAM_SEND_MESSAGE_URL
        data = {"chat_id": chat_id, "text": caption}

    for attempt in range(1, TELEGRAM_MAX_ATTEMPTS + 1):
        try:
            resp = requests.post(endpoint.format(token=TOKEN), data=data, timeout=15)
        except requests.RequestException as exc:
            if attempt == TELEGRAM_MAX_ATTEMPTS:
                logger.error("Telegram request failed after %s attempts for job=%s: %s", attempt, job.get("id"), exc)
                return False
            delay = TELEGRAM_BACKOFF_SECONDS * (2 ** (attempt - 1))
            logger.warning("Telegram network error for job=%s; retrying in %.1fs (%s/%s)", job.get("id"), delay, attempt, TELEGRAM_MAX_ATTEMPTS)
            time.sleep(delay)
            continue

        if resp.status_code == 200:
            try:
                telegram_ok = resp.json().get("ok", False)
            except (ValueError, AttributeError):
                telegram_ok = False
            if telegram_ok:
                logger.info("Sent to chat_id=%s: %s (%s)", chat_id, title, company)
                return True

        retryable = resp.status_code == 429 or 500 <= resp.status_code < 600
        if retryable and attempt < TELEGRAM_MAX_ATTEMPTS:
            delay = _telegram_retry_delay(resp, attempt)
            logger.warning("Telegram HTTP %s for job=%s; retrying in %.1fs (%s/%s)", resp.status_code, job.get("id"), delay, attempt, TELEGRAM_MAX_ATTEMPTS)
            time.sleep(delay)
            continue

        logger.error("Failed to notify chat_id=%s about job %s after %s attempt(s): HTTP %s %s", chat_id, job.get("id"), attempt, resp.status_code, resp.text)
        return False

    return False


async def send_fresh_menu(chat_id: int):
    if not TOKEN:
        raise RuntimeError("TOKEN not found in .env file.")

    bot = Bot(token=TOKEN)
    await bot.send_message(
        chat_id=chat_id,
        text="Menu:",
        reply_markup=main_menu_keyboard(),
    )


def main():
    logger.info("=" * 60)
    logger.info("Parser run started")

    try:
        user_ids = db.get_all_user_ids()
    except Exception:
        logger.exception("Could not load users from the database.")
        return 1

    if not user_ids:
        logger.info("No registered users yet. Nothing to do.")
        return 0

    try:
        user_filters = {chat_id: db.load_filters(chat_id) for chat_id in user_ids}
    except Exception:
        logger.exception("Could not load user filters from the database.")
        return 1

    all_keywords = sorted({kw for kws in user_filters.values() for kw in kws})
    if not all_keywords:
        logger.info("No filters configured by any user. Nothing to do.")
        return 0

    logger.info("Registered users: %s. Unique keywords to fetch: %s", len(user_ids), all_keywords)
    session = requests.Session()

    logger.info("Fetching current build_id...")
    try:
        build_id = get_build_id(session)
    except Exception:
        logger.exception("Could not fetch staff.am build_id; aborting this run.")
        return 1
    logger.info("build_id: %s", build_id)

    stats = {"keywords_failed": 0, "users_failed": 0, "sent": 0, "send_failed": 0}
    jobs_by_keyword = {}
    for keyword in all_keywords:
        try:
            jobs_by_keyword[keyword] = collect_jobs_for_keyword(
                session, build_id, key_word=keyword, sort_by=2
            )
        except Exception:
            stats["keywords_failed"] += 1
            jobs_by_keyword[keyword] = []
            logger.exception("Failed to collect jobs for keyword=%r; continuing.", keyword)

    for chat_id in user_ids:
        try:
            keywords = user_filters[chat_id]
            if not keywords:
                continue

            candidate_jobs = {}
            for keyword in keywords:
                for job in jobs_by_keyword.get(keyword, []):
                    candidate_jobs[job.get("id")] = job

            new_jobs = [
                job for job_id, job in candidate_jobs.items()
                if not db.is_job_seen(chat_id, job_id)
            ]

            if not new_jobs:
                logger.info("chat_id=%s: no new jobs to send.", chat_id)
                continue

            logger.info("chat_id=%s: sending %s new job(s).", chat_id, len(new_jobs))
            sent_any = False
            for job in new_jobs:
                try:
                    success = send_telegram_notification(chat_id, job)
                    if success:
                        db.mark_job_seen(chat_id, job.get("id"))
                        stats["sent"] += 1
                        sent_any = True
                    else:
                        stats["send_failed"] += 1
                except Exception:
                    stats["send_failed"] += 1
                    logger.exception(
                        "Unexpected error sending job=%s to chat_id=%s; continuing.",
                        job.get("id"), chat_id,
                    )
                time.sleep(1)

            if sent_any:
                try:
                    asyncio.run(send_fresh_menu(chat_id))
                except Exception:
                    logger.exception("Could not send fresh menu to chat_id=%s.", chat_id)
        except Exception:
            stats["users_failed"] += 1
            logger.exception("Failed to process chat_id=%s; continuing.", chat_id)

    try:
        db.cleanup_old_seen_jobs(days=30)
    except Exception:
        logger.exception("Could not clean up old seen_jobs records.")

    logger.info(
        "Parser run finished: sent=%s, send_failed=%s, keywords_failed=%s, users_failed=%s",
        stats["sent"], stats["send_failed"], stats["keywords_failed"], stats["users_failed"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())