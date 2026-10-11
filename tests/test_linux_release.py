"""Linux release recipes and CI/provenance guards; native packages are user-run."""
import copy
import io
import json
import os
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


def test_deb_uses_system_dependencies_without_copying_a_frozen_runtime(tmp_path):
    stage = packages.stage_deb(tmp_path / 'deb', ROOT, '0.9.1',
                               'Test Maintainer <test@example.invalid>')
    control = (stage / 'DEBIAN/control').read_text(encoding='utf-8')
    assert 'Package: convertall\nVersion: 0.9.1-1\nArchitecture: all\n' in control
    assert 'Depends: ' + ', '.join(packages.DEBIAN_DEPENDENCIES) in control
    assert 'python3-pyqt6 (>= 6.4.2)' in control
    assert 'libc6' not in control and 'Installed-Size: ' in control
    script = (stage / 'usr/bin/convertall').read_text(encoding='utf-8')
    assert 'exec /usr/bin/python3 -E -s "$HERE/../share/convertall/_debian_entry.py" "$@"' in script
    app = stage / 'usr/share/convertall'
    assert (app / 'convertall.py').read_bytes() == (ROOT / 'source/convertall.py').read_bytes()
    assert (app / 'data/units.dat').read_bytes() == (ROOT / 'data/units.dat').read_bytes()
    assert len(list((app / 'data').glob('*.dat'))) == 7
    assert len(list((app / 'translations').glob('convertall_*.qm'))) == 6
    assert not (stage / 'usr/lib/convertall').exists()
    assert not (app / 'PyQt6').exists() and not (app / 'setup.py').exists()
    assert not list(stage.rglob('*.so')) and not list(stage.rglob('*.dist-info'))
    assert not list(stage.rglob('*.ts'))
    packages.verify_thin_deb_payload(stage)
    assert (stage / 'usr/share/doc/convertall/LICENSE-GPL-3.0').is_file()
    assert (stage / 'usr/share/icons/hicolor/scalable/apps/convertall.svg').is_file()


@pytest.mark.parametrize('maintainer', ['missing-email', 'Name <mail>\nDepends: bad', 'Name <mail>'])
def test_deb_control_rejects_header_injection(maintainer):
    with pytest.raises(ReleaseError, match='Invalid Debian'):
        packages.deb_control('0.9.1', maintainer, 1)


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
    names += ['Bundle ubuntu-24.04 / Qt6', 'Bundle windows-2022 / Qt6',
              'Debian native Qt / bookworm', 'Debian native Qt / trixie']
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


def test_appimage_uses_the_locked_builders_supported_compressor():
    lock = json.loads((ROOT / 'tools/appimage-lock.json').read_text(encoding='utf-8'))
    assert lock['compression'] == 'zstd'
    arguments = release_qt6.appimage_command(
        'AppRun', 'runtime-x86_64', 'ConvertAll.AppDir', 'ConvertAll.AppImage', lock['compression'])
    assert arguments == ['AppRun', '--runtime-file', 'runtime-x86_64', '--comp', 'zstd',
                         '--no-appstream', 'ConvertAll.AppDir', 'ConvertAll.AppImage']
    assert 'xz' not in arguments


@pytest.mark.parametrize('compression', ['xz', 'gzip', '', None])
def test_appimage_rejects_unsupported_compression_before_execution(compression):
    with pytest.raises(ReleaseError, match='only zstd'):
        release_qt6.appimage_command('AppRun', 'runtime', 'AppDir', 'out.AppImage', compression)


def test_local_scratch_directories_are_unique_and_writable():
    directories = release_qt6.local_scratch_directories()
    assert directories
    assert len(set(directories)) == len(directories)
    assert all(directory.is_dir() and os.access(directory, os.W_OK) for directory in directories)


