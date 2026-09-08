# -*- coding: utf-8 -*-
"""
modbus_reader.py
Wrapper komunikasi Modbus RTU (RS-485) untuk pembacaan register sensor
ketinggian air (level transmitter), menggunakan pymodbus sebagai backend.

Didesain toleran terhadap perbedaan versi pymodbus (2.x / 3.x) dengan
beberapa fallback saat membuka koneksi maupun memanggil fungsi baca register,
karena signature API pymodbus berubah beberapa kali antar versi mayor.

Jika 'pymodbus' atau 'pyserial' belum terpasang, modul ini tetap bisa
diimpor tanpa error (PYMODBUS_AVAILABLE / PYSERIAL_AVAILABLE akan False),
sehingga aplikasi utama tetap bisa berjalan dan menampilkan pesan yang
jelas ke pengguna alih-alih crash saat import.
"""

import struct
import inspect

try:
    from pymodbus.client import ModbusSerialClient
    PYMODBUS_AVAILABLE = True
except ImportError:
    try:
        from pymodbus.client.sync import ModbusSerialClient  # pymodbus 2.x
        PYMODBUS_AVAILABLE = True
    except ImportError:
        PYMODBUS_AVAILABLE = False
        ModbusSerialClient = None

try:
    import pymodbus as _pymodbus_module
    PYMODBUS_VERSION = getattr(_pymodbus_module, "__version__", None)
except ImportError:
    PYMODBUS_VERSION = None

try:
    import serial.tools.list_ports as _list_ports
    PYSERIAL_AVAILABLE = True
except ImportError:
    PYSERIAL_AVAILABLE = False
    _list_ports = None


PARITY_MAP = {"None (N)": "N", "Even (E)": "E", "Odd (O)": "O"}

DATA_TYPE_OPTIONS = [
    "Unsigned 16-bit (uint16)",
    "Signed 16-bit (int16)",
    "Unsigned 32-bit (uint32)",
    "Signed 32-bit (int32)",
    "Float 32-bit (IEEE754)",
    "Unsigned 64-bit (uint64)",
    "Signed 64-bit (int64)",
    "Double 64-bit (float64, IEEE754)",
]

DATA_TYPE_KEY_MAP = {
    "Unsigned 16-bit (uint16)": "uint16",
    "Signed 16-bit (int16)": "int16",
    "Unsigned 32-bit (uint32)": "uint32",
    "Signed 32-bit (int32)": "int32",
    "Float 32-bit (IEEE754)": "float32",
    "Unsigned 64-bit (uint64)": "uint64",
    "Signed 64-bit (int64)": "int64",
    "Double 64-bit (float64, IEEE754)": "float64",
}

# Jumlah register (16-bit) yang dibutuhkan tiap tipe data.
REGISTER_COUNT_MAP = {
    "uint16": 1, "int16": 1,
    "uint32": 2, "int32": 2, "float32": 2,
    "uint64": 4, "int64": 4, "float64": 4,
}

# Format struct.unpack big-endian untuk tiap tipe data (byte mentah sudah
# disusun ulang jadi big-endian logis oleh decode_registers sebelum di-unpack).
STRUCT_FORMAT_MAP = {
    "uint16": ">H", "int16": ">h",
    "uint32": ">I", "int32": ">i", "float32": ">f",
    "uint64": ">Q", "int64": ">q", "float64": ">d",
}

# Urutan word/byte dinyatakan sebagai 2 pilihan independen (bukan 4 kombinasi
# string) supaya berlaku untuk tipe data apa pun (16/32/64-bit), bukan cuma
# 32-bit. Notasi Modbus standar yang setara:
#   swap_words=False, swap_bytes=False -> "1234" (Big word / Big byte)
#   swap_words=True,  swap_bytes=False -> "3412" (Little word / Big byte)
#   swap_words=True,  swap_bytes=True  -> "4321" (Little word / Little byte)
#   swap_words=False, swap_bytes=True  -> "2143" (Big word / Little byte)
WORD_ORDER_OPTIONS = [
    "Normal - Big Endian (1234)",
    "Word Terbalik (3412)",
    "Word & Byte Terbalik - Little Endian (4321)",
    "Byte Terbalik (2143)",
]

