"""Logika inti tanpa GUI: kompatibilitas pymodbus, decode/encode register,
statistik komunikasi, dan helper murni (mudah diuji tanpa perangkat keras)."""
import struct

from PyQt5.QtCore import QMutex

from .konfigurasi import *  # noqa: F401,F403
from .konfigurasi import PESAN_EXCEPTION_MODBUS, DAFTAR_ENCODING

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

def atur_retries_client(client, jumlah):
    """Ubah jumlah retry client pymodbus saat runtime (best-effort lintas
    versi: atribut bisa ada di client.retries, client.params.retries, atau
    client.transaction.retries). Mengembalikan daftar (objek, atribut,
    nilai_lama) untuk dipulihkan lewat pulihkan_retries_client()."""
    tersimpan = []
    if client is None:
        return tersimpan
    kandidat = [client, getattr(client, 'params', None), getattr(client, 'transaction', None)]
    for obj in kandidat:
        if obj is not None and hasattr(obj, 'retries'):
            try:
                lama = getattr(obj, 'retries')
                setattr(obj, 'retries', jumlah)
                tersimpan.append((obj, 'retries', lama))
            except Exception:
                continue
    return tersimpan


def pulihkan_retries_client(tersimpan):
    for obj, atribut, lama in tersimpan or []:
        try:
            setattr(obj, atribut, lama)
        except Exception:
            pass


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
            nilai = int(val_float)
            if not 0 <= nilai <= 0xFFFF:
                raise ValueError(f"Nilai {nilai} di luar rentang 16-bit UINT (0-65535). "
                                 f"Gunakan 'Signed 16-bit INT' untuk nilai negatif.")
            return [nilai]
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



NILAI_BOOL_BENAR = {'1', 'true', 'on', 'ya', 'yes'}
NILAI_BOOL_SALAH = {'0', 'false', 'off', 'tidak', 'no'}


def parse_nilai_bool(teks):
    """Ubah teks input pengguna menjadi bool. Nilai yang tidak dikenali
    ditolak (ValueError) -- sebelumnya teks seperti 'yes' atau '2' diam-diam
    dianggap False sehingga bisa menulis nilai yang salah ke perangkat."""
    t = str(teks).strip().lower()
    if t in NILAI_BOOL_BENAR:
        return True
    if t in NILAI_BOOL_SALAH:
        return False
    raise ValueError(f"Nilai coil '{teks}' tidak dikenali. Gunakan 1/0, true/false, on/off, ya/tidak.")


def peringatan_jumlah_register(tipe_reg, jumlah, encoding):
    """Peringatan jika jumlah register yang dibaca bukan kelipatan jumlah
    word encoding, sehingga register terakhir tidak bisa didekode."""
    if tipe_reg not in ('Holding', 'Input'):
        return None
    langkah = dapatkan_jumlah_word(encoding)
    if langkah > 1 and jumlah % langkah != 0:
        sisa = jumlah % langkah
        return (f"Jumlah register ({jumlah}) bukan kelipatan {langkah} untuk format '{encoding}'. "
                f"{sisa} register terakhir tidak bisa didekode dan akan tampil sebagai '-'.")
    return None


JENIS_REGISTER = ["Holding", "Input", "Coil", "Discrete Input"]
KOLOM_TAG_CSV = ["nama", "slave_id", "tipe_reg", "alamat", "encoding", "skala", "offset"]


def normalisasi_tag(baris):
    """Validasi & normalisasi satu baris tag (mis. dari CSV). Melempar
    ValueError dengan pesan jelas bila ada kolom yang tidak valid."""
    nama = str(baris.get('nama', '')).strip()
    if not nama:
        raise ValueError("nama kosong")
    tipe_reg = str(baris.get('tipe_reg', 'Holding')).strip() or 'Holding'
    if tipe_reg not in JENIS_REGISTER:
        raise ValueError(f"tipe_reg '{tipe_reg}' tidak valid")
    encoding = str(baris.get('encoding', DAFTAR_ENCODING[0])).strip() or DAFTAR_ENCODING[0]
    if encoding not in DAFTAR_ENCODING:
        raise ValueError(f"encoding '{encoding}' tidak dikenal")
    slave_id = int(str(baris.get('slave_id', 1)).strip() or 1)
    alamat = int(str(baris.get('alamat', 0)).strip() or 0)
    if not 0 <= slave_id <= 255:
        raise ValueError(f"slave_id {slave_id} di luar 0-255")
    if not 0 <= alamat <= 65535:
        raise ValueError(f"alamat {alamat} di luar 0-65535")
    skala = float(str(baris.get('skala', 1.0)).strip() or 1.0)
    offset = float(str(baris.get('offset', 0.0)).strip() or 0.0)
    return {'nama': nama, 'slave_id': slave_id, 'tipe_reg': tipe_reg, 'alamat': alamat,
            'encoding': encoding, 'skala': skala, 'offset': offset}


