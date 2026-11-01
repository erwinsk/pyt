"""Uji GUI (Qt offscreen): rentang input, tag, tabel, log, preset otomatis."""
import csv

import pytest

pytest.importorskip("PyQt5")

from PyQt5.QtWidgets import QFileDialog, QMessageBox  # noqa: E402

from modbus_app.jendela_utama import ModbusApp  # noqa: E402
from modbus_app.konfigurasi import DAFTAR_ENCODING, FILE_JOB_PRESET, FILE_PRESET  # noqa: E402


@pytest.fixture
def jendela(qapp):
    w = ModbusApp()
    yield w
    w.aksi_mode_gelap.setChecked(False)
    w.close()


def test_semua_spinbox_slave_id_sampai_255(jendela):
    for nama in ["spin_start_id", "spin_end_id", "spin_reg_scan_slave", "spin_read_slave",
                 "spin_write_slave", "spin_log_slave", "spin_tag_slave"]:
        spin = getattr(jendela, nama)
        spin.setValue(255)
        assert spin.value() == 255, nama


def test_semua_tab_terpasang(jendela):
    judul = [jendela.tabs.tabText(i) for i in range(jendela.tabs.count())]
    assert len(judul) == 6 and "Daftar Tag (Multi-Read)" in judul


def _tambah(w, nama, alamat):
    w.txt_tag_nama.setText(nama)
    w.spin_tag_addr.setValue(alamat)
    w.tambah_tag()


def test_crud_dan_urutan_tag(jendela):
    w = jendela
    _tambah(w, "A", 1)
    _tambah(w, "B", 2)
    _tambah(w, "C", 3)
    assert [t["nama"] for t in w.daftar_tag] == ["A", "B", "C"]

    w.tabel_tag.selectRow(2)
    assert w.txt_tag_nama.text() == "C"            # form terisi dari baris terpilih
    w.pindah_tag(-1)
    assert [t["nama"] for t in w.daftar_tag] == ["A", "C", "B"]
    assert w._baris_tag_terpilih() == [1]

    w.txt_tag_nama.setText("C2")
    w.spin_tag_skala.setValue(0.5)
    w.perbarui_tag_terpilih()
    assert w.daftar_tag[1]["nama"] == "C2" and w.daftar_tag[1]["skala"] == 0.5

    w.tabel_tag.selectRow(0)
    w.hapus_tag_terpilih()
    assert [t["nama"] for t in w.daftar_tag] == ["C2", "B"]
    assert w.tabel_tag.rowCount() == 2


def test_pindah_di_batas_tidak_berubah(jendela):
    w = jendela
    _tambah(w, "A", 1)
    _tambah(w, "B", 2)
    w.tabel_tag.selectRow(0)
    w.pindah_tag(-1)
    assert [t["nama"] for t in w.daftar_tag] == ["A", "B"]


def test_ekspor_lalu_impor_tag_csv(jendela, monkeypatch, tmp_path):
    w = jendela
    _tambah(w, "Suhu", 10)
    _tambah(w, "Tekanan", 20)
    jalur = str(tmp_path / "tag.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (jalur, "")))
    w.ekspor_tag_csv()
    baris = list(csv.DictReader(open(jalur, encoding="utf-8")))
    assert [b["nama"] for b in baris] == ["Suhu", "Tekanan"]

    # tambahkan baris rusak ke CSV -> harus dilewati, sisanya diimpor
    with open(jalur, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["Rusak", "1", "TipeAneh", "5", DAFTAR_ENCODING[0], "1", "0"])
        csv.writer(f).writerow(["Baru", "2", "Input", "7", DAFTAR_ENCODING[2], "0.1", "0"])

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (jalur, "")))
    asli_tambah = QMessageBox.addButton

    def rekam_tombol(self, teks, peran):
        tombol = asli_tambah(self, teks, peran)
        self.__dict__.setdefault("_rek", {})[teks] = tombol
        return tombol

    monkeypatch.setattr(QMessageBox, "addButton", rekam_tombol)
    monkeypatch.setattr(QMessageBox, "exec_", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: self._rek["Ganti Semua"])
    w.impor_tag_csv()
    assert [t["nama"] for t in w.daftar_tag] == ["Suhu", "Tekanan", "Baru"]
    assert w.daftar_tag[2]["tipe_reg"] == "Input" and w.daftar_tag[2]["skala"] == 0.1


