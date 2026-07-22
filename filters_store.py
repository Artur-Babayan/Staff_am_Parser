import json
import os

FILTERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "filters.json")

DEFAULT_FILTERS = ["Python", "Django"]


def load_filters() -> list:
    if not os.path.exists(FILTERS_FILE):
        save_filters(DEFAULT_FILTERS)
        return list(DEFAULT_FILTERS)

    try:
        with open(FILTERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except (json.JSONDecodeError, ValueError):
        pass

    save_filters(DEFAULT_FILTERS)
    return list(DEFAULT_FILTERS)


def save_filters(filters: list) -> None:
    with open(FILTERS_FILE, "w", encoding="utf-8") as f:
        json.dump(filters, f, ensure_ascii=False, indent=2)


def add_filter(keyword: str) -> tuple[bool, list]:
    filters = load_filters()
    keyword = keyword.strip()

    if not keyword:
        return False, filters

    if any(f.lower() == keyword.lower() for f in filters):
        return False, filters

    filters.append(keyword)
    save_filters(filters)
    return True, filters


def remove_filter(keyword: str) -> tuple[bool, list]:
    filters = load_filters()
    keyword = keyword.strip()

    new_filters = [f for f in filters if f.lower() != keyword.lower()]

    if len(new_filters) == len(filters):
        return False, filters

    save_filters(new_filters)
    return True, new_filters