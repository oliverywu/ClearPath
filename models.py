"""Data model for a single extracted labeling-requirement record.

Kept as a plain dataclass (not pydantic) so the project has minimal
dependencies -- only the `anthropic` SDK is required to run the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional


# Valid jurisdiction tags. Kept as a tuple (not an enum) so extraction code
# can validate against it with a simple `in` check.
JURISDICTIONS = ("US", "EU", "Japan", "Canada")

# How the "text" field relates to the authoritative regulation. Extraction
# must set this honestly based on what the source file itself claims --
# never assume a file is verbatim law just because it looks formal.
SOURCE_TYPES = (
    "verbatim_regulation",  # text is quoted directly from the official regulation/statute
    "secondary_summary",    # text is a summary of the regulation from a secondary source (e.g. a law firm article)
    "translation",          # text is a working translation of a non-English official text
)


@dataclass
class Regulation:
    id: str                         # stable id, e.g. "US-312.6-1"
    jurisdiction: str                # one of JURISDICTIONS
    article: Optional[str]           # article/section number/citation, e.g. "21 CFR 312.6" -- null if not stated
    title: Optional[str]             # short title of the provision, if the source states one
    text: str                        # verbatim excerpt from the *source file* (never paraphrased, never invented)
    source_url: Optional[str]        # URL as literally given in the source file, else null
    effective_date: Optional[str]    # date as literally given in the source file, else null
    source_type: str                 # one of SOURCE_TYPES
    topic: Optional[str]             # short topic tag, e.g. "storage conditions", "mandatory label content"
    notes: Optional[str]             # caveats carried over from the source file (verification status, etc.)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Regulation":
        return Regulation(
            id=d["id"],
            jurisdiction=d["jurisdiction"],
            article=d.get("article"),
            title=d.get("title"),
            text=d["text"],
            source_url=d.get("source_url"),
            effective_date=d.get("effective_date"),
            source_type=d.get("source_type", "verbatim_regulation"),
            topic=d.get("topic"),
            notes=d.get("notes"),
        )


# JSON Schema used for Claude structured outputs during extraction.
# One call returns an array of these for a given source file.
EXTRACTION_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "article": {
            "type": ["string", "null"],
            "description": "Article/section number or citation exactly as it appears in the source text (e.g. '21 CFR 312.6', 'Article 16, Paragraph 1'). Null if the source does not give one.",
        },
        "title": {
            "type": ["string", "null"],
            "description": "Short title of the provision if the source text states one. Null otherwise.",
        },
        "text": {
            "type": "string",
            "description": "The labeling-requirement text, quoted/extracted verbatim from the provided source document. Never paraphrase and never add content not present in the source.",
        },
        "source_url": {
            "type": ["string", "null"],
            "description": "URL exactly as it appears in the source document for this provision. Null if no URL is given.",
        },
        "effective_date": {
            "type": ["string", "null"],
            "description": "Effective/version date exactly as it appears in the source document. Null if none is given.",
        },
        "source_type": {
            "type": "string",
            "enum": list(SOURCE_TYPES),
            "description": "Whether `text` is verbatim law, a secondary-source summary, or a translation -- based on what the source document itself states about its own provenance.",
        },
        "topic": {
            "type": ["string", "null"],
            "description": "Short topic tag for this requirement, e.g. 'mandatory label content', 'storage conditions', 'prohibited label content'.",
        },
        "notes": {
            "type": ["string", "null"],
            "description": "Any caveat the source document states about this content (e.g. 'requires verification against official text', 'not verbatim legislation'). Null if none.",
        },
    },
    "required": ["article", "title", "text", "source_url", "effective_date", "source_type", "topic", "notes"],
    "additionalProperties": False,
}

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": EXTRACTION_ITEM_SCHEMA,
            "description": "All labeling-requirement provisions found in the source document. Empty array if none are present.",
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}