def elf64_with_a_payload(payload_offset, last_section=((0x100, 0x40)), section_table=(0x100, 64, 1)):
    """Minimal ELF with a section table, as an AppImage runtime is read by the tooling."""
    table_offset, entry_size, count = section_table
    image = bytearray(max(payload_offset, table_offset + entry_size * count) + 4)
    image[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<Q', image, 40, table_offset)
    struct.pack_into('<H', image, 58, entry_size)
    struct.pack_into('<H', image, 60, count)
    struct.pack_into('<Q', image, table_offset + 24, last_section[0])
    struct.pack_into('<Q', image, table_offset + 32, last_section[1])
    image[payload_offset:payload_offset + 4] = b'hsqs'
    return bytes(image)


def test_appimage_payload_offset_follows_the_runtime_rule(tmp_path):
    """The runtime uses the later of the section table end and the last section end."""
    table_end = tmp_path / 'table.AppImage'
    table_end.write_bytes(elf64_with_a_payload(0x140))
    assert release_qt6.appimage_payload_offset(table_end) == 0x140
    last_section_end = tmp_path / 'section.AppImage'
    last_section_end.write_bytes(elf64_with_a_payload(0x300, last_section=(0x100, 0x200)))
    assert release_qt6.appimage_payload_offset(last_section_end) == 0x300
    broken = tmp_path / 'broken.AppImage'
    broken.write_bytes(elf64_with_a_payload(0x140).replace(b'hsqs', b'zero'))
    with pytest.raises(ReleaseError, match='reads returned'):
        release_qt6.appimage_payload_offset(broken)


def test_local_scratch_copy_is_verified(monkeypatch, tmp_path):
    scratch = tmp_path / 'scratch'
    monkeypatch.setattr(release_qt6, 'local_scratch_directories', lambda: [scratch])
    source = tmp_path / 'source.bin'
    source.write_bytes(b'pinned bytes')
    copy = release_qt6.local_scratch_copy(source, packages.sha256(source))
    assert copy.read_bytes() == source.read_bytes()
    assert copy.stat().st_mode & 0o111
    with pytest.raises(ReleaseError, match='No verified local copy'):
        release_qt6.local_scratch_copy(source, 'f' * 64)


def test_appimage_extraction_retries_from_a_local_disk(monkeypatch, tmp_path):
    """A shared or synchronised work tree must not dead-end the AppImage step."""
    image = tmp_path / 'appimagetool-x86_64.AppImage'
    image.write_bytes(b'\x7fELF\x02\x01' + b'x' * 64)
    local = tmp_path / 'local-temp'
    local.mkdir()
    monkeypatch.setattr(release_qt6, 'local_scratch_directories', lambda: [local])
    seen = []

    def fake_command(arguments, *, cwd=None, quiet=False, **kwargs):
        seen.append((Path(arguments[0]), Path(cwd)))
        if len(seen) == 1:
            raise ReleaseError('Command failed (1): the mount cannot read its own image')
        (Path(cwd) / 'squashfs-root').mkdir(parents=True, exist_ok=True)
        (Path(cwd) / 'squashfs-root/AppRun').write_text('#!/bin/sh\n', encoding='utf-8')
        return ''

    monkeypatch.setattr(release_qt6, 'command', fake_command)
    root = release_qt6.extract_appimage(image, tmp_path / 'extracted', required='AppRun',
                                        expected_sha256=packages.sha256(image))
    assert len(seen) == 2
    assert Path(seen[1][1]) != Path(seen[0][1])  # retried somewhere else
    assert root == Path(seen[1][1]) / 'squashfs-root'
    assert (root / 'AppRun').is_file()
    assert Path(seen[1][0]).read_bytes() == image.read_bytes()  # same verified bytes


def test_appimage_extraction_can_use_the_pinned_runtime(monkeypatch, tmp_path):
    """TARGET_APPIMAGE makes the pinned runtime read the image by path, not /proc/self/exe."""
    image = tmp_path / 'tool.AppImage'
    image.write_bytes(b'\x7fELF\x02\x01' + b'x' * 64)
    runtime = tmp_path / 'runtime-x86_64'
    runtime.write_bytes(b'\x7fELF\x02\x01' + b'r' * 64)
    local = tmp_path / 'local-temp'
    local.mkdir()
    monkeypatch.setattr(release_qt6, 'local_scratch_directories', lambda: [local])
    environments = []

    def fake_command(arguments, *, cwd=None, quiet=False, env=None, **kwargs):
        environments.append((Path(arguments[0]), env))
        if Path(arguments[0]) != runtime:
            raise ReleaseError('Command failed (1): cannot open squashfs image')
        assert env['TARGET_APPIMAGE'] == str(image)
        (Path(cwd) / 'squashfs-root').mkdir(parents=True, exist_ok=True)
        (Path(cwd) / 'squashfs-root/AppRun').write_text('#!/bin/sh\n', encoding='utf-8')
        return ''

    monkeypatch.setattr(release_qt6, 'command', fake_command)
    root = release_qt6.extract_appimage(image, tmp_path / 'extracted', required='AppRun',
                                        runtime=runtime)
    # in place, then a local copy, then the pinned runtime with TARGET_APPIMAGE
    assert [program for program, _ in environments] == [image, local / image.name, runtime]
    assert environments[-1][1]['TARGET_APPIMAGE'] == str(image)
    assert (root / 'AppRun').is_file()


def test_payload_extraction_strips_the_elf_prefix(monkeypatch, tmp_path):
    """The last resort reads the squashfs itself, from the verified local copy."""
    image = tmp_path / 'tool.AppImage'
    image.write_bytes(b'P' * 0x140 + b'hsqs' + b'payload')
    local = tmp_path / 'local-temp'
    local.mkdir()
    monkeypatch.setattr(release_qt6, 'local_scratch_directories', lambda: [local])
    runs = []

    def fake_command(arguments, *, cwd=None, quiet=False, **kwargs):
        runs.append(arguments)
        root = Path(arguments[2])
        root.mkdir(parents=True, exist_ok=True)
        (root / 'AppRun').write_text('#!/bin/sh\n', encoding='utf-8')
        return ''

    monkeypatch.setattr(release_qt6, 'command', fake_command)
    root = release_qt6.extract_squashfs_payload(image, tmp_path / 'out', required='AppRun',
                                                offset=0x140,
                                                expected_sha256=packages.sha256(image))
    assert runs[0][0] == 'unsquashfs'
    assert Path(runs[0][3]).read_bytes() == b'hsqs' + b'payload'  # payload only, no ELF prefix
    assert root == tmp_path / 'out/squashfs-root'
    assert (root / 'AppRun').is_file()


def test_appimage_extraction_failure_stays_explicit(monkeypatch, tmp_path):
    image = tmp_path / 'tool.AppImage'
    image.write_bytes(b'\x7fELF\x02\x01' + b'x' * 16)
    local = tmp_path / 'local-temp'
    local.mkdir()
    monkeypatch.setattr(release_qt6, 'local_scratch_directories', lambda: [local])

    def failing_command(*arguments, **kwargs):
        raise ReleaseError('Command failed (1): no squashfs')
    monkeypatch.setattr(release_qt6, 'command', failing_command)
    def failing_offset(path):
        raise ReleaseError('No squashfs payload at offset 64')
    monkeypatch.setattr(release_qt6, 'appimage_payload_offset', failing_offset)
    with pytest.raises(ReleaseError) as failure:
        release_qt6.extract_appimage(image, tmp_path / 'out', required='AppRun',
                                     expected_sha256=packages.sha256(image))
    message = str(failure.value)
    assert 'No squashfs payload at offset 64' in message
    assert 'move the clone to a local disk' in message
    assert packages.sha256(image) in message  # the bytes on disk are reported, not hidden


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
