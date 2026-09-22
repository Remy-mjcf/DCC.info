# Things to revisit (round 2)

Picks up after: crawler roster expansion (95 entries), npc/item
extraction, the new book pipeline (8/8 books), the validate.py
related_crawlers name-vs-id fix, and confirming the npcs/items/books
site views render real data correctly. Everything through that point
is committed and pushed to `origin/main` (`6209937`).

## Tattoos: still zero real entries

All 10 cached tattoo pages are sitting in `needs_review/Tattoos/`,
0/10 in `DCCdata/tattoos.json` (the file doesn't even exist yet).
This is by design, not a bug -- `placement.position_3d` genuinely
can't be derived from wiki text -- but it means the tattoo tab's 3D
viewer (`DCCsite/js/tabs/tattoos.js`) has no data to actually show
yet. Needs a real decision on how position_3d gets populated:
- Hand-author position_3d for each of the 10 (coordinates against
  whatever body model the 3D viewer uses), promoting each out of
  needs_review manually, or
- Build a small authoring tool (e.g. click-to-place on the existing
  Three.js model) so this doesn't have to be hand-typed JSON, or
- Loosen the schema/extraction to accept a coarser placement (e.g.
  body_part + side only, no 3D coords) and treat position_3d as an
  optional enhancement layered in later.

Whichever direction, this is the biggest remaining gap between "data
pipeline is complete" and "site is complete."

## extract.py: retryDelay parsing (nice-to-have, carried over from round 1)

429 responses include a `retryDelay` field (e.g. "Please retry in
11.9s") that extract.py still ignores in favor of its own fixed
backoff. Matters less now that the 500 RPD / 15 RPM headroom
(gemini-3.5-flash-lite) makes hitting limits unlikely, but would make
retries more correct if a future run does get rate-limited.

## Site: no pagination/search now that crawlers.json is 95 entries

`renderCardGrid` in `js/lib/utils.js` just dumps every record into one
grid -- fine at 14 entries, less fine at 95. Worth adding a simple
text-filter input per tab (crawlers/npcs/items at least) before this
becomes a scroll-forever page. Not urgent, but the crawler roster
expansion this session made it a real usability question, not a
hypothetical one.

## Site: not deployed anywhere yet

Verified locally via `python -m http.server` + Chrome. There's a
GitHub repo (https://github.com/Remy-mjcf/DCC.info) but no live
deployment -- e.g. GitHub Pages would be a near-zero-config option
for a static site like this, if/when you want it public.

## Duplicate-detection is still manual/ad-hoc

This session found and removed 3 duplicate entities (`Crawler`
glossary page, `NPCs` glossary page, `Popov Brothers` joint page) by
manual inspection each time -- there's no automated check for this in
validate.py. Given the wiki has more joint/family pages (e.g. multiple
individual pages plus a combined page, like the Popov brothers
pattern), it might resurface. Not worth over-building for 3 instances
so far, but worth remembering if it starts showing up more.

## Not touching, per earlier decision

- `books.json` order/titles were pulled from the wiki this session and
  look internally consistent (each book states its own ordinal,
  chapter-summary pages 1-8 confirm 8 total) -- but these were never
  cross-checked against the real-world published titles/order, since
  that was explicitly out of scope for the wiki-scraping pipeline.
  Worth a quick sanity check against the actual book jackets if you
  want full confidence.
