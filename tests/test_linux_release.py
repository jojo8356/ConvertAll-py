"""Linux release recipes and CI/provenance guards; native packages are user-run."""
import copy
import io
import json
from pathlib import Path
import struct
import tarfile
import zipfile

import pytest

from helpers import ROOT
import linux_release as packages
from linux_release import ReleaseError
import release_qt6

pytestmark = pytest.mark.packaging
SHA = 'a' * 40


@pytest.fixture
def bundle(tmp_path):
    folder = tmp_path / 'bundle'
    folder.mkdir()
    for name, content in {'convertall': b'fake executable', 'data/units.dat': b'unit data',
                          'doc/LICENSE': b'GPL', 'PyQt6_sip-13.13.0.dist-info/METADATA': b'Version: 13.13.0'}.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return folder


def report_for(bundle):
    return {'status': 'PASS', 'checker_source_commit': SHA, 'checker_working_tree_dirty': False,
            'runtime': {'application': 'ConvertAll', 'version': '0.9.0', 'binding': 'PyQt6',
                        'pyqt_binding': '6.11.0', 'qt_runtime': '6.11.2',
                        'sip_package': '13.13.0', 'sip_generator': '6.17.0'},
            'bundle_sha256': packages.file_hashes(bundle)}


def test_report_binds_every_byte_to_clean_sha(bundle):
    report = report_for(bundle)
    packages.verify_bundle_report(bundle, report, SHA, '0.9.0')
    (bundle / 'convertall').write_bytes(b'changed')
    with pytest.raises(ReleaseError, match='bytes differ'):
        packages.verify_bundle_report(bundle, report, SHA, '0.9.0')


@pytest.mark.parametrize('field,value', [('status', 'FAIL'), ('checker_source_commit', 'b' * 40),
                                         ('checker_working_tree_dirty', True)])
def test_bundle_provenance_cannot_be_bypassed(bundle, field, value):
    report = report_for(bundle)
    report[field] = value
    with pytest.raises(ReleaseError, match='clean PASS'):
        packages.verify_bundle_report(bundle, report, SHA, '0.9.0')


def test_bundle_extra_or_missing_files_are_rejected(bundle):
    report = report_for(bundle)
    (bundle / 'extra').write_text('unexpected', encoding='utf-8')
    with pytest.raises(ReleaseError, match='bytes differ'):
        packages.verify_bundle_report(bundle, report, SHA, '0.9.0')
    (bundle / 'extra').unlink()
    (bundle / 'data/units.dat').unlink()
    with pytest.raises(ReleaseError, match='Missing/invalid'):
        packages.verify_bundle_report(bundle, report, SHA, '0.9.0')


@pytest.mark.parametrize('name', ['', '.', '../secret', '/etc/passwd', 'a/../b', './file',
                                 'a\\b', 'nul\x00file'])
def test_artifact_paths_cannot_escape(tmp_path, name):
    with pytest.raises(ReleaseError, match='Unsafe'):
        packages.safe_file(tmp_path, name)


def test_source_archive_checks_real_sha_and_checksum(tmp_path):
    name = 'ConvertAll-0.9.0-qt6-source.tar.gz'
    archive = tmp_path / name
    archive.write_bytes(b'archive fixture')
    digest = packages.sha256(archive)
    archive.with_name(name + '.sha256').write_text(f'{digest}  {name}\n', encoding='ascii')
    info = {'source_commit': SHA, 'version': '0.9.0', 'binding': 'Qt6', 'sha256': digest}
    provenance = archive.with_name(name + '.provenance.json')
    provenance.write_text(json.dumps(info), encoding='utf-8')
    assert packages.verify_source_archive(tmp_path, '0.9.0', SHA)[0] == archive
    info['source_commit'] = 'b' * 40
    provenance.write_text(json.dumps(info), encoding='utf-8')
    with pytest.raises(ReleaseError, match='mismatch'):
        packages.verify_source_archive(tmp_path, '0.9.0', SHA)


