"""Quick smoke test for fetch.py against the live wiki.

Hits the real MediaWiki API (no mocking) to confirm the client and its
caching behavior work end-to-end, before relying on it for extraction.
Network-dependent -- not part of an automated CI suite, just a manual
sanity check. Run with:

    python test_fetch.py
"""

import contextlib
import io

from fetch import CACHE_ROOT, MediaWikiClient, fetch_category


def test_get_wikitext_single_page():
    client = MediaWikiClient()
    wikitext = client.get_wikitext("Carl")
    assert wikitext, "expected non-empty wikitext for the Carl page"
    assert "Character info" in wikitext
    print(f"get_wikitext('Carl'): OK ({len(wikitext)} chars)")


def test_fetch_category_caches_and_skips():
    client = MediaWikiClient()
    cache_dir = CACHE_ROOT / "Characters"
    before = set(cache_dir.glob("*.wikitext")) if cache_dir.exists() else set()

    fetch_category(client, "Crawlers", force=False, limit=1)
    after = set(cache_dir.glob("*.wikitext"))
    assert after, "expected at least one cached .wikitext file"
    new_file = next(iter(after - before), next(iter(after)))
    assert new_file.read_text(encoding="utf-8").strip(), "cached file should not be empty"
    print(f"fetch_category('Crawlers', limit=1): OK -> {new_file.name}")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fetch_category(client, "Crawlers", force=False, limit=1)
    assert "skip (cached)" in buf.getvalue(), "re-running should skip the already-cached page"
    print("re-run skips already-cached page: OK")


if __name__ == "__main__":
    test_get_wikitext_single_page()
    test_fetch_category_caches_and_skips()
    print("\nAll fetch.py smoke tests passed.")