WORD_ORDER_KEY_MAP = {
    "Normal - Big Endian (1234)": (False, False),
    "Word Terbalik (3412)": (True, False),
    "Word & Byte Terbalik - Little Endian (4321)": (True, True),
    "Byte Terbalik (2143)": (False, True),
}


_last_list_ports_error = None


def list_serial_ports():
    """Mengembalikan list nama port serial yang terdeteksi pada sistem.
    Mengembalikan list kosong jika pyserial tidak terpasang atau deteksi gagal.
    Pesan error (bila ada) disimpan di last_list_ports_error()."""
    global _last_list_ports_error
    _last_list_ports_error = None
    if not PYSERIAL_AVAILABLE:
        return []
    try:
        return [p.device for p in _list_ports.comports()]
    except Exception as e:
        _last_list_ports_error = str(e)
        return []


def last_list_ports_error():
    """Pesan error terakhir dari list_serial_ports(), atau None bila sukses."""
    return _last_list_ports_error


class ModbusRTUReader:
    """Membungkus koneksi ModbusSerialClient + pembacaan register mentah."""

    def __init__(self):
        self.client = None
        self.connected = False
        self.last_error = None

    def connect(self, port, baudrate=9600, parity="N", bytesize=8, stopbits=1, timeout=1.0):
        if not PYMODBUS_AVAILABLE:
            self.last_error = ("Modul 'pymodbus' belum terpasang.\n"
                                "Install dengan: pip install pymodbus pyserial")
            return False
        if not port:
            self.last_error = "Port serial belum dipilih/diisi."
            return False
        try:
            try:
                # pymodbus 3.x
                self.client = ModbusSerialClient(
                    port=port, baudrate=int(baudrate), parity=parity,
                    bytesize=int(bytesize), stopbits=int(stopbits), timeout=float(timeout),
                )
            except TypeError:
                # pymodbus 2.x (memerlukan argumen 'method')
                self.client = ModbusSerialClient(
                    method="rtu", port=port, baudrate=int(baudrate), parity=parity,
                    bytesize=int(bytesize), stopbits=int(stopbits), timeout=float(timeout),
                )
            ok = self.client.connect()
            self.connected = bool(ok)
            if not ok:
                self.last_error = (f"Gagal membuka koneksi ke port {port}. "
                                    "Periksa apakah port benar dan tidak dipakai aplikasi lain.")
            return self.connected
        except Exception as e:
            self.last_error = str(e)
            self.connected = False
            return False

    def disconnect(self):
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
        self.connected = False

    @staticmethod
    def _call_read(func, address, count, slave_id):
        """Panggil fungsi read_*_registers dengan signature yang benar untuk
        versi pymodbus yang terpasang.

        Nama parameter utk ID perangkat berubah beberapa kali antar versi
        pymodbus:
          - 2.x           : 'unit'
          - 3.0 - 3.9(ish) : 'slave'
          - >= 3.10/3.11   : 'device_id' ('slave' dihapus/di-deprecate)
        Selain itu 'count' bersifat keyword-only di banyak versi 3.x
        ('def read_holding_registers(address, *, count=1, slave=1, ...)'),
        jadi semua percobaan di bawah mengirim count sebagai keyword.

        Coba beberapa cara pemanggilan, urut dari yang paling baru; kalau
        SEMUA gagal, lempar satu exception yang isinya rangkuman tiap
        percobaan + error aslinya, supaya pesan error yang tampil di
        aplikasi langsung jadi bahan diagnosis tanpa perlu coba-coba lagi."""
        try:
            params = inspect.signature(func).parameters
        except (TypeError, ValueError):
            params = {}

        attempts = []
        for pname in ("device_id", "slave", "unit"):
            if pname in params:
                attempts.append((f"address=, count=, {pname}=... (sesuai signature terdeteksi)",
                                  lambda pname=pname: func(**{"address": address, "count": count, pname: slave_id})))

        attempts += [
            ("address=, count=, device_id=... (fallback, pymodbus >=3.10)",
             lambda: func(address=address, count=count, device_id=slave_id)),
            ("address=, count=, slave=... (fallback, pymodbus 3.x lama)",
             lambda: func(address=address, count=count, slave=slave_id)),
            ("address=, count=, unit=... (fallback, pymodbus 2.x)",
             lambda: func(address=address, count=count, unit=slave_id)),
            ("address, count, device_id=... (fallback)",
             lambda: func(address, count=count, device_id=slave_id)),
            ("address, count, slave=... (fallback)",
             lambda: func(address, count=count, slave=slave_id)),
            ("address, count, unit=... (fallback)",
             lambda: func(address, count=count, unit=slave_id)),
            ("address, count, <slave_id> posisional penuh (fallback)",
             lambda: func(address, count, slave_id)),
        ]

        errors = []
        for label, attempt in attempts:
            try:
                return attempt()
            except TypeError as e:
                errors.append(f"[{label}] -> {e}")
                continue

        sig_desc = f"parameter terdeteksi: {list(params.keys())}" if params else "signature tidak dapat diintrospeksi"
        detail = "\n".join(errors) if errors else "(tidak ada percobaan yang cocok)"
        raise TypeError(
            f"Semua cara pemanggilan {getattr(func, '__name__', 'read_registers')}() gagal "
            f"({sig_desc}). Rincian tiap percobaan:\n{detail}\n"
            "Kemungkinan versi pymodbus yang terpasang punya signature yang belum "
            "dikenali kode ini — cek versi dengan: python -c \"import pymodbus; print(pymodbus.__version__)\""
        )

    def read_raw_registers(self, slave_id, address, count, function_code="holding"):
        """Membaca register mentah, mengembalikan list[int] atau None jika gagal.
        function_code: 'holding' (FC03) atau 'input' (FC04)."""
        if not self.connected or self.client is None:
            self.last_error = "Belum terhubung ke perangkat Modbus."
            return None

        func = self.client.read_input_registers if function_code == "input" else self.client.read_holding_registers
        try:
            result = self._call_read(func, address, count, slave_id)
        except Exception as e:
            self.last_error = str(e)
            return None

        if result is None or result.isError():
            self.last_error = (f"Perangkat tidak merespon dengan benar "
                                f"(slave ID {slave_id}, alamat register {address}). "
                                "Periksa kembali pemetaan register & pengaturan koneksi.")
            return None

        try:
            return list(result.registers)
        except AttributeError:
            self.last_error = "Format respon tidak dikenali."
            return None


