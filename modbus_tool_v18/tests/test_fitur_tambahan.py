"""Uji fitur yang dipindahkan dari modbus_tool.py (monolit) ke v18: Float Converter,
Daftar Perintah (Write), logger MySQL (Data Logger & Daftar Tag), logger CSV Daftar Tag,
dan tombol baca per-tag. MySQL diuji dengan koneksi/pencatat tiruan (tanpa server database)."""
import json
import math
import os
import time

import pytest

from modbus_app.inti import (
    DAFTAR_ENCODING, JENIS_FUNGSI_TULIS, URUTAN_FLOAT, MySQLDataLogger, float32_ke_register,
    nama_kolom_aman, nama_kolom_unik, nama_tabel_aman, normalisasi_perintah, pesan_error_mysql,
    register_ke_float32, susun_parameter_tulis,
)

U16 = "Mentah (16-bit UINT)"
F32 = "32-bit FLOAT (ABCD - Big Endian)"


# =====================================================================
# Float Converter (logika murni)
# =====================================================================
def test_float_abcd_nilai_acuan():
    assert float32_ke_register(3.5, "ABCD") == (0x4060, 0x0000)
    assert register_ke_float32(0x4060, 0x0000, "ABCD") == 3.5


@pytest.mark.parametrize("urutan", URUTAN_FLOAT)
@pytest.mark.parametrize("nilai", [0.0, 1.0, -12.25, 3.5, 100.125, 1e10])
def test_float_bolak_balik_untuk_semua_urutan(urutan, nilai):
    r1, r2 = float32_ke_register(nilai, urutan)
    assert 0 <= r1 <= 0xFFFF and 0 <= r2 <= 0xFFFF
    assert register_ke_float32(r1, r2, urutan) == pytest.approx(nilai, rel=1e-6)


def test_float_urutan_saling_berbeda_dan_cocok_dengan_encoding_inti():
    # Hasil konverter harus sama dengan jalur encode yang dipakai tab Write (satu sumber kebenaran).
    pasangan = {
        "ABCD": "32-bit FLOAT (ABCD - Big Endian)", "CDAB": "32-bit FLOAT (CDAB - Word Swap)",
        "BADC": "32-bit FLOAT (BADC - Byte Swap)", "DCBA": "32-bit FLOAT (DCBA - Little Endian)",
    }
    from modbus_app.inti import enkode_nilai_ke_register
    for urutan, encoding in pasangan.items():
        assert list(float32_ke_register(-12.25, urutan)) == enkode_nilai_ke_register("-12.25", encoding), urutan
    assert len({float32_ke_register(-12.25, u) for u in URUTAN_FLOAT}) == 4


def test_float_input_tidak_valid():
    with pytest.raises(ValueError):
        register_ke_float32(1, 2, "XXXX")
    with pytest.raises(ValueError):
        register_ke_float32(-1, 0)
    with pytest.raises(ValueError):
        register_ke_float32(0, 0x10000)
    with pytest.raises(ValueError):
        float32_ke_register(1.0, "XXXX")
    with pytest.raises(ValueError):
        float32_ke_register(1e39)                       # di luar jangkauan float32
    assert math.isnan(register_ke_float32(0x7FC0, 0x0000))     # NaN tetap bisa dibaca, bukan galat


# =====================================================================
# Parsing perintah tulis
# =====================================================================
def test_susun_parameter_tulis_semua_jenis():
    p = susun_parameter_tulis("Write Single Coil (FC 05)", "on", U16, 7, 3)
    assert (p['jenis'], p['nilai_bool'], p['alamat'], p['device_id']) == ('single_coil', True, 7, 3)

    p = susun_parameter_tulis("Write Multiple Coils (FC 15)", "1,0,true", U16, 0, 1)
    assert p['jenis'] == 'multi_coil' and p['daftar_bool'] == [True, False, True]

    p = susun_parameter_tulis("Mask Write Register (FC 22)", "0xFF00, 0x0012", U16, 0, 1)
    assert (p['jenis'], p['and_mask'], p['or_mask']) == ('mask', 0xFF00, 0x0012)

    p = susun_parameter_tulis("Write Single Register (FC 06)", "1234", U16, 0, 1, verifikasi=False)
    assert p['jenis'] == 'single_reg' and p['register_final'] == [1234] and p['verifikasi'] is False

    p = susun_parameter_tulis("Write Multiple Registers (FC 16)", "1.5, 2.5", F32, 0, 1)
    assert p['jenis'] == 'multi_reg' and len(p['register_final']) == 4