def susun_blok_tag(daftar_tag, maks_register=125):
    """Kelompokkan tag yang alamatnya bersambung/bertumpuk (slave ID dan tipe
    register sama) menjadi blok baca tunggal, sehingga jumlah request di bus
    jauh berkurang. Hanya alamat yang benar-benar bersambung yang digabung
    (tanpa celah), supaya satu alamat tak valid di tengah tidak menggagalkan
    blok. Mengembalikan list blok:
        {'slave_id','tipe_reg','mulai','akhir','anggota':[(indeks_tag, mulai_tag, jumlah_tag)]}
    """
    grup = {}
    for indeks, tag in enumerate(daftar_tag):
        slave_id = int(tag.get('slave_id', 1))
        tipe_reg = tag.get('tipe_reg', 'Holding')
        alamat = int(tag.get('alamat', 0))
        encoding = tag.get('encoding', 'Mentah (16-bit UINT)')
        jumlah = dapatkan_jumlah_word(encoding) if tipe_reg in ('Holding', 'Input') else 1
        grup.setdefault((slave_id, tipe_reg), []).append((alamat, jumlah, indeks))

    daftar_blok = []
    for (slave_id, tipe_reg), item in grup.items():
        item.sort(key=lambda x: x[0])
        blok = None
        for alamat, jumlah, indeks in item:
            akhir = alamat + jumlah
            if blok and alamat <= blok['akhir'] and (max(akhir, blok['akhir']) - blok['mulai']) <= maks_register:
                blok['akhir'] = max(blok['akhir'], akhir)
                blok['anggota'].append((indeks, alamat, jumlah))
            else:
                if blok:
                    daftar_blok.append(blok)
                blok = {'slave_id': slave_id, 'tipe_reg': tipe_reg, 'mulai': alamat,
                        'akhir': akhir, 'anggota': [(indeks, alamat, jumlah)]}
        if blok:
            daftar_blok.append(blok)
    return daftar_blok


def olah_nilai_tag(tag, data):
    """Hitung dict hasil sebuah tag dari data mentahnya: list register
    (Holding/Input) atau list bit (Coil/Discrete). Termasuk skala & offset."""
    nama = tag.get('nama', '-')
    tipe_reg = tag.get('tipe_reg', 'Holding')
    encoding = tag.get('encoding', 'Mentah (16-bit UINT)')
    skala = float(tag.get('skala', 1.0))
    offset = float(tag.get('offset', 0.0))
    if tipe_reg in ('Holding', 'Input'):
        nilai_decode = dekode_register_multi(list(data), encoding)
        try:
            nilai_akhir = f"{(float(nilai_decode) * skala) + offset:.4f}"
        except (ValueError, TypeError):
            nilai_akhir = nilai_decode
        return {'nama': nama, 'nilai_mentah': str(list(data)), 'nilai_akhir': nilai_akhir, 'status': 'OK'}
    bit = bool(data[0])
    return {'nama': nama, 'nilai_mentah': str([int(bit)]), 'nilai_akhir': str(bit), 'status': 'OK'}


# =====================================================================
# PENULISAN: parsing & validasi input
# Dipakai bersama oleh tab "Write Register / Coil" dan tab "Daftar Perintah (Write)".
# =====================================================================
JENIS_FUNGSI_TULIS = [
    "Write Single Coil (FC 05)", "Write Single Register (FC 06)",
    "Write Multiple Coils (FC 15)", "Write Multiple Registers (FC 16)",
    "Mask Write Register (FC 22)",
]


