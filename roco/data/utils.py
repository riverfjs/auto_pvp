"""Shared utilities for Roco Kingdom WIKI scraping."""

import time
import json
from pathlib import Path

import requests

API_BASE = "https://wiki.biligame.com/rocom/api.php"
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "_data"
INDEX_DIR = DATA_DIR / "index"
RAW_DIR = DATA_DIR / "raw"
PARSED_DIR = DATA_DIR / "parsed"
DB_DIR = ROOT / "_db"

CATEGORY_PETS = "Category:精灵"
CATEGORY_SKILLS = "Category:技能"
YINJI_SOURCE_PAGE = "印记"  # 印记 names are extracted from this page's wikitext

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/148.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://wiki.biligame.com/rocom/",
        "Origin": "https://wiki.biligame.com",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Ch-Ua": (
            '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"'
        ),
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
    }
)
SESSION.cookies.update(
    {
        "b_nut": "1778929320",
        "buvid3": "100B0293-2B63-246D-07F7-A5B7CA5E659819636infoc",
        "buvid4": (
            "E79D63A2-C0EB-7DE8-8866-AB79CDD7C8D720277-026051619-0/"
            "zQqU0bEgS984TQx8ez0g%3D%3D"
        ),
        "buvid_fp": "7484a23a6632c51c2f62217043984c53",
        "b_lsid": "4DD643C5_19E307AFC52",
        "bsource": "search_google",
    }
)

LAST_REQUEST = 0.0
MIN_INTERVAL = 0.05  # seconds between requests (serial mode)


def api_get(params: dict, use_post: bool = False) -> dict:
    """GET (or POST) the MediaWiki API with rate limiting. Returns parsed JSON."""
    global LAST_REQUEST
    elapsed = time.monotonic() - LAST_REQUEST
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    if use_post:
        resp = SESSION.post(API_BASE, data=params, timeout=30)
    else:
        resp = SESSION.get(API_BASE, params=params, timeout=30)
    LAST_REQUEST = time.monotonic()
    resp.raise_for_status()
    data = resp.json()
    if "query" not in data and "parse" not in data:
        raise RuntimeError(f"Unexpected API response keys: {list(data.keys())} — {resp.url}")
    return data


def fetch_category_members(category: str) -> list[str]:
    """Fetch all page titles in a category (handles pagination)."""
    titles: list[str] = []
    params: dict = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": category,
        "cmlimit": "max",
        "format": "json",
    }
    while True:
        data = api_get(params)
        for member in data["query"]["categorymembers"]:
            titles.append(member["title"])
        if "continue" in data:
            params["cmcontinue"] = data["continue"]["cmcontinue"]
        else:
            break
    return titles


def fetch_page_wikitext(title: str) -> str:
    """Fetch the raw wikitext of a wiki page."""
    data = api_get(
        {
            "action": "parse",
            "page": title,
            "prop": "wikitext",
            "format": "json",
        }
    )
    return data["parse"]["wikitext"]["*"]


def save_json(data, path: Path) -> None:
    """Save data as JSON to path, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(path: Path) -> dict | list:
    """Load JSON from path."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
