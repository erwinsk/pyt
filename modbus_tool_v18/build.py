"""Bangun aplikasi menjadi executable Windows/Linux dengan PyInstaller, dengan
pengaturan yang meminimalkan false positive antivirus, plus penandatanganan
kode (opsional) dan hash SHA-256 untuk distribusi.

Pemakaian (di Windows, dari folder proyek):
    pip install -r requirements-dev.txt
    python build.py                 # folder (DIREKOMENDASIKAN)
    python build.py --onefile       # satu .exe (lebih sering ditandai antivirus)
    python build.py --tanpa-zip     # mode folder tanpa membuat zip
  Di Windows, `build.bat` melakukan semuanya sekaligus (venv, dependensi, tes, build, zip).
  Mode folder menghasilkan dist/<nama>_v<versi>_win64.zip: BAGIKAN zip ini, bukan exe-nya saja.

Penandatanganan kode (opsional; butuh Windows SDK `signtool.exe` di PATH).
Mode folder: SEMUA exe/dll/pyd yang belum bertanda tangan sah ikut ditandatangani:
    set SIGN_THUMBPRINT=<sidik jari sertifikat di Windows Certificate Store>
    python build.py
  atau memakai berkas PFX:
    set SIGN_PFX=C:\\path\\sertifikat.pfx
    set SIGN_PFX_PASSWORD=...
  Opsional: SIGN_TIMESTAMP_URL (bawaan: http://timestamp.digicert.com)

Metadata yang tampil di Properties > Details (dan dipakai SmartScreen/AV):
    set PENERBIT="Nama Perusahaan Anda"      (bawaan: Kalingin)
Jika ada berkas `app.ico` di folder ini, otomatis dipakai sebagai ikon.
"""
import hashlib
import os
import shutil
import subprocess
import sys

import PyInstaller.__main__

from modbus_app import __version__

NAMA_APP = "ModbusToolsKalingin"
JUDUL_APP = "Modbus Tools Kalingin"
PENERBIT = os.environ.get("PENERBIT", "Kalingin")
ADALAH_WINDOWS = sys.platform.startswith("win")

