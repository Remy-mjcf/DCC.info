"""LLM-driven wikitext -> JSON extraction.

Reads cached wikitext for a given entity type (crawler, npc, tattoo),
extracts structured fields via the Gemini API's schema-constrained JSON
output (response_schema + response_mime_type="application/json") against
the matching DCCschema/*.schema.json contract, and routes each result:

  - passes schema validation AND has <=2 null required fields
        -> merged into DCCdata/<entity>.json
  - fails schema validation OR has >2 null required fields
        -> written to needs_review/<dir>/<title>.json, with the schema
           errors and null-field count attached for manual triage

The model is explicitly told not to guess: if a field's value isn't in
the article, it must set it to null rather than infer a plausible one.
DCCschema/*.schema.json permit null on every leaf field for exactly
this reason (structural container fields like `first_appearance` or
`placement` stay required, non-null objects -- only their scalar/array
leaves are nullable), so a handful of unknowns can still land directly
in DCCdata for later hand-correction rather than always being deferred
to needs_review.

Tattoos are the intentional exception in practice: `placement.
position_3d` has three required leaves (x, y, z) that can never be
determined from wiki text, which alone puts most tattoo extractions
over the >2-null threshold -- so they naturally keep landing in
needs_review/ until a human adds the art asset and 3D coordinates.

Some fields are never asked of the model at all, because the pipeline
computes them directly and any model guess would just be discarded:
  - id: crawler/npc get slug(title); tattoos get a sequential tattoo_NNN
  - tattoo.source_url: derived directly from the wiki page title

Uses the Gemini API free tier -- get a key at https://aistudio.google.com/apikey
and put it in .env as GEMINI_API_KEY. Free-tier requests are rate-limited
per minute, so calls are throttled client-side (--rate-limit) and retried
with backoff on transient/rate-limit errors (--max-retries).

Usage:
    python extract.py crawler
    python extract.py npc --limit 5
    python extract.py tattoo --force
"""

import argparse
import copy
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

from google import genai
from google.genai import types
from jsonschema.validators import Draft202012Validator

ROOT = Path(__file__).parent.parent
SCHEMA_DIR = ROOT / "DCCschema"
DATA_DIR = ROOT / "DCCdata"
CACHE_ROOT = Path(__file__).parent / "cache"
NEEDS_REVIEW_ROOT = Path(__file__).parent / "needs_review"

WIKI_BASE_URL = "https://dungeon-crawler-carl.fandom.com/wiki"
# Verify this is still a current free-tier model at https://ai.google.dev/gemini-api/docs/pricing
# before relying on it -- Google's free-tier lineup changes over time.
DEFAULT_MODEL = "gemini-2.0-flash"
MAX_NULL_REQUIRED_FIELDS = 2
DEFAULT_RATE_LIMIT_SECONDS = 4.0
DEFAULT_MAX_RETRIES = 3

