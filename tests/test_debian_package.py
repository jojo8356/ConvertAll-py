"""Thin .deb invariants; actual apt runtimes are exercised separately in CI."""
import copy
from pathlib import Path

import pytest

from helpers import ROOT
import linux_release as packages
from linux_release import ReleaseError

pytestmark = pytest.mark.packaging


@pytest.fixture
def native_runtime():
    return {'application': 'ConvertAll', 'version': '0.9.1', 'binding': 'PyQt6',
            'python_executable': '/usr/bin/python3', 'python_version': '3.11.2',
            'pyqt_binding': '6.4.2', 'qt_runtime': '6.4.2', 'sip_package': '13.4.1',
            'sip_generator': '6.7.7', 'frozen': False,
            'pyqt_location': '/usr/lib/python3/dist-packages/PyQt6/QtCore.cpython-311-x86_64-linux-gnu.so',
            'qt_translations_path': '/usr/share/qt6/translations'}


def test_system_qt_profile_is_distinct_from_frozen_wheel_pins(native_runtime):
    packages.validate_debian_runtime(native_runtime, '0.9.1')
    newer = copy.deepcopy(native_runtime)
    newer.update(python_version='3.13.5', pyqt_binding='6.8.4', qt_runtime='6.8.2', sip_package='13.10.2')
    packages.validate_debian_runtime(newer, '0.9.1')


@pytest.mark.parametrize('field,value', [('python_version', '3.10.9'), ('pyqt_binding', '6.3.0'),
                                         ('qt_runtime', '6.3.0'), ('sip_package', '13.3.0'),
                                         ('frozen', True), ('version', '0.9.0'),
                                         ('sip_generator', '')])
def test_native_profile_rejects_unsupported_or_wrong_app_runtime(native_runtime, field, value):
    native_runtime[field] = value
    with pytest.raises(ReleaseError, match='Unsupported Debian'):
        packages.validate_debian_runtime(native_runtime, '0.9.1')


@pytest.mark.parametrize('field,value', [
    ('python_executable', '/home/test/.venv/bin/python'),
    ('pyqt_location', '/home/test/.venv/lib/python3.11/site-packages/PyQt6/QtCore.so'),
    ('pyqt_location', '/usr/local/lib/python3.11/dist-packages/PyQt6/QtCore.so'),
])
def test_native_profile_cannot_be_validated_by_a_wheel_venv(native_runtime, field, value):
    native_runtime[field] = value
    with pytest.raises(ReleaseError, match='Debian package'):
        packages.validate_debian_runtime(native_runtime, '0.9.1')


@pytest.mark.parametrize('name,content', [('runtime.so', b'library'), ('python', b'\x7fELFbinary'),
                                        ('setup.py', b'build script'), ('module.pyc', b'bytecode'),
                                        ('PyQt6', None)])
def test_thin_package_rejects_any_bundled_runtime_or_build_file(tmp_path, name, content):
    stage = packages.stage_deb(tmp_path / 'deb', ROOT, '0.9.1', 'Test <test@example.invalid>')
    path = stage / 'usr/share/convertall' / name
    if content is None:
        path.mkdir()
    else:
        path.write_bytes(content)
    with pytest.raises(ReleaseError, match='Bundled runtime|ELF binary'):
        packages.verify_thin_deb_payload(stage)


def test_generated_debian_entry_compiles_and_preserves_relative_resource_layout():
    entry = packages.deb_entry()
    compile(entry, '_debian_entry.py', 'exec')
    assert 'convertall.dataFilePath = str(base / "data")' in entry
    assert 'convertall.helpFilePath = str(base.parent / "doc" / "convertall")' in entry
    assert 'sys.exit(convertall.main())' in entry
    assert 'pip install' not in entry and 'apt install' not in packages.deb_launcher()


def test_debian_packaging_does_not_collect_wheel_notices_or_frozen_payload(tmp_path):
    stage = packages.stage_deb(tmp_path / 'deb', ROOT, '0.9.1', 'Test <test@example.invalid>')
    assert not list(stage.rglob('third-party'))
    assert not list(stage.rglob('PyQt6'))
    assert not list(stage.rglob('*.dist-info'))
    assert not list(stage.rglob('*.exe'))
    assert len(list((stage / 'usr/share/doc/convertall').glob('README*.html'))) >= 5
    assert len(list((stage / 'usr/share/convertall/translations').glob('*.qm'))) == 6
    assert len(list((stage / 'usr/share/convertall/data').glob('*.dat'))) == 7
    assert not list(stage.rglob('*.ts'))  # TS/build inputs remain available in the source archive.


def test_ci_exercises_native_debian_versions_without_installing_qt_wheels():
    workflow = (ROOT / '.github/workflows/qt6-release.yml').read_text(encoding='utf-8')
    native = workflow.split('  native-deb:', 1)[1].split('  bundle:', 1)[0]
    assert 'suite: [bookworm, trixie]' in native
    assert '--system-site-packages' in native
    assert 'requirements-test-debian.txt' in native
    assert '/usr/bin/python3 -E -s tools/build_deb.py' in native
    assert 'requirements-qt6.txt' not in native
    assert '--cov=source' in native and '--cov-fail-under=0' not in native
    requirements = (ROOT / 'requirements-test-debian.txt').read_text(encoding='utf-8')
    assert 'PyQt6==' not in requirements and '-r requirements-qt6.txt' not in requirements