@pytest.mark.parametrize("fungsi,nilai,enc,potongan", [
    ("Write Single Register (FC 06)", "3.14", F32, "FC 16"),             # 32-bit tak muat di FC 06
    ("Write Multiple Coils (FC 15)", " , ", U16, "minimal satu"),
    ("Mask Write Register (FC 22)", "1", U16, "2 nilai"),
    ("Mask Write Register (FC 22)", "0x1FFFF,0", U16, "rentang"),
    ("Write Single Coil (FC 05)", "mungkin", U16, ""),
    ("Write Single Register (FC 06)", "abc", U16, ""),
])
def test_susun_parameter_tulis_menolak_isian_buruk(fungsi, nilai, enc, potongan):
    with pytest.raises(ValueError) as e:
        susun_parameter_tulis(fungsi, nilai, enc, 0, 1)
    assert potongan in str(e.value)


def test_normalisasi_perintah_valid_dan_bawaan():
    p = normalisasi_perintah({"nama": " Buka ", "tipe_fungsi": JENIS_FUNGSI_TULIS[0], "nilai": 1})
    assert p == {'nama': 'Buka', 'slave_id': 1, 'tipe_fungsi': JENIS_FUNGSI_TULIS[0], 'alamat': 0,
                 'encoding': DAFTAR_ENCODING[0], 'nilai': '1', 'verifikasi': True, 'lewati_konfirmasi': False}


@pytest.mark.parametrize("rusak", [
    {"nama": "", "tipe_fungsi": JENIS_FUNGSI_TULIS[0]},
    {"nama": "x", "tipe_fungsi": "FC 99"},
    {"nama": "x", "tipe_fungsi": JENIS_FUNGSI_TULIS[0], "encoding": "ngawur"},
    {"nama": "x", "tipe_fungsi": JENIS_FUNGSI_TULIS[0], "slave_id": 256},
    {"nama": "x", "tipe_fungsi": JENIS_FUNGSI_TULIS[0], "alamat": 70000},
    {"nama": "x", "tipe_fungsi": JENIS_FUNGSI_TULIS[0], "alamat": "bukan angka"},
])
def test_normalisasi_perintah_menolak_data_rusak(rusak):
    with pytest.raises(ValueError):
        normalisasi_perintah(rusak)


# =====================================================================
# MySQL: nama kolom/tabel dan pencatat (koneksi tiruan)
# =====================================================================
def test_nama_kolom_aman():
    assert nama_kolom_aman("Reg_40001-40002") == "reg_40001_40002"
    assert nama_kolom_aman("1 Suhu") == "c_1_suhu"
    assert nama_kolom_aman("   ") == "kolom"
    assert len(nama_kolom_aman("x" * 200)) == 64


def test_nama_kolom_unik_tidak_bentrok():
    hasil = nama_kolom_unik(["Suhu 1", "suhu_1", "Timestamp", "id", "A"])
    assert len(set(hasil)) == 5
    assert "timestamp" not in hasil and "id" not in hasil          # kolom baku dihindari
    assert hasil[0] == "suhu_1" and hasil[1] == "suhu_1_2"


def test_nama_tabel_aman_membuang_backtick():
    assert nama_tabel_aman("a`b; DROP") == "ab; DROP"             # backtick dibuang; nama selalu dibungkus `...`
    assert nama_tabel_aman("`", bawaan="cadangan") == "cadangan"
    assert nama_tabel_aman(None) == "modbus_log"


def test_pesan_error_mysql_ramah():
    assert "pymysql" in pesan_error_mysql(ImportError("x"))
    assert "cryptography" in pesan_error_mysql(RuntimeError("'cryptography' package is required"))
    assert pesan_error_mysql(RuntimeError("akses ditolak")) == "akses ditolak"


class KoneksiTiruan:
    def __init__(self, kolom_ada=("id", "timestamp")):
        self.perintah, self.tertutup, self._kolom = [], False, kolom_ada
        self._hasil = []

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.perintah.append((sql, params))
        self._hasil = [(k,) for k in self._kolom] if sql.startswith("SHOW COLUMNS") else []

    def fetchall(self):
        return self._hasil

    def close(self):
        self.tertutup = True


def test_siapkan_tabel_membuat_tabel_dan_menambah_kolom_yang_belum_ada():
    koneksi = KoneksiTiruan(kolom_ada=("id", "timestamp", "suhu"))
    pencatat = MySQLDataLogger("h", 3306, "u", "p", "db", "tabelku", pabrik_koneksi=lambda: koneksi)
    kolom = pencatat.siapkan_tabel(["Suhu", "Tekanan"])
    sql = [s for s, _ in koneksi.perintah]
    assert kolom == ["suhu", "tekanan"]
    assert sql[0].startswith("CREATE TABLE IF NOT EXISTS `tabelku`")
    assert sum(s.startswith("ALTER TABLE") for s in sql) == 1      # hanya "tekanan" yang ditambah
    assert "`tekanan`" in [s for s in sql if s.startswith("ALTER")][0]
    assert koneksi.tertutup


