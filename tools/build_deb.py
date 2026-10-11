#!/usr/bin/env python3
"""Build/check a small architecture-all .deb using Debian's SYSTEM Python/Qt.

User/CI-run only. No apt, pip, sudo, tag or release is performed.
"""
import argparse
from datetime import datetime, timezone
import json
import os
import platform
from pathlib import Path
import subprocess
import sys

import linux_release as packages
from linux_release import ReleaseError
from release_source import version_from_source

ROOT = Path(__file__).resolve().parents[1]


def environment(home=None):
    env = os.environ.copy()
    for key in ('PYTHONPATH', 'PYTHONHOME', 'LD_LIBRARY_PATH', 'QT_PLUGIN_PATH',
                'QT_QPA_PLATFORM_PLUGIN_PATH', 'APPDIR', 'APPIMAGE'):
        env.pop(key, None)
    env.update(QT_QPA_PLATFORM='offscreen', LANG='C.UTF-8', LC_MESSAGES='C',
               PYTHONIOENCODING='utf-8')
    if home is not None:
        env.update(HOME=str(home), APPDATA=str(home / 'appdata'), XDG_CONFIG_HOME=str(home / 'config'))
    return env


def run(arguments, *, cwd=ROOT, env=None):
    result = subprocess.run(list(map(str, arguments)), cwd=cwd, env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=180)
    if result.returncode:
        raise ReleaseError(f'{arguments[0]} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}')
    return result.stdout


def probe_system(version):
    runtime = json.loads(run(['/usr/bin/python3', '-E', '-s', ROOT / 'source/convertall.py',
                              '--runtime-info'], env=environment()))
    packages.validate_debian_runtime(runtime, version)
    return runtime


def check_extracted(directory, work, version):
    packages.verify_thin_deb_payload(directory)
    home = work / 'test-home'
    home.mkdir()
    env = environment(home)
    launcher = directory / 'usr/bin/convertall'
    def launch(*arguments):
        return run([launcher, *arguments], cwd=home, env=env)
    runtime = json.loads(launch('--runtime-info'))
    packages.validate_debian_runtime(runtime, version)
    qt_path = Path(runtime['qt_translations_path']).resolve()
    if qt_path.is_relative_to(directory.resolve()):
        raise ReleaseError('Thin .deb used bundled Qt translations instead of the system package')
    expected = [('1', 'in', 'cm', 2.54), ('0', 'C', 'F', 32.0),
                ('30', 'dBm', 'W', 1.0), ('1', 'kWh', 'J', 3600000.0)]
    for value, source, target, result in expected:
        text = launch('-q', value, source, target)
        actual = float(text.split('=', 1)[1].strip().split()[0])
        if abs(actual - result) > 1e-8 * abs(result):
            raise ReleaseError(f'Wrong native Debian conversion: {text}')
    if launch('--test-all').count('All units pass tests') != 7:
        raise ReleaseError('Not every native Debian catalogue passed')
    for locale in ('fr_FR.UTF-8', 'ca_ES.UTF-8', 'sv_SE.UTF-8'):
        env['LC_MESSAGES'] = locale
        text = launch('--test')
        if 'Warning' in text or 'All units pass tests' not in text:
            raise ReleaseError(f'Native Debian translations missing: {locale}')
    env['LC_MESSAGES'] = 'C'
    if 'GUI smoke test passed' not in launch('--gui-smoke-test'):
        raise ReleaseError('Native Debian GUI/resources failed')
    return {'status': 'PASS', 'runtime': runtime, 'qt_platform': 'offscreen',
            'tests': ['runtime-origin', 'four-conversions', 'seven-catalogues',
                      'system-qtbase/app-translations', 'gui-resources'],
            'manual_installation_tested': False}


def build(output, work, maintainer):
    commit = run(['git', 'rev-parse', 'HEAD']).strip()
    if run(['git', 'status', '--porcelain']).strip():
        raise ReleaseError('Thin Debian release requires a clean committed tree')
    if os.environ.get('GITHUB_SHA', commit) != commit:
        raise ReleaseError('Native Debian checkout differs from GITHUB_SHA')
    version = version_from_source((ROOT / 'source/convertall.py').read_text(encoding='utf-8'))
    packages.deb_control(version, maintainer, 1)
    probe_system(version)  # Do not validate with the wheel venv.
    output, work = Path(output).resolve(), Path(work).resolve()
    if any(path == ROOT or ROOT.is_relative_to(path) for path in (output, work)):
        raise ReleaseError('Use dedicated output/work directories, never the repository root/parent')
    work.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=True)
    stage = packages.stage_deb(work / 'stage', ROOT, version, maintainer)
    payload = {name: digest for name, digest in packages.file_hashes(stage).items()
               if not name.startswith('DEBIAN/')}
    run(['desktop-file-validate', stage / 'usr/share/applications/convertall.desktop'])
    deb = output / f'convertall_{version}-1_all.deb'
    if deb.exists():
        raise ReleaseError('Debian output already exists; no overwrite is performed')
    env = environment()
    env['SOURCE_DATE_EPOCH'] = run(['git', 'show', '-s', '--format=%ct', commit]).strip()
    run(['dpkg-deb', '--root-owner-group', '-Zxz', '-z9', '--build', stage, deb], env=env)
    extracted = work / 'extracted'
    run(['dpkg-deb', '--extract', deb, extracted])
    packages.verify_payload(extracted, payload)
    checks = check_extracted(extracted, work, version)
    if commit != run(['git', 'rev-parse', 'HEAD']).strip() or run(['git', 'status', '--porcelain']).strip():
        raise ReleaseError('Git inputs changed during native Debian packaging')
    report = {**checks, 'version': version, 'source_commit': commit,
              'package': deb.name, 'architecture': 'all', 'runtime_profile': 'debian-system-qt',
              'bundled_runtime': False, 'depends': list(packages.DEBIAN_DEPENDENCIES),
              'package_sha256': packages.sha256(deb), 'package_bytes': deb.stat().st_size,
              'payload_sha256': payload, 'build_os_release': platform.freedesktop_os_release()}
    report_path = output / 'native-deb-validation.json'
    packages.write_file(report_path, json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(f'PASS thin Debian package: {deb}\nBytes: {deb.stat().st_size}\nReport: {report_path}')
    return deb, report_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-system', action='store_true', help='check native Qt dependencies only')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist/debian')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + f'-{os.getpid()}'
    parser.add_argument('--work-dir', type=Path, default=ROOT / 'build/debian' / stamp)
    parser.add_argument('--maintainer', help='public package identity: Name <email>')
    args = parser.parse_args()
    try:
        if args.probe_system:
            version = version_from_source((ROOT / 'source/convertall.py').read_text(encoding='utf-8'))
            print(json.dumps(probe_system(version), ensure_ascii=False))
        else:
            if not args.maintainer:
                raise ReleaseError('Provide --maintainer "Name <email>"')
            build(args.output_dir, args.work_dir, args.maintainer)
        return 0
    except (ReleaseError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        print(f'Native Debian package FAILED: {error}\n'
              'Required system dependencies: python3-pyqt6 python3-pyqt6.sip qt6-translations-l10n',
              file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