ENTITY_CONFIG = {
    "crawler": {
        "schema_file": "crawler.schema.json",
        "cache_dir": "Characters",
        "data_file": "crawlers.json",
        "omit_fields": [],
        "instructions": (
            "This article is about a crawler (a human contestant in the dungeon). "
            "Extract: name; class (their current/most recent class, as free text); "
            "species; status (as stated, e.g. Alive/Dead -- use \"Unknown\" if not "
            "stated); first_appearance; affiliations (parties, guilds, and "
            "organizations they belong to, as a list of clean names with no wiki "
            "markup); and a 2-3 sentence summary in your own words."
        ),
    },
    "npc": {
        "schema_file": "npc.schema.json",
        "cache_dir": "NPCs",
        "data_file": "npcs.json",
        "omit_fields": [],
        "instructions": (
            "This article is about an NPC (a non-crawler character). Extract: "
            "name; role (their function/occupation); species; first_appearance; "
            "related_crawlers (names of the crawlers they are most closely "
            "associated with, e.g. as a manager, ally, or antagonist, as a list "
            "with no wiki markup); and a 2-3 sentence summary in your own words."
        ),
    },
    "tattoo": {
        "schema_file": "tattoo.schema.json",
        "cache_dir": "Tattoos",
        "data_file": "tattoos.json",
        "omit_fields": ["source_url"],
        "instructions": (
            "This article is about a tattoo (a mark or ability grant a crawler "
            "can receive). Extract: name; crawler_id (give the NAME, as it "
            "appears in the article, of the crawler most closely associated with "
            "holding or receiving this tattoo -- use \"unknown\" if the article "
            "doesn't tie it to a specific crawler; the pipeline will convert this "
            "to a proper id); acquired (book_id + chapter it was first acquired "
            "in, and a short name for the scenario/event); placement.body_part "
            "(where on the body it's applied, as stated in the text); "
            "placement.side (\"front\", \"back\", or \"unknown\"); and effect (a "
            "short description of its mechanical/game effect)."
        ),
    },
    "item": {
        "schema_file": "item.schema.json",
        "cache_dir": "Items",
        "data_file": "items.json",
        "omit_fields": ["source_url"],
        "instructions": (
            "This article is about an item (gear, a consumable, or a crafted "
            "object). Extract: name; type (the item's category/slot as stated, "
            "e.g. \"Clothing (Chest)\", \"Weapon\", \"Consumable\"); effects (a "
            "list of its stated mechanical effects/bonuses, each as clean text "
            "with no wiki markup); source (how it's typically obtained, as free "
            "text); and a 2-3 sentence summary in your own words."
        ),
    },
}


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def clean_wikitext(text: str) -> str:
    import mwparserfromhell

    wikicode = mwparserfromhell.parse(text)
    for tag in wikicode.filter_tags(matches=lambda n: n.tag in ("ref", "gallery")):
        try:
            wikicode.remove(tag)
        except ValueError:
            pass
    for template in wikicode.filter_templates(matches=lambda t: t.name.matches("cite")):
        try:
            wikicode.remove(template)
        except ValueError:
            pass
    return str(wikicode)


def load_schema(entity_type: str) -> dict:
    path = SCHEMA_DIR / ENTITY_CONFIG[entity_type]["schema_file"]
    return json.loads(path.read_text())


def omit_field(schema: dict, dotted_path: str) -> None:
    parts = dotted_path.split(".")
    node = schema
    for part in parts[:-1]:
        node = node["properties"][part]
    leaf = parts[-1]
    node["properties"].pop(leaf, None)
    if "required" in node and leaf in node["required"]:
        node["required"].remove(leaf)


def make_nullable(node: dict) -> None:
    """Recursively allow null on every leaf field. Object containers (e.g.
    first_appearance, placement) stay required, non-null structure -- only
    their scalar/array leaves become nullable."""
    if node.get("type") == "object" and "properties" in node:
        for prop_schema in node["properties"].values():
            make_nullable(prop_schema)
        return
    node_type = node.get("type")
    if node_type is None or node_type == "null":
        return
    if isinstance(node_type, list):
        if "null" not in node_type:
            node["type"] = [*node_type, "null"]
    else:
        node["type"] = [node_type, "null"]


def build_extraction_schema(schema: dict, omit_fields: list[str]) -> dict:
    extraction_schema = copy.deepcopy(schema)
    for key in ("$schema", "$id", "title"):
        extraction_schema.pop(key, None)
    for path in ["id", *omit_fields]:
        omit_field(extraction_schema, path)
    for prop_schema in extraction_schema["properties"].values():
        make_nullable(prop_schema)
    return extraction_schema


