import sys
import time
import csv
import json
import struct
import os
import logging
import traceback
from datetime import datetime
import serial.tools.list_ports

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QLabel, QLineEdit, QComboBox, QPushButton, QSpinBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QTextEdit, QFileDialog, QCheckBox, QGroupBox,
    QHeaderView, QMessageBox, QProgressBar, QStatusBar, QAction, QMenuBar,
    QSplitter, QInputDialog
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QMutex, QTimer
from PyQt5.QtGui import QColor, QFont, QPalette


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

logging.basicConfig(
    filename=os.path.join(DIR_CONFIG, "aplikasi.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger_aplikasi = logging.getLogger("ModbusToolsKalingin")


def catat_kesalahan(konteks, exc):
    """Helper agar semua exception yang sebelumnya 'ditelan diam-diam' tetap
    tercatat ke file log, memudahkan diagnosa masalah di lapangan."""
    logger_aplikasi.error(f"{konteks}: {exc}\n{traceback.format_exc()}")

# Mutex Global
kunci_komunikasi = QMutex()

# =====================================================================
# PYMODBUS MULTI-VERSION COMPATIBILITY LAYER
# =====================================================================
def get_modbus_device_kwargs(device_id):
    try:
        from pymodbus import __version__
        parts = __version__.split('.')
        v_major = int(parts[0]) if len(parts) > 0 else 0
        v_minor = int(parts[1]) if len(parts) > 1 else 0
    except ImportError:
        v_major, v_minor = 0, 0

    if v_major < 3:
        dev_key = "unit"
    elif v_major == 3 and v_minor < 11:
        dev_key = "slave"
    else:
        dev_key = "device_id"
        
    return {dev_key: device_id}


def client_terhubung(client):
    """Wrapper kompatibilitas status koneksi antar versi pymodbus.

    pymodbus >= 3.0 menyediakan properti `.connected` pada client.
    pymodbus 2.x (mis. 2.5.3 yang masih dipakai di beberapa board Raspberry
    Pi/embedded) TIDAK memiliki atribut ini sama sekali - mengaksesnya
    langsung memicu AttributeError ('ModbusSerialClient' object has no
    attribute 'connected'). Versi 2.x hanya menyediakan method
    is_socket_open() untuk keperluan yang sama.

    Fungsi ini mencoba `.connected` dulu (versi baru), lalu fallback ke
    is_socket_open() (versi lama), sehingga seluruh kode di aplikasi ini
    bisa memakai satu pemanggilan yang sama tanpa peduli versi pymodbus
    yang terpasang."""
    if client is None:
        return False
    if hasattr(client, 'connected'):
        try:
            return bool(client.connected)
        except Exception:
            pass
    if hasattr(client, 'is_socket_open'):
        try:
            return bool(client.is_socket_open())
        except Exception:
            return False
    return False

try:
    from pymodbus.client import ModbusSerialClient, ModbusTcpClient
except ImportError:
    from pymodbus.client.sync import ModbusSerialClient, ModbusTcpClient

def _buat_client_rtu(port, baudrate, parity, stopbits, bytesize, timeout, retries=3):
    try:
        from pymodbus import __version__
        v_major = int(__version__.split('.')[0])
    except:
        v_major = 0

    if v_major >= 3:
        return ModbusSerialClient(
            port=port, baudrate=baudrate, parity=parity,
            stopbits=stopbits, bytesize=bytesize, timeout=timeout, retries=retries
        )
    else:
        try:
            return ModbusSerialClient(
                method='rtu', port=port, baudrate=baudrate, parity=parity,
                stopbits=stopbits, bytesize=bytesize, timeout=timeout, retries=retries
            )
        except TypeError:
            # Beberapa versi lama tidak menerima kwarg 'retries'
            return ModbusSerialClient(
                method='rtu', port=port, baudrate=baudrate, parity=parity,
                stopbits=stopbits, bytesize=bytesize, timeout=timeout
            )

def _buat_client_tcp(host, port, timeout, retries=3):
    try:
        return ModbusTcpClient(host=host, port=port, timeout=timeout, retries=retries)
    except TypeError:
        return ModbusTcpClient(host=host, port=port, timeout=timeout)


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


def terjemahkan_respon_modbus(res):
    """Ubah objek error response pymodbus menjadi pesan Indonesia yang mudah
    dipahami teknisi di lapangan, alih-alih mencetak objek exception mentah."""
    try:
        kode = getattr(res, 'exception_code', None)
        if kode in PESAN_EXCEPTION_MODBUS:
            return f"{PESAN_EXCEPTION_MODBUS[kode]} (Kode: {kode})"
        return str(res)
    except Exception:
        return str(res)


# =====================================================================
# STATISTIK KESEHATAN KOMUNIKASI (untuk diagnosa bus RS-485/TCP)
# =====================================================================
class StatistikKomunikasi:
    def __init__(self):
        self._mutex = QMutex()
        self.sukses = 0
        self.gagal = 0
        self.timeout = 0

    def catat_sukses(self):
        self._mutex.lock()
        self.sukses += 1
        self._mutex.unlock()

    def catat_gagal(self, adalah_timeout=False):
        self._mutex.lock()
        self.gagal += 1
        if adalah_timeout:
            self.timeout += 1
        self._mutex.unlock()

    def reset(self):
        self._mutex.lock()
        self.sukses = 0
        self.gagal = 0
        self.timeout = 0
        self._mutex.unlock()

    def ringkasan(self):
        return f"Sukses: {self.sukses} | Gagal: {self.gagal} | Timeout: {self.timeout}"


statistik_global = StatistikKomunikasi()


# =====================================================================
# HELPER & DECODER
# =====================================================================
def baca_register_modbus(client, tipe_reg, address, count, device_id):
    kwargs = {'address': address, 'count': count}
    kwargs.update(get_modbus_device_kwargs(device_id))

    if tipe_reg == 'Holding':
        return client.read_holding_registers(**kwargs)
    elif tipe_reg == 'Input':
        return client.read_input_registers(**kwargs)
    elif tipe_reg == 'Coil':
        return client.read_coils(**kwargs)
    else:
        return client.read_discrete_inputs(**kwargs)

def dapatkan_jumlah_word(jenis_encoding):
    """Berapa banyak register (word) 16-bit yang dibutuhkan untuk 1 nilai
    dari suatu jenis encoding. Dipakai di semua tempat yang melakukan
    'chunking' register (scanner, reader, logger) agar tetap sinkron
    ketika ada tipe data baru (32-bit INT, 64-bit DOUBLE)."""
    if jenis_encoding in ("Mentah (16-bit UINT)", "Signed 16-bit INT"):
        return 1
    elif "64-bit" in jenis_encoding:
        return 4
    else:
        return 2  # semua varian 32-bit (FLOAT & INT)


def dekode_register_sepasang(r1, r2, jenis_encoding):
    """Dipertahankan untuk kompatibilitas: decode 32-bit FLOAT dari 2 register."""
    return dekode_register_multi([r1, r2], jenis_encoding)


def dekode_register_multi(list_reg, jenis_encoding):
    """Decode 1 nilai dari sejumlah register 16-bit sesuai jenis_encoding.
    Menggantikan logika pairing 'idx % 2 == 0' lama yang hanya berlaku untuk
    tipe 32-bit, agar mendukung juga 16-bit dan 64-bit DOUBLE secara konsisten."""
    try:
        n = dapatkan_jumlah_word(jenis_encoding)
        if len(list_reg) < n:
            return "-"

        if n == 1:
            if jenis_encoding == 'Signed 16-bit INT':
                return str(struct.unpack('h', struct.pack('H', int(list_reg[0]) & 0xFFFF))[0])
            return str(int(list_reg[0]) & 0xFFFF)

        potongan = [struct.pack('>H', int(r) & 0xFFFF) for r in list_reg[:n]]

        if n == 2:
            A, B = potongan[0][0], potongan[0][1]
            C, D = potongan[1][0], potongan[1][1]
            if "CDAB" in jenis_encoding:
                byte_final = bytes([C, D, A, B])
            elif "BADC" in jenis_encoding:
                byte_final = bytes([B, A, D, C])
            elif "DCBA" in jenis_encoding:
                byte_final = bytes([D, C, B, A])
            else:
                byte_final = bytes([A, B, C, D])

            if "INT" in jenis_encoding:
                val = struct.unpack('>i', byte_final)[0]
                return str(val)
            else:
                val = struct.unpack('>f', byte_final)[0]
                return f"{val:.4f}"

        else:  # n == 4 -> 64-bit DOUBLE
            semua_byte = b''.join(potongan)
            if "Little Endian" in jenis_encoding or "HGFEDCBA" in jenis_encoding:
                byte_final = semua_byte[::-1]
            else:
                byte_final = semua_byte
            val = struct.unpack('>d', byte_final)[0]
            return f"{val:.6f}"
    except Exception:
        return "Error Decode"


def enkode_nilai_ke_register(teks_input, jenis_encoding):
    try:
        val_float = float(teks_input)
        if jenis_encoding == 'Mentah (16-bit UINT)':
            return [int(val_float) & 0xFFFF]
        elif jenis_encoding == 'Signed 16-bit INT':
            return list(struct.unpack('>H', struct.pack('>h', int(val_float))))

        n = dapatkan_jumlah_word(jenis_encoding)

        if n == 4:  # 64-bit DOUBLE
            byte_mentah = struct.pack('>d', val_float)
            if "Little Endian" in jenis_encoding or "HGFEDCBA" in jenis_encoding:
                byte_final = byte_mentah[::-1]
            else:
                byte_final = byte_mentah
            return list(struct.unpack('>HHHH', byte_final))

        # n == 2: 32-bit FLOAT atau 32-bit INT Signed
        if "INT" in jenis_encoding:
            byte_mentah = struct.pack('>i', int(val_float))
        else:
            byte_mentah = struct.pack('>f', val_float)
        A, B, C, D = byte_mentah[0], byte_mentah[1], byte_mentah[2], byte_mentah[3]

        if "CDAB" in jenis_encoding:
            byte_final = bytes([C, D, A, B])
        elif "BADC" in jenis_encoding:
            byte_final = bytes([B, A, D, C])
        elif "DCBA" in jenis_encoding:
            byte_final = bytes([D, C, B, A])
        else:
            byte_final = bytes([A, B, C, D])

        return list(struct.unpack('>HH', byte_final))
    except Exception as e:
        raise ValueError(f"Gagal enkode format data: {str(e)}")


# =====================================================================
# THREAD WORKERS
# =====================================================================
class ModbusScannerThread(QThread):
    sinyal_progres = pyqtSignal(int, str)
    sinyal_hasil   = pyqtSignal(list)
    sinyal_selesai = pyqtSignal()
    sinyal_error   = pyqtSignal(str) 

    def __init__(self, client_global, jenis_scan="id", parameter_scan=None):
        super().__init__()
        self.client = client_global
        self.jenis_scan = jenis_scan
        self.parameter_scan = parameter_scan or {}
        self.apakah_berjalan = True

    def run(self):
        if not self.client or not client_terhubung(self.client):
            self.sinyal_error.emit("Master Modbus Utama belum terhubung!")
            self.sinyal_selesai.emit()
            return
        hasil = []
        if self.jenis_scan == "id":
            id_awal  = int(self.parameter_scan.get('id_awal', 1))
            id_akhir = int(self.parameter_scan.get('id_akhir', 247))
            tipe_reg = self.parameter_scan.get('tipe_reg', 'Holding')
            reg_uji  = int(self.parameter_scan.get('reg_uji', 0))
            total    = id_akhir - id_awal + 1

            for idx, slave_id in enumerate(range(id_awal, id_akhir + 1)):
                if not self.apakah_berjalan: break
                progres = int(((idx + 1) / total) * 100)
                self.sinyal_progres.emit(progres, f"Memindai Device ID: {slave_id}...")

                kunci_komunikasi.lock()
                try:
                    res = baca_register_modbus(self.client, tipe_reg, reg_uji, 1, slave_id)
                    if res and not res.isError():
                        hasil.append((slave_id, "MERESPON"))
                        statistik_global.catat_sukses()
                    elif res:
                        statistik_global.catat_gagal()
                except Exception as e:
                    adalah_timeout = "timeout" in str(e).lower() or "time out" in str(e).lower()
                    statistik_global.catat_gagal(adalah_timeout=adalah_timeout)
                    catat_kesalahan(f"Scan ID {slave_id}", e)
                    self.sinyal_error.emit(f"Error saat scan ID {slave_id}: {str(e)}")
                finally:
                    kunci_komunikasi.unlock()
                time.sleep(0.02)

        elif self.jenis_scan == "register":
            target_device_id = int(self.parameter_scan.get('slave_id', 1))
            tipe_reg  = self.parameter_scan.get('tipe_reg', 'Holding')
            reg_awal  = int(self.parameter_scan.get('reg_awal', 0))
            reg_akhir = int(self.parameter_scan.get('reg_akhir', 100))
            encoding  = self.parameter_scan.get('encoding', 'Mentah (16-bit UINT)')
            
            # Step selalu 1 agar tidak ada register yang terlewat
            langkah = 1
            daftar_reg = list(range(reg_awal, reg_akhir + 1, langkah))

            # FIX: jumlah register yang dibaca kini mengikuti kebutuhan
            # jenis encoding yang dipilih (1/2/4 word), bukan selalu 2.
            # Ini juga memperbaiki bug lama: nilai gabungan (float/int32/
            # double) sebelumnya hanya didekode pada baris dengan idx genap
            # (idx % 2 == 0), padahal di mode scan register setiap alamat
            # dibaca independen satu-per-satu sehingga seharusnya SELALU
            # bisa didekode jika register yang terbaca mencukupi.
            jumlah_word = dapatkan_jumlah_word(encoding)

            for idx, reg in enumerate(daftar_reg):
                if not self.apakah_berjalan: break
                progres = int(((idx + 1) / len(daftar_reg)) * 100)
                self.sinyal_progres.emit(progres, f"Memindai Register: {reg}...")

                jumlah_baca = jumlah_word if tipe_reg in ['Holding', 'Input'] else 1

                kunci_komunikasi.lock()
                try:
                    res = baca_register_modbus(self.client, tipe_reg, reg, jumlah_baca, target_device_id)
                    if res and not res.isError():
                        statistik_global.catat_sukses()
                        if tipe_reg in ['Holding', 'Input']:
                            val_int = str(struct.unpack('h', struct.pack('H', res.registers[0]))[0]) if encoding == 'Signed 16-bit INT' else str(res.registers[0])
                            val_gabungan = "-"
                            if jumlah_word > 1 and len(res.registers) >= jumlah_word:
                                val_gabungan = dekode_register_multi(res.registers, encoding)
                            hasil.append((reg, val_int, val_gabungan))
                        else:
                            hasil.append((reg, str(res.bits[0]), "-"))
                    elif res:
                        statistik_global.catat_gagal()
                        self.sinyal_error.emit(f"Register {reg}: {terjemahkan_respon_modbus(res)}")
                except Exception as e:
                    adalah_timeout = "timeout" in str(e).lower()
                    statistik_global.catat_gagal(adalah_timeout=adalah_timeout)
                    catat_kesalahan(f"Scan register {reg}", e)
                    self.sinyal_error.emit(f"Error saat scan register {reg}: {str(e)}")
                finally:
                    kunci_komunikasi.unlock()
                time.sleep(0.02)
                
        if self.apakah_berjalan: self.sinyal_progres.emit(100, "Proses Selesai.")
        self.sinyal_hasil.emit(hasil)
        self.sinyal_selesai.emit()


class ModbusPoolerLoggerThread(QThread):
    sinyal_data      = pyqtSignal(list, list, str, str)
    sinyal_kesalahan = pyqtSignal(str, str)
    sinyal_info      = pyqtSignal(str, str)

    # Batas mencoba ulang koneksi sebelum jeda tunggu berhenti bertambah
    BACKOFF_MAKS_DETIK = 30.0

    def __init__(self, client_global, parameter, target_tab="reader", single_shot=False, auto_reconnect=True):
        super().__init__()
        self.client     = client_global
        self.parameter  = parameter
        self.target_tab = target_tab
        self.single_shot = single_shot
        self.auto_reconnect = auto_reconnect
        self.apakah_berjalan = True

    def run(self):
        if not self.client:
            self.sinyal_kesalahan.emit("Koneksi master tidak aktif.", self.target_tab)
            return

        target_device_id = int(self.parameter['slave_id'])
        tipe_reg         = self.parameter['tipe_reg']
        reg_awal         = int(self.parameter['reg_awal'])
        jumlah           = int(self.parameter['jumlah'])
        encoding         = self.parameter['encoding']
        interval         = float(self.parameter['interval'])

        percobaan_reconnect = 0

        while self.apakah_berjalan:
            # FIX/Fitur: jika koneksi terputus di tengah polling/logging,
            # coba sambung ulang otomatis dengan backoff (0.5s, 1s, 2s, ...
            # sampai maksimum) alih-alih terus gagal diam-diam sampai
            # dihentikan manual oleh user.
            if not client_terhubung(self.client):
                if not self.auto_reconnect:
                    self.sinyal_kesalahan.emit("Koneksi terputus (auto-reconnect nonaktif).", self.target_tab)
                    break
                percobaan_reconnect += 1
                jeda = min(0.5 * (2 ** (percobaan_reconnect - 1)), self.BACKOFF_MAKS_DETIK)
                self.sinyal_info.emit(
                    f"Koneksi terputus. Mencoba sambung ulang (percobaan ke-{percobaan_reconnect})...",
                    self.target_tab
                )
                kunci_komunikasi.lock()
                try:
                    berhasil = self.client.connect()
                except Exception as e:
                    berhasil = False
                    catat_kesalahan("Auto-reconnect", e)
                finally:
                    kunci_komunikasi.unlock()

                if berhasil:
                    percobaan_reconnect = 0
                    self.sinyal_info.emit("Koneksi berhasil disambung kembali.", self.target_tab)
                else:
                    for _ in range(int(jeda * 10)):
                        if not self.apakah_berjalan: break
                        time.sleep(0.1)
                    continue

            kunci_komunikasi.lock()
            try:
                if client_terhubung(self.client):
                    res = baca_register_modbus(self.client, tipe_reg, reg_awal, jumlah, target_device_id)
                    if res and res.isError():
                        statistik_global.catat_gagal()
                        self.sinyal_kesalahan.emit(f"Modbus Error: {terjemahkan_respon_modbus(res)}", self.target_tab)
                    elif res:
                        statistik_global.catat_sukses()
                        list_alamat = list(range(reg_awal, reg_awal + jumlah))
                        if tipe_reg in ['Holding', 'Input']:
                            nilai_mentah = [str(r) for r in res.registers]
                        else:
                            nilai_mentah = [str(b) for b in res.bits[:jumlah]]
                        self.sinyal_data.emit(list_alamat, nilai_mentah, encoding, self.target_tab)
            except Exception as e:
                adalah_timeout = "timeout" in str(e).lower()
                statistik_global.catat_gagal(adalah_timeout=adalah_timeout)
                catat_kesalahan("Pooler/Logger", e)
                self.sinyal_kesalahan.emit(f"Gangguan Aliran Data: {str(e)}", self.target_tab)
            finally:
                kunci_komunikasi.unlock()

            if self.single_shot:
                break

            for _ in range(int(interval * 10)):
                if not self.apakah_berjalan: break
                time.sleep(0.1)


class TagListReaderThread(QThread):
    """Membaca sekumpulan tag yang alamatnya bisa TIDAK berurutan/kontinu
    (mis. suhu di Holding 100, tekanan di Input 40, status di Coil 5),
    masing-masing dengan tipe register, encoding, skala, dan offset sendiri.
    Ini melengkapi tab Reader/Logger yang hanya bisa membaca 1 blok alamat
    yang berurutan."""
    sinyal_hasil     = pyqtSignal(list)
    sinyal_kesalahan = pyqtSignal(str, str)
    sinyal_info      = pyqtSignal(str, str)

    def __init__(self, client_global, daftar_tag, single_shot=True, interval=2.0, auto_reconnect=True):
        super().__init__()
        self.client = client_global
        self.daftar_tag = daftar_tag
        self.single_shot = single_shot
        self.interval = interval
        self.auto_reconnect = auto_reconnect
        self.apakah_berjalan = True

    def run(self):
        if not self.client:
            self.sinyal_kesalahan.emit("Koneksi master tidak aktif.", "tag")
            return

        percobaan_reconnect = 0
        while self.apakah_berjalan:
            if not client_terhubung(self.client):
                if not self.auto_reconnect:
                    self.sinyal_kesalahan.emit("Koneksi terputus (auto-reconnect nonaktif).", "tag")
                    break
                percobaan_reconnect += 1
                jeda = min(0.5 * (2 ** (percobaan_reconnect - 1)), 30.0)
                self.sinyal_info.emit(f"Koneksi terputus, mencoba sambung ulang (ke-{percobaan_reconnect})...", "tag")
                kunci_komunikasi.lock()
                try:
                    berhasil = self.client.connect()
                except Exception as e:
                    berhasil = False
                    catat_kesalahan("Auto-reconnect (tag)", e)
                finally:
                    kunci_komunikasi.unlock()
                if berhasil:
                    percobaan_reconnect = 0
                else:
                    for _ in range(int(jeda * 10)):
                        if not self.apakah_berjalan: break
                        time.sleep(0.1)
                    continue

            hasil = []
            for tag in self.daftar_tag:
                if not self.apakah_berjalan: break
                nama = tag.get('nama', '-')
                slave_id = int(tag.get('slave_id', 1))
                tipe_reg = tag.get('tipe_reg', 'Holding')
                alamat = int(tag.get('alamat', 0))
                encoding = tag.get('encoding', 'Mentah (16-bit UINT)')
                skala = float(tag.get('skala', 1.0))
                offset = float(tag.get('offset', 0.0))
                jumlah = dapatkan_jumlah_word(encoding) if tipe_reg in ('Holding', 'Input') else 1

                kunci_komunikasi.lock()
                try:
                    res = baca_register_modbus(self.client, tipe_reg, alamat, jumlah, slave_id)
                    if res and not res.isError():
                        statistik_global.catat_sukses()
                        if tipe_reg in ('Holding', 'Input'):
                            nilai_mentah = list(res.registers[:jumlah])
                            nilai_decode = dekode_register_multi(nilai_mentah, encoding)
                            try:
                                nilai_akhir = f"{(float(nilai_decode) * skala) + offset:.4f}"
                            except (ValueError, TypeError):
                                nilai_akhir = nilai_decode
                        else:
                            nilai_mentah = [int(res.bits[0])]
                            nilai_akhir = str(bool(res.bits[0]))
                        hasil.append({'nama': nama, 'nilai_mentah': str(nilai_mentah), 'nilai_akhir': nilai_akhir, 'status': 'OK'})
                    elif res:
                        statistik_global.catat_gagal()
                        hasil.append({'nama': nama, 'nilai_mentah': '-', 'nilai_akhir': terjemahkan_respon_modbus(res), 'status': 'ERROR'})
                except Exception as e:
                    adalah_timeout = "timeout" in str(e).lower()
                    statistik_global.catat_gagal(adalah_timeout=adalah_timeout)
                    catat_kesalahan(f"Baca tag {nama}", e)
                    hasil.append({'nama': nama, 'nilai_mentah': '-', 'nilai_akhir': f"Error: {e}", 'status': 'ERROR'})
                finally:
                    kunci_komunikasi.unlock()
                time.sleep(0.01)

            self.sinyal_hasil.emit(hasil)

            if self.single_shot:
                break
            for _ in range(int(self.interval * 10)):
                if not self.apakah_berjalan: break
                time.sleep(0.1)


# =====================================================================
# ANTARMUKA UTAMA (GUI)
# =====================================================================
class ModbusApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modbus Tools Kalingin v4.17")
        self.resize(1100, 860)

        self.client_global    = None
        self.thread_pemindai  = None
        self.thread_pooler    = None
        self.thread_logger    = None
        self.thread_tag       = None
        self.memori_keterangan_user = {}
        self.nilai_sebelumnya = {}
        self.daftar_tag       = []   # daftar dict tag untuk tab "Daftar Tag"
        self.mode_gelap       = False
        self._rotasi_csv_hitungan = 0
        self._tanggal_csv_aktif = None

        self.inisialisasi_ui()
        self.penyegaran_port_serial()
        self._muat_preset_terakhir()

        # Timer untuk memperbarui label statistik komunikasi secara berkala
        self.timer_statistik = QTimer(self)
        self.timer_statistik.timeout.connect(self._perbarui_label_statistik)
        self.timer_statistik.start(1000)

    def inisialisasi_ui(self):
        widget_utama   = QWidget()
        self.setCentralWidget(widget_utama)
        tata_letak_utama = QVBoxLayout(widget_utama)
        tata_letak_utama.setSpacing(6)

        self._buat_menu_bar()
        self._buat_panel_koneksi(tata_letak_utama)
        self._buat_status_bar()

        self.tabs = QTabWidget()
        tata_letak_utama.addWidget(self.tabs)

        self.buat_tab_slave_id_scanner()
        self.buat_tab_register_scanner()
        self.buat_tab_reader_pooler()
        self.buat_tab_write_payload()
        self.buat_tab_logger()
        self.buat_tab_daftar_tag()

    def _buat_menu_bar(self):
        menubar = self.menuBar()
        menu_file = menubar.addMenu("File")
        aksi_simpan = QAction("Export Preset Koneksi...", self)
        aksi_simpan.setToolTip("Simpan hanya pengaturan koneksi (port/baud/host/dll)")
        aksi_simpan.triggered.connect(self.simpan_preset_koneksi)
        aksi_muat = QAction("Import Preset Koneksi...", self)
        aksi_muat.triggered.connect(self.muat_preset_koneksi)
        menu_file.addAction(aksi_simpan)
        menu_file.addAction(aksi_muat)
        menu_file.addSeparator()

        aksi_simpan_job = QAction("Export Preset Pekerjaan (Lengkap)...", self)
        aksi_simpan_job.setToolTip("Simpan koneksi + semua pengaturan tab (scan, reader, write, logger, daftar tag)")
        aksi_simpan_job.triggered.connect(self.simpan_preset_pekerjaan)
        aksi_muat_job = QAction("Import Preset Pekerjaan (Lengkap)...", self)
        aksi_muat_job.triggered.connect(self.muat_preset_pekerjaan)
        menu_file.addAction(aksi_simpan_job)
        menu_file.addAction(aksi_muat_job)
        menu_file.addSeparator()

        aksi_keluar = QAction("Keluar", self)
        aksi_keluar.setShortcut("Ctrl+Q")
        aksi_keluar.setToolTip("Tutup aplikasi (semua koneksi/thread yang aktif akan dihentikan lebih dahulu).")
        aksi_keluar.triggered.connect(self.close)
        menu_file.addAction(aksi_keluar)

        menu_export = menubar.addMenu("Export Data")
        aksi_exp_id  = QAction("Export Hasil Scan ID ke CSV", self)
        aksi_exp_id.triggered.connect(lambda: self._export_tabel_ke_csv(self.tabel_hasil_id, "scan_id"))
        aksi_exp_reg = QAction("Export Hasil Scan Register ke CSV", self)
        aksi_exp_reg.triggered.connect(lambda: self._export_tabel_ke_csv(self.tabel_hasil_register, "scan_register"))
        menu_export.addAction(aksi_exp_id)
        menu_export.addAction(aksi_exp_reg)

        menu_tampilan = menubar.addMenu("Tampilan")
        self.aksi_mode_gelap = QAction("Mode Gelap", self, checkable=True)
        self.aksi_mode_gelap.toggled.connect(self.toggle_mode_gelap)
        menu_tampilan.addAction(self.aksi_mode_gelap)

        menu_bantuan = menubar.addMenu("Bantuan")
        aksi_tentang = QAction("Tentang Aplikasi", self)
        aksi_tentang.triggered.connect(self._tampilkan_tentang)
        menu_bantuan.addAction(aksi_tentang)
        aksi_buka_log = QAction("Buka Folder Log/Config...", self)
        aksi_buka_log.triggered.connect(self._buka_folder_config)
        menu_bantuan.addAction(aksi_buka_log)

    def toggle_mode_gelap(self, aktif):
        self.mode_gelap = aktif
        app = QApplication.instance()
        if aktif:
            palet = QPalette()
            palet.setColor(QPalette.Window, QColor(45, 45, 48))
            palet.setColor(QPalette.WindowText, Qt.white)
            palet.setColor(QPalette.Base, QColor(30, 30, 30))
            palet.setColor(QPalette.AlternateBase, QColor(45, 45, 48))
            palet.setColor(QPalette.ToolTipBase, Qt.white)
            palet.setColor(QPalette.ToolTipText, Qt.white)
            palet.setColor(QPalette.Text, Qt.white)
            palet.setColor(QPalette.Button, QColor(45, 45, 48))
            palet.setColor(QPalette.ButtonText, Qt.white)
            palet.setColor(QPalette.Highlight, QColor(38, 79, 120))
            palet.setColor(QPalette.HighlightedText, Qt.white)
            app.setPalette(palet)
        else:
            app.setPalette(QApplication.style().standardPalette())

    def _buka_folder_config(self):
        try:
            import subprocess
            if sys.platform.startswith('win'):
                os.startfile(DIR_CONFIG)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', DIR_CONFIG])
            else:
                subprocess.Popen(['xdg-open', DIR_CONFIG])
        except Exception as e:
            QMessageBox.information(self, "Folder Config", f"Lokasi folder:\n{DIR_CONFIG}\n\n(Gagal membuka otomatis: {e})")

    def _perbarui_label_statistik(self):
        if hasattr(self, 'lbl_statistik'):
            self.lbl_statistik.setText(statistik_global.ringkasan())

    def _buat_panel_koneksi(self, tata_letak_utama):
        box_koneksi  = QGroupBox("Konfigurasi Jalur Komunikasi Master")
        box_koneksi.setMaximumHeight(140) 
        layout_utama = QHBoxLayout(box_koneksi)
        layout_utama.setContentsMargins(5, 5, 5, 5) 

        grp_mode = QGroupBox("Metode")
        vbox_mode = QVBoxLayout(grp_mode)
        vbox_mode.setContentsMargins(4, 10, 4, 4)
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["RTU (Serial)", "TCP (Ethernet)"])
        self.combo_mode.currentIndexChanged.connect(self.perubahan_ui_mode)
        vbox_mode.addWidget(self.combo_mode)
        vbox_mode.addStretch()
        layout_utama.addWidget(grp_mode)

        self.grp_rtu = QGroupBox("RTU Serial")
        grid_rtu = QGridLayout(self.grp_rtu)
        grid_rtu.setContentsMargins(2, 2, 2, 2)
        grid_rtu.setVerticalSpacing(2)
        grid_rtu.addWidget(QLabel("Port COM"), 0, 0)
        grid_rtu.addWidget(QLabel("Baud Rate"), 0, 1)
        grid_rtu.addWidget(QLabel("Data Bits"), 0, 2)
        grid_rtu.addWidget(QLabel("Stop Bits"), 0, 3)
        grid_rtu.addWidget(QLabel("Paritas"), 0, 4)

        self.combo_port = QComboBox()
        grid_rtu.addWidget(self.combo_port, 1, 0)
        self.combo_baud = QComboBox()
        self.combo_baud.addItems(["2400", "4800", "9600", "19200", "38400", "57600", "115200"])
        self.combo_baud.setCurrentText("9600")
        grid_rtu.addWidget(self.combo_baud, 1, 1)
        self.combo_bytesize = QComboBox()
        self.combo_bytesize.addItems(["8", "7"])
        grid_rtu.addWidget(self.combo_bytesize, 1, 2)
        self.combo_stopbits = QComboBox()
        self.combo_stopbits.addItems(["1", "2"])
        grid_rtu.addWidget(self.combo_stopbits, 1, 3)
        self.combo_parity = QComboBox()
        self.combo_parity.addItems(["N (None)", "E (Even)", "O (Odd)"])
        grid_rtu.addWidget(self.combo_parity, 1, 4)
        self.btn_refresh_port = QPushButton("Segarkan Port")
        self.btn_refresh_port.clicked.connect(self.penyegaran_port_serial)
        grid_rtu.addWidget(self.btn_refresh_port, 2, 0, 1, 2)
        layout_utama.addWidget(self.grp_rtu)

        self.grp_tcp = QGroupBox("TCP Ethernet")
        grid_tcp = QGridLayout(self.grp_tcp)
        grid_tcp.setContentsMargins(4, 10, 4, 4)
        grid_tcp.addWidget(QLabel("IP Host"), 0, 0)
        grid_tcp.addWidget(QLabel("Port TCP"), 0, 1)
        self.txt_host = QLineEdit("127.0.0.1")
        grid_tcp.addWidget(self.txt_host, 1, 0)
        self.spin_tcp_port = QSpinBox()
        self.spin_tcp_port.setRange(1, 65535)
        self.spin_tcp_port.setValue(502)
        grid_tcp.addWidget(self.spin_tcp_port, 1, 1)
        layout_utama.addWidget(self.grp_tcp)

        grp_timeout = QGroupBox("Timeout(s)")
        vbox_timeout = QVBoxLayout(grp_timeout)
        vbox_timeout.setContentsMargins(4, 10, 4, 4)
        self.spin_timeout = QDoubleSpinBox()
        self.spin_timeout.setRange(0.1, 30.0)
        self.spin_timeout.setValue(1.0)
        self.spin_timeout.setToolTip("Batas waktu menunggu balasan perangkat sebelum dianggap gagal.")
        vbox_timeout.addWidget(self.spin_timeout)
        vbox_timeout.addStretch()
        layout_utama.addWidget(grp_timeout)

        grp_retry = QGroupBox("Retry")
        vbox_retry = QVBoxLayout(grp_retry)
        vbox_retry.setContentsMargins(4, 10, 4, 4)
        self.spin_retries = QSpinBox()
        self.spin_retries.setRange(0, 10)
        self.spin_retries.setValue(3)
        self.spin_retries.setToolTip("Jumlah percobaan ulang otomatis oleh pymodbus jika 1 permintaan gagal (berguna untuk bus RS-485 yang noisy).")
        vbox_retry.addWidget(self.spin_retries)
        vbox_retry.addStretch()
        layout_utama.addWidget(grp_retry)

        grp_reconnect = QGroupBox("Auto-Reconnect")
        vbox_reconnect = QVBoxLayout(grp_reconnect)
        vbox_reconnect.setContentsMargins(4, 10, 4, 4)
        self.chk_auto_reconnect = QCheckBox("Aktif")
        self.chk_auto_reconnect.setChecked(True)
        self.chk_auto_reconnect.setToolTip("Jika koneksi terputus saat polling/logging berjalan, coba sambung ulang otomatis (backoff bertahap).")
        vbox_reconnect.addWidget(self.chk_auto_reconnect)
        vbox_reconnect.addStretch()
        layout_utama.addWidget(grp_reconnect)

        # ── Kolom Aksi & Indikator (Ditata Secara Proporsional) ─────────
        grp_aksi = QGroupBox("Koneksi")
        vbox_aksi = QVBoxLayout(grp_aksi)
        vbox_aksi.setContentsMargins(2, 2, 2, 2)
        
        # FIX: Tombol Hubungkan & Putuskan diposisikan side-by-side
        hbox_btn = QHBoxLayout()
        
        # Jarak antar tombol 10 pixel
        hbox_btn.setSpacing(10) 

        self.btn_hubungkan = QPushButton("Hubungkan")
        # Mengubah tinggi dan lebar tombol
        self.btn_hubungkan.setFixedSize(100, 35) 
        self.btn_hubungkan.clicked.connect(self.buka_koneksi_modbus)
        
        self.btn_putuskan = QPushButton("Putuskan")
        self.btn_putuskan.setFixedSize(100, 35)
        self.btn_putuskan.setEnabled(False)
        self.btn_putuskan.clicked.connect(self.tutup_koneksi_modbus)
        
        # Mendorong tombol ke tengah
        hbox_btn.addWidget(self.btn_hubungkan)
        hbox_btn.addWidget(self.btn_putuskan)

        self.lbl_indikator = QLabel("● OFFLINE")
        self.lbl_indikator.setAlignment(Qt.AlignCenter)
        self.lbl_indikator.setStyleSheet(f"color: {WARNA_GAGAL}; font-weight: bold; font-size: 13px;")
        
        vbox_aksi.addLayout(hbox_btn)
        vbox_aksi.addSpacing(4)
        vbox_aksi.addWidget(self.lbl_indikator)
        vbox_aksi.addStretch()
        layout_utama.addWidget(grp_aksi)

        tata_letak_utama.addWidget(box_koneksi)
        self.perubahan_ui_mode()

    def _buat_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.lbl_status_teks = QLabel("Sistem Berhenti / Belum Terkoneksi.")
        self.status_bar.addWidget(self.lbl_status_teks, 1)

        # Statistik kesehatan komunikasi (sukses/gagal/timeout), berguna
        # untuk diagnosa kualitas bus RS-485/TCP tanpa perlu buka log file.
        self.lbl_statistik = QLabel(statistik_global.ringkasan())
        self.lbl_statistik.setToolTip("Statistik kumulatif permintaan Modbus sejak aplikasi dibuka. Klik untuk reset.")
        self.lbl_statistik.mousePressEvent = lambda ev: self._reset_statistik()
        self.status_bar.addPermanentWidget(self.lbl_statistik)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumWidth(200)
        self.status_bar.addPermanentWidget(self.progress_bar)

    def _reset_statistik(self):
        statistik_global.reset()
        self._perbarui_label_statistik()

    def _set_status(self, pesan, progres=-1):
        self.lbl_status_teks.setText(pesan)
        if progres >= 0:
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(progres)
        else:
            self.progress_bar.setVisible(False)

    def penyegaran_port_serial(self):
        self.combo_port.clear()
        ports_terdeteksi = {}

        # 1) Deteksi via pyserial (comports()).
        #    Di banyak board Linux embedded (termasuk Rockchip), pyserial hanya
        #    mengenali port yang punya symlink 'device' lengkap di sysfs — biasanya
        #    UART via USB (ttyUSBx/ttyACMx). UART bawaan board seperti ttyS0-ttyS4
        #    sering TIDAK ikut terdeteksi walau nodenya benar-benar ada di /dev.
        try:
            for p in serial.tools.list_ports.comports():
                ports_terdeteksi[p.device] = p.description
        except Exception as e:
            self._log_gagal_deteksi_port(str(e))

        # 2) FIX: fallback pemindaian manual ke /dev untuk pola UART yang umum
        #    dipakai di board embedded (termasuk Rockchip ttyS0-ttyS4), supaya
        #    port yang terlewat oleh pyserial tetap muncul di daftar.
        pola_tambahan = [
            "/dev/ttyS*",      # UART bawaan SoC (mis. Rockchip ttyS0-ttyS4)
            "/dev/ttyUSB*",    # USB-to-serial (FTDI, CH340, dst)
            "/dev/ttyACM*",    # USB CDC-ACM
            "/dev/ttyAMA*",    # UART PL011 (mis. Raspberry Pi/board ARM lain)
            "/dev/ttyFIQ*",    # UART fastcall khusus sebagian board Rockchip
        ]
        try:
            import glob
            for pola in pola_tambahan:
                for dev in glob.glob(pola):
                    if dev not in ports_terdeteksi:
                        ports_terdeteksi[dev] = "Terdeteksi manual (UART board)"
        except Exception as e:
            self._log_gagal_deteksi_port(str(e))

        for dev in sorted(ports_terdeteksi.keys()):
            self.combo_port.addItem(dev)

        if self.combo_port.count() == 0:
            self.combo_port.addItem("Tidak Ada Port")

    def _log_gagal_deteksi_port(self, pesan_error):
        # Tidak menghentikan aplikasi hanya karena satu metode deteksi gagal
        # (mis. karena permission), tetapi tetap diberi tahu ke status bar.
        try:
            self._set_status(f"Peringatan saat memindai port: {pesan_error}")
        except Exception:
            pass

    def perubahan_ui_mode(self):
        is_rtu = "RTU" in self.combo_mode.currentText()
        self.grp_rtu.setVisible(is_rtu)
        self.grp_tcp.setVisible(not is_rtu)

    def dapatkan_konfigurasi_koneksi(self):
        paritas_map = {"N (None)": "N", "E (Even)": "E", "O (Odd)": "O"}
        return {
            'mode':     'RTU' if "RTU" in self.combo_mode.currentText() else 'TCP',
            'port':     self.combo_port.currentText(),
            'baudrate': self.combo_baud.currentText(),
            'parity':   paritas_map.get(self.combo_parity.currentText(), 'N'),
            'stopbits': self.combo_stopbits.currentText(),
            'bytesize': self.combo_bytesize.currentText(),
            'host':     self.txt_host.text(),
            'tcp_port': self.spin_tcp_port.value(),
            'timeout':  self.spin_timeout.value(),
            'retries':  self.spin_retries.value(),
            'auto_reconnect': self.chk_auto_reconnect.isChecked(),
        }

    def box_pengunci_koneksi(self, disabled):
        self.combo_mode.setEnabled(not disabled)
        self.combo_port.setEnabled(not disabled)
        self.combo_baud.setEnabled(not disabled)
        self.combo_parity.setEnabled(not disabled)
        self.combo_stopbits.setEnabled(not disabled)
        self.combo_bytesize.setEnabled(not disabled)
        self.txt_host.setEnabled(not disabled)
        self.spin_tcp_port.setEnabled(not disabled)
        self.spin_timeout.setEnabled(not disabled)
        self.spin_retries.setEnabled(not disabled)
        self.btn_refresh_port.setEnabled(not disabled)

    def buka_koneksi_modbus(self):
        config = self.dapatkan_konfigurasi_koneksi()
        if config['mode'] == 'RTU' and config['port'] == "Tidak Ada Port":
            QMessageBox.warning(self, "Port Tidak Tersedia",
                                 "Tidak ada port serial yang terdeteksi. "
                                 "Klik 'Segarkan Port' atau periksa hak akses /dev/ttyS*.")
            return
        try:
            if config['mode'] == 'RTU':
                self.client_global = _buat_client_rtu(
                    port=config['port'], baudrate=int(config['baudrate']),
                    parity=config['parity'], stopbits=int(config['stopbits']),
                    bytesize=int(config['bytesize']), timeout=float(config['timeout']),
                    retries=int(config['retries'])
                )
            else:
                self.client_global = _buat_client_tcp(
                    host=config['host'], port=int(config['tcp_port']), timeout=float(config['timeout']),
                    retries=int(config['retries'])
                )

            if self.client_global.connect():
                self.btn_hubungkan.setEnabled(False)
                self.btn_putuskan.setEnabled(True)
                self.box_pengunci_koneksi(True)
                if config['mode'] == 'RTU':
                    self._set_status("Menunggu inisialisasi sinkronisasi perangkat...")
                    QTimer.singleShot(2000, self._selesai_koneksi_rtu)
                else:
                    self._selesai_koneksi_rtu()
            else:
                self._set_status("Gagal membuka komunikasi fisik ke perangkat.")
        except Exception as e:
            QMessageBox.critical(self, "Error Koneksi", f"Gagal Inisialisasi: {str(e)}")

    def _selesai_koneksi_rtu(self):
        self.lbl_indikator.setText("● ONLINE")
        self.lbl_indikator.setStyleSheet(f"color: {WARNA_SUKSES}; font-weight: bold;")
        self._set_status("Koneksi berhasil dibuka.")

    def tutup_koneksi_modbus(self):
        self.matikan_semua_thread_aktif()
        if self.client_global:
            self.client_global.close()
        self.client_global = None
        self.btn_hubungkan.setEnabled(True)
        self.btn_putuskan.setEnabled(False)
        self.box_pengunci_koneksi(False)
        self.lbl_indikator.setText("● OFFLINE")
        self.lbl_indikator.setStyleSheet(f"color: {WARNA_GAGAL}; font-weight: bold;")
        self._set_status("Koneksi diputus.")

    def simpan_preset_koneksi(self):
        config = self.dapatkan_konfigurasi_koneksi()
        jalur, _ = QFileDialog.getSaveFileName(self, "Export Preset Pengaturan", "modbus_presets.json", "JSON Files (*.json)")
        if not jalur: return
        try:
            with open(jalur, 'w') as f:
                json.dump(config, f, indent=4)
            QMessageBox.information(self, "Berhasil", "Preset pengaturan berhasil diekspor.")
            with open(FILE_PRESET, 'w') as f:
                 json.dump(config, f)
        except Exception as e:
            catat_kesalahan("Simpan preset koneksi", e)
            QMessageBox.warning(self, "Error", f"Gagal mengekspor: {str(e)}")

    def muat_preset_koneksi(self):
        jalur, _ = QFileDialog.getOpenFileName(self, "Import Preset Pengaturan", "", "JSON Files (*.json)")
        if not jalur: return
        try:
            self._terapkan_preset_dari_file(jalur)
            QMessageBox.information(self, "Berhasil", "Preset pengaturan berhasil dimuat.")
        except Exception as e:
            catat_kesalahan("Muat preset koneksi", e)
            QMessageBox.warning(self, "Error", f"Gagal memuat preset: {str(e)}")

    def _muat_preset_terakhir(self):
        try:
            self._terapkan_preset_dari_file(FILE_PRESET)
        except Exception as e:
            # FIX: sebelumnya error di sini ditelan diam-diam (bare except: pass)
            # sehingga jika file preset korup, user tidak tahu kenapa setting
            # tidak termuat. Sekarang dicatat ke log aplikasi.
            catat_kesalahan("Muat preset terakhir", e)

    def _terapkan_preset_dari_file(self, jalur):
        if not os.path.exists(jalur): return
        with open(jalur, 'r') as f:
            config = json.load(f)
        if config.get('mode') == 'RTU':
            self.combo_mode.setCurrentText("RTU (Serial)")
        else:
            self.combo_mode.setCurrentText("TCP (Ethernet)")
        
        idx = self.combo_baud.findText(str(config.get('baudrate', '9600')))
        if idx >= 0: self.combo_baud.setCurrentIndex(idx)
        parity_rev = {"N": "N (None)", "E": "E (Even)", "O": "O (Odd)"}
        self.combo_parity.setCurrentText(parity_rev.get(config.get('parity', 'N'), 'N (None)'))
        self.combo_stopbits.setCurrentText(str(config.get('stopbits', '1')))
        self.combo_bytesize.setCurrentText(str(config.get('bytesize', '8')))
        self.txt_host.setText(config.get('host', '127.0.0.1'))
        self.spin_tcp_port.setValue(int(config.get('tcp_port', 502)))
        self.spin_timeout.setValue(float(config.get('timeout', 1.0)))
        self.spin_retries.setValue(int(config.get('retries', 3)))
        self.chk_auto_reconnect.setChecked(bool(config.get('auto_reconnect', True)))

        # FIX: preset port serial sebelumnya tidak pernah diterapkan kembali
        # (kolom 'port' pada config diabaikan sepenuhnya). Kini dicoba dipilih
        # ulang jika port tersebut masih terdeteksi di combo_port.
        port_tersimpan = config.get('port', '')
        if port_tersimpan:
            idx_port = self.combo_port.findText(port_tersimpan)
            if idx_port >= 0:
                self.combo_port.setCurrentIndex(idx_port)

    # ==================================================================
    # PRESET PEKERJAAN (LENGKAP) - koneksi + semua pengaturan tab
    # ==================================================================
    def _kumpulkan_preset_pekerjaan(self):
        return {
            'koneksi': self.dapatkan_konfigurasi_koneksi(),
            'scan_id': {
                'id_awal': self.spin_start_id.value(),
                'id_akhir': self.spin_end_id.value(),
                'tipe_reg': self.combo_id_scan_reg_type.currentText(),
                'reg_uji': self.spin_test_reg.value(),
            },
            'scan_register': {
                'slave_id': self.spin_reg_scan_slave.value(),
                'tipe_reg': self.combo_reg_scan_type.currentText(),
                'reg_awal': self.spin_reg_scan_start.value(),
                'reg_akhir': self.spin_reg_scan_end.value(),
                'encoding': self.combo_reg_scan_enc.currentText(),
            },
            'reader': {
                'slave_id': self.spin_read_slave.value(),
                'tipe_reg': self.combo_read_type.currentText(),
                'reg_awal': self.spin_read_addr.value(),
                'jumlah': self.spin_read_count.value(),
                'encoding': self.combo_encoding.currentText(),
                'interval': self.spin_pool_interval.value(),
            },
            'write': {
                'slave_id': self.spin_write_slave.value(),
                'tipe_fungsi': self.combo_write_type.currentText(),
                'alamat': self.spin_write_addr.value(),
                'encoding': self.combo_write_encoding.currentText(),
            },
            'logger': {
                'slave_id': self.spin_log_slave.value(),
                'tipe_reg': self.combo_log_type.currentText(),
                'reg_awal': self.spin_log_addr.value(),
                'jumlah': self.spin_log_count.value(),
                'encoding': self.combo_log_encoding.currentText(),
                'interval': self.spin_log_interval.value(),
                'csv_path': self.txt_csv_path.text(),
                'simpan_csv': self.chk_save_csv.isChecked(),
                'rotasi_mb': self.spin_rotasi_mb.value(),
                'rotasi_harian': self.chk_rotasi_harian.isChecked(),
            },
            'daftar_tag': self.daftar_tag,
        }

    def _terapkan_preset_pekerjaan(self, data):
        koneksi = data.get('koneksi')
        if koneksi:
            tmp_path = os.path.join(DIR_CONFIG, "_tmp_job_koneksi.json")
            with open(tmp_path, 'w') as f:
                json.dump(koneksi, f)
            self._terapkan_preset_dari_file(tmp_path)
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        si = data.get('scan_id', {})
        self.spin_start_id.setValue(int(si.get('id_awal', self.spin_start_id.value())))
        self.spin_end_id.setValue(int(si.get('id_akhir', self.spin_end_id.value())))
        if 'tipe_reg' in si: self.combo_id_scan_reg_type.setCurrentText(si['tipe_reg'])
        self.spin_test_reg.setValue(int(si.get('reg_uji', self.spin_test_reg.value())))

        sr = data.get('scan_register', {})
        self.spin_reg_scan_slave.setValue(int(sr.get('slave_id', self.spin_reg_scan_slave.value())))
        if 'tipe_reg' in sr: self.combo_reg_scan_type.setCurrentText(sr['tipe_reg'])
        self.spin_reg_scan_start.setValue(int(sr.get('reg_awal', self.spin_reg_scan_start.value())))
        self.spin_reg_scan_end.setValue(int(sr.get('reg_akhir', self.spin_reg_scan_end.value())))
        if 'encoding' in sr: self.combo_reg_scan_enc.setCurrentText(sr['encoding'])

        rd = data.get('reader', {})
        self.spin_read_slave.setValue(int(rd.get('slave_id', self.spin_read_slave.value())))
        if 'tipe_reg' in rd: self.combo_read_type.setCurrentText(rd['tipe_reg'])
        self.spin_read_addr.setValue(int(rd.get('reg_awal', self.spin_read_addr.value())))
        self.spin_read_count.setValue(int(rd.get('jumlah', self.spin_read_count.value())))
        if 'encoding' in rd: self.combo_encoding.setCurrentText(rd['encoding'])
        self.spin_pool_interval.setValue(float(rd.get('interval', self.spin_pool_interval.value())))

        wr = data.get('write', {})
        self.spin_write_slave.setValue(int(wr.get('slave_id', self.spin_write_slave.value())))
        if 'tipe_fungsi' in wr: self.combo_write_type.setCurrentText(wr['tipe_fungsi'])
        self.spin_write_addr.setValue(int(wr.get('alamat', self.spin_write_addr.value())))
        if 'encoding' in wr: self.combo_write_encoding.setCurrentText(wr['encoding'])

        lg = data.get('logger', {})
        self.spin_log_slave.setValue(int(lg.get('slave_id', self.spin_log_slave.value())))
        if 'tipe_reg' in lg: self.combo_log_type.setCurrentText(lg['tipe_reg'])
        self.spin_log_addr.setValue(int(lg.get('reg_awal', self.spin_log_addr.value())))
        self.spin_log_count.setValue(int(lg.get('jumlah', self.spin_log_count.value())))
        if 'encoding' in lg: self.combo_log_encoding.setCurrentText(lg['encoding'])
        self.spin_log_interval.setValue(float(lg.get('interval', self.spin_log_interval.value())))
        if 'csv_path' in lg: self.txt_csv_path.setText(lg['csv_path'])
        self.chk_save_csv.setChecked(bool(lg.get('simpan_csv', self.chk_save_csv.isChecked())))
        self.spin_rotasi_mb.setValue(float(lg.get('rotasi_mb', self.spin_rotasi_mb.value())))
        self.chk_rotasi_harian.setChecked(bool(lg.get('rotasi_harian', self.chk_rotasi_harian.isChecked())))

        self.daftar_tag = data.get('daftar_tag', [])
        self._render_ulang_tabel_tag()

    def simpan_preset_pekerjaan(self):
        jalur, _ = QFileDialog.getSaveFileName(self, "Export Preset Pekerjaan", "modbus_job_preset.json", "JSON Files (*.json)")
        if not jalur: return
        try:
            data = self._kumpulkan_preset_pekerjaan()
            with open(jalur, 'w') as f:
                json.dump(data, f, indent=4)
            with open(FILE_JOB_PRESET, 'w') as f:
                json.dump(data, f)
            QMessageBox.information(self, "Berhasil", "Preset pekerjaan lengkap berhasil diekspor.")
        except Exception as e:
            catat_kesalahan("Simpan preset pekerjaan", e)
            QMessageBox.warning(self, "Error", f"Gagal mengekspor preset pekerjaan: {str(e)}")

    def muat_preset_pekerjaan(self):
        jalur, _ = QFileDialog.getOpenFileName(self, "Import Preset Pekerjaan", "", "JSON Files (*.json)")
        if not jalur: return
        try:
            with open(jalur, 'r') as f:
                data = json.load(f)
            self._terapkan_preset_pekerjaan(data)
            QMessageBox.information(self, "Berhasil", "Preset pekerjaan lengkap berhasil dimuat.")
        except Exception as e:
            catat_kesalahan("Muat preset pekerjaan", e)
            QMessageBox.warning(self, "Error", f"Gagal memuat preset pekerjaan: {str(e)}")

    def manajemen_interlock_tombol(self, tab_aktif, status_reset=False):
        kondisi = status_reset
        if tab_aktif != "scan_id": self.btn_start_id_scan.setEnabled(kondisi)
        if tab_aktif != "scan_reg": self.btn_start_reg_scan.setEnabled(kondisi)
        if tab_aktif != "pool":
            self.btn_toggle_pool.setEnabled(kondisi)
        # FIX BUG: "Baca Sekali" memakai objek thread yang SAMA (self.thread_pooler)
        # dengan polling otomatis. Sebelumnya baris ini ada di dalam blok
        # "if tab_aktif != 'pool'", sehingga saat polling AKTIF (tab_aktif == 'pool')
        # tombol Baca Sekali tetap ikut aktif. Kalau diklik, thread polling yang
        # sedang berjalan akan tertimpa/terlantar (orphan) dan tombol "Hentikan
        # Polling" jadi tidak berfungsi lagi karena sudah menunjuk ke thread baru
        # yang bukan polling. Sekarang tombol ini SELALU ikut dikunci setiap kali
        # ada operasi lain (termasuk polling) yang sedang berjalan.
        self.btn_single_read.setEnabled(kondisi)
        if tab_aktif != "log": self.btn_toggle_logger.setEnabled(kondisi)
        if tab_aktif != "write": self.btn_execute_write.setEnabled(kondisi)
        if hasattr(self, 'btn_tag_baca_semua') and tab_aktif != "tag":
            self.btn_tag_baca_semua.setEnabled(kondisi)
        if hasattr(self, 'btn_tag_toggle_polling') and tab_aktif != "tag":
            self.btn_tag_toggle_polling.setEnabled(kondisi)


    # ==================================================================
    # TAB 1: DEVICE ID SCANNER
    # ==================================================================
    def buat_tab_slave_id_scanner(self):
        tab = QWidget()
        tata_letak = QHBoxLayout(tab)
        
        box_kontrol = QGroupBox("Pengaturan ID")
        box_kontrol.setMaximumWidth(320)
        grid_kiri = QGridLayout(box_kontrol)
        
        grid_kiri.addWidget(QLabel("ID Awal:"), 0, 0)
        self.spin_start_id = QSpinBox()
        self.spin_start_id.setRange(1, 247)
        self.spin_start_id.setValue(1)
        grid_kiri.addWidget(self.spin_start_id, 0, 1)

        grid_kiri.addWidget(QLabel("ID Akhir:"), 1, 0)
        self.spin_end_id = QSpinBox()
        self.spin_end_id.setRange(1, 247)
        self.spin_end_id.setValue(10)
        grid_kiri.addWidget(self.spin_end_id, 1, 1)

        grid_kiri.addWidget(QLabel("Tipe Reg Uji:"), 2, 0)
        self.combo_id_scan_reg_type = QComboBox()
        self.combo_id_scan_reg_type.addItems(["Holding", "Input", "Coil", "Discrete Input"])
        grid_kiri.addWidget(self.combo_id_scan_reg_type, 2, 1)

        grid_kiri.addWidget(QLabel("Alamat Reg Uji:"), 3, 0)
        self.spin_test_reg = QSpinBox()
        self.spin_test_reg.setRange(0, 65535)
        self.spin_test_reg.setToolTip("Alamat register yang dicoba dibaca dari tiap Device ID untuk menguji apakah ada perangkat yang merespon.")
        grid_kiri.addWidget(self.spin_test_reg, 3, 1)

        self.btn_start_id_scan = QPushButton("Mulai Scan")
        self.btn_start_id_scan.clicked.connect(self.eksekusi_scan_id)
        grid_kiri.addWidget(self.btn_start_id_scan, 4, 0, 1, 2)
        
        self.btn_stop_id_scan = QPushButton("Berhenti")
        self.btn_stop_id_scan.setEnabled(False)
        self.btn_stop_id_scan.clicked.connect(self.hentikan_scan_id_paksa)
        grid_kiri.addWidget(self.btn_stop_id_scan, 5, 0, 1, 2)
        
        btn_export_id = QPushButton("Export CSV")
        btn_export_id.clicked.connect(lambda: self._export_tabel_ke_csv(self.tabel_hasil_id, "scan_id_hasil"))
        grid_kiri.addWidget(btn_export_id, 6, 0, 1, 2)
        
        grid_kiri.setRowStretch(7, 1) 

        self.tabel_hasil_id = QTableWidget(0, 2)
        self.tabel_hasil_id.setHorizontalHeaderLabels(["Device ID", "Status Komunikasi"])
        self.tabel_hasil_id.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        panel_kanan = self._bungkus_tabel_dengan_filter(self.tabel_hasil_id, "Cari Device ID...")

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(box_kontrol)
        splitter.addWidget(panel_kanan)
        splitter.setStretchFactor(0, 0) 
        splitter.setStretchFactor(1, 1)
        tata_letak.addWidget(splitter)
        self.tabs.addTab(tab, "Pemindai Device ID")

    def eksekusi_scan_id(self):
        if not self.client_global or not client_terhubung(self.client_global):
            self._set_status("Error: Hubungkan koneksi utama terlebih dahulu!")
            return
        if self.spin_start_id.value() > self.spin_end_id.value():
            QMessageBox.warning(self, "Parameter Salah", "ID Awal harus <= ID Akhir.")
            return

        self.manajemen_interlock_tombol("scan_id")
        self.btn_stop_id_scan.setEnabled(True)
        params = {
            'id_awal': self.spin_start_id.value(),
            'id_akhir': self.spin_end_id.value(),
            'tipe_reg': self.combo_id_scan_reg_type.currentText(),
            'reg_uji': self.spin_test_reg.value()
        }
        self.tabel_hasil_id.setRowCount(0)
        self.thread_pemindai = ModbusScannerThread(self.client_global, "id", params)
        self.thread_pemindai.sinyal_progres.connect(lambda p, s: self._set_status(f"[{p}%] {s}", p))
        self.thread_pemindai.sinyal_hasil.connect(self.tampilkan_hasil_scan_id)
        self.thread_pemindai.sinyal_selesai.connect(self.selesai_scan_id_callback)
        self.thread_pemindai.sinyal_error.connect(lambda msg: self._set_status(f"{msg}"))
        self.thread_pemindai.start()

    def hentikan_scan_id_paksa(self):
        if self.thread_pemindai and self.thread_pemindai.isRunning():
            self.thread_pemindai.apakah_berjalan = False
            self.btn_stop_id_scan.setEnabled(False)

    def selesai_scan_id_callback(self):
        self.btn_stop_id_scan.setEnabled(False)
        self.manajemen_interlock_tombol(None, status_reset=True)
        self._set_status(f"Scan ID selesai. {self.tabel_hasil_id.rowCount()} device ditemukan.")

    def tampilkan_hasil_scan_id(self, hasil):
        for slave_id, status in hasil:
            baris = self.tabel_hasil_id.rowCount()
            self.tabel_hasil_id.insertRow(baris)
            item_id = QTableWidgetItem(str(slave_id))
            item_id.setTextAlignment(Qt.AlignCenter)
            item_status = QTableWidgetItem(status)
            item_status.setTextAlignment(Qt.AlignCenter)
            item_status.setForeground(QColor(WARNA_SUKSES))
            font = QFont(); font.setBold(True); item_status.setFont(font)
            self.tabel_hasil_id.setItem(baris, 0, item_id)
            self.tabel_hasil_id.setItem(baris, 1, item_status)


    # ==================================================================
    # TAB 2: REGISTER MAP SCANNER (MENAMPILKAN INT & FLOAT SECARA BERSAMAAN)
    # ==================================================================
    def buat_tab_register_scanner(self):
        tab = QWidget()
        tata_letak = QHBoxLayout(tab)
        box_kontrol = QGroupBox("Pengaturan Register")
        box_kontrol.setMaximumWidth(320)
        grid_kiri = QGridLayout(box_kontrol)

        grid_kiri.addWidget(QLabel("Target ID:"), 0, 0)
        self.spin_reg_scan_slave = QSpinBox()
        self.spin_reg_scan_slave.setValue(1)
        grid_kiri.addWidget(self.spin_reg_scan_slave, 0, 1)

        grid_kiri.addWidget(QLabel("Jenis Register:"), 1, 0)
        self.combo_reg_scan_type = QComboBox()
        self.combo_reg_scan_type.addItems(["Holding", "Input", "Coil", "Discrete Input"])
        grid_kiri.addWidget(self.combo_reg_scan_type, 1, 1)

        grid_kiri.addWidget(QLabel("Alamat Awal:"), 2, 0)
        self.spin_reg_scan_start = QSpinBox()
        self.spin_reg_scan_start.setRange(0, 65535)
        grid_kiri.addWidget(self.spin_reg_scan_start, 2, 1)

        grid_kiri.addWidget(QLabel("Alamat Akhir:"), 3, 0)
        self.spin_reg_scan_end = QSpinBox()
        self.spin_reg_scan_end.setRange(0, 65535)
        self.spin_reg_scan_end.setValue(100)
        grid_kiri.addWidget(self.spin_reg_scan_end, 3, 1)

        grid_kiri.addWidget(QLabel("Format Nilai:"), 4, 0)
        self.combo_reg_scan_enc = QComboBox()
        self.combo_reg_scan_enc.addItems(DAFTAR_ENCODING)
        self.combo_reg_scan_enc.setToolTip("Format untuk mendekode 2/4 register bertetangga (float, int32, atau double 64-bit).")
        grid_kiri.addWidget(self.combo_reg_scan_enc, 4, 1)

        self.btn_start_reg_scan = QPushButton("Mulai Pemindaian")
        self.btn_start_reg_scan.clicked.connect(self.eksekusi_scan_register)
        grid_kiri.addWidget(self.btn_start_reg_scan, 5, 0, 1, 2)

        self.btn_stop_reg_scan = QPushButton("Berhenti")
        self.btn_stop_reg_scan.setEnabled(False)
        self.btn_stop_reg_scan.clicked.connect(self.hentikan_scan_reg_paksa)
        grid_kiri.addWidget(self.btn_stop_reg_scan, 6, 0, 1, 2)
        
        grid_kiri.setRowStretch(7, 1)

        # FIX: Tabel menampung Alamat, INT, dan nilai gabungan (float/int32/double) sekaligus
        self.tabel_hasil_register = QTableWidget(0, 3)
        self.tabel_hasil_register.setHorizontalHeaderLabels(["Alamat Register", "Nilai INT (16-bit)", "Nilai Gabungan (32/64-bit)"])
        self.tabel_hasil_register.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        panel_kanan_reg = self._bungkus_tabel_dengan_filter(self.tabel_hasil_register, "Cari alamat/nilai...")

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(box_kontrol)
        splitter.addWidget(panel_kanan_reg)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        tata_letak.addWidget(splitter)
        self.tabs.addTab(tab, "Pemindai Peta Register")

    def eksekusi_scan_register(self):
        if not self.client_global or not client_terhubung(self.client_global):
            self._set_status("Error: Koneksi utama belum aktif!")
            return
        if self.spin_reg_scan_start.value() > self.spin_reg_scan_end.value():
            QMessageBox.warning(self, "Parameter Salah", "Alamat Awal tidak boleh > Akhir.")
            return

        self.manajemen_interlock_tombol("scan_reg")
        self.btn_stop_reg_scan.setEnabled(True)
        params = {
            'slave_id': self.spin_reg_scan_slave.value(),
            'tipe_reg': self.combo_reg_scan_type.currentText(),
            'reg_awal': self.spin_reg_scan_start.value(),
            'reg_akhir': self.spin_reg_scan_end.value(),
            'encoding': self.combo_reg_scan_enc.currentText()
        }
        self.tabel_hasil_register.setRowCount(0)

        self.thread_pemindai = ModbusScannerThread(self.client_global, "register", params)
        self.thread_pemindai.sinyal_progres.connect(lambda p, s: self._set_status(f"[{p}%] {s}", p))
        self.thread_pemindai.sinyal_hasil.connect(self.tampilkan_hasil_scan_register)
        self.thread_pemindai.sinyal_selesai.connect(self.selesai_scan_reg_callback)
        self.thread_pemindai.sinyal_error.connect(lambda msg: self._set_status(f"{msg}"))
        self.thread_pemindai.start()

    def hentikan_scan_reg_paksa(self):
        if self.thread_pemindai and self.thread_pemindai.isRunning():
            self.thread_pemindai.apakah_berjalan = False
            self.btn_stop_reg_scan.setEnabled(False)

    def selesai_scan_reg_callback(self):
        self.btn_stop_reg_scan.setEnabled(False)
        self.manajemen_interlock_tombol(None, status_reset=True)
        self._set_status(f"Scan register selesai. {self.tabel_hasil_register.rowCount()} ditemukan.")

    def tampilkan_hasil_scan_register(self, hasil):
        for reg, val_int, val_float in hasil:
            baris = self.tabel_hasil_register.rowCount()
            self.tabel_hasil_register.insertRow(baris)
            self.tabel_hasil_register.setItem(baris, 0, QTableWidgetItem(str(reg)))
            self.tabel_hasil_register.setItem(baris, 1, QTableWidgetItem(val_int))
            self.tabel_hasil_register.setItem(baris, 2, QTableWidgetItem(val_float))


    # ==================================================================
    # TAB 3: DATA READER (POOLER) & INT FLOAT DECODE BERSAMAAN
    # ==================================================================
    def buat_tab_reader_pooler(self):
        tab = QWidget()
        tata_letak = QHBoxLayout(tab)
        box_konfig = QGroupBox("Pengaturan Pembacaan")
        box_konfig.setMaximumWidth(320)
        grid_kiri = QGridLayout(box_konfig)

        grid_kiri.addWidget(QLabel("Target ID:"), 0, 0)
        self.spin_read_slave = QSpinBox()
        self.spin_read_slave.setValue(1)
        grid_kiri.addWidget(self.spin_read_slave, 0, 1)

        grid_kiri.addWidget(QLabel("Jenis Reg:"), 1, 0)
        self.combo_read_type = QComboBox()
        self.combo_read_type.addItems(["Holding", "Input", "Coil", "Discrete Input"])
        grid_kiri.addWidget(self.combo_read_type, 1, 1)

        grid_kiri.addWidget(QLabel("Alamat Awal:"), 2, 0)
        self.spin_read_addr = QSpinBox()
        self.spin_read_addr.setRange(0, 65535)
        grid_kiri.addWidget(self.spin_read_addr, 2, 1)

        grid_kiri.addWidget(QLabel("Jumlah Baris:"), 3, 0)
        self.spin_read_count = QSpinBox()
        self.spin_read_count.setRange(1, 125)
        self.spin_read_count.setValue(4)
        grid_kiri.addWidget(self.spin_read_count, 3, 1)

        grid_kiri.addWidget(QLabel("Format Nilai:"), 4, 0)
        self.combo_encoding = QComboBox()
        self.combo_encoding.addItems(DAFTAR_ENCODING)
        self.combo_encoding.setToolTip("Format untuk mendekode register bertetangga (float, int32, atau double 64-bit).")
        grid_kiri.addWidget(self.combo_encoding, 4, 1)

        grid_kiri.addWidget(QLabel("Interval (s):"), 5, 0)
        self.spin_pool_interval = QDoubleSpinBox()
        self.spin_pool_interval.setRange(0.1, 10.0)
        self.spin_pool_interval.setValue(1.0)
        grid_kiri.addWidget(self.spin_pool_interval, 5, 1)

        self.btn_single_read = QPushButton("Baca Sekali (Tunggal)")
        self.btn_single_read.clicked.connect(lambda: self.eksekusi_baca_reader(tunggal=True))
        grid_kiri.addWidget(self.btn_single_read, 6, 0, 1, 2)

        self.btn_toggle_pool = QPushButton("▶ Mulai Polling Otomatis")
        self.btn_toggle_pool.clicked.connect(lambda: self.eksekusi_baca_reader(tunggal=False))
        grid_kiri.addWidget(self.btn_toggle_pool, 7, 0, 1, 2)
        
        grid_kiri.setRowStretch(8, 1)

        # FIX: Tabel Reader Live yang menampilkan gabungan int & float secara bersamaan
        self.tabel_reader_output = QTableWidget(0, 4)
        self.tabel_reader_output.setHorizontalHeaderLabels(["Alamat", "Nilai INT", "Nilai Gabungan", "Keterangan"])
        self.tabel_reader_output.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(box_konfig)
        splitter.addWidget(self.tabel_reader_output)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        tata_letak.addWidget(splitter)
        self.tabs.addTab(tab, "Pembaca Modbus Live")

    def eksekusi_baca_reader(self, tunggal=False):
        if not tunggal and self.thread_pooler and self.thread_pooler.isRunning():
            self.thread_pooler.apakah_berjalan = False
            self.btn_toggle_pool.setText("▶ Mulai Polling Otomatis")
            self.manajemen_interlock_tombol(None, status_reset=True)
            self._set_status("Polling dihentikan.")
            return

        if not self.client_global or not client_terhubung(self.client_global):
            self._set_status("Error: Koneksi utama belum aktif.")
            return

        # FIX BUG: penjaga tambahan (selain penguncian tombol di atas) agar
        # "Baca Sekali" tidak pernah menimpa thread_pooler yang masih berjalan
        # (baik dari polling maupun dari klik ganda pada baca sekali).
        if tunggal and self.thread_pooler and self.thread_pooler.isRunning():
            self._set_status("Masih ada pembacaan/polling yang berjalan, tunggu selesai dahulu.")
            return

        target_device_id = self.spin_read_slave.value()
        tipe_reg_saat_ini = self.combo_read_type.currentText()
        params = {
            'slave_id': target_device_id,
            'tipe_reg': tipe_reg_saat_ini,
            'reg_awal': self.spin_read_addr.value(),
            'jumlah': self.spin_read_count.value(),
            'encoding': self.combo_encoding.currentText(),
            'interval': self.spin_pool_interval.value()
        }

        if not tunggal:
            self.manajemen_interlock_tombol("pool")
            self.btn_toggle_pool.setText("■ Hentikan Polling")
            self._set_status("Polling berkala aktif...")
        else:
            self._set_status("Melakukan pembacaan tunggal...")

        self.thread_pooler = ModbusPoolerLoggerThread(
            self.client_global, params, "reader", single_shot=tunggal,
            auto_reconnect=self.chk_auto_reconnect.isChecked()
        )
        self.thread_pooler.sinyal_data.connect(lambda la, nm, enc, _: self.perbarui_tabel_reader(la, nm, enc, tipe_reg_saat_ini, target_device_id))
        self.thread_pooler.sinyal_kesalahan.connect(lambda msg, _: self._set_status(f"Pooler: {msg}"))
        self.thread_pooler.sinyal_info.connect(self.proses_info_thread)
        self.thread_pooler.start()

    def perbarui_tabel_reader(self, list_alamat, nilai_mentah, encoding, tipe_reg, device_id=0):
        try: self.tabel_reader_output.itemChanged.disconnect(self.tangkap_perubahan_keterangan_user)
        except TypeError: pass

        self.tabel_reader_output.setRowCount(0)

        # FIX: pairing register sekarang mengikuti kebutuhan word encoding
        # yang dipilih (1/2/4 word) via dapatkan_jumlah_word(), bukan
        # hardcode 2 (idx % 2 == 0). Ini memperbaiki tampilan saat tipe
        # register bukan Holding/Input (Coil/Discrete) dan mendukung
        # tipe baru 32-bit INT & 64-bit DOUBLE.
        jumlah_word = dapatkan_jumlah_word(encoding)
        for idx, addr in enumerate(list_alamat):
            baris = self.tabel_reader_output.rowCount()
            self.tabel_reader_output.insertRow(baris)
            
            item_addr = QTableWidgetItem(f"Reg {addr}")
            item_addr.setFlags(item_addr.flags() & ~Qt.ItemIsEditable)
            self.tabel_reader_output.setItem(baris, 0, item_addr)

            if tipe_reg in ['Holding', 'Input']:
                if encoding == 'Signed 16-bit INT':
                    val_int = str(struct.unpack('h', struct.pack('H', int(nilai_mentah[idx])))[0])
                else:
                    val_int = str(nilai_mentah[idx])

                val_float = "-"
                if jumlah_word > 1 and idx % jumlah_word == 0 and (idx + jumlah_word) <= len(nilai_mentah):
                    potongan_reg = [int(nilai_mentah[j]) for j in range(idx, idx + jumlah_word)]
                    val_float = dekode_register_multi(potongan_reg, encoding)
            else:
                val_int = str(nilai_mentah[idx])
                val_float = "-"

            item_val_int = QTableWidgetItem(val_int)
            item_val_int.setFlags(item_val_int.flags() & ~Qt.ItemIsEditable)
            item_val_float = QTableWidgetItem(val_float)
            item_val_float.setFlags(item_val_float.flags() & ~Qt.ItemIsEditable)
            
            kunci_cache_int = f"{device_id}_{tipe_reg}_{addr}_int"
            if kunci_cache_int in self.nilai_sebelumnya and self.nilai_sebelumnya[kunci_cache_int] != val_int:
                item_val_int.setBackground(QColor(WARNA_HIGHLIGHT))
            self.nilai_sebelumnya[kunci_cache_int] = val_int

            kunci_cache_float = f"{device_id}_{tipe_reg}_{addr}_flt"
            if kunci_cache_float in self.nilai_sebelumnya and self.nilai_sebelumnya[kunci_cache_float] != val_float:
                item_val_float.setBackground(QColor(WARNA_HIGHLIGHT))
            self.nilai_sebelumnya[kunci_cache_float] = val_float

            self.tabel_reader_output.setItem(baris, 1, item_val_int)
            self.tabel_reader_output.setItem(baris, 2, item_val_float)

            ket = self.memori_keterangan_user.get(f"{device_id}_{tipe_reg}_{addr}", "")
            self.tabel_reader_output.setItem(baris, 3, QTableWidgetItem(ket))

        self.tabel_reader_output.itemChanged.connect(self.tangkap_perubahan_keterangan_user)

    def tangkap_perubahan_keterangan_user(self, item):
        # FIX: Pindah penangkapan keterangan ke indeks kolom ke-3 (karena 1 dan 2 dihuni Int dan Float)
        if item.column() == 3: 
            baris = item.row()
            addr_str = self.tabel_reader_output.item(baris, 0).text().replace("Reg ", "")
            dev_id = self.spin_read_slave.value()
            t_reg = self.combo_read_type.currentText()
            kunci = f"{dev_id}_{t_reg}_{addr_str}"
            self.memori_keterangan_user[kunci] = item.text()


    # ==================================================================
    # TAB 4: WRITE PAYLOAD
    # ==================================================================
    def buat_tab_write_payload(self):
        tab = QWidget()
        tata_letak = QHBoxLayout(tab)
        box_nulis = QGroupBox("Kontrol Transmisi")
        box_nulis.setMaximumWidth(320)
        grid_kiri = QGridLayout(box_nulis)

        grid_kiri.addWidget(QLabel("Target ID:"), 0, 0)
        self.spin_write_slave = QSpinBox()
        self.spin_write_slave.setValue(1)
        grid_kiri.addWidget(self.spin_write_slave, 0, 1)

        grid_kiri.addWidget(QLabel("Fungsi Tulis:"), 1, 0)
        self.combo_write_type = QComboBox()
        self.combo_write_type.addItems(["Write Single Coil (FC 05)", "Write Single Register (FC 06)", 
                                        "Write Multiple Coils (FC 15)", "Write Multiple Registers (FC 16)",
                                        "Mask Write Register (FC 22)"])
        grid_kiri.addWidget(self.combo_write_type, 1, 1)

        grid_kiri.addWidget(QLabel("Alamat Tujuan:"), 2, 0)
        self.spin_write_addr = QSpinBox()
        self.spin_write_addr.setRange(0, 65535)
        grid_kiri.addWidget(self.spin_write_addr, 2, 1)

        grid_kiri.addWidget(QLabel("Format Data:"), 3, 0)
        self.combo_write_encoding = QComboBox()
        self.combo_write_encoding.addItems(DAFTAR_ENCODING)
        self.combo_write_encoding.setToolTip("Diabaikan untuk Coil dan Mask Write Register.")
        grid_kiri.addWidget(self.combo_write_encoding, 3, 1)

        grid_kiri.addWidget(QLabel("Nilai Input:"), 4, 0)
        self.txt_write_payload = QLineEdit("12.34")
        self.txt_write_payload.setToolTip(
            "Coil: 1/0/true/false/on/off.\n"
            "Register tunggal: satu angka.\n"
            "Multiple Registers/Coils: pisahkan dengan koma, mis. 1,2,3.\n"
            "Mask Write Register: dua angka dipisah koma 'AND_mask,OR_mask' (boleh desimal atau 0xHEX)."
        )
        grid_kiri.addWidget(self.txt_write_payload, 4, 1)

        self.chk_verify_write = QCheckBox("Baca ulang untuk verifikasi setelah menulis")
        self.chk_verify_write.setChecked(True)
        self.chk_verify_write.setToolTip("Setelah menulis, baca kembali alamat yang sama untuk memastikan nilai benar-benar tersimpan di perangkat.")
        grid_kiri.addWidget(self.chk_verify_write, 5, 0, 1, 2)

        self.chk_skip_confirm_write = QCheckBox("Lewati dialog konfirmasi sebelum menulis")
        self.chk_skip_confirm_write.setToolTip("Perintah tulis akan langsung dieksekusi ke perangkat tanpa dialog konfirmasi. Gunakan dengan hati-hati.")
        grid_kiri.addWidget(self.chk_skip_confirm_write, 6, 0, 1, 2)

        self.btn_execute_write = QPushButton("Transmisikan Data")
        self.btn_execute_write.clicked.connect(self.eksekusi_penulisan_modbus)
        grid_kiri.addWidget(self.btn_execute_write, 7, 0, 1, 2)
        
        grid_kiri.setRowStretch(8, 1)

        box_log_nulis = QGroupBox("Terminal Validasi")
        tata_letak_log = QVBoxLayout(box_log_nulis)
        self.txt_write_log = QTextEdit()
        self.txt_write_log.setReadOnly(True)
        tata_letak_log.addWidget(self.txt_write_log)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(box_nulis)
        splitter.addWidget(box_log_nulis)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        tata_letak.addWidget(splitter)
        self.tabs.addTab(tab, "Write Register / Coil")

    def eksekusi_penulisan_modbus(self):
        if not self.client_global or not client_terhubung(self.client_global):
            QMessageBox.critical(self, "Error", "Master Modbus belum terhubung!")
            return

        tipe_fungsi = self.combo_write_type.currentText()
        alamat_tujuan = self.spin_write_addr.value()
        target_device_id = self.spin_write_slave.value()
        input_user = self.txt_write_payload.text()
        waktu_skrg = datetime.now().strftime("%H:%M:%S")
        register_final = []
        val_bool = False
        and_mask = or_mask = None

        if "Coil" in tipe_fungsi and "Multiple" not in tipe_fungsi:
            val_bool = input_user.lower() in ['1', 'true', 'on']
        elif "Mask Write" in tipe_fungsi:
            try:
                bagian = [b.strip() for b in input_user.split(",")]
                if len(bagian) != 2:
                    raise ValueError("Perlu 2 nilai dipisah koma: AND_mask,OR_mask")
                and_mask = int(bagian[0], 0)
                or_mask = int(bagian[1], 0)
            except ValueError as e:
                self.txt_write_log.append(f"[{waktu_skrg}] <font color='red'>Error Parsing Mask: {str(e)}</font>")
                return
        elif "Multiple Coils" not in tipe_fungsi:
            try:
                if "Multiple" in tipe_fungsi and "," in input_user:
                    elemen = input_user.split(",")
                    for e in elemen:
                        register_final.extend(enkode_nilai_ke_register(e.strip(), self.combo_write_encoding.currentText()))
                else:
                    register_final = enkode_nilai_ke_register(input_user, self.combo_write_encoding.currentText())
            except ValueError as e:
                self.txt_write_log.append(f"[{waktu_skrg}] <font color='red'>Error Parsing Data: {str(e)}</font>")
                return

        # Fitur keamanan: minta konfirmasi sebelum benar-benar menulis ke
        # perangkat, karena write yang salah alamat/nilai bisa berdampak ke
        # proses/perangkat industrial yang sedang berjalan.
        if not self.chk_skip_confirm_write.isChecked():
            jawaban = QMessageBox.question(
                self, "Konfirmasi Penulisan",
                f"Anda akan menulis ke:\n\n"
                f"  Fungsi : {tipe_fungsi}\n"
                f"  Slave ID : {target_device_id}\n"
                f"  Alamat : {alamat_tujuan}\n"
                f"  Nilai  : {input_user}\n\n"
                f"Lanjutkan menulis ke perangkat?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if jawaban != QMessageBox.Yes:
                self.txt_write_log.append(f"[{waktu_skrg}] Penulisan dibatalkan oleh pengguna.")
                return

        self.manajemen_interlock_tombol("write")
        kunci_komunikasi.lock()
        try:
            kwargs = {'address': alamat_tujuan}
            kwargs.update(get_modbus_device_kwargs(target_device_id))

            if "Single Coil" in tipe_fungsi:
                kwargs['value'] = val_bool
                res = self.client_global.write_coil(**kwargs)
            elif "Single Register" in tipe_fungsi:
                kwargs['value'] = register_final[0]
                res = self.client_global.write_register(**kwargs)
            elif "Multiple Coils" in tipe_fungsi:
                elemen = [e for e in input_user.split(",") if e.strip()]
                kwargs['values'] = [x.lower() in ['1', 'true', 'on'] for x in elemen]
                res = self.client_global.write_coils(**kwargs)
            elif "Multiple Registers" in tipe_fungsi:
                kwargs['values'] = register_final
                res = self.client_global.write_registers(**kwargs)
            elif "Mask Write" in tipe_fungsi:
                kwargs['and_mask'] = and_mask
                kwargs['or_mask'] = or_mask
                if hasattr(self.client_global, 'mask_write_register'):
                    res = self.client_global.mask_write_register(**kwargs)
                else:
                    raise AttributeError("Versi pymodbus ini tidak mendukung mask_write_register().")
            else:
                res = None

            if res and res.isError():
                statistik_global.catat_gagal()
                self.txt_write_log.append(f"[{waktu_skrg}] <font color='red'>Gagal! {terjemahkan_respon_modbus(res)}</font>")
            elif res:
                statistik_global.catat_sukses()
                # Tangkap nilai data yang dieksekusi berdasarkan jenis perintah
                if "Single Coil" in tipe_fungsi:
                    data_kirim = str(val_bool)
                elif "Single Register" in tipe_fungsi:
                    data_kirim = str(register_final[0])
                elif "Multiple Coils" in tipe_fungsi:
                    data_kirim = str(kwargs.get('values', []))
                elif "Mask Write" in tipe_fungsi:
                    data_kirim = f"AND=0x{and_mask:04X}, OR=0x{or_mask:04X}"
                else:
                    # Untuk Multiple Registers
                    data_kirim = str(register_final)
                
                # Tampilkan data_kirim pada log interface
                self.txt_write_log.append(f"[{waktu_skrg}] <font color='green'>Transmisi Sukses → Addr: {alamat_tujuan} | ID: {target_device_id} | Data: {data_kirim}</font>")

                # Fitur: baca ulang untuk verifikasi nilai benar-benar tersimpan
                if self.chk_verify_write.isChecked() and "Mask Write" not in tipe_fungsi:
                    self._verifikasi_baca_ulang(tipe_fungsi, alamat_tujuan, target_device_id, register_final, val_bool, input_user)
        except Exception as e:
            catat_kesalahan("Eksekusi tulis Modbus", e)
            self.txt_write_log.append(f"[{waktu_skrg}] <font color='red'>Kesalahan Hardware: {str(e)}</font>")
        finally:
            kunci_komunikasi.unlock()
            self.manajemen_interlock_tombol(None, status_reset=True)

    def _verifikasi_baca_ulang(self, tipe_fungsi, alamat, device_id, register_final, val_bool, input_user):
        """Baca kembali alamat yang baru saja ditulis untuk memastikan
        nilainya benar-benar tersimpan di perangkat, bukan hanya berasumsi
        sukses karena tidak ada exception."""
        waktu_skrg = datetime.now().strftime("%H:%M:%S")
        try:
            if "Coil" in tipe_fungsi:
                jumlah = len([e for e in input_user.split(",") if e.strip()]) if "Multiple" in tipe_fungsi else 1
                res = baca_register_modbus(self.client_global, "Coil", alamat, jumlah, device_id)
                if res and not res.isError():
                    nilai_terbaca = res.bits[:jumlah]
                    self.txt_write_log.append(f"[{waktu_skrg}] Verifikasi baca ulang Coil: {nilai_terbaca}")
                else:
                    self.txt_write_log.append(f"[{waktu_skrg}] <font color='orange'>Verifikasi gagal: {terjemahkan_respon_modbus(res)}</font>")
            else:
                jumlah = max(1, len(register_final))
                res = baca_register_modbus(self.client_global, "Holding", alamat, jumlah, device_id)
                if res and not res.isError():
                    if list(res.registers[:jumlah]) == register_final:
                        self.txt_write_log.append(f"[{waktu_skrg}] <font color='green'>Verifikasi OK: nilai di perangkat cocok ({list(res.registers[:jumlah])}).</font>")
                    else:
                        self.txt_write_log.append(f"[{waktu_skrg}] <font color='orange'>Verifikasi TIDAK cocok! Diharapkan {register_final}, terbaca {list(res.registers[:jumlah])}.</font>")
                else:
                    self.txt_write_log.append(f"[{waktu_skrg}] <font color='orange'>Verifikasi gagal: {terjemahkan_respon_modbus(res)}</font>")
        except Exception as e:
            catat_kesalahan("Verifikasi baca ulang write", e)
            self.txt_write_log.append(f"[{waktu_skrg}] <font color='orange'>Verifikasi gagal: {str(e)}</font>")


    # ==================================================================
    # TAB 5: AUTOMATED LOGGER KE CSV
    # ==================================================================
    def buat_tab_logger(self):
        tab = QWidget()
        tata_letak = QHBoxLayout(tab) 

        box_kontrol = QGroupBox("Pengaturan Data Logger")
        box_kontrol.setMaximumWidth(320)
        grid_kiri = QGridLayout(box_kontrol)
        
        grid_kiri.addWidget(QLabel("Target ID:"), 0, 0)
        self.spin_log_slave = QSpinBox()
        self.spin_log_slave.setValue(1)
        grid_kiri.addWidget(self.spin_log_slave, 0, 1)

        grid_kiri.addWidget(QLabel("Jenis Reg:"), 1, 0)
        self.combo_log_type = QComboBox()
        self.combo_log_type.addItems(["Holding", "Input", "Coil", "Discrete Input"])
        grid_kiri.addWidget(self.combo_log_type, 1, 1)

        grid_kiri.addWidget(QLabel("Alamat Awal:"), 2, 0)
        self.spin_log_addr = QSpinBox()
        self.spin_log_addr.setRange(0, 65535)
        grid_kiri.addWidget(self.spin_log_addr, 2, 1)

        grid_kiri.addWidget(QLabel("Jumlah:"), 3, 0)
        self.spin_log_count = QSpinBox()
        self.spin_log_count.setRange(1, 125)
        grid_kiri.addWidget(self.spin_log_count, 3, 1)

        grid_kiri.addWidget(QLabel("Format:"), 4, 0)
        self.combo_log_encoding = QComboBox()
        self.combo_log_encoding.addItems(DAFTAR_ENCODING)
        grid_kiri.addWidget(self.combo_log_encoding, 4, 1)

        grid_kiri.addWidget(QLabel("Interval (s):"), 5, 0)
        self.spin_log_interval = QDoubleSpinBox()
        self.spin_log_interval.setRange(0.1, 3600.0)
        self.spin_log_interval.setValue(2.0)
        grid_kiri.addWidget(self.spin_log_interval, 5, 1)

        grid_kiri.addWidget(QLabel("File CSV:"), 6, 0)
        layout_csv = QHBoxLayout()
        self.txt_csv_path = QLineEdit("modbus_log_terbaru.csv")
        layout_csv.addWidget(self.txt_csv_path)
        btn_browse = QPushButton("...")
        btn_browse.setMaximumWidth(40)
        btn_browse.clicked.connect(self._pilih_file_csv)
        layout_csv.addWidget(btn_browse)
        grid_kiri.addLayout(layout_csv, 6, 1)

        self.chk_save_csv = QCheckBox("Simpan CSV")
        self.chk_save_csv.setChecked(True)
        grid_kiri.addWidget(self.chk_save_csv, 7, 0, 1, 2)

        grp_rotasi = QGroupBox("Rotasi File CSV")
        grid_rotasi = QGridLayout(grp_rotasi)
        grid_rotasi.addWidget(QLabel("Maks Ukuran (MB):"), 0, 0)
        self.spin_rotasi_mb = QDoubleSpinBox()
        self.spin_rotasi_mb.setRange(0.0, 10000.0)
        self.spin_rotasi_mb.setValue(0.0)
        self.spin_rotasi_mb.setToolTip("0 = nonaktif. Jika terisi, file CSV otomatis diganti dengan file baru saat ukurannya melebihi batas ini, supaya file logger tidak tumbuh tak terbatas.")
        grid_rotasi.addWidget(self.spin_rotasi_mb, 0, 1)
        self.chk_rotasi_harian = QCheckBox("Rotasi harian (file baru tiap ganti tanggal)")
        grid_rotasi.addWidget(self.chk_rotasi_harian, 1, 0, 1, 2)
        grid_kiri.addWidget(grp_rotasi, 8, 0, 1, 2)

        self.btn_toggle_logger = QPushButton("▶ Mulai Perekaman Data")
        self.btn_toggle_logger.clicked.connect(self.toggle_logger)
        grid_kiri.addWidget(self.btn_toggle_logger, 9, 0, 1, 2)
        
        grid_kiri.setRowStretch(10, 1)

        box_monitor = QGroupBox("Monitor Live Data")
        tata_letak_monitor = QVBoxLayout(box_monitor)
        self.txt_logger_monitor = QTextEdit()
        self.txt_logger_monitor.setReadOnly(True)
        tata_letak_monitor.addWidget(self.txt_logger_monitor)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(box_kontrol)
        splitter.addWidget(box_monitor)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        tata_letak.addWidget(splitter)
        self.tabs.addTab(tab, "Data Logger CSV")

    def _pilih_file_csv(self):
        jalur, _ = QFileDialog.getSaveFileName(self, "Simpan Log Sebagai", "modbus_log.csv", "CSV Files (*.csv)")
        if jalur: self.txt_csv_path.setText(jalur)

    def _buat_header_csv_logger(self, reg_awal, jumlah, tipe_reg, encoding):
        """Bangun header CSV dengan pemasangan register yang identik dengan
        logika decode di proses_data_logger_thread, supaya jumlah kolom
        header selalu sinkron dengan jumlah kolom data yang benar-benar ditulis."""
        header = []
        langkah = dapatkan_jumlah_word(encoding) if tipe_reg in ('Holding', 'Input') else 1
        i = 0
        while i < jumlah:
            if langkah > 1 and i + langkah - 1 < jumlah:
                header.append(f"Reg_{reg_awal + i}-{reg_awal + i + langkah - 1}")
                i += langkah
            else:
                header.append(f"Reg_{reg_awal + i}")
                i += 1
        return header

    def _cek_rotasi_csv(self):
        """Rotasi file CSV jika ukurannya melebihi batas atau tanggal sudah
        berganti sejak file dibuat, supaya file logger tidak tumbuh tak
        terbatas saat logging dijalankan berhari-hari."""
        jalur = self.txt_csv_path.text()
        perlu_rotasi = False

        if self.chk_rotasi_harian.isChecked():
            tanggal_hari_ini = datetime.now().strftime("%Y%m%d")
            if getattr(self, '_tanggal_csv_aktif', None) != tanggal_hari_ini:
                if self._tanggal_csv_aktif is not None:
                    perlu_rotasi = True
                self._tanggal_csv_aktif = tanggal_hari_ini

        batas_mb = self.spin_rotasi_mb.value()
        if batas_mb > 0 and os.path.exists(jalur):
            ukuran_mb = os.path.getsize(jalur) / (1024 * 1024)
            if ukuran_mb >= batas_mb:
                perlu_rotasi = True

        if perlu_rotasi:
            base, ext = os.path.splitext(jalur)
            jalur_baru = f"{base}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext or '.csv'}"
            self.txt_csv_path.setText(jalur_baru)
            self._tulis_header_csv_logger(jalur_baru)
            self.txt_logger_monitor.append(f"<i>Rotasi file CSV → {jalur_baru}</i>")

    def _tulis_header_csv_logger(self, jalur_csv):
        header = ["Timestamp"] + self._buat_header_csv_logger(
            self.spin_log_addr.value(),
            self.spin_log_count.value(),
            self.combo_log_type.currentText(),
            self.combo_log_encoding.currentText()
        )
        with open(jalur_csv, 'w', newline='') as f:
            csv.writer(f).writerow(header)

    def toggle_logger(self):
        if self.thread_logger and self.thread_logger.isRunning():
            self.thread_logger.apakah_berjalan = False
            self.btn_toggle_logger.setText("▶ Mulai Perekaman Data")
            self.manajemen_interlock_tombol(None, status_reset=True)
            self._set_status("Logging dihentikan.")
            return

        if not self.client_global or not client_terhubung(self.client_global):
            self._set_status("Error: Koneksi utama belum aktif!")
            return

        self.manajemen_interlock_tombol("log")
        params = {
            'slave_id': self.spin_log_slave.value(),
            'tipe_reg': self.combo_log_type.currentText(),
            'reg_awal': self.spin_log_addr.value(),
            'jumlah': self.spin_log_count.value(),
            'encoding': self.combo_log_encoding.currentText(),
            'interval': self.spin_log_interval.value()
        }

        if self.chk_save_csv.isChecked():
            jalur_csv = self.txt_csv_path.text()
            try:
                file_baru = not os.path.exists(jalur_csv) or os.path.getsize(jalur_csv) == 0
                if file_baru:
                    # FIX BUG: header sebelumnya selalu membuat 1 kolom per
                    # register (mis. 4 register -> 4 kolom "Reg_x"), padahal
                    # kalau encoding-nya 32-bit FLOAT, proses_data_logger_thread
                    # menggabungkan tiap 2 register jadi 1 nilai float, sehingga
                    # baris data yang tersimpan hanya punya separuh kolom dari
                    # header -> data di CSV jadi bergeser/tidak sinkron dengan
                    # header. Header sekarang dibangun dengan logika pemasangan
                    # register yang SAMA PERSIS dengan proses_data_logger_thread.
                    self._tulis_header_csv_logger(jalur_csv)
                self._tanggal_csv_aktif = datetime.now().strftime("%Y%m%d")
            except Exception as e:
                catat_kesalahan("Tulis header CSV logger", e)
                self.txt_logger_monitor.append(f"Gagal tulis header CSV: {str(e)}")
                self.manajemen_interlock_tombol(None, status_reset=True)
                return

        self.txt_logger_monitor.clear()
        self.thread_logger = ModbusPoolerLoggerThread(
            self.client_global, params, "logger",
            auto_reconnect=self.chk_auto_reconnect.isChecked()
        )
        self.thread_logger.sinyal_data.connect(self.proses_data_logger_thread)
        self.thread_logger.sinyal_kesalahan.connect(self.proses_kesalahan_thread)
        self.thread_logger.sinyal_info.connect(self.proses_info_thread)
        self.thread_logger.start()
        
        self.btn_toggle_logger.setText("■ Hentikan Perekaman")
        self._set_status("Data logger berjalan...")

    def proses_data_logger_thread(self, list_alamat, nilai_mentah, encoding, target_tab):
        if target_tab != "logger": return
        stempel = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        hasil_decoded_list = []
        # FIX BUG: sebelumnya hanya mengecek "32-bit" in encoding tanpa memeriksa
        # tipe register. Kalau tipe register yang dipilih Coil/Discrete Input
        # tapi dropdown encoding masih menunjuk salah satu format FLOAT (bekas
        # pilihan sebelumnya), nilai bit (0/1) akan ikut "didekode" seolah-olah
        # pasangan register 16-bit -> menghasilkan angka float yang tidak berarti.
        # Sekarang decode hanya dilakukan jika tipe register-nya Holding/Input,
        # dan jumlah word mengikuti dapatkan_jumlah_word() (mendukung 32-bit
        # FLOAT/INT maupun 64-bit DOUBLE), bukan hardcode 2.
        langkah = dapatkan_jumlah_word(encoding) if self.combo_log_type.currentText() in ('Holding', 'Input') else 1

        i = 0
        while i < len(nilai_mentah):
            if langkah > 1 and i + langkah <= len(nilai_mentah):
                potongan = [int(x) for x in nilai_mentah[i:i + langkah]]
                val_str = dekode_register_multi(potongan, encoding)
                hasil_decoded_list.append(val_str)
                i += langkah
            else:
                if encoding == 'Signed 16-bit INT':
                    val_str = str(struct.unpack('h', struct.pack('H', int(nilai_mentah[i])))[0])
                else:
                    val_str = str(nilai_mentah[i])
                hasil_decoded_list.append(val_str)
                i += 1

        str_decoded = ", ".join(hasil_decoded_list)
        self.txt_logger_monitor.append(f"[{stempel}] Raw: {nilai_mentah} → Decoded: {str_decoded}")

        if self.chk_save_csv.isChecked():
            try:
                self._cek_rotasi_csv()
                with open(self.txt_csv_path.text(), mode='a', newline='') as f:
                    csv.writer(f).writerow([stempel] + hasil_decoded_list)
            except Exception as e:
                catat_kesalahan("Tulis baris CSV logger", e)
                self.txt_logger_monitor.append(f"<font color='red'>Gagal simpan CSV: {str(e)}</font>")

    def proses_kesalahan_thread(self, pesan_kesalahan, target_tab):
        if target_tab == "logger":
            self.txt_logger_monitor.append(f"<font color='red'>[Kegagalan] {pesan_kesalahan}</font>")
        elif target_tab == "tag":
            self.txt_tag_monitor.append(f"<font color='red'>[Kegagalan] {pesan_kesalahan}</font>")

    def proses_info_thread(self, pesan_info, target_tab):
        if target_tab == "logger":
            self.txt_logger_monitor.append(f"<font color='#3498db'>[Info] {pesan_info}</font>")
        elif target_tab == "reader":
            self._set_status(pesan_info)
        elif target_tab == "tag":
            self.txt_tag_monitor.append(f"<font color='#3498db'>[Info] {pesan_info}</font>")

    def _tampilkan_tentang(self):
        QMessageBox.about(
            self, "Tentang Aplikasi",
            "<b>All-In-One Modbus Industrial Tool v16.0</b><br><br>"
            "Aplikasi Master Modbus dengan Dukungan Semua Versi PyModbus<br><br>"
            "Fitur pada versi ini:<br>"
            "• Auto-reconnect dengan backoff saat koneksi terputus<br>"
            "• Konfirmasi &amp; verifikasi baca-ulang sebelum/sesudah menulis<br>"
            "• Filter pencarian pada tabel hasil scan<br>"
            "• Tipe data 32-bit INT &amp; 64-bit DOUBLE, Mask Write Register (FC 22)<br>"
            "• Statistik kesehatan komunikasi (sukses/gagal/timeout)<br>"
            "• Preset pekerjaan lengkap, rotasi file CSV, mode gelap<br>"
            "• Tab Daftar Tag untuk multi-read alamat non-kontinu dengan skala/offset<br><br>"
            f"Folder konfigurasi &amp; log: {DIR_CONFIG}"
        )


    # ==================================================================
    # EXPORT CSV
    # ==================================================================
    def _bungkus_tabel_dengan_filter(self, tabel: QTableWidget, placeholder="Ketik untuk memfilter baris..."):
        """Bungkus sebuah QTableWidget dengan kotak pencarian di atasnya.
        Memudahkan menelusuri hasil scan yang jumlah barisnya banyak
        (mis. scan 247 Device ID atau ribuan alamat register)."""
        wadah = QWidget()
        layout = QVBoxLayout(wadah)
        layout.setContentsMargins(0, 0, 0, 0)
        kotak_filter = QLineEdit()
        kotak_filter.setPlaceholderText(placeholder)
        kotak_filter.textChanged.connect(lambda teks: self._filter_baris_tabel(tabel, teks))
        layout.addWidget(kotak_filter)
        layout.addWidget(tabel)
        return wadah

    def _filter_baris_tabel(self, tabel: QTableWidget, teks: str):
        teks = teks.strip().lower()
        for baris in range(tabel.rowCount()):
            if not teks:
                tabel.setRowHidden(baris, False)
                continue
            cocok = False
            for kolom in range(tabel.columnCount()):
                item = tabel.item(baris, kolom)
                if item and teks in item.text().lower():
                    cocok = True
                    break
            tabel.setRowHidden(baris, not cocok)

    def _export_tabel_ke_csv(self, tabel: QTableWidget, nama_file_default: str):
        """Export isi QTableWidget ke file CSV yang dipilih user."""
        if tabel.rowCount() == 0:
            QMessageBox.information(self, "Export CSV", "Tidak ada data untuk diekspor.")
            return

        jalur, _ = QFileDialog.getSaveFileName(
            self,
            "Simpan Data sebagai CSV",
            f"{nama_file_default}.csv",
            "CSV Files (*.csv)"
        )
        if not jalur:
            return

        try:
            with open(jalur, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)

                # Tulis header dari kolom tabel
                headers = []
                for col in range(tabel.columnCount()):
                    item = tabel.horizontalHeaderItem(col)
                    headers.append(item.text() if item else f"Kolom {col + 1}")
                writer.writerow(headers)

                # Tulis setiap baris data
                for row in range(tabel.rowCount()):
                    baris = []
                    for col in range(tabel.columnCount()):
                        item = tabel.item(row, col)
                        baris.append(item.text() if item else "")
                    writer.writerow(baris)

            self._set_status(f"Export berhasil → {jalur}")
            QMessageBox.information(self, "Export CSV", f"Data berhasil diekspor ke:\n{jalur}")

        except Exception as e:
            QMessageBox.warning(self, "Gagal Export", f"Terjadi kesalahan saat menyimpan:\n{str(e)}")

    # ==================================================================
    # TAB BARU: DAFTAR TAG (multi-read alamat non-kontinu + skala/offset)
    # ==================================================================
    def buat_tab_daftar_tag(self):
        tab = QWidget()
        tata_letak = QHBoxLayout(tab)

        box_kontrol = QGroupBox("Definisi Tag")
        box_kontrol.setMaximumWidth(320)
        grid_kiri = QGridLayout(box_kontrol)

        grid_kiri.addWidget(QLabel("Nama Tag:"), 0, 0)
        self.txt_tag_nama = QLineEdit("Tag_1")
        grid_kiri.addWidget(self.txt_tag_nama, 0, 1)

        grid_kiri.addWidget(QLabel("Slave ID:"), 1, 0)
        self.spin_tag_slave = QSpinBox()
        self.spin_tag_slave.setRange(0, 247)
        self.spin_tag_slave.setValue(1)
        grid_kiri.addWidget(self.spin_tag_slave, 1, 1)

        grid_kiri.addWidget(QLabel("Tipe Register:"), 2, 0)
        self.combo_tag_type = QComboBox()
        self.combo_tag_type.addItems(["Holding", "Input", "Coil", "Discrete Input"])
        grid_kiri.addWidget(self.combo_tag_type, 2, 1)

        grid_kiri.addWidget(QLabel("Alamat:"), 3, 0)
        self.spin_tag_addr = QSpinBox()
        self.spin_tag_addr.setRange(0, 65535)
        grid_kiri.addWidget(self.spin_tag_addr, 3, 1)

        grid_kiri.addWidget(QLabel("Format Nilai:"), 4, 0)
        self.combo_tag_encoding = QComboBox()
        self.combo_tag_encoding.addItems(DAFTAR_ENCODING)
        self.combo_tag_encoding.setToolTip("Diabaikan untuk tipe Coil/Discrete Input.")
        grid_kiri.addWidget(self.combo_tag_encoding, 4, 1)

        grid_kiri.addWidget(QLabel("Skala (×):"), 5, 0)
        self.spin_tag_skala = QDoubleSpinBox()
        self.spin_tag_skala.setRange(-1000000.0, 1000000.0)
        self.spin_tag_skala.setDecimals(4)
        self.spin_tag_skala.setValue(1.0)
        self.spin_tag_skala.setToolTip("Nilai mentah dikalikan faktor ini, mis. 0.1 untuk sensor yang mengirim suhu x10.")
        grid_kiri.addWidget(self.spin_tag_skala, 5, 1)

        grid_kiri.addWidget(QLabel("Offset (+):"), 6, 0)
        self.spin_tag_offset = QDoubleSpinBox()
        self.spin_tag_offset.setRange(-1000000.0, 1000000.0)
        self.spin_tag_offset.setDecimals(4)
        self.spin_tag_offset.setValue(0.0)
        self.spin_tag_offset.setToolTip("Ditambahkan setelah dikalikan skala: nilai_akhir = nilai_mentah × skala + offset.")
        grid_kiri.addWidget(self.spin_tag_offset, 6, 1)

        btn_tambah_tag = QPushButton("+ Tambah Tag")
        btn_tambah_tag.clicked.connect(self.tambah_tag)
        grid_kiri.addWidget(btn_tambah_tag, 7, 0, 1, 2)

        btn_hapus_tag = QPushButton("Hapus Tag Terpilih")
        btn_hapus_tag.clicked.connect(self.hapus_tag_terpilih)
        grid_kiri.addWidget(btn_hapus_tag, 8, 0, 1, 2)

        grid_kiri.addWidget(QLabel("Interval Polling (s):"), 9, 0)
        self.spin_tag_interval = QDoubleSpinBox()
        self.spin_tag_interval.setRange(0.2, 3600.0)
        self.spin_tag_interval.setValue(2.0)
        grid_kiri.addWidget(self.spin_tag_interval, 9, 1)

        self.btn_tag_baca_semua = QPushButton("Baca Semua Tag (Sekali)")
        self.btn_tag_baca_semua.clicked.connect(lambda: self.eksekusi_baca_tag(tunggal=True))
        grid_kiri.addWidget(self.btn_tag_baca_semua, 10, 0, 1, 2)

        self.btn_tag_toggle_polling = QPushButton("▶ Mulai Polling Semua Tag")
        self.btn_tag_toggle_polling.clicked.connect(lambda: self.eksekusi_baca_tag(tunggal=False))
        grid_kiri.addWidget(self.btn_tag_toggle_polling, 11, 0, 1, 2)

        grid_kiri.setRowStretch(12, 1)

        panel_kanan = QWidget()
        layout_kanan = QVBoxLayout(panel_kanan)
        layout_kanan.setContentsMargins(0, 0, 0, 0)

        self.tabel_tag = QTableWidget(0, 9)
        self.tabel_tag.setHorizontalHeaderLabels(
            ["Nama", "Slave ID", "Tipe", "Alamat", "Encoding", "Skala", "Offset", "Nilai Mentah", "Nilai Akhir"]
        )
        self.tabel_tag.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabel_tag.setSelectionBehavior(QTableWidget.SelectRows)
        layout_kanan.addWidget(self.tabel_tag, 2)

        box_monitor_tag = QGroupBox("Monitor / Log Tag")
        layout_monitor_tag = QVBoxLayout(box_monitor_tag)
        self.txt_tag_monitor = QTextEdit()
        self.txt_tag_monitor.setReadOnly(True)
        layout_monitor_tag.addWidget(self.txt_tag_monitor)
        layout_kanan.addWidget(box_monitor_tag, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(box_kontrol)
        splitter.addWidget(panel_kanan)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        tata_letak.addWidget(splitter)
        self.tabs.addTab(tab, "Daftar Tag (Multi-Read)")

    def tambah_tag(self):
        nama = self.txt_tag_nama.text().strip()
        if not nama:
            QMessageBox.warning(self, "Nama Kosong", "Nama tag tidak boleh kosong.")
            return
        tag = {
            'nama': nama,
            'slave_id': self.spin_tag_slave.value(),
            'tipe_reg': self.combo_tag_type.currentText(),
            'alamat': self.spin_tag_addr.value(),
            'encoding': self.combo_tag_encoding.currentText(),
            'skala': self.spin_tag_skala.value(),
            'offset': self.spin_tag_offset.value(),
        }
        self.daftar_tag.append(tag)
        self._render_ulang_tabel_tag()

    def hapus_tag_terpilih(self):
        baris_terpilih = sorted({idx.row() for idx in self.tabel_tag.selectedIndexes()}, reverse=True)
        if not baris_terpilih:
            QMessageBox.information(self, "Tidak Ada Pilihan", "Pilih dulu satu atau lebih baris tag yang ingin dihapus.")
            return
        for baris in baris_terpilih:
            if 0 <= baris < len(self.daftar_tag):
                del self.daftar_tag[baris]
        self._render_ulang_tabel_tag()

    def _render_ulang_tabel_tag(self):
        self.tabel_tag.setRowCount(0)
        for tag in self.daftar_tag:
            baris = self.tabel_tag.rowCount()
            self.tabel_tag.insertRow(baris)
            nilai_kolom = [
                tag.get('nama', ''), str(tag.get('slave_id', '')), tag.get('tipe_reg', ''),
                str(tag.get('alamat', '')), tag.get('encoding', ''), str(tag.get('skala', '')),
                str(tag.get('offset', '')), '-', '-'
            ]
            for kolom, teks in enumerate(nilai_kolom):
                item = QTableWidgetItem(teks)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.tabel_tag.setItem(baris, kolom, item)

    def eksekusi_baca_tag(self, tunggal=False):
        if not tunggal and self.thread_tag and self.thread_tag.isRunning():
            self.thread_tag.apakah_berjalan = False
            self.btn_tag_toggle_polling.setText("▶ Mulai Polling Semua Tag")
            self.manajemen_interlock_tombol(None, status_reset=True)
            self._set_status("Polling daftar tag dihentikan.")
            return

        if not self.client_global or not client_terhubung(self.client_global):
            self._set_status("Error: Koneksi utama belum aktif.")
            return

        if not self.daftar_tag:
            QMessageBox.information(self, "Daftar Tag Kosong", "Tambahkan minimal satu tag terlebih dahulu.")
            return

        if tunggal and self.thread_tag and self.thread_tag.isRunning():
            self._set_status("Masih ada pembacaan tag yang berjalan, tunggu selesai dahulu.")
            return

        if not tunggal:
            self.manajemen_interlock_tombol("tag")
            self.btn_tag_toggle_polling.setText("■ Hentikan Polling")
            self._set_status("Polling daftar tag aktif...")
        else:
            self._set_status("Membaca semua tag...")

        self.thread_tag = TagListReaderThread(
            self.client_global, self.daftar_tag, single_shot=tunggal,
            interval=self.spin_tag_interval.value(),
            auto_reconnect=self.chk_auto_reconnect.isChecked()
        )
        self.thread_tag.sinyal_hasil.connect(self.proses_hasil_tag_thread)
        self.thread_tag.sinyal_kesalahan.connect(self.proses_kesalahan_thread)
        self.thread_tag.sinyal_info.connect(self.proses_info_thread)
        if tunggal:
            self.thread_tag.finished.connect(lambda: self.manajemen_interlock_tombol(None, status_reset=True))
        self.thread_tag.start()

    def proses_hasil_tag_thread(self, hasil):
        stempel = datetime.now().strftime("%H:%M:%S")
        for baris, item_hasil in enumerate(hasil):
            if baris >= self.tabel_tag.rowCount():
                break
            item_mentah = QTableWidgetItem(item_hasil['nilai_mentah'])
            item_mentah.setFlags(item_mentah.flags() & ~Qt.ItemIsEditable)
            item_akhir = QTableWidgetItem(item_hasil['nilai_akhir'])
            item_akhir.setFlags(item_akhir.flags() & ~Qt.ItemIsEditable)
            if item_hasil['status'] == 'ERROR':
                item_akhir.setBackground(QColor(WARNA_GAGAL))
            self.tabel_tag.setItem(baris, 7, item_mentah)
            self.tabel_tag.setItem(baris, 8, item_akhir)
        self.txt_tag_monitor.append(f"[{stempel}] Pembacaan {len(hasil)} tag selesai.")


    def matikan_semua_thread_aktif(self):
        # FIX: batas tunggu sebelumnya tetap 1000ms walau timeout komunikasi
        # yang dikonfigurasi user bisa sampai 30 detik. Kalau sebuah thread
        # sedang menunggu balasan Modbus (blocking read) lebih dari 1 detik,
        # thread itu belum sempat berhenti saat closeEvent tetap melanjutkan
        # menutup koneksi -> thread latar masih memakai client yang sudah
        # ditutup dan berisiko exception/crash saat aplikasi keluar.
        # Sekarang batas tunggu disesuaikan dengan timeout komunikasi yang aktif.
        #
        # FIX Stabilitas: sebelumnya tiap thread di-stop lalu langsung
        # di-wait() satu-per-satu secara berurutan, sehingga total waktu
        # tunggu saat menutup aplikasi bisa mencapai N x batas_tunggu_ms jika
        # beberapa thread aktif bersamaan. Sekarang sinyal berhenti dikirim
        # ke SEMUA thread terlebih dahulu, baru menunggu satu-per-satu -
        # secara praktis semua thread berhenti kurang lebih bersamaan.
        batas_tunggu_ms = int(self.spin_timeout.value() * 1000) + 500
        daftar_thread = [self.thread_pemindai, self.thread_pooler, self.thread_logger, self.thread_tag]
        for th in daftar_thread:
            if th and th.isRunning():
                th.apakah_berjalan = False
        for th in daftar_thread:
            if th and th.isRunning():
                th.wait(batas_tunggu_ms)

    def closeEvent(self, event):
        self.matikan_semua_thread_aktif()
        if self.client_global:
            self.client_global.close()
        event.accept()


# =====================================================================
# ENTRY POINT
# =====================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ModbusApp()
    window.show()
    sys.exit(app.exec_())
