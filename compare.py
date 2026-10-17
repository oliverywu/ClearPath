"""Cross-jurisdiction comparison of labeling requirements.

Retrieval is run independently per jurisdiction (never pooled) so a
jurisdiction with no matching passage is reported as missing, rather than
silently backfilled from another jurisdiction's results.
"""

from __future__ import annotations

import anthropic

from models import Regulation
from retrieval import search_all_jurisdictions

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """\
You compare pharmaceutical labeling requirements across jurisdictions for a regulatory \
agent used in international clinical-trial drug shipments.

You will be given, for each jurisdiction, either a set of retrieved regulation passages or \
an explicit note that none were found. Rules:
1. Base every claim ONLY on the passages given to you. Never use outside knowledge of these \
regulations, even if you believe you know the actual legal requirement.
2. For any jurisdiction with no retrieved passages, state plainly that no matching requirement \
was found in the dataset for that jurisdiction -- do not guess what it might say.
3. When a passage is marked as a secondary-source summary or a translation rather than verbatim \
law, say so and note it should be verified against the official text before being relied on.
4. Cite the jurisdiction and article/section for every claim you make.
5. Produce a short side-by-side comparison, then a one-paragraph summary of the most important \
differences you can actually support from the given passages.
"""


def _format_passages(jurisdiction: str, regs: list[Regulation]) -> str:
    if not regs:
        return f"### {jurisdiction}\nNo matching passages found in the dataset.\n"

    lines = [f"### {jurisdiction}"]
    for r in regs:
        lines.append(f"- Article/Section: {r.article or 'unspecified'}")
        lines.append(f"  Source type: {r.source_type}")
        if r.notes:
            lines.append(f"  Notes: {r.notes}")
        lines.append(f"  Text: {r.text}")
    return "\n".join(lines) + "\n"


def compare_topic(
    topic: str,
    client: anthropic.Anthropic | None = None,
    top_k: int = 3,
    regulations: list[Regulation] | None = None,
) -> str:
    """Return a Claude-generated cross-jurisdiction comparison for `topic`.

    `topic` is a free-text query, e.g. "storage conditions on the label" or
    "mandatory label content". `regulations` defaults to loading
    regulations.json from disk; pass it explicitly in tests.
    """
    client = client or anthropic.Anthropic()
    results = search_all_jurisdictions(topic, regulations, top_k_per_jurisdiction=top_k)

    context = "\n".join(_format_passages(j, regs) for j, regs in results.items())

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Topic to compare: {topic}\n\n"
                    f"Retrieved passages by jurisdiction:\n\n{context}\n\n"
                    "Produce the comparison following the system rules."
                ),
            }
        ],
    )

    return next(b.text for b in response.content if b.type == "text")
