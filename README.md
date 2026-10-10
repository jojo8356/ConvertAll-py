# ConvertAll-py — Qt5 0.8.1

ConvertAll combines units freely: inches per decade, meter-pounds or cubic
nautical miles. This repository maintains the **Python / PyQt5** application,
not the newer Flutter application published upstream.

## Run from source

Use Python **3.10–3.14** and a dedicated Qt5 virtual environment:

```sh
python3.11 -m venv .venv/release
. .venv/release/bin/activate
python -m pip install -r requirements-qt5.txt
python source/convertall.py
python source/convertall.py -q 1 in cm
```

On Windows, activate with `.venv\release\Scripts\Activate.ps1`. Linux needs
its normal Qt system libraries even for offscreen widget tests. The pinned
profile uses PyQt5 5.15.11; Qt is 5.15.19 on Linux/macOS and 5.15.2 on Windows.
Do not mix PyQt5 and PyQt6 in this environment.

## Validate a release

```sh
python -m pip install -r requirements-test.txt
python tools/validate_release.py
```

The gate runs all seven unit catalogues, numerical references and round trips,
CLI subprocesses, real Qt5 widgets/signals/keyboard/dialogs, translations,
preferences, the isolated Unix installer and reproducible source archives.
It requires **80% line/branch combined coverage** and saves JUnit, coverage
and input hashes under `build/test-results/` (not committed).

Additional application diagnostics:

```sh
python source/convertall.py --version
python source/convertall.py --test-all
python source/convertall.py --gui-smoke-test
```

The last command opens/checks/closes the application; it is not a normal GUI
session. Use `QT_QPA_PLATFORM=offscreen` on a headless Linux machine.

**Publication procedure, actual local results and manual acceptance checklist:**
[doc/RELEASE_QT5_FR.md](doc/RELEASE_QT5_FR.md) (French).
The CI workflow also builds and smoke-tests native Linux/Windows PyInstaller
bundles; it does **not** publish a release or certify an Inno Setup installer.

## Background

The [Qt6 audit and benchmark](doc/MIGRATION_QT6_FR.md) describe the historical
0.8.0 reference commit, not 0.8.1. Qt5 is retained here for this maintenance
release; passing application tests does not restore Qt5's upstream security
support. The original project licence is in [doc/LICENSE](doc/LICENSE);
binary distribution must also respect PyQt5/Qt/PyInstaller licences.
