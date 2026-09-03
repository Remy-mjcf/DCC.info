"""MediaWiki API client for the Dungeon Crawler Carl Fandom wiki.

Fetches raw wikitext for pages in a given category and caches each page
as a .wikitext file under cache/<dir>/. Re-running skips pages already
cached unless --force is passed.

Usage:
    python fetch.py --category Crawlers
    python fetch.py --category NPCs --limit 5
    python fetch.py --category Tattoos --force
"""

import argparse
import re
import time
from pathlib import Path

import requests

API_URL = "https://dungeon-crawler-carl.fandom.com/api.php"
USER_AGENT = "DCCinfo-fan-site-bot/0.1 (personal project; contact: crowleyfarengar@gmail.com)"
DEFAULT_RATE_LIMIT_SECONDS = 1.0
CACHE_ROOT = Path(__file__).parent / "cache"

# Wiki category name -> local cache subdirectory name (per DCCinfo folder spec)
CATEGORY_CACHE_DIRS = {
    "Crawlers": "Characters",
    "NPCs": "NPCs",
    "Tattoos": "Tattoos",
}


def sanitize_filename(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", title).strip()


class MediaWikiClient:
    def __init__(self, api_url=API_URL, user_agent=USER_AGENT, rate_limit_seconds=DEFAULT_RATE_LIMIT_SECONDS):
        self.api_url = api_url
        self.rate_limit_seconds = rate_limit_seconds
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self._last_request_time = 0.0

    def _get(self, params: dict) -> dict:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        response = self.session.get(self.api_url, params={**params, "format": "json"}, timeout=30)
        response.raise_for_status()
        self._last_request_time = time.monotonic()
        return response.json()

    def get_category_members(self, category: str, namespace: int = 0) -> list[str]:
        titles = []
        cmcontinue = None
        while True:
            params = {
                "action": "query",
                "list": "categorymembers",
                "cmtitle": f"Category:{category}",
                "cmnamespace": namespace,
                "cmlimit": 500,
            }
            if cmcontinue:
                params["cmcontinue"] = cmcontinue
            data = self._get(params)
            titles.extend(m["title"] for m in data["query"]["categorymembers"])
            cmcontinue = data.get("continue", {}).get("cmcontinue")
            if not cmcontinue:
                break
        return titles

    def get_wikitext(self, title: str) -> str | None:
        data = self._get({
            "action": "query",
            "prop": "revisions",
            "rvslots": "main",
            "rvprop": "content",
            "titles": title,
        })
        pages = data["query"]["pages"]
        page = next(iter(pages.values()))
        if "missing" in page:
            return None
        return page["revisions"][0]["slots"]["main"]["*"]


def fetch_category(client: MediaWikiClient, category: str, cache_dir_name: str | None = None,
                    force: bool = False, limit: int | None = None) -> None:
    cache_dir_name = cache_dir_name or CATEGORY_CACHE_DIRS.get(category, category)
    cache_dir = CACHE_ROOT / cache_dir_name
    cache_dir.mkdir(parents=True, exist_ok=True)

    titles = client.get_category_members(category)
    if limit:
        titles = titles[:limit]

    print(f"Category:{category} -> {len(titles)} page(s), caching to {cache_dir}/")

    for title in titles:
        dest = cache_dir / f"{sanitize_filename(title)}.wikitext"
        if dest.exists() and not force:
            print(f"  skip (cached): {title}")
            continue

        wikitext = client.get_wikitext(title)
        if wikitext is None:
            print(f"  skip (missing page): {title}")
            continue

        dest.write_text(wikitext, encoding="utf-8")
        print(f"  fetched: {title}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--category", required=True, help="Wiki category name, e.g. Crawlers, NPCs, Tattoos")
    parser.add_argument("--cache-dir", help="Override the local cache subdirectory name")
    parser.add_argument("--force", action="store_true", help="Re-fetch pages even if already cached")
    parser.add_argument("--limit", type=int, help="Only fetch the first N pages (for testing)")
    parser.add_argument("--rate-limit", type=float, default=DEFAULT_RATE_LIMIT_SECONDS,
                         help="Minimum seconds between requests (default: %(default)s)")
    args = parser.parse_args()

    client = MediaWikiClient(rate_limit_seconds=args.rate_limit)
    fetch_category(client, args.category, cache_dir_name=args.cache_dir, force=args.force, limit=args.limit)


if __name__ == "__main__":
    main()