def test_simpan_baris_terparameter_dan_dipotong():
    koneksi = KoneksiTiruan()
    pencatat = MySQLDataLogger("h", "3306", "u", "p", "db", "t", pabrik_koneksi=lambda: koneksi)
    assert pencatat.port == 3306                                   # port teks dikonversi
    pencatat.simpan_baris("2026-01-01 00:00:00", ["A", "B"], [1.5, "x" * 100])
    sql, params = koneksi.perintah[-1]
    assert sql == "INSERT INTO `t` (timestamp, `a`, `b`) VALUES (%s, %s, %s)"
    assert params[0] == "2026-01-01 00:00:00" and params[1] == "1.5" and len(params[2]) == 64
    assert koneksi.tertutup


def test_simpan_baris_menolak_jumlah_tak_cocok_atau_kosong():
    pencatat = MySQLDataLogger("h", 1, "u", "p", "d", "t", pabrik_koneksi=lambda: KoneksiTiruan())
    with pytest.raises(ValueError):
        pencatat.simpan_baris("t", ["A"], [1, 2])
    with pytest.raises(ValueError):
        pencatat.simpan_baris("t", [], [])


def test_koneksi_ditutup_walau_query_gagal():
    class Gagal(KoneksiTiruan):
        def execute(self, sql, params=None):
            raise RuntimeError("server mati")
    koneksi = Gagal()
    pencatat = MySQLDataLogger("h", 1, "u", "p", "d", "t", pabrik_koneksi=lambda: koneksi)
    with pytest.raises(RuntimeError):
        pencatat.simpan_baris("t", ["A"], [1])
    assert koneksi.tertutup


# =====================================================================
# Thread penulis MySQL
# =====================================================================
class PencatatTiruan:
    def __init__(self, gagal=False, jeda=0.0):
        self.baris, self.gagal, self.jeda, self.table = [], gagal, jeda, "t"

    def simpan_baris(self, stempel, label, nilai):
        if self.jeda:
            time.sleep(self.jeda)
        if self.gagal:
            raise RuntimeError("db mati")
        self.baris.append((stempel, list(label), list(nilai)))


def _tunggu_selesai(th, timeout=8):
    assert th.wait(int(timeout * 1000)), "thread penulis tidak berhenti"
    from PyQt5.QtWidgets import QApplication
    QApplication.processEvents()          # sinyal dari thread ke callable biasa diantrekan ke thread utama


def test_penulis_menulis_semua_baris_sebelum_berhenti(qapp):
    from modbus_app.worker import PenulisMySQLThread
    pencatat = PencatatTiruan()
    th = PenulisMySQLThread(pencatat)
    th.start()
    for i in range(20):
        th.kirim(f"t{i}", ["A"], [i])
    th.berhenti()
    _tunggu_selesai(th)
    assert [b[2] for b in pencatat.baris] == [[i] for i in range(20)]      # urutan terjaga
    assert th.jumlah_tersimpan == 20 and th.jumlah_dibuang == 0


def test_penulis_antrean_penuh_membuang_baris_terlama(qapp):
    from modbus_app.worker import PenulisMySQLThread
    pencatat = PencatatTiruan()
    th = PenulisMySQLThread(pencatat, maks_antrean=3)        # belum start: antrean pasti menumpuk
    for i in range(5):
        th.kirim("t", ["A"], [i])
    assert th.jumlah_dibuang == 2
    th.start()
    th.berhenti()
    _tunggu_selesai(th)
    assert [b[2][0] for b in pencatat.baris] == [2, 3, 4]     # yang tertua (0,1) yang terbuang


def test_penulis_database_mati_melapor_dan_tidak_menahan_aplikasi(qapp):
    from modbus_app.worker import PenulisMySQLThread
    th = PenulisMySQLThread(PencatatTiruan(gagal=True))
    pesan = []
    th.sinyal_log.connect(pesan.append)
    th.start()
    for i in range(5):
        th.kirim("t", ["A"], [i])
    th.berhenti()
    _tunggu_selesai(th)
    assert th.jumlah_gagal == 5 and th.jumlah_tersimpan == 0
    assert len([p for p in pesan if "Gagal simpan ke MySQL" in p]) == 1   # dilaporkan sekali, tidak membanjiri log


