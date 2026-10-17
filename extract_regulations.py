"""Step 1: read data/*.txt and extract labeling requirements into regulations.json.

Usage:
    python extract_regulations.py

Each data/<jurisdiction>.txt file is sent to Claude once, with a strict
instruction to extract ONLY labeling-related requirements and to never
invent article numbers, URLs, or dates that are not literally present in
the source text. An empty source file simply yields zero records for that
jurisdiction -- that is treated as "no data available", not an error.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from models import Regulation, EXTRACTION_SCHEMA

load_dotenv()

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_PATH = Path(__file__).parent / "regulations.json"

MODEL = "claude-opus-5"

# Maps data file -> jurisdiction tag used throughout the rest of the app.
FILES = {
    "us.txt": "US",
    "eu.txt": "EU",
    "japan.txt": "Japan",
    "canada.txt": "Canada",
}

SYSTEM_PROMPT = """\
You extract pharmaceutical labeling requirements for international clinical-trial \
drug shipments from a single regulatory source document.

Rules you must follow exactly:
1. Extract ONLY provisions that concern the labeling of investigational/clinical-trial \
drug products or their packaging (e.g. required label content, prohibited label content, \
language requirements, storage/expiry statements on labels). Skip unrelated content such as \
monitoring procedures, adverse-event reporting, or committee structures, even if it appears \
in the same document.
2. The "text" field must be an excerpt from the provided document -- never paraphrase, \
summarize, invent, or add information that is not present in the source text.
3. Never invent an article number, title, source_url, or effective_date. If the document does \
not literally state one, return null for that field.
4. Set "source_type" based on what the document itself says about its own provenance: \
"verbatim_regulation" if it is quoting the official regulation/statute directly, \
"secondary_summary" if it is a summary from a secondary source (news, law-firm article, etc.), \
"translation" if it is a working translation of a non-English official text.
5. Carry over any caveat the document states about verification status, translation status, or \
whether the content is authoritative, into the "notes" field.
6. If the document contains no labeling-related content, return an empty items array. Do not \
fabricate content to avoid returning an empty array.
"""


def extract_from_file(client: anthropic.Anthropic, jurisdiction: str, raw_text: str) -> list[dict]:
    if not raw_text.strip():
        return []

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Jurisdiction: {jurisdiction}\n\n"
                    f"Source document:\n---\n{raw_text}\n---\n\n"
                    "Extract all labeling-requirement provisions following the system rules."
                ),
            }
        ],
    )

    text_block = next(b for b in response.content if b.type == "text")
    parsed = json.loads(text_block.text)
    return parsed["items"]


def build_regulations() -> list[Regulation]:
    client = anthropic.Anthropic()
    regulations: list[Regulation] = []

    for filename, jurisdiction in FILES.items():
        path = DATA_DIR / filename
        raw_text = path.read_text(encoding="utf-8") if path.exists() else ""

        if not raw_text.strip():
            print(f"[{jurisdiction}] {filename} is empty -- no regulations extracted "
                  f"(will show up as missing data).")
            continue

        print(f"[{jurisdiction}] extracting from {filename} ({len(raw_text)} chars)...")
        items = extract_from_file(client, jurisdiction, raw_text)
        print(f"[{jurisdiction}] extracted {len(items)} labeling-requirement record(s).")

        for i, item in enumerate(items, start=1):
            article_slug = (item.get("article") or f"item{i}").strip()
            article_slug = "".join(c if c.isalnum() else "-" for c in article_slug).strip("-")
            reg_id = f"{jurisdiction}-{article_slug or i}-{i}"
            regulations.append(
                Regulation(
                    id=reg_id,
                    jurisdiction=jurisdiction,
                    article=item.get("article"),
                    title=item.get("title"),
                    text=item["text"],
                    source_url=item.get("source_url"),
                    effective_date=item.get("effective_date"),
                    source_type=item.get("source_type", "verbatim_regulation"),
                    topic=item.get("topic"),
                    notes=item.get("notes"),
                )
            )

    return regulations


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        print(
            "No ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN set in the environment and no "
            "active `ant auth login` profile was assumed. Set one of these before running "
            "extraction.",
            file=sys.stderr,
        )

    regulations = build_regulations()
    OUTPUT_PATH.write_text(
        json.dumps([r.to_dict() for r in regulations], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nWrote {len(regulations)} regulation record(s) to {OUTPUT_PATH}")

    jurisdictions_present = {r.jurisdiction for r in regulations}
    from models import JURISDICTIONS

    missing = [j for j in JURISDICTIONS if j not in jurisdictions_present]
    if missing:
        print(f"No data available for: {', '.join(missing)} "
              f"(empty or missing source file -- not fabricated).")


if __name__ == "__main__":
    main()