def susun_parameter_tulis(tipe_fungsi, input_user, encoding, alamat, device_id, verifikasi=True):
    """Validasi & ubah isian pengguna menjadi parameter untuk ModbusWriteThread.
    Tidak menyentuh bus. Melempar ValueError dengan pesan yang bisa langsung
    ditampilkan bila isian tidak valid."""
    p = {'alamat': int(alamat), 'device_id': int(device_id), 'verifikasi': bool(verifikasi)}
    if "Single Coil" in tipe_fungsi:
        p['jenis'] = 'single_coil'
        p['nilai_bool'] = parse_nilai_bool(input_user)
    elif "Multiple Coils" in tipe_fungsi:
        elemen = [e for e in input_user.split(",") if e.strip()]
        if not elemen:
            raise ValueError("Isi minimal satu nilai coil, dipisah koma (mis. 1,0,1).")
        p['jenis'] = 'multi_coil'
        p['daftar_bool'] = [parse_nilai_bool(e) for e in elemen]
    elif "Mask Write" in tipe_fungsi:
        bagian = [b.strip() for b in input_user.split(",")]
        if len(bagian) != 2:
            raise ValueError("Perlu 2 nilai dipisah koma: AND_mask,OR_mask")
        and_mask, or_mask = int(bagian[0], 0), int(bagian[1], 0)
        for nama_mask, nilai in (("AND_mask", and_mask), ("OR_mask", or_mask)):
            if not 0 <= nilai <= 0xFFFF:
                raise ValueError(f"{nama_mask} {nilai} di luar rentang 0-65535 (0xFFFF).")
        p.update(jenis='mask', and_mask=and_mask, or_mask=or_mask)
    elif "Single Register" in tipe_fungsi:
        register_final = enkode_nilai_ke_register(input_user, encoding)
        if len(register_final) != 1:
            raise ValueError(
                f"FC 06 hanya menulis 1 register (16-bit), sedangkan format '{encoding}' "
                f"membutuhkan {len(register_final)} register. Pilih 'Write Multiple Registers "
                f"(FC 16)' atau ubah format ke 16-bit.")
        p.update(jenis='single_reg', register_final=register_final)
    else:  # Write Multiple Registers (FC 16)
        register_final = []
        for e in input_user.split(","):
            register_final.extend(enkode_nilai_ke_register(e.strip(), encoding))
        p.update(jenis='multi_reg', register_final=register_final)
    return p


def normalisasi_perintah(data):
    """Validasi & normalisasi satu perintah tulis tersimpan (mis. dari preset).
    Melempar ValueError bila ada isian yang tidak valid. Isi kolom 'nilai'
    sengaja tidak diurai di sini (lihat susun_parameter_tulis)."""
    nama = str(data.get('nama', '')).strip()
    if not nama:
        raise ValueError("nama kosong")
    tipe_fungsi = str(data.get('tipe_fungsi', '')).strip()
    if tipe_fungsi not in JENIS_FUNGSI_TULIS:
        raise ValueError(f"tipe_fungsi '{tipe_fungsi}' tidak dikenal")
    encoding = str(data.get('encoding', DAFTAR_ENCODING[0])).strip() or DAFTAR_ENCODING[0]
    if encoding not in DAFTAR_ENCODING:
        raise ValueError(f"encoding '{encoding}' tidak dikenal")
    slave_id = int(data.get('slave_id', 1))
    alamat = int(data.get('alamat', 0))
    if not 0 <= slave_id <= 255:
        raise ValueError(f"slave_id {slave_id} di luar 0-255")
    if not 0 <= alamat <= 65535:
        raise ValueError(f"alamat {alamat} di luar 0-65535")
    return {'nama': nama, 'slave_id': slave_id, 'tipe_fungsi': tipe_fungsi, 'alamat': alamat,
            'encoding': encoding, 'nilai': str(data.get('nilai', '')),
            'verifikasi': bool(data.get('verifikasi', True)),
            'lewati_konfirmasi': bool(data.get('lewati_konfirmasi', False))}


# =====================================================================
# KONVERTER FLOAT32 <-> 2 REGISTER 16-BIT
# =====================================================================
URUTAN_FLOAT = ("ABCD", "BADC", "CDAB", "DCBA")


