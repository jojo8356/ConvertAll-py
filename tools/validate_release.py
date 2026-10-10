#!/usr/bin/env python3
"""Qt5 release gate: pinned environment, tests, coverage and provenance.

Usage: python tools/validate_release.py
Reports go to build/test-results (ignored by Git). Never publishes anything.
"""
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def expected_packages():
    return {'PyQt5': '5.15.11', 'PyQt5-sip': '12.20.0',
            'PyQt5-Qt5': '5.15.2' if sys.platform == 'win32' else '5.15.19',
            'pytest': '9.1.1', 'pytest-qt': '4.5.0',
            'pytest-cov': '7.1.0', 'coverage': '7.16.2'}


def input_hashes():
    paths = []
    for name in ('source', 'data', 'icons', 'translations', 'doc', 'docs',
                 'tests', 'tools', 'win', '.github'):
        paths += [p for p in (ROOT / name).rglob('*') if p.is_file()
                  and '__pycache__' not in p.parts and p.suffix != '.pyc']
    paths += [ROOT / name for name in ('install.py', 'uninstall.py', 'README.md',
                                      'requirements-qt5.txt', 'requirements-test.txt',
                                      'requirements-build.txt', 'pytest.ini', '.coveragerc',
                                      '.gitignore', '.gitattributes', 'convertall.desktop')]
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def main():
    if not (3, 10) <= sys.version_info[:2] <= (3, 14):
        print('Release validation requires Python 3.10–3.14', file=sys.stderr)
        return 2
    try:
        installed = {name: metadata.version(name) for name in expected_packages()}
    except metadata.PackageNotFoundError as error:
        print(f'{error}\nInstall requirements-test.txt in a fresh venv.', file=sys.stderr)
        return 2
    if installed != expected_packages():
        print(f'Incorrect release environment: {installed}\nExpected: {expected_packages()}', file=sys.stderr)
        return 2
    if subprocess.run([sys.executable, '-m', 'pip', 'check'], cwd=ROOT).returncode:
        return 2
    environment = os.environ.copy()
    environment.setdefault('QT_QPA_PLATFORM', 'offscreen')
    environment['QT_API'] = 'pyqt5'
    results = ROOT / 'build/test-results'
    results.mkdir(parents=True, exist_ok=True)
    before = input_hashes()
    command = [sys.executable, '-m', 'pytest', '-q', '--cov=source', '--cov-branch',
               '--cov-report=term-missing:skip-covered',
               '--cov-report=xml:build/test-results/coverage.xml',
               '--cov-report=json:build/test-results/coverage.json',
               '--junitxml=build/test-results/junit.xml']
    result = subprocess.run(command, cwd=ROOT, env=environment)
    unchanged = before == input_hashes()
    if not unchanged:
        print('Files changed during validation: rerun on the final tree.', file=sys.stderr)
    commit = None
    dirty = None
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                         text=True).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'],
                                              cwd=ROOT, text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        pass  # extracted archives may legitimately lack .git
    report = {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'python': sys.version, 'platform': sys.platform, 'packages': installed,
              'commit': commit, 'working_tree_dirty': dirty,
              'input_sha256': before, 'inputs_unchanged': unchanged,
              'pytest_exit_code': result.returncode}
    (results / 'validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return result.returncode if result.returncode else (0 if unchanged else 1)


if __name__ == '__main__':
    sys.exit(main())
