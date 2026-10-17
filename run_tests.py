"""Run every test suite in the repository and print a summary.

    python run_tests.py            # all suites
    python run_tests.py --fast     # skip browser and fresh-clone tests
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SUITES = [
    ('planner + integrated API', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'], ROOT / 'planner', False),
    ('planner evals (ship-by accuracy, citations)', [sys.executable, 'evals/run.py'], ROOT / 'planner', False),
    ('messaging (Anna)', [sys.executable, '-m', 'pytest', '-q'], ROOT / 'messaging', False),
    ('browser end-to-end', [sys.executable, '-m', 'unittest', '-v', 'tests.e2e.test_browser_workflow'], ROOT, True),
    ('fresh clone startup', [sys.executable, '-m', 'unittest', '-v', 'tests.e2e.test_fresh_clone'], ROOT, True),
]


def main():
    fast = '--fast' in sys.argv
    results = []
    for name, command, cwd, slow in SUITES:
        if fast and slow:
            results.append((name, 'skipped', 0))
            continue
        print(f'\n=== {name}: {" ".join(command[1:])} (in {cwd.relative_to(ROOT) or "."})', flush=True)
        start = time.time()
        code = subprocess.run(command, cwd=cwd).returncode
        results.append((name, 'passed' if code == 0 else f'FAILED ({code})', time.time() - start))
    print('\n=== Summary')
    for name, status, seconds in results:
        print(f'  {status:<12} {name} ({seconds:.0f}s)')
    sys.exit(0 if all(status in ('passed', 'skipped') for _, status, _ in results) else 1)


if __name__ == '__main__':
    main()