def register_ke_float32(r1, r2, urutan="ABCD"):
    """Dua register 16-bit -> float32. `urutan` = susunan byte float di kawat:
    ABCD (big-endian), BADC (byte swap), CDAB (word swap), DCBA (little-endian)."""
    if urutan not in URUTAN_FLOAT:
        raise ValueError(f"Urutan '{urutan}' tidak dikenal (pilih salah satu dari {', '.join(URUTAN_FLOAT)}).")
    for nomor, r in ((1, r1), (2, r2)):
        if not 0 <= r <= 0xFFFF:
            raise ValueError(f"Register {nomor} ({r}) di luar rentang 0-65535.")
    urutan_byte = {
        "ABCD": [r1 >> 8, r1 & 0xFF, r2 >> 8, r2 & 0xFF],
        "BADC": [r1 & 0xFF, r1 >> 8, r2 & 0xFF, r2 >> 8],
        "CDAB": [r2 >> 8, r2 & 0xFF, r1 >> 8, r1 & 0xFF],
        "DCBA": [r2 & 0xFF, r2 >> 8, r1 & 0xFF, r1 >> 8],
    }[urutan]
    return struct.unpack(">f", bytes(urutan_byte))[0]


def float32_ke_register(nilai, urutan="ABCD"):
    """float32 -> (register1, register2) 16-bit. Kebalikan register_ke_float32."""
    if urutan not in URUTAN_FLOAT:
        raise ValueError(f"Urutan '{urutan}' tidak dikenal (pilih salah satu dari {', '.join(URUTAN_FLOAT)}).")
    try:
        b = list(struct.pack(">f", nilai))
    except OverflowError:
        raise ValueError("Nilai di luar jangkauan float32 (sekitar ±3.4e38).")
    m = {
        "ABCD": b,
        "BADC": [b[1], b[0], b[3], b[2]],
        "CDAB": [b[2], b[3], b[0], b[1]],
        "DCBA": [b[3], b[2], b[1], b[0]],
    }[urutan]
    return (m[0] << 8) + m[1], (m[2] << 8) + m[3]


# =====================================================================
# LOGGER DATABASE (MySQL)
# Dipakai tab "Data Logger CSV" dan "Daftar Tag". Kolom diberi nama sesuai
# header CSV (mis. "Reg_40001") supaya baris di DB mudah dicocokkan dengan
# baris di file CSV yang sama. `pymysql` di-import lokal (bukan di top-level)
# supaya aplikasi tetap jalan tanpa pymysql bila fitur ini tidak dipakai.
# =====================================================================
BATAS_NAMA_MYSQL = 64
LEBAR_KOLOM_MYSQL = 64          # kolom data dibuat VARCHAR(64)
KOLOM_BAKU_MYSQL = ("id", "timestamp")


def nama_kolom_aman(label):
    """Ubah label header (mis. 'Reg_40001-40002') jadi nama kolom SQL yang
    aman: huruf kecil, karakter non alfanumerik jadi underscore, diberi
    prefiks 'c_' bila diawali angka, dan dipotong ke batas 64 karakter MySQL."""
    aman = "".join(c if c.isalnum() else "_" for c in str(label).strip().lower())
    if not aman:
        aman = "kolom"
    if aman[0].isdigit():
        aman = f"c_{aman}"
    return aman[:BATAS_NAMA_MYSQL]


def nama_kolom_unik(daftar_label):
    """Nama kolom aman untuk setiap label, dijamin unik dan tidak bentrok dengan
    kolom baku (id, timestamp). Label yang setelah disanitasi sama (mis. 'Suhu 1'
    dan 'suhu_1', atau tag bernama 'Timestamp') diberi akhiran _2, _3, ..."""
    dipakai = set(KOLOM_BAKU_MYSQL)
    hasil = []
    for label in daftar_label:
        dasar = nama_kolom_aman(label)
        nama, n = dasar, 2
        while nama in dipakai:
            akhiran = f"_{n}"
            nama = dasar[:BATAS_NAMA_MYSQL - len(akhiran)] + akhiran
            n += 1
        dipakai.add(nama)
        hasil.append(nama)
    return hasil


def nama_tabel_aman(nama, bawaan="modbus_log"):
    """Nama tabel tanpa karakter backtick (yang bisa merusak SQL), maks 64 karakter."""
    bersih = (nama or "").strip().replace("`", "")[:BATAS_NAMA_MYSQL]
    return bersih or bawaan


def pesan_error_mysql(exc):
    """Teks galat MySQL yang ramah pengguna, dengan petunjuk untuk kasus umum."""
    teks = str(exc)
    if isinstance(exc, ImportError):
        return "paket 'pymysql' belum ter-install (pip install pymysql)."
    if "cryptography" in teks.lower():
        return (f"{teks} -- MySQL 8 memakai autentikasi caching_sha2_password: pasang paket "
                f"'cryptography' (pip install cryptography), atau pakai user dengan mysql_native_password.")
    return teks


