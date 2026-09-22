# Things to revisit

## Important: Gemini free-tier quota is much tighter than expected
The background crawler run crashed (not a bug -- confirmed by reading
the actual output file; my earlier `grep` pipe was masking the real
exit code) after hitting a 429 RESOURCE_EXHAUSTED error. Confirmed the
real numbers on the Google AI Studio rate-limit dashboard
(https://aistudio.google.com/rate-limit):

| Model | RPM | RPD |
|---|---|---|
| gemini-3.6-flash (current default) | 5 | 20 |
| gemini-3.5-flash-lite | 15 | 500 |
| gemini-3.1-flash-lite | 15 | 500 |

Two real bugs this exposes in `extract.py`:
- `DEFAULT_RATE_LIMIT_SECONDS = 4.0` allows ~15 req/min, but
  gemini-3.6-flash's real limit is 5 RPM (needs ~12s+ between calls).
  This alone likely caused some of the 503s we saw, before the daily
  cap was even hit.
- The 429 error response includes a `retryDelay` field (e.g. "Please
  retry in 11.9s") that `extract.py` currently ignores in favor of its
  own fixed 5s*attempt backoff. Should parse and respect the API's
  actual suggested delay instead of guessing.

**Decided:** switched `DEFAULT_MODEL` to `gemini-3.5-flash-lite` (500
RPD / 15 RPM vs the old 20 RPD / 5 RPM), and dropped
`DEFAULT_RATE_LIMIT_SECONDS` to 4.5s to match the new model's real RPM.
Verified live on the 5 remaining crawler pages: all 5 succeeded, no
503/429s, and quality looks at least as good as gemini-3.6-flash on
spot-check -- notably `Maggie My`'s `"class"` came back as proper JSON
`null` this time, not the `"None"` string artifact seen earlier. Not
exhaustively verified across all entity types yet, but promising.

The `retryDelay`-parsing improvement (still not done) matters less now
that RPD headroom is much larger, but would still be a nice-to-have.

## Crawler extraction: complete
All 15 cached crawler pages processed: 14 in `crawlers.json`, 1
(`Crawler.wikitext` -- the wiki's generic "what is a crawler" glossary
page, not a specific character) correctly flagged to
`needs_review/Characters/Crawler.json`. Probably just delete that one
rather than try to fix it -- it's not really a crawler entity.

## Still queued (pipeline "rest of it")
Fetched but not yet extracted:
- `npc` -- 10 pages cached in `DCCscraping/cache/NPCs/`
- `tattoo` -- 10 pages cached in `DCCscraping/cache/Tattoos/` (remember:
  most/all of these will land in `needs_review/` by design, since
  `placement.position_3d` can't be determined from wiki text)
- `item` -- 10 pages cached in `DCCscraping/cache/Items/`

Run each with `python extract.py <entity>`, then `python validate.py`
to sanity-check the whole set together (schema + cross-references).
500 RPD headroom now makes it reasonable to just run these normally.

## Data quality notes
- `crawlers.json` Agatha entry (extracted under the old model) still
  has `"class": "None"` as a literal string, not JSON null. Harmless,
  candidate for a hand-correction pass later.
- `validate.py` currently reports 1 cross-reference error: Louis's
  `first_appearance.book_id` is `"b4"`, which doesn't exist in
  `books.json` (only books 1-3 are seeded, per your original hand-given
  list, and it's meant to be hand-maintained). Not an extraction bug --
  `books.json` genuinely needs book 4+ added. Didn't add entries myself
  since I can't verify exact titles/order confidently and you said this
  file is hand-maintained.
- The NPCs category fetch pulled in a page literally titled "NPCs"
  (the category's own index page) -- expect that one to behave oddly
  during npc extraction, similar to the "Crawler" glossary page above.

## Not set up yet
- **No git remote configured.** Everything so far is local commits only
  (`git remote -v` is empty) -- nothing has been pushed anywhere. Decide
  whether to create a GitHub repo (`gh repo create`) or point at an
  existing remote when ready.

## Uncommitted local changes
- `DCCdata/crawlers.json` has the 9 new entries above, not yet
  committed.