def test_penulis_batas_kuras_membuang_sisa_bila_db_lambat(qapp, monkeypatch):
    from modbus_app.worker import PenulisMySQLThread
    monkeypatch.setattr(PenulisMySQLThread, "BATAS_KURAS_DETIK", 0.3)
    pencatat = PencatatTiruan(jeda=0.2)
    th = PenulisMySQLThread(pencatat)
    pesan = []
    th.sinyal_log.connect(pesan.append)
    th.start()
    for i in range(30):                                       # 30 x 0.2 dtk >> batas kuras
        th.kirim("t", ["A"], [i])
    th.berhenti()
    t0 = time.monotonic()
    _tunggu_selesai(th)
    assert time.monotonic() - t0 < 3
    assert 0 < th.jumlah_tersimpan < 30 and th.jumlah_dibuang > 0
    assert any("tidak sempat disimpan" in p for p in pesan)


def test_penulis_kompatibel_dengan_flag_apakah_berjalan(qapp):
    from modbus_app.worker import PenulisMySQLThread
    th = PenulisMySQLThread(PencatatTiruan())
    assert th.apakah_berjalan is True
    th.apakah_berjalan = False                 # yang dilakukan matikan_semua_thread_aktif()
    assert th.apakah_berjalan is False


# =====================================================================
# GUI: tab, Float Converter, Daftar Perintah, preset
# =====================================================================
pytest.importorskip("PyQt5")
from PyQt5.QtWidgets import QMessageBox  # noqa: E402

from conftest import tunggu_sampai  # noqa: E402
from modbus_app.jendela_utama import ModbusApp  # noqa: E402
from modbus_app.konfigurasi import FILE_JOB_PRESET  # noqa: E402


@pytest.fixture
def jendela(qapp):
    w = ModbusApp()
    yield w
    w.aksi_mode_gelap.setChecked(False)
    w.close()


@pytest.fixture
def jendela_terhubung(qapp, server_uji, client_uji):
    w = ModbusApp()
    w.client_global = client_uji
    w.chk_skip_confirm_write.setChecked(True)
    yield w
    w.client_global = None
    w.aksi_mode_gelap.setChecked(False)
    w.close()


@pytest.fixture
def pesan_kotak(monkeypatch):
    """Tangkap QMessageBox.warning/critical/information (tidak ada dialog modal di tes)."""
    tertangkap = []
    for nama in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, nama,
                            staticmethod(lambda *a, _n=nama, **k: tertangkap.append((_n, a[1], a[2] if len(a) > 2 else ""))))
    return tertangkap


def test_delapan_tab_dengan_urutan_seperti_monolit(jendela):
    judul = [jendela.tabs.tabText(i) for i in range(jendela.tabs.count())]
    assert judul == ["Pemindai Device ID", "Pemindai Peta Register", "Pembaca Modbus Live",
                     "Write Register / Coil", "Daftar Perintah (Write)", "Data Logger CSV",
                     "Daftar Tag (Multi-Read)", "Float Converter"]


def test_float_converter_gui(jendela, pesan_kotak):
    w = jendela
    w.txt_fc_reg1.setText("0x4060")
    w.txt_fc_reg2.setText("0")
    w.combo_fc_encoding.setCurrentText("ABCD")
    w._fc_convert_ke_float()
    assert "3.500000" in w.lbl_fc_hasil_float.text()

    w.txt_fc_float.setText("3,5")                           # koma desimal diterima
    w._fc_convert_ke_register()
    assert "16480 , 0" in w.lbl_fc_hasil_reg.text() and "0x4060" in w.lbl_fc_hasil_reg.text()

    w.combo_fc_encoding.setCurrentText("CDAB")
    w._fc_convert_ke_register()
    assert "0 , 16480" in w.lbl_fc_hasil_reg.text()

    assert pesan_kotak == []
    for isian in ("", "abc", "70000"):                      # kosong, bukan angka, di luar 16-bit
        w.txt_fc_reg1.setText(isian)
        w._fc_convert_ke_float()
    w.txt_fc_float.setText("")
    w._fc_convert_ke_register()
    w.txt_fc_float.setText("1e39")
    w._fc_convert_ke_register()
    assert [p[0] for p in pesan_kotak] == ["critical"] * 5   # semua jadi pesan galat, tanpa exception


def _perintah(w, nama, nilai="1", alamat=0, fungsi="Write Single Coil (FC 05)"):
    w.txt_perintah_nama.setText(nama)
    w.combo_perintah_type.setCurrentText(fungsi)
    w.spin_perintah_addr.setValue(alamat)
    w.txt_perintah_nilai.setText(nilai)
    w.tambah_perintah_write()


