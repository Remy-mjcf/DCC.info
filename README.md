# DCCinfo

A fan site for the *Dungeon Crawler Carl* book series. Content (crawlers,
NPCs, tattoos, items, etc.) is sourced from the [Dungeon Crawler Carl
Fandom wiki](https://dungeon-crawler-carl.fandom.com) via its MediaWiki
API, run through an LLM extraction step into structured JSON, validated
against shared schemas, and rendered as a static site.

## Architecture

```
DCCinfo/
├── DCCscraping/   data-acquisition pipeline (Python)
├── DCCschema/     JSON Schema contracts shared by scraping + site
├── DCCdata/       committed output JSON (hand-corrected, source of truth)
└── DCCsite/       static frontend (vanilla JS + Three.js for tattoos)
```

**Pipeline flow:** `fetch.py` pulls wikitext from the MediaWiki API into
`DCCscraping/cache/` (gitignored, regenerable) → `extract.py` runs an
LLM extraction pass to turn wikitext into JSON matching the schemas in
`DCCschema/`, writing low-confidence results to `DCCscraping/needs_review/`
(gitignored, pipeline-internal only — the site never reads from here) →
`validate.py` checks extracted JSON against `DCCschema/*.schema.json` →
reviewed/corrected JSON is committed to `DCCdata/`.

`DCCdata/` is real, committed output — not disposable cache. Some of it
(tattoo 3D placement coordinates, misc corrections) is maintained by hand
over time and should never be regenerated wholesale or gitignored.

`DCCschema/` is a sibling of `DCCscraping`, not nested inside it, because
both the scraping pipeline and the frontend may eventually validate
against it.

## Setup

### Scraping pipeline

```bash
cd DCCscraping
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` at the repo root and fill in your API key:

```bash
cp .env.example .env
# then edit .env and set ANTHROPIC_API_KEY
```

### Site

`DCCsite/` is a static site (no build step). Serve it locally with any
static file server, e.g.:

```bash
cd DCCsite
python3 -m http.server 8000
```

## Status

Currently scaffolding schemas in `DCCschema/` before building the
scraping pipeline (`fetch.py`, `extract.py`) or the frontend.
