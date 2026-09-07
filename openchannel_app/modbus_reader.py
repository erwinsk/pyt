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
]

DATA_TYPE_KEY_MAP = {
    "Unsigned 16-bit (uint16)": "uint16",
    "Signed 16-bit (int16)": "int16",
    "Unsigned 32-bit (uint32)": "uint32",
    "Signed 32-bit (int32)": "int32",
    "Float 32-bit (IEEE754)": "float32",
}

WORD_ORDER_OPTIONS = [
    "1234 (Big/Big)",
    "3412 (Little/Big)",
    "4321 (Little/Little)",
    "2143 (Big/Little)",
]

WORD_ORDER_KEY_MAP = {
    "1234 (Big/Big)": "1234",
    "3412 (Little/Big)": "3412",
    "4321 (Little/Little)": "4321",
    "2143 (Big/Little)": "2143",
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


def decode_registers(registers, data_type, word_order="1234"):
    """Mengubah list register mentah (16-bit unsigned) menjadi nilai numerik.

    data_type  : 'uint16' | 'int16' | 'uint32' | 'int32' | 'float32'
    word_order : untuk tipe 32-bit, salah satu dari '1234', '3412', '4321', '2143'
                 (notasi urutan byte standar Modbus, lihat WORD_ORDER_KEY_MAP).
                 '1234' = big-endian penuh (register tinggi dulu, byte MSB dulu).
    """
    if not registers:
        raise ValueError("Tidak ada data register untuk didekode.")

    if data_type in ("uint16", "int16"):
        val = registers[0] & 0xFFFF
        if data_type == "int16" and val >= 32768:
            val -= 65536
        return float(val)

    if len(registers) < 2:
        raise ValueError(f"Tipe data '{data_type}' memerlukan 2 register, hanya tersedia {len(registers)}.")

    r0, r1 = registers[0] & 0xFFFF, registers[1] & 0xFFFF
    b0h, b0l = (r0 >> 8) & 0xFF, r0 & 0xFF
    b1h, b1l = (r1 >> 8) & 0xFF, r1 & 0xFF

    # Peta urutan byte akhir (big-endian logis) untuk tiap kombinasi word/byte order.
    byte_order_map = {
        "1234": (b0h, b0l, b1h, b1l),  # Big word / Big byte — standar
        "3412": (b1h, b1l, b0h, b0l),  # Little word / Big byte
        "4321": (b1l, b1h, b0l, b0h),  # Little word / Little byte
        "2143": (b0l, b0h, b1l, b1h),  # Big word / Little byte
    }
    if word_order not in byte_order_map:
        raise ValueError(f"Urutan word/byte tidak dikenal: {word_order}")

    raw_bytes = bytes(byte_order_map[word_order])

    if data_type == "uint32":
        return float(struct.unpack(">I", raw_bytes)[0])
    elif data_type == "int32":
        return float(struct.unpack(">i", raw_bytes)[0])
    elif data_type == "float32":
        return float(struct.unpack(">f", raw_bytes)[0])
    else:
        raise ValueError(f"Tipe data tidak dikenal: {data_type}")


def register_count_for(data_type):
    """Jumlah register (16-bit) yang perlu dibaca untuk suatu tipe data."""
    return 1 if data_type in ("uint16", "int16") else 2
