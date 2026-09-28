# -*- mode: python ; coding: utf-8 -*-
# Update: sekarang meng-compile pdf_suite/main.py (aplikasi gabungan
# Compressor + PDF->Gambar), bukan lagi ultimate-pdf-compresor.py.
# Jalankan spec ini dari dalam folder pdf_tools/.

a = Analysis(
    ['pdf_suite/main.py'],
    pathex=['pdf_suite'],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PDF_Tools_Suite',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
