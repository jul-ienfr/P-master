# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

spec_dir = Path(SPECPATH)
repo_root = spec_dir.parent

datas = [
    (str(spec_dir / 'gui' / 'ui' / '*.ui'), '.'),
    (str(spec_dir / 'gui' / 'ui' / '*.ui'), 'gui/ui'),
    (str(spec_dir / 'decisionmaker' / '*.json'), 'decisionmaker'),
    (str(spec_dir / 'config.ini'), '.'),
    (str(spec_dir / 'config_default.ini'), '.'),
    (str(spec_dir / 'icon.ico'), '.'),
    (str(repo_root / 'tessdata'), 'tessdata'),
]
datas += collect_data_files('rapidocr')

binaries = []
gto_server_exe = repo_root / 'gto_server' / 'target' / 'release' / 'gto_server.exe'
if gto_server_exe.exists():
    binaries.append((str(gto_server_exe), '.'))

a = Analysis(['main.py'],
             pathex=[str(spec_dir)],
             datas=datas,
             binaries=binaries,
             hiddenimports=['fastapi'],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          [],
          exclude_binaries=True,
          name='main',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=True,
          icon='icon.ico')
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=True,
               upx_exclude=[],
               name='main')