def test_crud_dan_urutan_perintah(jendela):
    w = jendela
    _perintah(w, "A", alamat=1)
    _perintah(w, "B", alamat=2)
    _perintah(w, "C", alamat=3)
    assert [p["nama"] for p in w.daftar_perintah_write] == ["A", "B", "C"]
    assert w.tabel_perintah.rowCount() == 3

    w.tabel_perintah.selectRow(2)
    assert w.txt_perintah_nama.text() == "C" and w.spin_perintah_addr.value() == 3   # form terisi
    w.pindah_perintah(-1)
    assert [p["nama"] for p in w.daftar_perintah_write] == ["A", "C", "B"]
    assert w._baris_perintah_terpilih() == [1]

    w.txt_perintah_nama.setText("C2")
    w.perbarui_perintah_terpilih()
    assert w.daftar_perintah_write[1]["nama"] == "C2"

    w.tabel_perintah.selectRow(0)
    w.hapus_perintah_terpilih()
    assert [p["nama"] for p in w.daftar_perintah_write] == ["C2", "B"]


def test_perintah_tidak_valid_tidak_disimpan(jendela, pesan_kotak):
    w = jendela
    w.txt_perintah_nama.setText("   ")
    w.tambah_perintah_write()
    w.txt_perintah_nama.setText("X")
    w.combo_perintah_type.setCurrentText("Write Single Coil (FC 05)")
    w.txt_perintah_nilai.setText("mungkin")
    w.tambah_perintah_write()
    assert w.daftar_perintah_write == []
    assert [p[0] for p in pesan_kotak] == ["warning", "warning"]


def test_tombol_jalankan_per_baris_memakai_baris_masing_masing(jendela, monkeypatch):
    w = jendela
    _perintah(w, "Satu", "1", 10)
    _perintah(w, "Dua", "0", 20)
    _perintah(w, "Tiga", "1", 30)
    dipanggil = []
    monkeypatch.setattr(w, "_mulai_penulisan", lambda **k: dipanggil.append((k["nama_perintah"], k["alamat"])))
    for baris in (1, 0, 2):
        w.tabel_perintah.cellWidget(baris, 6).click()
    assert dipanggil == [("Dua", 20), ("Satu", 10), ("Tiga", 30)]   # bukan semuanya baris terakhir (late-binding)


def test_perintah_dijalankan_ke_perangkat_dan_tombol_dikunci_selama_berjalan(jendela_terhubung, server_uji):
    w = jendela_terhubung
    _perintah(w, "Set reg", "1.5, 2.5", alamat=70, fungsi="Write Multiple Registers (FC 16)")
    w.daftar_perintah_write[0]["encoding"] = F32
    w.daftar_perintah_write[0]["lewati_konfirmasi"] = True
    w._render_ulang_tabel_perintah()

    w.tabel_perintah.cellWidget(0, 6).click()
    assert w.thread_tulis is not None
    assert not w.btn_execute_write.isEnabled()
    assert tunggu_sampai(lambda: "Verifikasi OK" in w.txt_perintah_log.toPlainText())
    assert "Verifikasi OK" not in w.txt_write_log.toPlainText()      # log masuk ke terminal tab perintah
    assert tunggu_sampai(lambda: w.tabel_perintah.cellWidget(0, 6).isEnabled() and w.btn_execute_write.isEnabled())
    from modbus_app.inti import enkode_nilai_ke_register
    assert server_uji.baca_holding(1, 70, 4) == (enkode_nilai_ke_register("1.5", F32)
                                                 + enkode_nilai_ke_register("2.5", F32))


def test_perintah_konfirmasi_ditolak_tidak_menulis(jendela_terhubung, server_uji, monkeypatch):
    w = jendela_terhubung
    _perintah(w, "Coil", "1", alamat=5)                    # lewati_konfirmasi = False
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No))
    w.tabel_perintah.cellWidget(0, 6).click()
    assert w.thread_tulis is None
    assert server_uji.baca_coil(1, 5, 1) == [False]
    assert "dibatalkan" in w.txt_perintah_log.toPlainText()


def test_perintah_tanpa_koneksi_tidak_melempar(jendela, pesan_kotak):
    _perintah(jendela, "Coil", "1")
    jendela.tabel_perintah.cellWidget(0, 6).click()
    assert [p[0] for p in pesan_kotak] == ["critical"] and "belum terhubung" in pesan_kotak[0][2]


