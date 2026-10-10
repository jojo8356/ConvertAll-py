"""Release drivers fail closed. Native bundle execution is a separate CI gate."""
from pathlib import Path
import subprocess

import pytest

from helpers import ROOT
import check_bundle
import release_source
import validate_release


def test_release_environment_versions_are_explicit():
    packages = validate_release.expected_packages()
    assert packages['PyQt5'] == '5.15.11'
    assert packages['pytest'] == '9.1.1'
    assert 'PyQt6' not in packages
    hashes = validate_release.input_hashes()
    assert 'source/convertall.py' in hashes
    assert 'data/units.dat' in hashes
    assert all(len(value) == 64 for value in hashes.values())
    assert not any('__pycache__' in name for name in hashes)
    assert all('\\' not in name for name in hashes)  # canonical JSON paths on every OS


@pytest.mark.parametrize('source', ["__version__ = '0.8.1-beta'", 'x = 1',
                                    '__version__ = 1'])
def test_archive_version_must_be_a_stable_semver(source):
    with pytest.raises(ValueError, match='stable'):
        release_source.version_from_source(source)


def test_bundle_validator_rejects_missing_executable(tmp_path):
    with pytest.raises(RuntimeError, match='Missing bundle resource'):
        check_bundle.check_bundle(tmp_path)


@pytest.mark.parametrize('reason', ['_internal', 'PyQt6'])
def test_bundle_validator_rejects_wrong_layout_or_binding(tmp_path, monkeypatch, reason):
    monkeypatch.setattr(check_bundle.sys, 'platform', 'linux')
    for name in ('convertall', 'data/units.dat', 'doc/LICENSE',
                 'icons/convertall_med.png', 'translations/convertall_fr.qm'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    (tmp_path / reason).mkdir()
    with pytest.raises(RuntimeError, match='flat|binding'):
        check_bundle.check_bundle(tmp_path)


def test_workflow_pins_actions_and_has_test_then_native_bundle_gate():
    workflow = (ROOT / '.github/workflows/qt5-release.yml').read_text()
    for action in ('checkout', 'setup-python', 'upload-artifact'):
        assert f'actions/{action}@' in workflow
    import re
    for ref in re.findall(r'uses: actions/[^@]+@([^\s]+)', workflow):
        assert re.fullmatch('[0-9a-f]{40}', ref)
    assert 'needs: tests' in workflow
    assert 'python tools/validate_release.py' in workflow
    assert 'python tools/check_bundle.py dist/convertall' in workflow
    assert 'windows-2022' in workflow and 'ubuntu-24.04' in workflow
    assert "'3.10'" in workflow and "'3.14'" in workflow
    assert 'contents: read' in workflow
    assert 'gh release create' not in workflow  # never publish automatically


def test_required_release_configuration_is_not_gitignored(tmp_path):
    # Also runnable from an extracted source archive with no .git directory.
    (tmp_path / '.gitignore').write_bytes((ROOT / '.gitignore').read_bytes())
    subprocess.run(['git', 'init', '-b', 'arena/0adacf84-convertall-py'],
                   cwd=tmp_path, check=True, capture_output=True, timeout=10)
    paths = ['.coveragerc', 'pytest.ini', 'requirements-test.txt',
             '.github/workflows/qt5-release.yml']
    result = subprocess.run(['git', 'check-ignore', '--', *paths], cwd=tmp_path,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1 and result.stdout == '', result.stdout + result.stderr