TEMPLATE_VERSI = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({a}, {b}, {c}, 0), prodvers=({a}, {b}, {c}, 0),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{penerbit}'),
      StringStruct('FileDescription', '{judul}'),
      StringStruct('FileVersion', '{versi}'),
      StringStruct('InternalName', '{nama}'),
      StringStruct('LegalCopyright', 'Copyright (C) {penerbit}'),
      StringStruct('OriginalFilename', '{nama}.exe'),
      StringStruct('ProductName', '{judul}'),
      StringStruct('ProductVersion', '{versi}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ])
"""


def buat_berkas_versi(jalur="version_info.txt"):
    """Buat resource versi Windows. Exe tanpa metadata (publisher/versi/deskripsi)
    lebih sering dicurigai heuristik antivirus dan tampil 'Unknown publisher'."""
    bagian = (__version__.split(".") + ["0", "0", "0"])[:3]
    a, b, c = (int(x) for x in bagian)
    with open(jalur, "w", encoding="utf-8") as f:
        f.write(TEMPLATE_VERSI.format(a=a, b=b, c=c, penerbit=PENERBIT, judul=JUDUL_APP,
                                      versi=__version__, nama=NAMA_APP))
    return jalur


def bangun(onefile):
    argumen = [
        "modbus_tool.py", "--name", NAMA_APP, "--windowed", "--noconfirm", "--clean",
        "--noupx",                           # kompresi UPX sering memicu deteksi antivirus
        "--collect-submodules", "serial",    # pyserial memuat backend per-OS secara dinamis
        "--hidden-import", "serial.tools.list_ports",
        "--onefile" if onefile else "--onedir",
    ]
    if ADALAH_WINDOWS:
        argumen += ["--version-file", buat_berkas_versi()]
    if os.path.exists("app.ico"):
        argumen += ["--icon", "app.ico"]
    PyInstaller.__main__.run(argumen)


def exe_utama():
    """Jalur executable utama hasil build (satu file atau di dalam folder)."""
    kandidat = [
        os.path.join("dist", NAMA_APP + ".exe"),                    # --onefile Windows
        os.path.join("dist", NAMA_APP, NAMA_APP + ".exe"),          # --onedir Windows
        os.path.join("dist", NAMA_APP),                             # --onefile Linux/macOS
        os.path.join("dist", NAMA_APP, NAMA_APP),                   # --onedir Linux/macOS
    ]
    return next((k for k in kandidat if os.path.isfile(k)), None)


EKSTENSI_PE = (".exe", ".dll", ".pyd")


def kumpulkan_pe(folder):
    """Semua berkas PE (exe/dll/pyd) di dalam folder hasil build."""
    return [os.path.join(akar, nama)
            for akar, _dirs, namanama in os.walk(folder)
            for nama in namanama if nama.lower().endswith(EKSTENSI_PE)]


def sudah_bertanda_tangan(berkas):
    """True bila tanda tangan berkas sah dan berantai ke root tepercaya Windows."""
    return subprocess.call(["signtool", "verify", "/pa", berkas],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def tanda_tangani(berkas_berkas, ukuran_batch=40):
    """Tanda tangani SEMUA berkas PE yang belum bertanda tangan sah, bila
    SIGN_THUMBPRINT atau SIGN_PFX diset.

    Penting untuk Smart App Control: ia menilai semua kode yang dimuat, bukan hanya
    exe utama. Modul .pyd PyQt5 dan beberapa DLL tidak bertanda tangan, jadi menandatangani
    exe saja belum tentu cukup. Berkas yang sudah bertanda tangan sah (mis. python3xx.dll)
    dilewati supaya tanda tangan penerbit aslinya tidak tertimpa.
    Kembalian: True bila setelah itu semua berkas bertanda tangan sah."""
    thumbprint = os.environ.get("SIGN_THUMBPRINT")
    pfx = os.environ.get("SIGN_PFX")
    if not (thumbprint or pfx):
        print("[info] Penandatanganan dilewati (SIGN_THUMBPRINT/SIGN_PFX tidak diset).")
        return False
    if not ADALAH_WINDOWS:
        print("[peringatan] Penandatanganan hanya didukung di Windows (signtool).")
        return False
    stempel = os.environ.get("SIGN_TIMESTAMP_URL", "http://timestamp.digicert.com")
    perintah = ["signtool", "sign", "/fd", "SHA256", "/tr", stempel, "/td", "SHA256"]
    if thumbprint:
        perintah += ["/sha1", thumbprint]
    else:
        perintah += ["/f", pfx, "/p", os.environ.get("SIGN_PFX_PASSWORD", "")]

    belum = [b for b in berkas_berkas if not sudah_bertanda_tangan(b)]
    print(f"[info] {len(belum)} dari {len(berkas_berkas)} berkas PE perlu ditandatangani.")
    for i in range(0, len(belum), ukuran_batch):       # batch: hindari batas panjang baris perintah
        subprocess.check_call(perintah + belum[i:i + ukuran_batch])

    gagal = [b for b in berkas_berkas if not sudah_bertanda_tangan(b)]
    if gagal:
        print(f"[peringatan] {len(gagal)} berkas masih tanpa tanda tangan sah (contoh: {gagal[0]}).")
        return False
    print("[info] Semua berkas PE bertanda tangan sah.")
    return True


def cetak_sha256(berkas):
    with open(berkas, "rb") as f:
        hasil = hashlib.sha256(f.read()).hexdigest()
    print(f"SHA-256 {os.path.basename(berkas)}: {hasil}")
    return hasil


def buat_zip(folder_dist="dist"):
    """Kemas folder hasil build (--onedir) menjadi satu zip untuk dibagikan.
    Exe TIDAK bisa dipakai tanpa folder `_internal` di sebelahnya, jadi seluruh
    folder harus ikut. Dipanggil SETELAH penandatanganan agar isinya sudah final.
    Di dalam zip ada satu folder induk, sehingga hasil ekstraksi rapi."""
    folder_app = os.path.join(folder_dist, NAMA_APP)
    if not os.path.isdir(folder_app):
        raise FileNotFoundError(f"Folder hasil build tidak ditemukan: {folder_app}")
    if os.path.exists("PETUNJUK_PENGGUNA.txt"):
        shutil.copy("PETUNJUK_PENGGUNA.txt", folder_app)
    platform = "win64" if ADALAH_WINDOWS and sys.maxsize > 2**32 else sys.platform
    dasar = os.path.join(folder_dist, f"{NAMA_APP}_v{__version__}_{platform}")
    return shutil.make_archive(dasar, "zip", root_dir=folder_dist, base_dir=NAMA_APP)


def main():
    onefile = "--onefile" in sys.argv
    if onefile:
        print("[peringatan] --onefile mengekstrak dirinya ke folder sementara saat start; perilaku ini "
              "mirip packer malware sehingga lebih sering ditandai antivirus. Pakai default (folder) bila bisa.")
    bangun(onefile)
    berkas = exe_utama()
    if not berkas:
        sys.exit("Executable hasil build tidak ditemukan di folder dist/.")
    if onefile:
        # Isi --onefile tidak bisa ditandatangani satu-per-satu setelah dibungkus, dan saat start
        # ia mengekstrak DLL/pyd TANPA tanda tangan ke folder sementara -> Smart App Control menolaknya.
        tanda_tangani([berkas])
    else:
        tanda_tangani(kumpulkan_pe(os.path.join("dist", NAMA_APP)))
    cetak_sha256(berkas)     # hash exe: berguna untuk allow-list (WDAC/AppLocker)
    if not onefile and "--tanpa-zip" not in sys.argv:
        berkas_zip = buat_zip()
        print(f"[info] Paket siap dibagikan: {berkas_zip}")
        cetak_sha256(berkas_zip)   # bagikan hash zip agar penerima bisa memverifikasi unduhan


if __name__ == "__main__":
    main()
