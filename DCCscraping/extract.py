"""LLM-driven wikitext -> JSON extraction.

Reads cached wikitext for a given entity type (crawler, npc, tattoo),
extracts structured fields via a forced Claude tool call against the
matching DCCschema/*.schema.json contract, and routes each result:

  - passes full schema validation -> merged into DCCdata/<entity>.json
  - fails validation               -> written to needs_review/<dir>/<title>.json

Some fields are never asked of the model and are injected by the
pipeline instead:
  - id: crawler/npc get slug(title); tattoos get a sequential tattoo_NNN
  - tattoo.source_url: derived directly from the wiki page title

Tattoos also omit `image` and `placement.position_3d` from the model's
tool schema entirely, since neither can be determined from wiki text.
Every tattoo extraction therefore fails schema validation and lands in
needs_review/ until a human adds the art asset and 3D coordinates and
promotes it into DCCdata/tattoos.json by hand -- this is intentional,
not a bug.

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
from pathlib import Path
from urllib.parse import quote

from anthropic import Anthropic
from jsonschema.validators import Draft202012Validator

ROOT = Path(__file__).parent.parent
SCHEMA_DIR = ROOT / "DCCschema"
DATA_DIR = ROOT / "DCCdata"
CACHE_ROOT = Path(__file__).parent / "cache"
NEEDS_REVIEW_ROOT = Path(__file__).parent / "needs_review"

WIKI_BASE_URL = "https://dungeon-crawler-carl.fandom.com/wiki"
DEFAULT_MODEL = "claude-sonnet-5"

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
        "omit_fields": ["image", "placement.position_3d", "source_url"],
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


def build_extraction_schema(schema: dict, omit_fields: list[str]) -> dict:
    extraction_schema = copy.deepcopy(schema)
    for key in ("$schema", "$id", "title"):
        extraction_schema.pop(key, None)
    for path in ["id", *omit_fields]:
        omit_field(extraction_schema, path)
    return extraction_schema


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
        "wikitext of a single article. Call the record_extraction tool exactly "
        "once with the extracted fields. Only use information explicitly "
        "stated or very clearly implied by the article -- never invent facts. "
        "Strip wiki markup (double brackets, templates) from extracted text so "
        "it reads as clean prose/names.\n\n"
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


def inject_fields(entity_type: str, title: str, extracted: dict, existing_ids: set[str]) -> dict:
    extracted = dict(extracted)
    if entity_type == "tattoo":
        extracted["id"] = next_tattoo_id(existing_ids)
        extracted["source_url"] = f"{WIKI_BASE_URL}/{quote(title.replace(' ', '_'))}"
        if "crawler_id" in extracted:
            extracted["crawler_id"] = slugify(extracted["crawler_id"])
    else:
        extracted["id"] = unique_slug(slugify(title), existing_ids)
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


def extract_page(client: Anthropic, model: str, entity_type: str, title: str, wikitext: str,
                  extraction_schema: dict, system_prompt: str) -> dict:
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        tools=[{
            "name": "record_extraction",
            "description": "Record the structured data extracted from the wiki article.",
            "input_schema": extraction_schema,
        }],
        tool_choice={"type": "tool", "name": "record_extraction"},
        messages=[{"role": "user", "content": f"Article title: {title}\n\n{wikitext}"}],
    )
    tool_use = next(block for block in response.content if block.type == "tool_use")
    return tool_use.input


def process_entity(client: Anthropic, model: str, entity_type: str, force: bool, limit: int | None) -> None:
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

    for wikitext_file in wikitext_files:
        title = wikitext_file.stem
        marker = wikitext_file.with_suffix(".extracted")
        if marker.exists() and not force:
            print(f"  skip (already extracted): {title}")
            continue

        raw_wikitext = wikitext_file.read_text(encoding="utf-8")
        cleaned = clean_wikitext(raw_wikitext)

        extracted = extract_page(client, model, entity_type, title, cleaned, extraction_schema, system_prompt)
        extracted = inject_fields(entity_type, title, extracted, existing_ids)

        errors = validate(schema, extracted)
        if not errors:
            if extracted["id"] in existing_ids:
                print(f"  skip (id already in {config['data_file']}): {title}")
            else:
                data.append(extracted)
                existing_ids.add(extracted["id"])
                write_json(data_path, data)
                print(f"  extracted -> {config['data_file']}: {title}")
        else:
            write_json(review_dir / f"{title}.json", {
                "source_title": title,
                "cache_file": str(wikitext_file.relative_to(CACHE_ROOT.parent)),
                "extracted": extracted,
                "validation_errors": errors,
            })
            print(f"  needs review ({len(errors)} error(s)): {title}")

        marker.touch()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("entity_type", choices=sorted(ENTITY_CONFIG))
    parser.add_argument("--force", action="store_true", help="Re-extract pages even if already processed")
    parser.add_argument("--limit", type=int, help="Only process the first N cached pages (for testing)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Anthropic model id (default: %(default)s)")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    client = Anthropic()
    process_entity(client, args.model, args.entity_type, args.force, args.limit)


if __name__ == "__main__":
    main()