def to_gemini_schema(schema: dict) -> dict:
    """Converts our JSON Schema (type unions for nullability) into Gemini's
    Schema format (uppercase type + a separate `nullable` bool)."""
    node_type = schema.get("type")
    result = {}

    if isinstance(node_type, list):
        non_null_types = [t for t in node_type if t != "null"]
        if non_null_types:
            result["type"] = non_null_types[0].upper()
        if "null" in node_type:
            result["nullable"] = True
    elif isinstance(node_type, str):
        result["type"] = node_type.upper()

    if result.get("type") == "OBJECT" and "properties" in schema:
        result["properties"] = {k: to_gemini_schema(v) for k, v in schema["properties"].items()}
        if "required" in schema:
            result["required"] = schema["required"]
    if result.get("type") == "ARRAY" and "items" in schema:
        result["items"] = to_gemini_schema(schema["items"])
    for key in ("enum", "minimum", "maximum"):
        if key in schema:
            result[key] = schema[key]

    return result


def count_null_required_fields(schema: dict, record: dict) -> int:
    """Recursively counts required leaf fields that are missing or null."""
    count = 0
    for name in schema.get("required", []):
        prop_schema = schema["properties"].get(name, {})
        value = record.get(name) if isinstance(record, dict) else None
        if prop_schema.get("type") == "object" and "properties" in prop_schema:
            count += count_null_required_fields(prop_schema, value or {})
        elif value is None:
            count += 1
    return count


def load_books() -> list[dict]:
    path = DATA_DIR / "books.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


def build_system_prompt(entity_type: str, books: list[dict]) -> str:
    books_summary = json.dumps(
        [{"id": b["id"], "title": b["title"], "order": b["order"]} for b in books]
    )
    return (
        "You are extracting structured data from an article on the Dungeon "
        "Crawler Carl Fandom wiki, for a fan site. You will be given the "
        "wikitext of a single article. Respond with exactly one JSON object "
        "matching the required schema. Only use information explicitly "
        "stated or very clearly implied by the article -- never invent facts. "
        "If a field's value cannot be determined from the article text, set "
        "it to null -- do not guess or infer a plausible-sounding value just "
        "to fill the field in. Strip wiki markup (double brackets, templates) "
        "from extracted text so it reads as clean prose/names.\n\n"
        f"The books in the series, in order, are: {books_summary}. Where the "
        "article gives a value like \"Book 1, Chapter 2\", match the book "
        "number to the corresponding id from this list and extract the "
        "chapter as an integer.\n\n"
        f"{ENTITY_CONFIG[entity_type]['instructions']}"
    )


def next_tattoo_id(existing_ids: set[str]) -> str:
    max_n = 0
    for existing_id in existing_ids:
        match = re.match(r"tattoo_(\d+)$", existing_id)
        if match:
            max_n = max(max_n, int(match.group(1)))
    return f"tattoo_{max_n + 1:03d}"


def unique_slug(base_slug: str, existing_ids: set[str]) -> str:
    if base_slug not in existing_ids:
        return base_slug
    n = 2
    while f"{base_slug}_{n}" in existing_ids:
        n += 1
    return f"{base_slug}_{n}"


SOURCE_URL_ENTITIES = {"tattoo", "item"}


def inject_fields(entity_type: str, title: str, extracted: dict, existing_ids: set[str]) -> dict:
    extracted = dict(extracted)
    if entity_type == "tattoo":
        extracted["id"] = next_tattoo_id(existing_ids)
        if extracted.get("crawler_id"):
            extracted["crawler_id"] = slugify(extracted["crawler_id"])
    else:
        extracted["id"] = unique_slug(slugify(title), existing_ids)
    if entity_type in SOURCE_URL_ENTITIES:
        extracted["source_url"] = f"{WIKI_BASE_URL}/{quote(title.replace(' ', '_'))}"
    return extracted


def validate(schema: dict, record: dict) -> list[str]:
    validator = Draft202012Validator(schema)
    return [error.message for error in validator.iter_errors(record)]


def load_json_array(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text())


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class RateLimiter:
    def __init__(self, min_interval_seconds: float):
        self.min_interval = min_interval_seconds
        self._last_call = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()


