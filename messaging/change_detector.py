"""Simulated regulation-change detection.

There is no live feed of regulatory changes in this v1 -- this module
simulates detection by diffing the current regulations.json against a
previously saved snapshot (regulations_snapshot.json), keyed by regulation
id. To "simulate" a change: edit a data/*.txt file, re-run
extract_regulations.py, then run `python change_detector.py`.

Run `python change_detector.py --snapshot` to save the current
regulations.json as the new baseline snapshot (e.g. right after extraction,
so the next run has something to diff against).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from models import Regulation
from retrieval import load_regulations

REGULATIONS_PATH = Path(__file__).parent / "regulations.json"
SNAPSHOT_PATH = Path(__file__).parent / "regulations_snapshot.json"


@dataclass
class ChangeReport:
    added: list[Regulation]
    removed: list[Regulation]
    modified: list[tuple[Regulation, Regulation]]  # (old, new)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.modified)

    def format(self) -> str:
        if not self.has_changes:
            return "No changes detected since the last snapshot."

        lines: list[str] = []
        if self.added:
            lines.append(f"Added ({len(self.added)}):")
            for r in self.added:
                lines.append(f"  + [{r.jurisdiction}] {r.article or r.id}: {r.title or r.text[:80]}")
        if self.removed:
            lines.append(f"Removed ({len(self.removed)}):")
            for r in self.removed:
                lines.append(f"  - [{r.jurisdiction}] {r.article or r.id}: {r.title or r.text[:80]}")
        if self.modified:
            lines.append(f"Modified ({len(self.modified)}):")
            for old, new in self.modified:
                lines.append(f"  * [{new.jurisdiction}] {new.article or new.id}")
                if old.text != new.text:
                    lines.append(f"      text changed")
                if old.effective_date != new.effective_date:
                    lines.append(f"      effective_date: {old.effective_date!r} -> {new.effective_date!r}")
                if old.source_url != new.source_url:
                    lines.append(f"      source_url: {old.source_url!r} -> {new.source_url!r}")
        return "\n".join(lines)


def detect_changes(
    old_regulations: list[Regulation],
    new_regulations: list[Regulation],
) -> ChangeReport:
    old_by_id = {r.id: r for r in old_regulations}
    new_by_id = {r.id: r for r in new_regulations}

    added = [r for rid, r in new_by_id.items() if rid not in old_by_id]
    removed = [r for rid, r in old_by_id.items() if rid not in new_by_id]
    modified = [
        (old_by_id[rid], new_by_id[rid])
        for rid in old_by_id.keys() & new_by_id.keys()
        if old_by_id[rid] != new_by_id[rid]
    ]

    return ChangeReport(added=added, removed=removed, modified=modified)


def save_snapshot(regulations: list[Regulation], path: Path = SNAPSHOT_PATH) -> None:
    path.write_text(
        json.dumps([r.to_dict() for r in regulations], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="Save the current regulations.json as the new baseline snapshot instead of diffing.",
    )
    args = parser.parse_args()

    current = load_regulations(REGULATIONS_PATH)

    if args.snapshot:
        save_snapshot(current)
        print(f"Saved snapshot of {len(current)} regulation(s) to {SNAPSHOT_PATH}")
        return

    if not SNAPSHOT_PATH.exists():
        print(
            f"No snapshot found at {SNAPSHOT_PATH}. Run `python change_detector.py --snapshot` "
            "first to establish a baseline.",
            file=sys.stderr,
        )
        sys.exit(1)

    previous = load_regulations(SNAPSHOT_PATH)
    report = detect_changes(previous, current)
    print(report.format())


if __name__ == "__main__":
    main()