def test_tabel_reader_update_di_tempat_dan_keterangan_tetap(jendela):
    w = jendela
    alamat = list(range(10))
    w.perbarui_tabel_reader(alamat, [str(i) for i in range(10)], "Mentah (16-bit UINT)", "Holding", 1)
    struktur = w._reader_struktur_terakhir
    item_awal = w.tabel_reader_output.item(0, 1)
    w.tabel_reader_output.item(0, 3).setText("catatan saya")

    w.perbarui_tabel_reader(alamat, [str(i + 5) for i in range(10)], "Mentah (16-bit UINT)", "Holding", 1)
    assert w._reader_struktur_terakhir == struktur
    assert w.tabel_reader_output.item(0, 1) is item_awal          # item dipakai ulang, tidak dibuat ulang
    assert w.tabel_reader_output.item(0, 1).text() == "5"
    assert w.tabel_reader_output.item(0, 3).text() == "catatan saya"
    assert w.memori_keterangan_user.get("1_Holding_0") == "catatan saya"

    # ubah spinbox selama polling TIDAK boleh membelokkan kunci keterangan
    w.spin_read_slave.setValue(99)
    w.tabel_reader_output.item(1, 3).setText("baris dua")
    assert w.memori_keterangan_user.get("1_Holding_1") == "baris dua"


def test_decode_gabungan_mengikuti_jumlah_word(jendela):
    w = jendela
    w.perbarui_tabel_reader(list(range(4)), ["0x0", "0", "0", "0"], "Mentah (16-bit UINT)", "Holding", 1) \
        if False else None
    enc = "64-bit DOUBLE (ABCDEFGH - Big Endian)"
    from modbus_app.inti import enkode_nilai_ke_register
    reg = enkode_nilai_ke_register("1.5", enc)
    w.perbarui_tabel_reader(list(range(4)), [str(r) for r in reg], enc, "Holding", 1)
    assert w.tabel_reader_output.item(0, 2).text() == "1.500000"
    assert w.tabel_reader_output.item(1, 2).text() == "-"


def test_log_dibatasi(jendela):
    for i in range(650):
        jendela._log_dibatasi(jendela.txt_tag_monitor, f"baris {i}", batas_baris=500)
    assert jendela.txt_tag_monitor.document().blockCount() == 500
    assert "baris 649" in jendela.txt_tag_monitor.toPlainText()


def test_filter_tabel(jendela):
    w = jendela
    w.tampilkan_hasil_scan_register([(i, str(i), "-") for i in range(100)])
    w._filter_baris_tabel(w.tabel_hasil_register, "99")
    tampak = [r for r in range(100) if not w.tabel_hasil_register.isRowHidden(r)]
    assert tampak == [99]
    w._filter_baris_tabel(w.tabel_hasil_register, "")
    assert not any(w.tabel_hasil_register.isRowHidden(r) for r in range(100))


def test_hasil_scan_bulk(jendela):
    jendela.tampilkan_hasil_scan_id([(i, "MERESPON") for i in range(1, 256)])
    assert jendela.tabel_hasil_id.rowCount() == 255


def test_simpan_otomatis_dan_muat_kembali(qapp):
    w1 = ModbusApp()
    w1.spin_read_addr.setValue(1234)
    w1.spin_timeout.setValue(2.5)
    w1.spin_retries.setValue(1)
    w1.spin_write_slave.setValue(200)
    w1.txt_tag_nama.setText("Tersimpan")
    w1.tambah_tag()
    w1.aksi_mode_gelap.setChecked(True)
    w1.close()                                   # closeEvent -> simpan otomatis

    import os
    assert os.path.exists(FILE_JOB_PRESET) and os.path.exists(FILE_PRESET)

    w2 = ModbusApp()
    try:
        assert w2.spin_read_addr.value() == 1234
        assert w2.spin_timeout.value() == 2.5 and w2.spin_retries.value() == 1
        assert w2.spin_write_slave.value() == 200
        assert [t["nama"] for t in w2.daftar_tag] == ["Tersimpan"]
        assert w2.mode_gelap is True
    finally:
        w2.aksi_mode_gelap.setChecked(False)
        w2.daftar_tag = []
        w2.close()


def test_preset_rusak_tidak_membuat_aplikasi_gagal(qapp):
    with open(FILE_JOB_PRESET, "w") as f:
        f.write("{ bukan json")
    w = ModbusApp()                               # tidak boleh melempar exception
    try:
        assert w.spin_read_slave.value() >= 0
    finally:
        import os
        w.close()
        os.remove(FILE_JOB_PRESET)


def test_indikator_tanpa_koneksi(jendela):
    jendela._perbarui_indikator_koneksi()
    assert "OFFLINE" in jendela.lbl_indikator.text()
