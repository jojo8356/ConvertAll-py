#!/usr/bin/env python3
"""Smoke test a native PyInstaller flat onedir Qt5 bundle.

python tools/check_bundle.py dist/convertall
Runs both the console/GUI entry points and checks all shipped catalogues.
Preferences are isolated; command timeouts turn missing dialogs/loops into errors.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'source'))
# Import only version metadata; no QtWidgets/QApplication in the driver.
from convertall import __version__


def check_bundle(directory):
    directory = Path(directory).resolve()
    gui = directory / ('convertall.exe' if sys.platform == 'win32' else 'convertall')
    cli = directory / ('convertall_dos.exe' if sys.platform == 'win32' else 'convertall')
    for path in (gui, cli, directory / 'data/units.dat',
                 directory / 'doc/LICENSE', directory / 'icons/convertall_med.png',
                 directory / 'translations/convertall_fr.qm'):
        if not path.is_file():
            raise RuntimeError(f'Missing bundle resource: {path}')
    if (directory / '_internal').exists():
        raise RuntimeError('Expected the flat --contents-directory=. layout')
    if any(p.name.lower().startswith(('pyqt6', 'pyside')) for p in directory.rglob('*')):
        raise RuntimeError('Another Qt binding leaked into the Qt5 bundle')
    with tempfile.TemporaryDirectory(prefix='convertall-bundle-test-') as temp:
        home = Path(temp)
        env = os.environ.copy()
        env.update({'HOME': temp, 'APPDATA': str(home / 'appdata'),
                    'QT_QPA_PLATFORM': 'offscreen', 'LC_MESSAGES': 'C',
                    'LANG': 'C.UTF-8', 'PYTHONIOENCODING': 'utf-8'})
        def run(program, *args):
            result = subprocess.run([str(program), *args], env=env, cwd=home,
                                    capture_output=True, text=True, encoding='utf-8',
                                    errors='replace', timeout=45)
            if result.returncode:
                raise RuntimeError(f'{program.name} {args}: exit {result.returncode}\n'
                                   f'{result.stdout}\n{result.stderr}')
            return result.stdout
        version = run(cli, '--version').strip()
        if version != f'ConvertAll {__version__} (Qt5)':
            raise RuntimeError(f'Wrong bundle version: {version}')
        cases = [('1', 'in', 'cm', 2.54), ('0', 'C', 'F', 32.0),
                 ('30', 'dBm', 'W', 1.0), ('1', 'kWh', 'J', 3600000.0)]
        for value, source, target, expected in cases:
            text = run(cli, '-q', value, source, target)
            actual = float(text.split('=', 1)[1].strip().split()[0])
            if abs(actual - expected) > 1e-8 * abs(expected):
                raise RuntimeError(f'Wrong frozen conversion: {text}')
        validation = run(cli, '--test-all')
        if validation.count('All units pass tests') != 7:
            raise RuntimeError(f'Not every bundled catalogue was validated:\n{validation}')
        for locale in ('fr_FR.UTF-8', 'ca_ES.UTF-8', 'sv_SE.UTF-8'):
            env['LC_MESSAGES'] = locale
            validation = run(cli, '--test')
            if 'Warning' in validation or 'All units pass tests' not in validation:
                raise RuntimeError(f'Frozen translations not loadable: {locale}\n{validation}')
        env['LC_MESSAGES'] = 'C'
        if 'GUI smoke test passed' not in run(cli, '--gui-smoke-test'):
            raise RuntimeError('Console entry point did not run the Qt widget smoke test')
        run(gui, '--gui-smoke-test')
    print(f'Qt5 {__version__} bundle passed: CLI, 7 catalogues, translations, GUI/resources')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    try:
        check_bundle(args.directory)
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f'Bundle validation failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
