#!/usr/bin/env python3
# Bump the project version everywhere it is pinned, and check that the pinned
# copies agree. The same coherence rules are asserted by
# tests/test_packaging.py::test_versions_are_consistent_without_rewriting_history,
# so a missed spot fails CI: this tool exists to avoid that round trip.
#
# Usage :
#   python3 tools/bump_version.py --check           état de cohérence actuel
#   python3 tools/bump_version.py 0.9.2 --dry-run   montre les changements
#   python3 tools/bump_version.py 0.9.2             applique
#
# It never commits, tags, pushes or touches a release. Historical versions stay
# untouched: only the *first* version number of the HTML manuals is the header,
# and RELEASE_NOTES_<old>.md files are kept as history.
import argparse
import re
import sys
from pathlib import Path

DESCRIPTION = ('met à jour la version partout où elle est épinglée, ou vérifie que les copies '
               'sont cohérentes')

ROOT = Path(__file__).resolve().parent.parent
# The manual header is the first 0.x.y of the file: a bare x.y.z pattern would
# match the generator meta tag first on the translated manuals (LibreOffice
# 5.4.6, for instance), which is exactly what the packaging test avoids.
HEADER = re.compile(r'0\.\d+\.\d+')
VERSION = re.compile(r'\d+\.\d+\.\d+')

# Files whose version is the *current* one. 'first' replaces the manual header
# only (older versions are mentioned later in the same file on purpose).
ALL_FIRST = ('doc/README*.html', 'docs/README*.html')
ALL_EVERYWHERE = ('tests/test_cli.py', 'tests/test_gui.py', 'tests/test_packaging.py')
ISS_KEYS = ('AppVersion=', 'convertall-', '-install')


def read(path):
    # newline='' preserves CRLF: the Inno Setup recipes are CRLF files, and
    # letting text mode translate them rewrites every line of the file.
    with (ROOT / path).open(encoding='utf-8', newline='') as stream:
        return stream.read()


def write(path, text):
    with (ROOT / path).open('w', encoding='utf-8', newline='') as stream:
        stream.write(text)


def source_version():
    match = re.search(r"^__version__\s*=\s*'([^']+)'", read('source/convertall.py'), re.M)
    if not match:
        raise SystemExit('source/convertall.py has no __version__ line')
    return match.group(1)


def html_manuals():
    for pattern in ALL_FIRST:
        for path in sorted(ROOT.glob(pattern)):
            yield path.relative_to(ROOT)


def iss_files():
    for path in sorted((ROOT / 'win').glob('*.iss')):
        yield path.relative_to(ROOT)


def plan(old, new):
    """Return [(path, new_text)] for every file that must change."""
    changes = []
    for path in html_manuals():
        text = read(path)
        match = HEADER.search(text)
        if match is None:
            raise SystemExit(f'{path}: no 0.x.y version found in the manual header')
        if match.group() != new:
            changes.append((path, text[:match.start()] + new + text[match.end():]))
    for path in iss_files():
        text = read(path)
        replaced = text.replace(f'AppVersion={old}', f'AppVersion={new}')
        replaced = replaced.replace(f'convertall-{old}-install', f'convertall-{new}-install')
        if replaced != text:
            changes.append((path, replaced))
    for path in ALL_EVERYWHERE:
        text = read(path)
        replaced = text.replace(f"'{old}'", f"'{new}'").replace(f'-{old}-', f'-{new}-')
        if replaced != text:
            changes.append((path, replaced))
    text = read('source/convertall.py')
    replaced = text.replace(f"__version__ = '{old}'", f"__version__ = '{new}'")
    if replaced != text:
        changes.append(('source/convertall.py', replaced))
    return changes


