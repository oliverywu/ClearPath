"""Cleared for Takeoff -- interactive regulatory chatbot.

Run with:
    python agent.py

Commands inside the REPL:
    compare <topic>     cross-jurisdiction comparison (e.g. "compare storage conditions")
    jurisdiction <US|EU|Japan|Canada> <question>   ask scoped to one jurisdiction
    check updates        run simulated regulation-change detection against the last snapshot
    exit / quit           leave

Anything else is treated as a free-text question answered only from
retrieved passages in regulations.json.
"""

from __future__ import annotations

import sys

import anthropic
from dotenv import load_dotenv

from models import JURISDICTIONS, Regulation
from retrieval import load_regulations, search
from compare import compare_topic
from change_detector import detect_changes, load_regulations as _load_for_diff, SNAPSHOT_PATH

load_dotenv()

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """\
You are "Cleared for Takeoff", a regulatory assistant for pharmaceutical international \
clinical-trial drug shipments. You answer questions about labeling requirements using ONLY \
the regulation passages given to you in each turn.

Rules you must follow exactly:
1. Never state a regulatory requirement that is not supported by the passages you were given \
this turn. If the passages don't answer the question, say so explicitly -- do not fall back on \
outside/general knowledge of these regulations.
2. Always cite jurisdiction and article/section for every claim.
3. If a passage's source_type is "secondary_summary" or "translation", mention that the passage \
is not verbatim official law/translation and should be verified before being relied on.
4. If no passages were retrieved at all, say plainly that nothing in the dataset matches the \
question, and suggest the user rephrase or that the jurisdiction may have no data loaded.
5. Keep answers focused and cite your sources; do not pad with generic disclaimers beyond what \
rule 3 requires.
"""

# Used for the Photon/iMessage channel only (requirement: short mobile-first
# answers, full citations available on request). The CLI (agent.py's own
# REPL) keeps using SYSTEM_PROMPT above by default.
SYSTEM_PROMPT_CONCISE = """\
You are "Takeoff", a concise supply-chain regulatory assistant answering over iMessage. Answer \
using ONLY the regulation passages given to you this turn.

Rules you must follow exactly:
1. Lead with the direct answer in 1-3 short sentences. No Markdown, no bullet lists, no headers \
-- this is a plain-text text message.
2. Never state a requirement not supported by the passages given this turn. If nothing matches, \
say so plainly in one sentence.
3. End with exactly one line starting with "Sources: " naming jurisdiction and article/section \
for every claim, then "Reply SOURCE for full citations." If a cited passage's source_type is \
"secondary_summary" or "translation", append " (unverified -- verify before relying on it)" to \
that source on this line.
4. Keep the whole reply short -- a few sentences plus the one-line source footer, not a report.
"""


def _format_passages(regs: list[Regulation], jurisdiction: str | None = None) -> str:
    if not regs:
        if jurisdiction:
            return (
                f"No passages were retrieved for jurisdiction={jurisdiction}. This may mean "
                f"there is no data loaded for {jurisdiction} in the dataset, or that no "
                f"loaded record for {jurisdiction} matches this question's wording."
            )
        return "No matching passages were found in the dataset for this question."
    lines = []
    for r in regs:
        lines.append(f"[{r.jurisdiction}] Article/Section: {r.article or 'unspecified'}")
        lines.append(f"  source_type: {r.source_type}")
        if r.notes:
            lines.append(f"  notes: {r.notes}")
        if r.source_url:
            lines.append(f"  source_url: {r.source_url}")
        if r.effective_date:
            lines.append(f"  effective_date: {r.effective_date}")
        lines.append(f"  text: {r.text}")
    return "\n".join(lines)


def answer_question(
    client: anthropic.Anthropic,
    question: str,
    regulations: list[Regulation],
    jurisdiction: str | None = None,
    concise: bool = False,
) -> str:
    results = search(question, regulations, jurisdiction=jurisdiction, top_k=5)
    passages = _format_passages(results, jurisdiction=jurisdiction)
    scope_line = f"Jurisdiction scope requested by user: {jurisdiction}\n\n" if jurisdiction else ""
    system_prompt = SYSTEM_PROMPT_CONCISE if concise else SYSTEM_PROMPT

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": f"{scope_line}Question: {question}\n\nRetrieved passages:\n{passages}",
            }
        ],
    )
    return next(b.text for b in response.content if b.type == "text")


def run_check_updates() -> str:
    current = _load_for_diff()
    if not SNAPSHOT_PATH.exists():
        return (
            "No baseline snapshot found yet -- run `python change_detector.py --snapshot` "
            "after your first extraction to establish one, then re-run extraction later to "
            "simulate a regulation change."
        )
    previous = _load_for_diff(SNAPSHOT_PATH)
    report = detect_changes(previous, current)
    return report.format()


def main() -> None:
    regulations = load_regulations()
    if not regulations:
        print(
            "regulations.json is empty or missing -- run `python extract_regulations.py` "
            "first.\n"
        )

    jurisdictions_present = {r.jurisdiction for r in regulations}
    missing = [j for j in JURISDICTIONS if j not in jurisdictions_present]
    if missing:
        print(f"Note: no data loaded for {', '.join(missing)}.\n")

    client = anthropic.Anthropic()

    print("Cleared for Takeoff -- regulatory labeling assistant")
    print("Type a question, 'compare <topic>', 'check updates', or 'exit'.\n")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break

        if user_input.lower() == "check updates":
            print(run_check_updates())
            print()
            continue

        if user_input.lower().startswith("compare "):
            topic = user_input[len("compare "):].strip()
            print(compare_topic(topic, client=client))
            print()
            continue

        jurisdiction = None
        question = user_input
        if user_input.lower().startswith("jurisdiction "):
            rest = user_input[len("jurisdiction "):].strip()
            parts = rest.split(" ", 1)
            candidate = parts[0]
            matched = next((j for j in JURISDICTIONS if j.lower() == candidate.lower()), None)
            if matched and len(parts) > 1:
                jurisdiction = matched
                question = parts[1]
            else:
                print(f"Unknown jurisdiction {candidate!r}. Valid: {', '.join(JURISDICTIONS)}\n")
                continue

        answer = answer_question(client, question, regulations, jurisdiction=jurisdiction)
        print(answer)
        print()


if __name__ == "__main__":
    main()
