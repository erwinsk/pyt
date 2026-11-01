"""Bangun aplikasi menjadi executable mandiri dengan PyInstaller.

Pemakaian:
    pip install -r requirements-dev.txt
    python build.py            # satu folder (cepat start, direkomendasikan)
    python build.py --onefile  # satu file .exe/biner (start lebih lambat)

Hasil ada di folder dist/. Jalankan di OS target (Windows build di Windows, dst.).
"""
import sys

import PyInstaller.__main__


def main():
    argumen = [
        "modbus_tool.py",
        "--name", "ModbusToolsKalingin",
        "--windowed",                        # tanpa jendela konsol
        "--noconfirm",
        "--clean",
        "--collect-submodules", "serial",    # pyserial memuat backend per-OS secara dinamis
        "--hidden-import", "serial.tools.list_ports",
    ]
    argumen.append("--onefile" if "--onefile" in sys.argv else "--onedir")
    PyInstaller.__main__.run(argumen)


if __name__ == "__main__":
    main()