def test_preset_menyimpan_perintah_database_dan_logger_tag_tanpa_password(qapp, tmp_path):
    w1 = ModbusApp()
    _perintah(w1, "Buka", "1", 9)
    w1.panel_db_logger.txt_host.setText("db.lokal")
    w1.panel_db_logger.spin_port.setValue(3307)
    w1.panel_db_logger.txt_pass.setText("RAHASIA-LOGGER")
    w1.panel_db_logger.chk.setChecked(True)
    w1.panel_db_tag.txt_tabel.setText("tag_saya")
    w1.panel_db_tag.txt_pass.setText("RAHASIA-TAG")
    w1.txt_tag_csv_path.setText("tag_saya.csv")
    w1.chk_tag_save_csv.setChecked(True)
    data = w1._kumpulkan_preset_pekerjaan()
    assert "RAHASIA" not in json.dumps(data)               # kata sandi tidak pernah ikut ke preset
    w1.aksi_mode_gelap.setChecked(False)
    w1.close()                                             # simpan otomatis
    with open(FILE_JOB_PRESET, encoding="utf-8") as f:
        assert "RAHASIA" not in f.read()

    w2 = ModbusApp()
    try:
        assert [p["nama"] for p in w2.daftar_perintah_write] == ["Buka"]
        assert w2.tabel_perintah.rowCount() == 1
        assert w2.panel_db_logger.txt_host.text() == "db.lokal" and w2.panel_db_logger.spin_port.value() == 3307
        assert w2.panel_db_logger.aktif() and w2.panel_db_logger.txt_pass.text() == ""
        assert w2.panel_db_tag.txt_tabel.text() == "tag_saya"
        assert w2.txt_tag_csv_path.text() == "tag_saya.csv" and w2.chk_tag_save_csv.isChecked()
    finally:
        w2.daftar_perintah_write = []
        w2.aksi_mode_gelap.setChecked(False)
        w2.close()


def test_preset_melewati_perintah_rusak_tanpa_membatalkan_sisanya(jendela):
    w = jendela
    w._terapkan_preset_pekerjaan({
        "daftar_perintah_write": [
            {"nama": "Baik", "tipe_fungsi": JENIS_FUNGSI_TULIS[0]},
            {"nama": "", "tipe_fungsi": JENIS_FUNGSI_TULIS[0]},
            {"nama": "Fungsi aneh", "tipe_fungsi": "FC 99"},
            "bukan dict",
            None,
        ],
        "database": "bukan dict",                           # struktur salah tidak boleh melempar
    })
    assert [p["nama"] for p in w.daftar_perintah_write] == ["Baik"]


def test_preset_lama_tanpa_bagian_baru_tetap_termuat(jendela):
    jendela._terapkan_preset_pekerjaan({"scan_id": {"id_awal": 5}})      # preset v18.0 lama
    assert jendela.spin_start_id.value() == 5 and jendela.daftar_perintah_write == []


# =====================================================================
# Daftar Tag: logger CSV, baca per tag
# =====================================================================
def _tambah_tag(w, nama, alamat):
    w.txt_tag_nama.setText(nama)
    w.spin_tag_addr.setValue(alamat)
    w.tambah_tag()


def test_tag_logger_csv(jendela_terhubung, server_uji, tmp_path):
    w = jendela_terhubung
    server_uji.isi_holding(1, 5, [11, 12])
    _tambah_tag(w, "Suhu", 5)
    _tambah_tag(w, "Tekanan", 6)
    jalur = str(tmp_path / "tag.csv")
    w.txt_tag_csv_path.setText(jalur)
    w.chk_tag_save_csv.setChecked(True)
    w.eksekusi_baca_tag(tunggal=True)
    assert tunggu_sampai(lambda: os.path.exists(jalur) and len(open(jalur, encoding="utf-8-sig").read().splitlines()) >= 2)
    baris = open(jalur, encoding="utf-8-sig").read().splitlines()
    assert baris[0] == "Timestamp,Suhu,Tekanan"
    assert baris[1].endswith("11.0000,12.0000")
    assert tunggu_sampai(lambda: w.btn_tambah_tag.isEnabled())


def test_tag_logger_csv_header_beda_diperingatkan_tanpa_menimpa(jendela_terhubung, server_uji, tmp_path):
    w = jendela_terhubung
    _tambah_tag(w, "Baru", 5)
    jalur = tmp_path / "lama.csv"
    jalur.write_text("Timestamp,Lama\n2026-01-01 00:00:00,1\n", encoding="utf-8")
    w.txt_tag_csv_path.setText(str(jalur))
    w.chk_tag_save_csv.setChecked(True)
    assert w._siapkan_csv_tag() is True
    assert "Peringatan" in w.txt_tag_monitor.toPlainText()
    assert jalur.read_text(encoding="utf-8").startswith("Timestamp,Lama")      # file lama tidak ditimpa


