@echo off
rem Build satu-perintah untuk Windows: venv bersih -> dependensi -> tes -> PyInstaller -> zip.
rem Pemakaian:  build.bat            (mode folder + zip, direkomendasikan)
rem             build.bat --onefile  (satu exe, tanpa zip)
rem Lewati tes: set LEWATI_TES=1 && build.bat
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    py -3 -m venv .venv || goto :gagal
)
call .venv\Scripts\activate.bat || goto :gagal
python -m pip install --upgrade pip || goto :gagal
python -m pip install -r requirements-dev.txt || goto :gagal

if not defined LEWATI_TES (
    python -m pytest -q || goto :gagal
)

python build.py %* || goto :gagal
echo.
echo Selesai. Hasil ada di folder dist\
exit /b 0

:gagal
echo.
echo BUILD GAGAL. Periksa pesan di atas.
exit /b 1