def test_glibc_baseline_comes_from_elf_requirements_not_platform(bundle):
    (bundle / 'convertall').write_bytes(b'\x7fELFfixture')
    (bundle / 'libfixture.so').write_bytes(b'\x7fELFfixture')
    values = {'convertall': 'Name: GLIBC_2.9 Name: GLIBC_2.28',
              'libfixture.so': 'Name: GLIBC_2.34 Name: GLIBC_PRIVATE'}
    assert packages.glibc_requirement(bundle, lambda path: values[path.name]) == '2.34'
    with pytest.raises(ReleaseError, match='No GLIBC'):
        packages.glibc_requirement(bundle, lambda path: 'static binary')


def test_deb_private_runtime_and_relocatable_launcher(bundle, tmp_path):
    stage = packages.stage_deb(bundle, tmp_path / 'deb', ROOT, '0.9.0',
                               'Test Maintainer <test@example.invalid>', '2.36')
    control = (stage / 'DEBIAN/control').read_text(encoding='utf-8')
    assert 'Package: convertall\nVersion: 0.9.0-1\nArchitecture: amd64\n' in control
    assert 'libc6 (>= 2.36)' in control
    assert 'Depends: ' in control and 'python3-pyqt6' not in control
    assert 'Installed-Size: ' in control
    script = (stage / 'usr/bin/convertall').read_text(encoding='utf-8')
    assert 'exec "$HERE/../lib/convertall/convertall" "$@"' in script
    assert (stage / 'usr/lib/convertall/data/units.dat').read_bytes() == b'unit data'
    assert (stage / 'usr/share/doc/convertall/LICENSE-GPL-3.0').is_file()
    assert (stage / 'usr/share/icons/hicolor/scalable/apps/convertall.svg').is_file()


@pytest.mark.parametrize('maintainer', ['missing-email', 'Name <mail>\nDepends: bad', 'Name <mail>'])
def test_deb_control_rejects_header_injection(maintainer):
    with pytest.raises(ReleaseError, match='Invalid Debian'):
        packages.deb_control('0.9.0', maintainer, '2.36', 1)


def test_appdir_keeps_full_bundle_icon_and_argument_forwarding(bundle, tmp_path):
    stage = packages.stage_appdir(bundle, tmp_path / 'ConvertAll.AppDir', ROOT)
    assert 'exec "$HERE/usr/lib/convertall/convertall" "$@"' in (stage / 'AppRun').read_text()
    assert (stage / 'usr/lib/convertall/PyQt6_sip-13.13.0.dist-info/METADATA').is_file()
    assert (stage / '.DirIcon').read_bytes() == (ROOT / 'icons/convertall_lg.png').read_bytes()
    desktop = (stage / 'convertall.desktop').read_text(encoding='utf-8')
    assert 'Exec=convertall\nIcon=convertall\n' in desktop
    assert 'Terminal=false' in desktop and 'Categories=Education;Math;' in desktop


def test_portable_tar_is_repeatable_and_retains_executable(bundle, tmp_path):
    first, second = tmp_path / 'one.tar.gz', tmp_path / 'two.tar.gz'
    packages.make_tar(bundle, first, 1234567890)
    packages.make_tar(bundle, second, 1234567890)
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first, 'r:gz') as archive:
        info = archive.getmember('bundle/convertall')
        assert info.mode == 0o755 and info.mtime == 1234567890
        assert info.uid == info.gid == 0
    out = tmp_path / 'extracted'
    out.mkdir()
    packages.extract_own_tar(first, out)
    assert (out / 'bundle/convertall').read_bytes() == (bundle / 'convertall').read_bytes()


@pytest.mark.parametrize('name,link', [('../escape', None), ('/absolute', None),
                                      ('bundle/link', '../../escape')])
def test_tar_extraction_rejects_unsafe_members(tmp_path, name, link):
    path = tmp_path / 'bad.tar.gz'
    with tarfile.open(path, 'w:gz') as archive:
        info = tarfile.TarInfo(name)
        if link is not None:
            info.type, info.linkname = tarfile.SYMTYPE, link
            archive.addfile(info)
        else:
            info.size = 1
            archive.addfile(info, io.BytesIO(b'x'))
    with pytest.raises(ReleaseError, match='Unsafe'):
        packages.extract_own_tar(path, tmp_path / 'out')