def test_tag_logger_csv_gagal_dibuat_membatalkan_pembacaan(jendela_terhubung, tmp_path):
    w = jendela_terhubung
    _tambah_tag(w, "A", 1)
    w.txt_tag_csv_path.setText(str(tmp_path / "tidak_ada_folder" / "x.csv"))
    w.chk_tag_save_csv.setChecked(True)
    w.eksekusi_baca_tag(tunggal=True)
    assert w.thread_tag is None or not w.thread_tag.isRunning()
    assert "Gagal menyiapkan file CSV" in w.txt_tag_monitor.toPlainText()


def test_tombol_baca_per_tag_hanya_membaca_barisnya(jendela_terhubung, server_uji):
    w = jendela_terhubung
    server_uji.isi_holding(1, 5, [11, 12, 13])
    for i, nama in enumerate(["A", "B", "C"]):
        _tambah_tag(w, nama, 5 + i)
    w.tabel_tag.cellWidget(1, 9).click()                      # hanya "B"
    assert not w.btn_tambah_tag.isEnabled()                   # daftar dikunci agar baris tak bergeser
    assert not w.tabel_tag.cellWidget(0, 9).isEnabled()       # tombol baris lain ikut terkunci
    assert tunggu_sampai(lambda: w.tabel_tag.item(1, 8) is not None and w.tabel_tag.item(1, 8).text() == "12.0000")
    assert w.tabel_tag.item(0, 8).text() in ("-", "")         # baris lain tak disentuh
    assert w.tabel_tag.item(2, 8).text() in ("-", "")
    assert tunggu_sampai(lambda: w.btn_tambah_tag.isEnabled() and w.tabel_tag.cellWidget(0, 9).isEnabled())


def test_tombol_baca_per_tag_tidak_ditulis_ke_logger(jendela_terhubung, server_uji, tmp_path):
    w = jendela_terhubung
    _tambah_tag(w, "A", 5)
    jalur = tmp_path / "tidak_boleh.csv"
    w.txt_tag_csv_path.setText(str(jalur))
    w.chk_tag_save_csv.setChecked(True)
    w.tabel_tag.cellWidget(0, 9).click()
    assert tunggu_sampai(lambda: w.btn_tambah_tag.isEnabled())
    assert not jalur.exists()


def test_tombol_baca_per_tag_tanpa_koneksi(jendela):
    _tambah_tag(jendela, "A", 5)
    jendela.tabel_tag.cellWidget(0, 9).click()                # tidak boleh melempar
    assert jendela.thread_tag is None


# =====================================================================
# MySQL di GUI (pencatat tiruan lewat tab_mysql.MySQLDataLogger)
# =====================================================================
class PencatatGUI(PencatatTiruan):
    instans = []
    gagal_siapkan = False

    def __init__(self, host, port, user, password, database, table):
        super().__init__()
        self.kunci_koneksi = (host, port, user, password, database)
        self.table = table
        self.label_kolom = None
        PencatatGUI.instans.append(self)

    def siapkan_tabel(self, label):
        if PencatatGUI.gagal_siapkan:
            raise RuntimeError("Access denied for user")
        self.label_kolom = list(label)


@pytest.fixture
def mysql_tiruan(monkeypatch):
    PencatatGUI.instans, PencatatGUI.gagal_siapkan = [], False
    monkeypatch.setattr("modbus_app.tab_mysql.MySQLDataLogger", PencatatGUI)
    return PencatatGUI


def test_logger_menulis_baris_yang_sama_ke_csv_dan_mysql(jendela_terhubung, server_uji, tmp_path, mysql_tiruan):
    w = jendela_terhubung
    server_uji.isi_holding(1, 0, [1, 2, 3, 4])
    jalur = str(tmp_path / "log.csv")
    w.txt_csv_path.setText(jalur)
    w.spin_log_count.setValue(4)
    w.combo_log_encoding.setCurrentText(U16)
    w.spin_log_interval.setValue(0.1)
    p = w.panel_db_logger
    p.txt_host.setText("10.0.0.5"); p.spin_port.setValue(3307); p.txt_user.setText("u1")
    p.txt_pass.setText("pw"); p.txt_db.setText("dbx"); p.txt_tabel.setText("log_saya"); p.chk.setChecked(True)

    w.toggle_logger()
    assert not p.txt_host.isEnabled() and not p.chk.isEnabled()          # isian DB dikunci selama merekam
    assert tunggu_sampai(lambda: len(mysql_tiruan.instans) == 1 and len(mysql_tiruan.instans[0].baris) >= 2)
    w.toggle_logger()
    assert tunggu_sampai(lambda: p.txt_host.isEnabled() and w.btn_toggle_logger.text().startswith("▶"))

    db = mysql_tiruan.instans[0]
    assert db.kunci_koneksi == ("10.0.0.5", 3307, "u1", "pw", "dbx") and db.table == "log_saya"
    assert db.label_kolom == ["Reg_0", "Reg_1", "Reg_2", "Reg_3"]        # sama dengan header CSV
    assert all(b[2] == ["1", "2", "3", "4"] or b[2] == [1, 2, 3, 4] for b in db.baris)
    assert tunggu_sampai(lambda: not w._penulis_mysql and all(not t.isRunning() for t in w._penulis_mysql_lama))
    jumlah_csv = len(open(jalur).read().splitlines()) - 1                # tanpa header
    assert len(db.baris) == jumlah_csv                                   # satu baris DB per baris CSV