class MySQLDataLogger:
    """Logger sederhana ke MySQL. Setiap operasi membuka lalu menutup koneksi
    sendiri (tanpa koneksi persisten), sehingga tidak ada state koneksi basi
    bila server sempat mati/restart. `pabrik_koneksi` (opsional) dipakai uji
    untuk mengganti koneksi pymysql dengan koneksi tiruan."""

    # Batas waktu (detik). connect_timeout saja TIDAK cukup: server yang menerima koneksi TCP
    # tetapi tidak menjawab (macet/overload/proxy tersendat) membuat pembacaan handshake
    # menunggu tanpa batas -- GUI membeku saat penyiapan tabel dan thread penulis tak
    # pernah berhenti. read/write_timeout membatasi itu.
    TIMEOUT_KONEKSI_DETIK = 5
    TIMEOUT_BACA_TULIS_DETIK = 10

    def __init__(self, host, port, user, password, database, table, pabrik_koneksi=None,
                 timeout_koneksi=None, timeout_baca_tulis=None):
        self.timeout_koneksi = timeout_koneksi or self.TIMEOUT_KONEKSI_DETIK
        self.timeout_baca_tulis = timeout_baca_tulis or self.TIMEOUT_BACA_TULIS_DETIK
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.database = database
        self.table = nama_tabel_aman(table)
        self._pabrik_koneksi = pabrik_koneksi

    def _connect(self):
        if self._pabrik_koneksi is not None:
            return self._pabrik_koneksi()
        import pymysql
        return pymysql.connect(
            host=self.host, port=self.port, user=self.user, password=self.password,
            database=self.database, autocommit=True, charset="utf8mb4",
            connect_timeout=self.timeout_koneksi,
            read_timeout=self.timeout_baca_tulis, write_timeout=self.timeout_baca_tulis
        )

    def siapkan_tabel(self, daftar_label_kolom):
        """Dipanggil sekali saat logging dimulai: buat tabel bila belum ada, lalu
        tambahkan kolom data yang belum ada (VARCHAR(64) -- dipilih ketimbang
        DOUBLE karena nilai bisa berupa teks hasil decode, float, int, atau 0/1
        untuk coil). Mengembalikan daftar nama kolom yang dipakai."""
        kolom_aman = nama_kolom_unik(daftar_label_kolom)
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS `{self.table}` ("
                f"id INT AUTO_INCREMENT PRIMARY KEY, timestamp DATETIME NOT NULL) ENGINE=InnoDB;"
            )
            cur.execute(f"SHOW COLUMNS FROM `{self.table}`;")
            kolom_ada = {str(baris[0]).lower() for baris in cur.fetchall()}
            for kolom in kolom_aman:
                if kolom not in kolom_ada:
                    cur.execute(f"ALTER TABLE `{self.table}` ADD COLUMN `{kolom}` VARCHAR({LEBAR_KOLOM_MYSQL});")
                    kolom_ada.add(kolom)
        finally:
            conn.close()
        return kolom_aman

    def simpan_baris(self, stempel_waktu, daftar_label_kolom, daftar_nilai):
        """Sisipkan 1 baris. Label dan nilai harus berpasangan (jumlah sama)."""
        if not daftar_label_kolom:
            raise ValueError("Tidak ada kolom data untuk disimpan.")
        if len(daftar_label_kolom) != len(daftar_nilai):
            raise ValueError(
                f"Jumlah kolom ({len(daftar_label_kolom)}) tidak sama dengan jumlah nilai ({len(daftar_nilai)}).")
        kolom_aman = nama_kolom_unik(daftar_label_kolom)
        daftar_kolom_sql = ", ".join(f"`{k}`" for k in kolom_aman)
        placeholder = ", ".join(["%s"] * (len(kolom_aman) + 1))
        sql = f"INSERT INTO `{self.table}` (timestamp, {daftar_kolom_sql}) VALUES ({placeholder})"
        conn = self._connect()
        try:
            cur = conn.cursor()
            # Dipotong ke lebar kolom: mode strict MySQL menolak seluruh baris bila ada
            # nilai yang lebih panjang (mis. teks galat Modbus pada baris tag yang gagal).
            cur.execute(sql, [stempel_waktu] + [str(v)[:LEBAR_KOLOM_MYSQL] for v in daftar_nilai])
        finally:
            conn.close()
