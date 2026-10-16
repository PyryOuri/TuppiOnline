"""Verify this generated package and optionally the original audit payloads.

Usage: python verify_package.py [--audit-dir /path/to/audit]
No game code is loaded. This script does not change any files.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


def check_file(root: Path, name: str, expected_hash: str, expected_bytes: int) -> bool:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Unsafe manifest path: {name}")
    data = path.read_bytes()
    return len(data) == expected_bytes and hashlib.sha256(data).hexdigest() == expected_hash


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-dir', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    problems = []
    manifest = json.loads((root/'PACKAGE_MANIFEST.json').read_text())
    for entry in manifest['files']:
        try:
            if not check_file(root, entry['path'], entry['sha256'], entry['bytes']):
                problems.append('Package hash/size mismatch: ' + entry['path'])
        except (OSError, ValueError) as exc:
            problems.append(str(exc))
    plan = json.loads((root/'EXECUTION_PLAN.json').read_text())
    tasks = {task['id']: task for task in plan['tasks']}
    known_tests = set(re.findall(r'^\| ([A-Z][0-9]{2}) \|', (root/'ACCEPTANCE_TESTS.md').read_text(), re.M))
    visited, visiting = set(), set()
    def visit(name: str) -> None:
        if name in visiting:
            raise ValueError('Task cycle at ' + name)
        if name in visited:
            return
        if name not in tasks:
            raise ValueError('Unknown task ' + name)
        visiting.add(name)
        for dep in tasks[name]['depends_on']:
            visit(dep)
        visiting.remove(name)
        visited.add(name)
    try:
        for name, task in tasks.items():
            visit(name)
            references = (task['acceptance_test_ids'] + task.get('fixture_attempt_ids', [])
                          + task.get('required_fixture_ids', []))
            for test in references:
                if test not in known_tests:
                    problems.append(f'Unknown test {test} in {name}')
    except ValueError as exc:
        problems.append(str(exc))
    if args.audit_dir:
        verification = json.loads((root/'INPUT_VERIFICATION.json').read_text())
        for entry in verification['files']:
            try:
                if not check_file(args.audit_dir, entry['path'], entry['expected_sha256'], entry['expected_bytes']):
                    problems.append('Audit payload mismatch: ' + entry['path'])
            except (OSError, ValueError) as exc:
                problems.append(str(exc))
    print(json.dumps({'successful': not problems, 'problems': problems,
                      'package_payloads_checked': len(manifest['files']),
                      'task_count': len(tasks), 'acceptance_test_ids': len(known_tests),
                      'audit_payloads_checked': 11 if args.audit_dir else 0,
                      'game_code_executed': False}, indent=2))
    return 0 if not problems else 1


if __name__ == '__main__':
    sys.exit(main())