def release_notes(old, new):
    """A starting point for the human changelog, not a generated document."""
    import subprocess

    def git(*arguments):
        return subprocess.run(['git', *arguments], cwd=ROOT, capture_output=True,
                              text=True, check=False).stdout

    if git('rev-parse', '--verify', '--quiet', f'refs/tags/v{old}').strip():
        lines = git('log', '--oneline', '--no-merges', f'v{old}..HEAD')
        origin = f'Contenu depuis v{old}'
    else:
        # A local clone may not have the tag (it was created by the release).
        lines = git('log', '--oneline', '--no-merges', '-25')
        origin = (f'Tag v{old} absent de ce clone : les 25 derniers commits ; '
                  f'faites « git fetch --tags » pour la liste exacte')
    body = '\n'.join(f'- {line.split(" ", 1)[1]}' for line in lines.splitlines() if ' ' in line)
    return (f'# ConvertAll {new} — notes de version\n\n'
            f'À compléter avant publication. {origin} :\n\n'
            f'{body or "- (aucun commit listé)"}\n\n'
            '## Points à vérifier à la main\n\n'
            '- bureau réel, DPI et GPU : non certifiés par la CI ;\n'
            '- installation, mise à niveau et désinstallation du `.deb` ;\n'
            '- AppImage : double-clic (AppImageLauncher ne lit pas le zstd, voir '
            'doc/RELEASE_LINUX_FR.md) ;\n'
            '- licences et attributions.\n')


def check(expected=None):
    """The coherence rules of the packaging test, without pytest."""
    problems = []
    current = source_version()
    if expected and current != expected:
        problems.append(f'source/convertall.py pins {current}, expected {expected}')
    from release_source import version_from_source          # noqa: E402
    derived = version_from_source(read('source/convertall.py'))
    if derived != current:
        problems.append(f'release_source derives {derived} but __version__ is {current}')
    for path in iss_files():
        text = read(path)
        if f'AppVersion={current}' not in text:
            problems.append(f'{path}: AppVersion is not {current}')
        if f'convertall-{current}-install' not in text:
            problems.append(f'{path}: installer file name is not {current}')
    for path in html_manuals():
        match = HEADER.search(read(path))
        if match is None or match.group() != current:
            problems.append(f'{path}: manual header is not {current}')
    for path in ALL_EVERYWHERE:
        if f"'{current}'" not in read(path):
            problems.append(f'{path}: does not pin {current}')
    if not (ROOT / f'doc/RELEASE_NOTES_{current}.md').is_file():
        problems.append(f'doc/RELEASE_NOTES_{current}.md is missing')
    return current, problems


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('version', nargs='?', help='nouvelle version, ex. 0.9.2')
    parser.add_argument('--check', action='store_true', help='vérifie la cohérence')
    parser.add_argument('--dry-run', action='store_true', help='montre sans écrire')
    arguments = parser.parse_args()
    sys.path.insert(0, str(ROOT / 'tools'))

    if arguments.check or not arguments.version:
        current, problems = check(arguments.version)
        print(f'Version actuelle : {current}')
        if problems:
            print('Incohérences :')
            for problem in problems:
                print(f'  - {problem}')
            return 1
        print('Cohérence : OK (source, .iss, manuels HTML, tests, notes de version)')
        return 0

    new = arguments.version
    if not VERSION.fullmatch(new):
        print(f'Version invalide : {new} (attendu x.y.z)', file=sys.stderr)
        return 2
    old = source_version()
    if old == new:
        print(f'La version est déjà {new} ; rien à faire.')
        return 0
    for path, text in plan(old, new):
        previous = HEADER.search(read(path))
        print(f'  {path}' + (f'   ({previous.group()} -> {new})' if previous else ''))
    if not (ROOT / f'doc/RELEASE_NOTES_{new}.md').is_file():
        print(f'  doc/RELEASE_NOTES_{new}.md (nouveau, à compléter)')
    if arguments.dry_run:
        print(f'\nRien écrit (--dry-run). {old} -> {new}')
        return 0
    for path, text in plan(old, new):
        write(path, text)
    notes = f'doc/RELEASE_NOTES_{new}.md'
    if not (ROOT / notes).is_file():
        write(notes, release_notes(old, new))
    current, problems = check(new)
    print(f'\n{old} -> {new}')
    if problems:
        print('À corriger :')
        for problem in problems:
            print(f'  - {problem}')
        return 1
    print('Cohérence vérifiée après modification.')
    print('Prochaine étape, à vous : relire git diff, puis committer.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