def extract_page(client: "genai.Client", model: str, title: str, wikitext: str,
                  extraction_schema: dict, system_prompt: str,
                  rate_limiter: RateLimiter, max_retries: int) -> dict:
    gemini_schema = to_gemini_schema(extraction_schema)
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_schema=gemini_schema,
        max_output_tokens=4096,
    )

    last_error = None
    for attempt in range(1, max_retries + 1):
        rate_limiter.wait()
        try:
            response = client.models.generate_content(
                model=model,
                contents=f"Article title: {title}\n\n{wikitext}",
                config=config,
            )
            return json.loads(response.text)
        except Exception as error:  # broad: retry on any transient/rate-limit error from the SDK
            last_error = error
            if attempt < max_retries:
                backoff = 5 * attempt
                print(f"    retrying after error ({error}); waiting {backoff}s...")
                time.sleep(backoff)
    raise last_error


def process_entity(client: "genai.Client", model: str, entity_type: str, force: bool, limit: int | None,
                    rate_limiter: RateLimiter, max_retries: int) -> None:
    config = ENTITY_CONFIG[entity_type]
    cache_dir = CACHE_ROOT / config["cache_dir"]
    review_dir = NEEDS_REVIEW_ROOT / config["cache_dir"]
    data_path = DATA_DIR / config["data_file"]

    schema = load_schema(entity_type)
    extraction_schema = build_extraction_schema(schema, config["omit_fields"])
    books = load_books()
    system_prompt = build_system_prompt(entity_type, books)

    data = load_json_array(data_path)
    existing_ids = {record["id"] for record in data}

    wikitext_files = sorted(cache_dir.glob("*.wikitext"))
    if limit:
        wikitext_files = wikitext_files[:limit]

    print(f"Extracting {entity_type}: {len(wikitext_files)} cached page(s)")

    succeeded = 0
    flagged = 0
    skipped = 0

    for wikitext_file in wikitext_files:
        title = wikitext_file.stem
        marker = wikitext_file.with_suffix(".extracted")
        if marker.exists() and not force:
            print(f"  skip (already extracted): {title}")
            skipped += 1
            continue

        raw_wikitext = wikitext_file.read_text(encoding="utf-8")
        cleaned = clean_wikitext(raw_wikitext)

        extracted = extract_page(client, model, title, cleaned, extraction_schema, system_prompt,
                                  rate_limiter, max_retries)
        extracted = inject_fields(entity_type, title, extracted, existing_ids)

        errors = validate(schema, extracted)
        null_count = count_null_required_fields(schema, extracted)

        if not errors and null_count <= MAX_NULL_REQUIRED_FIELDS:
            if extracted["id"] in existing_ids:
                print(f"  skip (id already in {config['data_file']}): {title}")
                skipped += 1
            else:
                data.append(extracted)
                existing_ids.add(extracted["id"])
                write_json(data_path, data)
                print(f"  extracted -> {config['data_file']}: {title}")
                succeeded += 1
        else:
            write_json(review_dir / f"{title}.json", {
                "source_title": title,
                "cache_file": str(wikitext_file.relative_to(CACHE_ROOT.parent)),
                "extracted": extracted,
                "null_field_count": null_count,
                "schema_errors": errors,
            })
            print(f"  needs review ({len(errors)} schema error(s), {null_count} null field(s)): {title}")
            flagged += 1

        marker.touch()

    print(f"\nDone: {succeeded} succeeded, {flagged} flagged for review"
          + (f", {skipped} skipped (already processed)" if skipped else ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("entity_type", choices=sorted(ENTITY_CONFIG))
    parser.add_argument("--force", action="store_true", help="Re-extract pages even if already processed")
    parser.add_argument("--limit", type=int, help="Only process the first N cached pages (for testing)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model id (default: %(default)s)")
    parser.add_argument("--rate-limit", type=float, default=DEFAULT_RATE_LIMIT_SECONDS,
                         help="Minimum seconds between API calls, for the free-tier rate limit (default: %(default)s)")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES,
                         help="Retry attempts per page on API errors (default: %(default)s)")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    client = genai.Client()
    rate_limiter = RateLimiter(args.rate_limit)
    process_entity(client, args.model, args.entity_type, args.force, args.limit, rate_limiter, args.max_retries)


if __name__ == "__main__":
    main()
