"""Initialize or migrate the canonical database for the integrated application.

    python -m apps.api.init_db --db ../.local/cleared.sqlite3 --fixture data/demo/trial_logistics.json [--reset]

Creates the database if needed, applies schema migrations, seeds the synthetic demo
baseline on first run, calculates proposals for open disruptions and prints a summary.
--reset replaces the active demo dataset (historical plans and audit are kept).
"""
import argparse
import json
from pathlib import Path

from .integrated import IntegratedService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--fixture', required=True)
    parser.add_argument('--reset', action='store_true')
    args = parser.parse_args()
    fresh = not Path(args.db).exists()
    service = IntegratedService(args.db, args.fixture)
    if args.reset and not fresh:
        service.reset(json.loads(Path(args.fixture).read_text(encoding='utf-8')))
    plan = service.frontend.current_plan()
    print(json.dumps({'database': str(Path(args.db).resolve()), 'created': fresh, 'reset': bool(args.reset and not fresh),
                      'schema_version': service.repo.schema_version(), 'current_plan_id': plan['planId'],
                      'current_plan_version': plan['version'], 'events': len(service.repo.events())}))
    service.repo.close()


if __name__ == '__main__':
    main()
