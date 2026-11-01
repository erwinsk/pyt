"""Konfigurasi, konstanta, logging aplikasi, dan utilitas file konfigurasi."""
import os
import json
import time
import logging
import threading
import traceback
from logging.handlers import RotatingFileHandler

# =====================================================================
# DIREKTORI KONFIGURASI & LOGGING APLIKASI
# =====================================================================
def dapatkan_direktori_config():
    """Simpan file konfigurasi di folder config milik user (bukan di folder
    kerja saat ini), supaya preset tidak 'hilang' saat aplikasi dijalankan
    dari shortcut/folder yang berbeda-beda."""
    try:
        if os.name == 'nt':
            base = os.environ.get('APPDATA', os.path.expanduser('~'))
        else:
            base = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
        direktori = os.path.join(base, 'ModbusToolsKalingin')
        os.makedirs(direktori, exist_ok=True)
        return direktori
    except Exception:
        # Fallback ke direktori kerja jika folder config tidak bisa dibuat
        return os.getcwd()


DIR_CONFIG = dapatkan_direktori_config()

def _siapkan_logger():
    """Logger aplikasi dengan rotasi file (maks ~1 MB x 4 file) agar log tidak
    memenuhi disk walau ada error komunikasi yang berulang terus-menerus."""
    logger = logging.getLogger("ModbusToolsKalingin")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        try:
            handler = RotatingFileHandler(
                os.path.join(DIR_CONFIG, "aplikasi.log"),
                maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
        except Exception:
            handler = logging.NullHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
    return logger


logger_aplikasi = _siapkan_logger()

# Pembatas pencatatan error yang sama berulang-ulang (mis. perangkat mati yang
# dipolling tiap detik): traceback lengkap hanya dicatat sekali per jeda ini,
# kejadian serupa di antaranya cukup dihitung.
JEDA_LOG_ERROR_SAMA_DETIK = 60
_status_error_terakhir = {}
_kunci_status_error = threading.Lock()


def catat_kesalahan(konteks, exc):
    """Helper agar semua exception yang sebelumnya 'ditelan diam-diam' tetap
    tercatat ke file log, memudahkan diagnosa masalah di lapangan. Error yang
    sama (konteks + jenis exception) tidak dicatat berulang dalam
    JEDA_LOG_ERROR_SAMA_DETIK detik; jumlah yang ditahan ikut dilaporkan pada
    pencatatan berikutnya."""
    sekarang = time.time()
    kunci = f"{konteks}|{type(exc).__name__}"
    with _kunci_status_error:
        waktu_lama, tertahan = _status_error_terakhir.get(kunci, (0.0, 0))
        if sekarang - waktu_lama < JEDA_LOG_ERROR_SAMA_DETIK:
            _status_error_terakhir[kunci] = (waktu_lama, tertahan + 1)
            return
        _status_error_terakhir[kunci] = (sekarang, 0)
    keterangan = f" (+{tertahan} kejadian serupa ditahan)" if tertahan else ""
    logger_aplikasi.error(f"{konteks}: {exc}{keterangan}\n{traceback.format_exc()}")


def tulis_json_atomik(jalur, data, indent=None):
    """Tulis JSON lewat file sementara lalu os.replace(), supaya file
    konfigurasi tidak korup bila aplikasi/komputer mati saat sedang menulis."""
    sementara = jalur + ".tmp"
    with open(sementara, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=indent)
    os.replace(sementara, jalur)



# =====================================================================
# KONSTANTA GLOBAL
# =====================================================================
DAFTAR_ENCODING = [
    "Mentah (16-bit UINT)",
    "Signed 16-bit INT",
    "32-bit FLOAT (ABCD - Big Endian)",
    "32-bit FLOAT (CDAB - Word Swap)",
    "32-bit FLOAT (BADC - Byte Swap)",
    "32-bit FLOAT (DCBA - Little Endian)",
    "32-bit INT Signed (ABCD - Big Endian)",
    "32-bit INT Signed (CDAB - Word Swap)",
    "64-bit DOUBLE (ABCDEFGH - Big Endian)",
    "64-bit DOUBLE (HGFEDCBA - Little Endian)",
]

WARNA_SUKSES    = "#2ecc71"   
WARNA_GAGAL     = "#e74c3c"   
WARNA_HIGHLIGHT = "#f39c12"   

# File-file konfigurasi kini disimpan di folder config user, bukan di
# direktori kerja, supaya tidak hilang saat aplikasi dijalankan dari
# shortcut/folder lain.
FILE_PRESET      = os.path.join(DIR_CONFIG, "modbus_presets.json")
FILE_JOB_PRESET  = os.path.join(DIR_CONFIG, "modbus_job_presets.json")

WARNA_PERINGATAN = "#f1c40f"
# Awalan pesan status koneksi dari thread; dipakai UI untuk mengubah indikator.
AWALAN_PESAN_TERPUTUS   = "Koneksi terputus"
AWALAN_PESAN_TERSAMBUNG = "Koneksi berhasil disambung kembali"

# =====================================================================
# TERJEMAHAN KODE EXCEPTION MODBUS KE BAHASA MANUSIA
# =====================================================================
PESAN_EXCEPTION_MODBUS = {
    1: "Illegal Function - Perangkat tidak mendukung fungsi ini.",
    2: "Illegal Data Address - Alamat register tidak ada di perangkat.",
    3: "Illegal Data Value - Nilai yang dikirim tidak valid untuk perangkat.",
    4: "Slave Device Failure - Perangkat mengalami kegagalan internal.",
    5: "Acknowledge - Perangkat menerima perintah tapi masih memprosesnya.",
    6: "Slave Device Busy - Perangkat sedang sibuk, coba lagi nanti.",
    8: "Memory Parity Error - Kesalahan paritas memori pada perangkat.",
    10: "Gateway Path Unavailable - Gateway tidak menemukan jalur ke perangkat.",
    11: "Gateway Target Failed to Respond - Perangkat tujuan tidak merespon gateway.",
}
