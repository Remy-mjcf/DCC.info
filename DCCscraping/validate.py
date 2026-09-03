"""Bulk jsonschema validation pass over DCCdata/.

Unlike extract.py's per-page validation (which only ever sees one
freshly-extracted record at a time), this checks the *committed* state
of DCCdata/*.json as a whole -- useful after hand-editing a file (e.g.
promoting a tattoo out of needs_review/ with real image/position_3d
values, or hand-correcting a crawler entry) to catch schema breaks and
dangling cross-file references before they land in the site.

Checks per file:
  - top-level value is a JSON array
  - each record validates against its DCCschema/*.schema.json
  - no duplicate ids within the file

Cross-file reference checks (only run with no entity_type filter, since
they require multiple files):
  - crawlers[].first_appearance.book_id      -> books.json
  - npcs[].first_appearance.book_id          -> books.json
  - npcs[].related_crawlers[]                -> crawlers.json
  - tattoos[].acquired.book_id                -> books.json
  - tattoos[].crawler_id                      -> crawlers.json

Usage:
    python validate.py             # validate everything present + cross-references
    python validate.py tattoo      # schema-only check of tattoos.json
"""

import argparse
import json
import sys
from pathlib import Path

from jsonschema.validators import Draft202012Validator

ROOT = Path(__file__).parent.parent
SCHEMA_DIR = ROOT / "DCCschema"
DATA_DIR = ROOT / "DCCdata"

ENTITY_FILES = {
    "book": ("book.schema.json", "books.json"),
    "crawler": ("crawler.schema.json", "crawlers.json"),
    "npc": ("npc.schema.json", "npcs.json"),
    "tattoo": ("tattoo.schema.json", "tattoos.json"),
    "item": ("item.schema.json", "items.json"),
}

REFERENCE_CHECKS = [
    ("crawlers.json", "first_appearance.book_id", "books.json"),
    ("npcs.json", "first_appearance.book_id", "books.json"),
    ("npcs.json", "related_crawlers", "crawlers.json"),
    ("tattoos.json", "acquired.book_id", "books.json"),
    ("tattoos.json", "crawler_id", "crawlers.json"),
]


def get_path(record: dict, dotted_path: str):
    node = record
    for part in dotted_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def load_data_file(data_file: str):
    path = DATA_DIR / data_file
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return None, [f"{data_file}: invalid JSON ({e})"]
    if not isinstance(data, list):
        return None, [f"{data_file}: expected a top-level JSON array"]
    return data, None


def validate_file(schema_file: str, data_file: str):
    """Returns (ids, errors) for one DCCdata file. ids is None if the file is absent."""
    data, load_errors = load_data_file(data_file)
    if load_errors:
        return None, load_errors
    if data is None:
        return None, []

    schema = json.loads((SCHEMA_DIR / schema_file).read_text())
    validator = Draft202012Validator(schema)

    errors = []
    ids = []
    seen_ids = set()
    for idx, record in enumerate(data):
        label = f"{data_file}[{idx}] (id={record.get('id', '?')})" if isinstance(record, dict) else f"{data_file}[{idx}]"
        for error in validator.iter_errors(record):
            errors.append(f"{label}: {error.message}")
        if isinstance(record, dict) and "id" in record:
            if record["id"] in seen_ids:
                errors.append(f"{label}: duplicate id '{record['id']}' in {data_file}")
            seen_ids.add(record["id"])
            ids.append(record["id"])

    print(f"{data_file}: {len(data)} record(s), {len(errors)} error(s)")
    return set(ids), errors


def check_references(all_ids: dict[str, set]) -> list[str]:
    errors = []
    for source_file, field_path, target_file in REFERENCE_CHECKS:
        if source_file not in all_ids or target_file not in all_ids:
            continue
        data, _ = load_data_file(source_file)
        target_ids = all_ids[target_file]
        for idx, record in enumerate(data):
            value = get_path(record, field_path)
            if value is None:
                continue
            refs = value if isinstance(value, list) else [value]
            for ref in refs:
                if ref not in target_ids:
                    label = f"{source_file}[{idx}] (id={record.get('id', '?')})"
                    errors.append(f"{label}: {field_path} references '{ref}', not found in {target_file}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("entity_type", nargs="?", choices=sorted(ENTITY_FILES), default=None,
                         help="Validate only this entity's file (schema check only, no cross-references)")
    args = parser.parse_args()

    entity_types = [args.entity_type] if args.entity_type else sorted(ENTITY_FILES)

    all_errors = []
    all_ids: dict[str, set] = {}
    for entity_type in entity_types:
        schema_file, data_file = ENTITY_FILES[entity_type]
        ids, errors = validate_file(schema_file, data_file)
        if ids is None and not errors:
            print(f"{data_file}: skip (not present)")
            continue
        if ids is not None:
            all_ids[data_file] = ids
        all_errors.extend(errors)

    if args.entity_type is None:
        print("Checking cross-references...")
        ref_errors = check_references(all_ids)
        all_errors.extend(ref_errors)
        print(f"  {len(ref_errors)} reference error(s)")

    print()
    if all_errors:
        print(f"FAILED ({len(all_errors)} error(s)):")
        for error in all_errors:
            print(f"  - {error}")
        sys.exit(1)
    else:
        print("All checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