def test_logger_mysql_gagal_tersambung_tidak_memulai_perekaman(jendela_terhubung, mysql_tiruan, tmp_path):
    w = jendela_terhubung
    mysql_tiruan.gagal_siapkan = True
    w.txt_csv_path.setText(str(tmp_path / "log.csv"))
    w.panel_db_logger.chk.setChecked(True)
    w.toggle_logger()
    assert w.thread_logger is None or not w.thread_logger.isRunning()
    assert "Gagal terhubung ke MySQL" in w.txt_logger_monitor.toPlainText()
    assert w.btn_toggle_logger.text().startswith("▶")
    assert w.btn_toggle_logger.isEnabled() and w.btn_execute_write.isEnabled()      # tombol tidak tertinggal terkunci
    assert w.panel_db_logger.txt_host.isEnabled()
    assert not w._penulis_mysql


def test_tag_menulis_ke_mysql_dengan_nama_tag_sebagai_kolom(jendela_terhubung, server_uji, mysql_tiruan):
    w = jendela_terhubung
    server_uji.isi_holding(1, 5, [11, 12])
    _tambah_tag(w, "Suhu", 5)
    _tambah_tag(w, "Tekanan", 6)
    w.panel_db_tag.chk.setChecked(True)
    w.eksekusi_baca_tag(tunggal=True)
    assert tunggu_sampai(lambda: len(mysql_tiruan.instans) == 1 and len(mysql_tiruan.instans[0].baris) == 1)
    db = mysql_tiruan.instans[0]
    assert db.label_kolom == ["Suhu", "Tekanan"] and db.table == "modbus_tag_log"
    assert db.baris[0][2] == ["11.0000", "12.0000"]
    assert tunggu_sampai(lambda: w.btn_tambah_tag.isEnabled() and not w._penulis_mysql)


def test_tag_mysql_gagal_membatalkan_pembacaan(jendela_terhubung, mysql_tiruan):
    w = jendela_terhubung
    mysql_tiruan.gagal_siapkan = True
    _tambah_tag(w, "Suhu", 5)
    w.panel_db_tag.chk.setChecked(True)
    w.eksekusi_baca_tag(tunggal=True)
    assert w.thread_tag is None or not w.thread_tag.isRunning()
    assert "Gagal terhubung ke MySQL" in w.txt_tag_monitor.toPlainText()
    assert w.btn_tambah_tag.isEnabled()


def test_menutup_aplikasi_menghentikan_penulis_mysql(qapp, server_uji, client_uji, mysql_tiruan):
    w = ModbusApp()
    w.client_global = client_uji
    server_uji.isi_holding(1, 5, [1])
    _tambah_tag(w, "A", 5)
    w.panel_db_tag.chk.setChecked(True)
    w.spin_tag_interval.setValue(0.1)
    w.eksekusi_baca_tag(tunggal=False)                         # polling berjalan
    assert tunggu_sampai(lambda: len(mysql_tiruan.instans) == 1 and mysql_tiruan.instans[0].baris)
    penulis = w._penulis_mysql['tag'][0]
    w.client_global = None
    w.daftar_tag = []
    w.aksi_mode_gelap.setChecked(False)
    w.close()
    assert not penulis.isRunning()                             # tidak ada thread yatim setelah ditutup
    assert not w._penulis_mysql


def test_panel_mysql_kunci_dan_terapkan_toleran(jendela):
    p = jendela.panel_db_tag
    p.terapkan({"host": "x", "port": "bukan angka", "aktif": True, "tak_dikenal": 1})
    assert p.txt_host.text() == "x" and p.spin_port.value() == 3306 and p.aktif()
    p.terapkan(None)
    p.terapkan([1, 2])
    assert "password" not in p.pengaturan() and p.konfigurasi()["password"] == ""
    p.kunci(True)
    assert not any(w.isEnabled() for w in p.widget_isian())
    p.kunci(False)
    assert all(w.isEnabled() for w in p.widget_isian())
