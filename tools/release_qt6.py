#!/usr/bin/env python3
"""User-run release: local Linux executable/.deb/AppImage, CI Windows .exe ZIP.

Default: prepare assets only. --draft: create a NON-PUBLISHED GitHub release.
Never installs dependencies, uses sudo, switches branches, pushes, retags,
updates an existing release, or publishes Latest. See doc/RELEASE_LINUX_FR.md.
"""
import argparse
from datetime import datetime, timezone
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

import linux_release as packages
from linux_release import ReleaseError
from release_source import version_from_source

ROOT = Path(__file__).resolve().parents[1]
REPO = 'jojo8356/ConvertAll-py'
BRANCH = 'arena/0adacf84-convertall-py'
WORKFLOW = '.github/workflows/qt6-release.yml'
LOG = None


def command(arguments, *, cwd=ROOT, env=None, timeout=1800, quiet=False):
    arguments = list(map(str, arguments))
    if not quiet:
        print('+ ' + ' '.join(arguments), flush=True)
    result = subprocess.run(arguments, cwd=cwd, env=env, timeout=timeout,
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if LOG is not None:
        with LOG.open('a', encoding='utf-8') as stream:
            stream.write('+ ' + ' '.join(arguments) + '\n' + result.stdout + result.stderr + '\n')
    if not quiet or result.returncode:
        print(result.stdout, end='')
        print(result.stderr, end='', file=sys.stderr)
    if result.returncode:
        raise ReleaseError(f'Command failed ({result.returncode}): {arguments[0]}')
    return result.stdout


def github(endpoint, *, missing_ok=False):
    result = subprocess.run(['gh', 'api', endpoint], cwd=ROOT, capture_output=True,
                            text=True, encoding='utf-8', timeout=90)
    if result.returncode:
        if missing_ok and 'HTTP 404' in result.stderr:
            return None
        raise ReleaseError(f'GitHub request failed: {endpoint}\n{result.stderr}')
    return json.loads(result.stdout)


def git(*arguments):
    return command(['git', *arguments], quiet=True).strip()


def require_clean_sha(commit=None):
    if git('branch', '--show-current') != BRANCH:
        raise ReleaseError(f'Run from the session branch: {BRANCH}')
    if git('status', '--porcelain'):
        raise ReleaseError('Working tree is dirty; commit/push changes and revalidate first')
    head = git('rev-parse', 'HEAD')
    if commit is not None and head != commit:
        raise ReleaseError('HEAD changed during release preparation')
    return head


def validate_ci_run(run, commit):
    if (run.get('head_sha') != commit or run.get('head_branch') != BRANCH
            or run.get('path', '').split('@', 1)[0] != WORKFLOW
            or run.get('event') != 'push'
            or run.get('status') != 'completed' or run.get('conclusion') != 'success'):
        raise ReleaseError('CI run is not a successful push of the exact current SHA/workflow')


def validate_ci_jobs(jobs):
    expected = {f'Tests {os_name} / Python {version} / Qt6'
                for os_name in ('ubuntu-24.04', 'windows-2022')
                for version in ('3.11', '3.12', '3.13', '3.14')}
    expected |= {f'Bundle {os_name} / Qt6' for os_name in ('ubuntu-24.04', 'windows-2022')}
    expected |= {f'Debian native Qt / {suite}' for suite in ('bookworm', 'trixie')}
    passed = {job['name'] for job in jobs
              if job.get('status') == 'completed' and job.get('conclusion') == 'success'}
    if not expected.issubset(passed):
        raise ReleaseError(f'Missing/failed CI jobs: {sorted(expected - passed)}')


def select_ci(commit, run_id, wait):
    if run_id:
        run = github(f'repos/{REPO}/actions/runs/{run_id}')
    else:
        query = urlencode({'branch': BRANCH, 'head_sha': commit, 'event': 'push', 'per_page': 100})
        data = github(f'repos/{REPO}/actions/workflows/qt6-release.yml/runs?{query}')
        candidates = [item for item in data['workflow_runs'] if item['head_sha'] == commit]
        if not candidates:
            raise ReleaseError('No CI run for this SHA. Push this branch and wait for Actions.')
        run = next((item for item in candidates if item['conclusion'] == 'success'), candidates[0])
    if (run.get('head_sha') != commit or run.get('head_branch') != BRANCH
            or run.get('path', '').split('@', 1)[0] != WORKFLOW or run.get('event') != 'push'):
        raise ReleaseError('The selected CI run belongs to another SHA/branch/workflow')
    if run['status'] != 'completed' and wait:
        print(f'Waiting for CI {run["id"]} (no local build has started)...', flush=True)
        command(['gh', 'run', 'watch', run['id'], '--repo', REPO, '--exit-status'])
        run = github(f'repos/{REPO}/actions/runs/{run["id"]}')
    validate_ci_run(run, commit)
    jobs = github(f'repos/{REPO}/actions/runs/{run["id"]}/jobs?per_page=100')['jobs']
    validate_ci_jobs(jobs)
    return run


def download_artifact(run, name, destination):
    artifacts = github(f'repos/{REPO}/actions/runs/{run}/artifacts?per_page=100')['artifacts']
    matches = [item for item in artifacts if item['name'] == name and not item['expired']]
    if len(matches) != 1:
        raise ReleaseError(f'Missing/expired/ambiguous CI artifact: {name}')
    destination.mkdir(parents=True)
    command(['gh', 'run', 'download', run, '--repo', REPO, '--name', name, '--dir', destination])


def validate_tool_pin(pin):
    if (pin.get('repository') not in ('AppImage/appimagetool', 'AppImage/type2-runtime')
            or type(pin.get('asset_id')) is not int or pin['asset_id'] < 1
            or not re.fullmatch(r'[0-9a-f]{64}', pin.get('sha256', ''))
            or Path(pin.get('name', '')).name != pin.get('name')
            or pin.get('name') in ('', '.', '..')):
        raise ReleaseError('Invalid AppImage tool lock')


def appimage_command(tool, runtime, appdir, output, compression):
    """The pinned builder embeds a zstd-only mksquashfs, not the host tool."""
    if compression != 'zstd':
        raise ReleaseError('Pinned appimagetool supports only zstd compression')
    return [tool, '--runtime-file', runtime, '--comp', compression,
            '--no-appstream', appdir, output]


def fetch_tool(pin, destination):
    """No floating latest download: specific asset ID AND expected SHA-256."""
    validate_tool_pin(pin)
    path = destination / pin['name']
    if path.exists():
        raise ReleaseError(f'Download destination already exists: {path}')
    endpoint = f'repos/{pin["repository"]}/releases/assets/{pin["asset_id"]}'
    print(f'Download pinned {pin["name"]}...', flush=True)
    with path.open('wb') as stream:
        result = subprocess.run(['gh', 'api', endpoint, '-H', 'Accept: application/octet-stream'],
                                cwd=ROOT, stdout=stream, stderr=subprocess.PIPE, timeout=300)
    if result.returncode:
        raise ReleaseError('Pinned AppImage asset download failed. It may have been removed; '
                           'do not replace it with an unverified latest binary.\n'
                           + result.stderr.decode('utf-8', errors='replace'))
    if packages.sha256(path) != pin['sha256']:
        raise ReleaseError(f'AppImage tool checksum mismatch: {path.name}; refusing to execute it')
    require_amd64_elf(path)
    path.chmod(0o755)
    return path


def require_amd64_elf(path):
    with Path(path).open('rb') as stream:
        header = stream.read(20)
    if (len(header) < 20 or header[:4] != b'\x7fELF' or header[4:6] != b'\x02\x01'
            or struct.unpack_from('<H', header, 18)[0] != 62):
        raise ReleaseError(f'Expected an x86_64 ELF executable: {path}')


def retry_directories():
    """Local scratch directories used when the work tree cannot self-parse."""
    candidates = [{}]
    shm = Path('/dev/shm')
    if shm.is_dir() and os.access(shm, os.W_OK):
        candidates.append({'dir': shm})
    directories = []
    for extra in candidates:
        try:
            path = Path(tempfile.mkdtemp(prefix='convertall-appimage-', **extra))
        except OSError:
            continue
        if path not in directories:
            directories.append(path)
    return directories


def extract_appimage(image, destination, *, required, expected_sha256=None):
    """Extract an AppImage without FUSE, retrying from a local disk if needed.

    `--appimage-extract` needs no FUSE, but the embedded runtime locates its own
    squashfs by reading the file it was started from. That lookup can fail when
    the work tree sits on a shared, synchronised or otherwise exotic mount, so
    the image is copied to a private temporary directory (TMPDIR, then tmpfs)
    and retried there before the release gives up. Copies are re-verified.
    """
    image, destination = Path(image), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    attempts = [(destination, image)]
    attempts.extend((retry / 'image', retry / image.name) for retry in retry_directories())
    errors = []
    for where, source in attempts:
        try:
            if source != image:
                where.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(image, source)
                source.chmod(0o755)
                if expected_sha256 is not None and packages.sha256(source) != expected_sha256:
                    raise ReleaseError('temporary AppImage copy checksum mismatch')
            command([source, '--appimage-extract'], cwd=where, quiet=True)
            root = where / 'squashfs-root'
            if (root / required).exists():
                return root
            errors.append(f'no {required} after extraction in {where}')
        except ReleaseError as error:
            errors.append(str(error))
            if source == image:
                print(f'Extraction in {where} failed; retrying outside the work tree...',
                      flush=True)
    raise ReleaseError('AppImage could not be extracted: ' + '; '.join(errors)
                       + '\nRun the release from a local filesystem (not a shared or '
                         'synchronised folder); checksum pins stay enforced.')


def maintainer_identity(provided):
    if provided:
        return provided
    def identity(key):
        result = subprocess.run(['git', 'config', '--get', key], cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8', timeout=10)
        if result.returncode not in (0, 1):
            raise ReleaseError(f'Cannot read public Git identity: {key}')
        return result.stdout.strip()
    name, email = identity('user.name'), identity('user.email')
    if not name or not email:
        raise ReleaseError('Set --maintainer "Name <email>" (public .deb metadata)')
    return f'{name} <{email}>'


def tag_target(tag):
    ref = github(f'repos/{REPO}/git/ref/tags/{tag}', missing_ok=True)
    if ref is None:
        return None
    target = ref['object']
    for _ in range(20):
        if target['type'] == 'commit':
            return target['sha']
        if target['type'] != 'tag':
            break
        target = github(f'repos/{REPO}/git/tags/{target["sha"]}')['object']
    raise ReleaseError('Tag cannot be resolved to an immutable commit')


def check_launch(program, label, work, environment, version, *, bundle=None, prefix=()):
    home = work / ('home-' + label)
    home.mkdir()
    env = {**environment, 'HOME': str(home), 'APPDATA': str(home / 'appdata'),
           'XDG_CONFIG_HOME': str(home / 'config'), 'QT_QPA_PLATFORM': 'offscreen',
           'LANG': 'C.UTF-8', 'LC_MESSAGES': 'C', 'PYTHONIOENCODING': 'utf-8'}
    for key in ('PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH',
                'LD_LIBRARY_PATH', 'APPDIR', 'APPIMAGE'):
        env.pop(key, None)
    def launch(*arguments):
        return command([program, *prefix, *arguments], cwd=home, env=env, timeout=180, quiet=True)
    runtime = json.loads(launch('--runtime-info'))
    from check_bundle import validate_runtime_info
    validate_runtime_info(runtime)
    if runtime['version'] != version:
        raise ReleaseError(f'{label}: wrong application version')
    if bundle is not None and not Path(runtime['qt_translations_path']).resolve().is_relative_to(bundle.resolve()):
        raise ReleaseError(f'{label}: Qt translations escaped the packaged bundle')
    text = launch('-q', '1', 'in', 'cm')
    if abs(float(text.split('=', 1)[1].strip().split()[0]) - 2.54) > 1e-10:
        raise ReleaseError(f'{label}: wrong packaged conversion')
    if launch('--test-all').count('All units pass tests') != 7:
        raise ReleaseError(f'{label}: not all seven packaged catalogues passed')
    if 'GUI smoke test passed' not in launch('--gui-smoke-test'):
        raise ReleaseError(f'{label}: packaged Qt widgets failed')
    print(f'PASS {label}: runtime, conversion, 7 catalogues, GUI offscreen', flush=True)
    return {'status': 'PASS', 'runtime': runtime, 'qt_platform': 'offscreen'}


def test_summary():
    report = json.loads((ROOT / 'build/test-results/validation.json').read_text(encoding='utf-8'))
    junit = ET.parse(ROOT / 'build/test-results/junit.xml').getroot()
    suites = [junit] if junit.tag == 'testsuite' else junit.findall('testsuite')
    counts = {key: sum(int(suite.get(key, 0)) for suite in suites)
              for key in ('tests', 'failures', 'errors', 'skipped')}
    coverage = json.loads((ROOT / 'build/test-results/coverage.json').read_text(encoding='utf-8'))
    return report, {**counts, 'coverage_percent': coverage['totals']['percent_covered']}


def build_release(args):
    global LOG
    if sys.platform != 'linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
        raise ReleaseError('Build .deb/AppImage on Linux x86_64; Windows executables come from native CI')
    os_release = platform.freedesktop_os_release()
    if not {'debian', 'ubuntu'}.intersection(
            {os_release.get('ID', ''), *os_release.get('ID_LIKE', '').split()}):
        raise ReleaseError('The .deb builder currently targets Debian/Ubuntu family hosts')
    for executable in ('git', 'gh', 'dpkg-deb', 'readelf', 'mksquashfs', 'desktop-file-validate'):
        if shutil.which(executable) is None:
            raise ReleaseError(f'Missing {executable}; see doc/RELEASE_LINUX_FR.md (no auto-install)')
    if not (3, 11) <= sys.version_info[:2] <= (3, 14):
        raise ReleaseError('Use the pinned Python 3.11–3.14 release venv')
    for name, required in (('PyInstaller', '6.22.3'), ('pyinstaller-hooks-contrib', '2026.8')):
        if metadata.version(name) != required:
            raise ReleaseError(f'Wrong {name}; install requirements-build.txt yourself')
    commit = require_clean_sha()
    version = version_from_source((ROOT / 'source/convertall.py').read_text(encoding='utf-8'))
    tag = 'v' + version
    maintainer = maintainer_identity(args.maintainer)
    # Validate user-supplied headers before any long-running command.
    packages.deb_control(version, maintainer, 1)
    # The .deb must be tested with Debian's shared runtime, never the wheel venv.
    command(['/usr/bin/python3', '-E', '-s', ROOT / 'tools/build_deb.py', '--probe-system'], quiet=True)
    lock = json.loads((ROOT / 'tools/appimage-lock.json').read_text(encoding='utf-8'))
    if lock.get('architecture') != 'x86_64':
        raise ReleaseError('AppImage tool architecture mismatch')
    if lock.get('compression') != 'zstd':
        raise ReleaseError('Pinned appimagetool supports only zstd compression')
    validate_tool_pin(lock['appimagetool'])
    validate_tool_pin(lock['runtime'])
    existing_target = tag_target(tag)
    if existing_target is not None and existing_target != commit:
        raise ReleaseError(f'{tag} already targets another SHA. Never retarget it; choose a new version.')
    if args.draft and github(f'repos/{REPO}/releases/tags/{tag}', missing_ok=True) is not None:
        raise ReleaseError(f'Release {tag} already exists. No overwrite/clobber is performed.')
    run = select_ci(commit, args.run_id, args.wait_ci)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + f'-{os.getpid()}'
    work = ROOT / 'build/qt6-release' / stamp
    assets = ROOT / 'dist/qt6-release' / (commit + '-' + stamp)
    work.mkdir(parents=True)
    assets.mkdir(parents=True)
    LOG = work / 'release.log'
    epoch = int(git('show', '-s', '--format=%ct', commit))
    environment = {**os.environ, 'SOURCE_DATE_EPOCH': str(epoch), 'QT_API': 'pyqt6',
                   'QT_QPA_PLATFORM': 'offscreen', 'PYTHONIOENCODING': 'utf-8'}
    for key in ('APPDIR', 'APPIMAGE', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
        environment.pop(key, None)
    print(f'SHA={commit}\nCI={run["html_url"]}\nAssets={assets}', flush=True)

    print('\n[1/7] Full local source QA (clean SHA, pinned profile, coverage)', flush=True)
    command([sys.executable, ROOT / 'tools/validate_release.py', '--require-clean'], env=environment)
    source_report, tests = test_summary()
    if source_report.get('commit') != commit or source_report.get('release_eligible') is not True:
        raise ReleaseError('Local source report does not certify the current clean SHA')
    shutil.copyfile(ROOT / 'build/test-results/validation.json', assets / 'source-validation.json')
    shutil.copyfile(ROOT / 'build/test-results/junit.xml', assets / 'junit.xml')
    shutil.copyfile(ROOT / 'build/test-results/coverage.json', assets / 'coverage.json')

    print('\n[2/7] Local Linux bundle (do not impose Ubuntu CI GLIBC on Debian)', flush=True)
    command([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
             '--distpath', work / 'dist', '--workpath', work / 'pyinstaller',
             ROOT / 'source/convertall.spec'], env=environment)
    bundle = work / 'dist/convertall'
    require_amd64_elf(bundle / 'convertall')
    linux_report = work / 'linux-bundle-validation.json'
    command([sys.executable, ROOT / 'tools/check_bundle.py', bundle, '--report', linux_report], env=environment)
    base_report = json.loads(linux_report.read_text(encoding='utf-8'))
    packages.verify_bundle_report(bundle, base_report, commit, version)
    shutil.copyfile(linux_report, assets / 'linux-bundle-validation.json')
    glibc = packages.glibc_requirement(bundle, lambda path: command(
        ['readelf', '--version-info', path], quiet=True))
    notices = packages.collect_notices(bundle)
    # Include a CPython notice where supplied by the build host (not a legal guarantee).
    python_notice = Path('/usr/share/doc') / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'copyright'
    if python_notice.is_file():
        shutil.copyfile(python_notice, bundle / 'doc/third-party/CPython-copyright')
    info = {'version': version, 'source_commit': commit, 'ci_run': run['id'],
            'architecture': 'x86_64', 'glibc_required': glibc, 'runtime': base_report['runtime']}
    packages.write_file(bundle / 'RELEASE-INFO.json', json.dumps(info, indent=2) + '\n')

    print('\n[3/7] Portable executable archive and Debian package', flush=True)
    portable_name = f'ConvertAll-{version}-qt6-linux-x86_64'
    portable = work / portable_name
    packages.copy_bundle(bundle, portable)
    tarball = assets / (portable_name + '.tar.gz')
    packages.make_tar(portable, tarball, epoch)
    tar_extract = work / 'portable-extracted'
    tar_extract.mkdir()
    packages.extract_own_tar(tarball, tar_extract)
    packages.verify_payload(tar_extract / portable_name, base_report['bundle_sha256'])
    checks = {'portable': check_launch(tar_extract / portable_name / 'convertall', 'portable', work,
                                      environment, version, bundle=tar_extract / portable_name)}
    command(['/usr/bin/python3', '-E', '-s', ROOT / 'tools/build_deb.py',
             '--output-dir', assets, '--work-dir', work / 'native-deb',
             '--maintainer', maintainer], env=environment)
    deb = assets / f'convertall_{version}-1_all.deb'
    checks['deb'] = json.loads((assets / 'native-deb-validation.json').read_text(encoding='utf-8'))
    if (checks['deb'].get('status') != 'PASS' or checks['deb'].get('source_commit') != commit
            or checks['deb'].get('bundled_runtime') is not False
            or checks['deb'].get('package_sha256') != packages.sha256(deb)):
        raise ReleaseError('Native Debian package did not pass for this exact SHA')

    print('\n[4/7] AppImage with checksum-pinned builder AND runtime (no FUSE for tests)', flush=True)
    tools = work / 'appimage-tools'
    tools.mkdir()
    tool_image = fetch_tool(lock['appimagetool'], tools)
    runtime = fetch_tool(lock['runtime'], tools)
    tool = extract_appimage(tool_image, tools / 'extracted', required='AppRun',
                            expected_sha256=lock['appimagetool']['sha256']) / 'AppRun'
    appdir = packages.stage_appdir(bundle, work / 'ConvertAll.AppDir', ROOT)
    command(['desktop-file-validate', appdir / 'convertall.desktop'])
    image = assets / f'ConvertAll-{version}-x86_64.AppImage'
    command(appimage_command(tool, runtime, appdir, image, lock['compression']),
            env={**environment, 'ARCH': 'x86_64', 'VERSION': version})
    image.chmod(0o755)
    # First exercise the actual AppImage runtime, not just the uncompressed AppDir.
    checks['appimage_runtime'] = check_launch(image, 'appimage-runtime', work, environment,
                                             version, prefix=('--appimage-extract-and-run',))
    extracted_app = extract_appimage(image, work / 'appimage-extracted',
                                     required='usr/lib/convertall')
    packages.verify_payload(extracted_app / 'usr/lib/convertall', base_report['bundle_sha256'])
    checks['appimage_apprun'] = check_launch(extracted_app / 'AppRun', 'appimage-apprun', work,
                                            environment, version, bundle=extracted_app / 'usr/lib/convertall')

    print('\n[5/7] Exact CI source archive and Windows executables (complete onedir ZIP)', flush=True)
    source_input = work / 'ci-source'
    download_artifact(run['id'], f'qt6-source-{commit}', source_input)
    for path in packages.verify_source_archive(source_input, version, commit):
        shutil.copyfile(path, assets / path.name)
    windows_input, windows_report_dir = work / 'ci-windows', work / 'ci-windows-report'
    download_artifact(run['id'], 'qt6-bundle-windows-2022', windows_input)
    download_artifact(run['id'], 'qt6-bundle-report-windows-2022', windows_report_dir)
    report_path = windows_report_dir / 'bundle-validation.json'
    windows_report = json.loads(report_path.read_text(encoding='utf-8'))
    packages.verify_bundle_report(windows_input, windows_report, commit, version)
    for name in ('convertall.exe', 'convertall_dos.exe'):
        with (windows_input / name).open('rb') as stream:
            if stream.read(2) != b'MZ':
                raise ReleaseError(f'Not a Windows executable: {name}')
    windows_zip = assets / f'ConvertAll-{version}-qt6-windows-x86_64.zip'
    windows_prefix = f'ConvertAll-{version}-qt6-windows-x86_64'
    packages.make_windows_zip(windows_input, windows_zip, windows_prefix, epoch)
    import zipfile
    with zipfile.ZipFile(windows_zip) as archive:
        expected_names = {f'{windows_prefix}/{name}' for name in windows_report['bundle_sha256']}
        if set(archive.namelist()) != expected_names or archive.testzip() is not None:
            raise ReleaseError('Windows portable ZIP integrity/file list mismatch')
    shutil.copyfile(report_path, assets / 'windows-bundle-validation.json')

    print('\n[6/7] Provenance, checksums and observed release notes', flush=True)
    require_clean_sha(commit)
    manifest = {**info, 'ci_url': run['html_url'], 'packager_commit': commit,
                'build_host': platform.platform(), 'build_os_release': os_release,
                'build_python': sys.version, 'source_tests': tests, 'package_checks': checks,
                'appimage_lock': lock, 'wheel_notices': notices,
                'debian_profile': {'architecture': 'all', 'bundled_runtime': False,
                                   'depends': list(packages.DEBIAN_DEPENDENCIES)},
                'manual_acceptance': 'NOT CERTIFIED: real desktop/DPI/GPU, apt install/remove, Windows, licences',
                'assets': {path.name: {'sha256': packages.sha256(path), 'bytes': path.stat().st_size}
                           for path in sorted(assets.iterdir()) if path.is_file()}}
    packages.write_file(assets / 'release-provenance.json', json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    notes = (f'# ConvertAll {version} — Python / Qt6\n\n'
             f'Source SHA: `{commit}`\nCI: {run["html_url"]}\n\n'
             f'Local Linux QA: {tests["tests"]} tests, {tests["failures"]} failures, '
             f'{tests["errors"]} errors, {tests["skipped"]} skips; '
             f'combined coverage {tests["coverage_percent"]:.2f}%.\n'
             'CI: Ubuntu/Windows × Python 3.11–3.14 and both native bundles passed.\n\n'
             '## Downloads\n'
             f'- `{tarball.name}`: Linux executable AND all private Qt/Python resources.\n'
             f'- `{deb.name}`: small Debian architecture-all package; Python/PyQt6/Qt supplied by apt Depends.\n'
             f'- `{image.name}`: Linux x86_64 AppImage; `chmod +x` before running.\n'
             f'- `{windows_zip.name}`: extract the WHOLE directory, then run `convertall.exe`.\n'
             f'- `ConvertAll-{version}-qt6-source.tar.gz`: exact CI application source.\n\n'
             f'Portable/AppImage minimum ELF GLIBC requirement detected: **{glibc}**. '
             'This does not apply to the source-only .deb: apt manages its shared runtime.\n'
             'Desktop/graphics system libraries are still required; not universal Linux compatibility.\n'
             'Portable/AppImage and native Debian runtime, conversions, 7 catalogues and offscreen GUI passed locally.\n'
             'Debian native Qt regressions/package checks passed in Bookworm and Trixie CI.\n'
             'SHA256SUMS and JSON reports bind these assets to the source/CI/build host.\n\n'
             '## Review before publishing\n'
             'Real desktop/DPI/GPU and apt install/upgrade/remove still require manual acceptance.\n'
             'Windows ZIP is NOT an Inno installer. No macOS build is provided.\n'
             'Review GPLv3 and all third-party notices/corresponding-source obligations. '
             'Collected wheel notices are not a complete legal inventory.\n'
             'Qt5 v0.8.1 is unchanged. This release is a draft, not automatically Latest.\n')
    packages.write_file(assets / 'RELEASE_NOTES.md', notes)
    payloads = sorted(path for path in assets.iterdir() if path.is_file())
    packages.write_file(assets / 'SHA256SUMS', ''.join(
        f'{packages.sha256(path)}  {path.name}\n' for path in payloads))
    print(f'\nLinux baseline: GLIBC >= {glibc}\nAssets: {assets}\nLog: {LOG}', flush=True)

    print('\n[7/7] GitHub draft (only with --draft; never Latest)', flush=True)
    if args.draft:
        require_clean_sha(commit)
        current_target = tag_target(tag)
        if current_target is not None and current_target != commit:
            raise ReleaseError('Tag changed while packaging; refusing to publish any draft')
        if github(f'repos/{REPO}/releases/tags/{tag}', missing_ok=True) is not None:
            raise ReleaseError('Release was created while packaging; no overwrite is performed')
        if current_target is None:
            command(['gh', 'api', '--method', 'POST', f'repos/{REPO}/git/refs',
                     '-f', f'ref=refs/tags/{tag}', '-f', f'sha={commit}'])
        if tag_target(tag) != commit:
            raise ReleaseError('Tag verification failed before draft creation')
        command(['gh', 'release', 'create', tag, '--repo', REPO, '--verify-tag', '--draft',
                 '--title', f'ConvertAll {version} — Qt6', '--notes-file', assets / 'RELEASE_NOTES.md',
                 *sorted(path for path in assets.iterdir() if path.is_file())])
        print(f'Draft created: https://github.com/{REPO}/releases/tag/{tag}\n'
              'Review/manual acceptance required. NOTHING was published as Latest.', flush=True)
    else:
        print('Assets ready locally; no tag/release created. Use --draft to prepare a GitHub draft.', flush=True)
    return assets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--draft', action='store_true', help='create a non-published GitHub draft after all checks')
    parser.add_argument('--wait-ci', action='store_true', help='wait for the current SHA CI before local builds')
    parser.add_argument('--run-id', type=int, help='use this exact successful CI push run (same SHA required)')
    parser.add_argument('--maintainer', help='public .deb Maintainer: "Name <email>"; default: local git identity')
    args = parser.parse_args()
    try:
        build_release(args)
        return 0
    except (ReleaseError, OSError, ValueError, KeyError, TypeError,
            metadata.PackageNotFoundError, subprocess.TimeoutExpired) as error:
        print(f'Release preparation FAILED: {error}', file=sys.stderr)
        if LOG is not None:
            print(f'Log retained: {LOG}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Interrupted; no automatic cleanup, retry into a fresh output directory.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