def test_windows_zip_contains_runtime_not_a_lone_exe(bundle, tmp_path):
    (bundle / 'convertall.exe').write_bytes(b'MZfixture')
    output = tmp_path / 'windows.zip'
    packages.make_windows_zip(bundle, output, 'ConvertAll-Windows', 1234567890)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert archive.read('ConvertAll-Windows/convertall.exe') == b'MZfixture'
        assert archive.read('ConvertAll-Windows/data/units.dat') == b'unit data'
        assert archive.getinfo('ConvertAll-Windows/convertall.exe').external_attr >> 16 == 0o100755


def good_run():
    return {'head_sha': SHA, 'head_branch': release_qt6.BRANCH, 'path': release_qt6.WORKFLOW,
            'event': 'push', 'status': 'completed', 'conclusion': 'success'}


@pytest.mark.parametrize('field,value', [('head_sha', 'b' * 40), ('head_branch', 'master'),
                                         ('event', 'pull_request'), ('conclusion', 'failure'),
                                         ('status', 'in_progress'), ('path', 'another.yml')])
def test_release_requires_green_ci_of_exact_sha(field, value):
    run = good_run()
    release_qt6.validate_ci_run(run, SHA)
    run[field] = value
    with pytest.raises(ReleaseError, match='exact current SHA'):
        release_qt6.validate_ci_run(run, SHA)


def test_ci_requires_all_eight_tests_and_both_native_bundles():
    names = [f'Tests {os_name} / Python {version} / Qt6'
             for os_name in ('ubuntu-24.04', 'windows-2022') for version in ('3.11', '3.12', '3.13', '3.14')]
    names += ['Bundle ubuntu-24.04 / Qt6', 'Bundle windows-2022 / Qt6']
    jobs = [{'name': name, 'status': 'completed', 'conclusion': 'success'} for name in names]
    release_qt6.validate_ci_jobs(jobs)
    jobs[-1]['conclusion'] = 'skipped'
    with pytest.raises(ReleaseError, match='Missing/failed'):
        release_qt6.validate_ci_jobs(jobs)


def test_tool_locks_are_explicit_and_unverified_assets_are_not_executed(tmp_path, monkeypatch):
    lock = json.loads((ROOT / 'tools/appimage-lock.json').read_text(encoding='utf-8'))
    assert lock['architecture'] == 'x86_64'
    for name in ('appimagetool', 'runtime'):
        release_qt6.validate_tool_pin(lock[name])
    pin = copy.deepcopy(lock['runtime'])
    pin['sha256'] = '0' * 64
    class Result:
        returncode = 0
        stderr = b''
    def download(arguments, **kwargs):
        # Only fake a download; the test must never execute a real tool.
        assert arguments[:2] == ['gh', 'api']
        kwargs['stdout'].write(b'unverified downloaded bytes')
        return Result()
    monkeypatch.setattr(release_qt6.subprocess, 'run', download)
    with pytest.raises(ReleaseError, match='checksum mismatch'):
        release_qt6.fetch_tool(pin, tmp_path)


def test_release_elf_architecture_is_checked_before_execution(tmp_path):
    path = tmp_path / 'elf'
    header = bytearray(20)
    header[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', header, 18, 62)
    path.write_bytes(header)
    release_qt6.require_amd64_elf(path)
    struct.pack_into('<H', header, 18, 183)  # AArch64, not a valid x86_64 artifact
    path.write_bytes(header)
    with pytest.raises(ReleaseError, match='x86_64 ELF'):
        release_qt6.require_amd64_elf(path)


def test_new_script_is_hashed_archived_and_does_not_publish_latest():
    import validate_release
    assert 'release_qt6.sh' in validate_release.input_hashes()
    text = (ROOT / 'tools/release_qt6.py').read_text(encoding='utf-8')
    assert "'--verify-tag', '--draft'" in text
    assert '--latest' not in text and '--clobber' not in text
    assert 'sudo' not in (ROOT / 'release_qt6.sh').read_text()
