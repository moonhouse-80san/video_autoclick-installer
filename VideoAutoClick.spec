# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 설정: build_exe.bat / GitHub Actions 에서 사용합니다.
# vac 패키지의 모든 모듈(gui 포함)을 확실히 포함시키기 위해 collect_submodules 를 씁니다.
from PyInstaller.utils.hooks import collect_all, collect_submodules

hiddenimports = collect_submodules('vac')
hiddenimports += ['tkinter', 'tkinter.ttk', 'tkinter.filedialog', 'tkinter.messagebox']
datas, binaries = [], []
for pkg in ('cv2', 'numpy', 'mss'):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VideoAutoClick',
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
