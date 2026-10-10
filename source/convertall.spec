# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 6.22.3, Qt5 only. Run from any cwd using an absolute spec path.
# Flat onedir layout is retained for the Unix resource loader and Inno Setup.
from pathlib import Path
import sys

source = Path(SPECPATH).resolve()
root = source.parent
resources = [(str(root / name), name)
             for name in ('data', 'doc', 'icons', 'translations')]
resources += [(str(path), 'source') for pattern in ('*.py', '*.pro', '*.spec')
              for path in source.glob(pattern)]
resources += [(str(path), '.') for path in (root / 'win').iterdir()
              if path.is_file()]

analysis = Analysis(
    [str(source / 'convertall.py')],
    pathex=[str(source)],
    binaries=[],
    datas=resources,
    hiddenimports=['PyQt5.QtWidgets'],  # CLI keeps GUI imports lazy
    hookspath=[],
    runtime_hooks=[],
    excludes=['PyQt6', 'PySide6', 'PySide2'],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
windows = sys.platform == 'win32'
common = dict(exclude_binaries=True, debug=False, strip=False, upx=False,
              contents_directory='.')
if windows:
    common['icon'] = str(root / 'win' / 'convertall.ico')
gui = EXE(pyz, analysis.scripts, [], name='convertall',
          console=not windows, **common)
executables = [gui]
if windows:
    # Keep a console entry point for CLI validation; convertall.exe is GUI-only.
    cli = EXE(pyz, analysis.scripts, [], name='convertall_dos', console=True,
              **common)
    executables.append(cli)
collection = COLLECT(*executables, analysis.binaries, analysis.datas,
                     strip=False, upx=False, name='convertall')