def decode_registers(registers, data_type, swap_words=False, swap_bytes=False):
    """Mengubah list register mentah (16-bit unsigned) menjadi nilai numerik.

    data_type   : salah satu key di DATA_TYPE_KEY_MAP, contoh 'uint16',
                  'int32', 'float32', 'uint64', 'int64', 'float64'.
    swap_words  : True -> urutan register dibalik sebelum digabung (dipakai
                  perangkat yang mengirim word order little-endian).
    swap_bytes  : True -> dua byte di dalam tiap register ditukar (dipakai
                  perangkat yang mengirim byte order little-endian per register).

    Berlaku untuk tipe 16/32/64-bit sekaligus (bukan cuma 32-bit) karena
    logikanya generik: susun ulang register+byte jadi big-endian logis,
    baru di-unpack sesuai lebar tipe datanya. Lihat WORD_ORDER_KEY_MAP
    untuk kombinasi yang setara dengan notasi Modbus umum (1234/3412/dst).
    """
    if not registers:
        raise ValueError("Tidak ada data register untuk didekode.")
    if data_type not in REGISTER_COUNT_MAP:
        raise ValueError(f"Tipe data tidak dikenal: {data_type}")

    needed = REGISTER_COUNT_MAP[data_type]
    if len(registers) < needed:
        raise ValueError(f"Tipe data '{data_type}' memerlukan {needed} register, hanya tersedia {len(registers)}.")

    regs = [r & 0xFFFF for r in registers[:needed]]
    if swap_words:
        regs = list(reversed(regs))

    raw = bytearray()
    for r in regs:
        hi, lo = (r >> 8) & 0xFF, r & 0xFF
        if swap_bytes:
            raw += bytes([lo, hi])
        else:
            raw += bytes([hi, lo])

    fmt = STRUCT_FORMAT_MAP[data_type]
    return float(struct.unpack(fmt, bytes(raw))[0])


def register_count_for(data_type):
    """Jumlah register (16-bit) yang perlu dibaca untuk suatu tipe data."""
    return REGISTER_COUNT_MAP.get(data_type, 1)
