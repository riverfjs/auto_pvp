"""BWiki MediaWiki API client for team sample fetching."""

import time
import threading

import requests

API_BASE = "https://wiki.biligame.com/rocom/api.php"

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
MIN_INTERVAL = 0.12
REQUEST_LOCK = threading.Lock()


class WikiPageMissing(RuntimeError):
    """Raised when a BWiki team page lookup targets a missing page."""

    def __init__(self, title: str, info: str):
        super().__init__(f"missingtitle: {title}: {info}")
        self.title = title
        self.info = info


def api_get(params: dict, use_post: bool = False) -> dict:
    """GET (or POST) the MediaWiki API with rate limiting. Returns parsed JSON."""
    global LAST_REQUEST
    last_error: Exception | None = None
    with REQUEST_LOCK:
        for attempt in range(3):
            elapsed = time.monotonic() - LAST_REQUEST
            if elapsed < MIN_INTERVAL:
                time.sleep(MIN_INTERVAL - elapsed)
            if use_post:
                resp = SESSION.post(API_BASE, data=params, timeout=30)
            else:
                resp = SESSION.get(API_BASE, params=params, timeout=30)
            LAST_REQUEST = time.monotonic()
            resp.raise_for_status()
            try:
                data = resp.json()
                break
            except ValueError as exc:
                last_error = exc
                if attempt == 2:
                    snippet = resp.text[:200].replace("\n", " ")
                    ctype = resp.headers.get("content-type", "")
                    raise RuntimeError(f"BWiki returned non-JSON content-type={ctype!r} prefix={snippet!r}") from exc
                time.sleep(0.5 * (attempt + 1))
        else:
            raise RuntimeError(f"Failed to parse API response: {last_error}")
    if "error" in data:
        error = data["error"]
        code = str(error.get("code", ""))
        info = str(error.get("info", ""))
        if code == "missingtitle":
            raise WikiPageMissing(str(params.get("page", "")), info)
        raise RuntimeError(f"BWiki API error {code}: {info}")
    if "query" not in data and "parse" not in data:
        raise RuntimeError(f"Unexpected API response keys: {list(data.keys())} — {resp.url}")
    return data
