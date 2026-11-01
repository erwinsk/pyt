"""Uji ujung-ke-ujung memakai client pymodbus ASLI terhadap server Modbus TCP uji."""
import time

import pytest

pytest.importorskip("PyQt5")
pytest.importorskip("pymodbus")

from conftest import tunggu_sampai  # noqa: E402
from modbus_app import worker  # noqa: E402
from modbus_app.inti import enkode_nilai_ke_register, statistik_global  # noqa: E402
from modbus_app.worker import (ModbusPoolerLoggerThread, ModbusScannerThread,  # noqa: E402
                               ModbusWriteThread, TagListReaderThread)

F32 = "32-bit FLOAT (ABCD - Big Endian)"
U16 = "Mentah (16-bit UINT)"


def _tag(nama, alamat, enc=U16, slave=1, tipe="Holding", skala=1.0, offset=0.0):
    return {"nama": nama, "slave_id": slave, "tipe_reg": tipe, "alamat": alamat,
            "encoding": enc, "skala": skala, "offset": offset}


def _jalankan_tag(client, tags):
    keluaran = []
    th = TagListReaderThread(client, tags, single_shot=True)
    th.sinyal_hasil.connect(keluaran.append)
    th.run()                      # sinkron: langsung di thread uji
    return keluaran[-1] if keluaran else None


def test_tag_dibaca_per_blok_bukan_per_tag(server_uji, client_uji, monkeypatch):
    server_uji.isi_holding(1, 100, enkode_nilai_ke_register("3.5", F32) + [42])
    server_uji.isi_holding(1, 200, [50])
    server_uji.data[1]["co"][5] = True

    panggilan = []
    asli = worker.baca_register_modbus
    monkeypatch.setattr(worker, "baca_register_modbus",
                        lambda *a, **k: (panggilan.append(a[1:4]), asli(*a, **k))[1])

    hasil = _jalankan_tag(client_uji, [
        _tag("Float", 100, F32), _tag("Uint", 102), _tag("Skala", 200, skala=0.1, offset=1.0),
        _tag("Coil", 5, tipe="Coil"),
    ])
    assert [h["nama"] for h in hasil] == ["Float", "Uint", "Skala", "Coil"]     # urutan asli terjaga
    assert [h["nilai_akhir"] for h in hasil] == ["3.5000", "42.0000", "6.0000", "True"]
    assert all(h["status"] == "OK" for h in hasil)
    assert len(panggilan) == 3          # 4 tag -> hanya 3 request (HR 100-102 digabung)
    assert ("Holding", 100, 3) in panggilan


def test_blok_gagal_jatuh_ke_baca_satu_per_satu(server_uji, client_uji):
    server_uji.isi_holding(1, 298, [9])
    # float di 299 butuh register 299 & 300, padahal register hanya 0..299 -> blok 298-300 ditolak
    hasil = _jalankan_tag(client_uji, [_tag("Ok", 298), _tag("Rusak", 299, F32)])
    assert hasil[0]["status"] == "OK" and hasil[0]["nilai_akhir"] == "9.0000"
    assert hasil[1]["status"] == "ERROR" and "Illegal Data Address" in hasil[1]["nilai_akhir"]


def test_tag_slave_tak_menjawab_ditandai_error(server_uji, client_uji):
    client_uji.timeout = 0.2
    hasil = _jalankan_tag(client_uji, [_tag("Hilang", 1, slave=77)])
    assert hasil[0]["status"] == "ERROR"


def test_scan_id_cepat_dan_retries_dipulihkan(server_uji, client_uji):
    ditemukan, selesai = [], []
    th = ModbusScannerThread(client_uji, "id", {"id_awal": 1, "id_akhir": 6, "tipe_reg": "Holding", "reg_uji": 0})
    th.sinyal_hasil.connect(ditemukan.append)
    th.sinyal_selesai.connect(lambda: selesai.append(True))
    awal = time.time()
    th.run()
    lama = time.time() - awal
    assert [i for i, _ in ditemukan[0]] == [1, 4]
    assert selesai
    # 4 ID kosong x timeout 0.3s = ~1.2s. Dengan retry 3 akan >= 4.8s.
    assert lama < 3.0, f"scan terlalu lambat ({lama:.1f}s): retry tidak diturunkan?"
    assert client_uji.retries == 3      # nilai asli dipulihkan


def test_scan_register(server_uji, client_uji):
    server_uji.isi_holding(1, 10, enkode_nilai_ke_register("2.5", F32))
    hasil = []
    th = ModbusScannerThread(client_uji, "register", {"slave_id": 1, "tipe_reg": "Holding", "reg_awal": 10,
                                                      "reg_akhir": 12, "encoding": F32})
    th.sinyal_hasil.connect(hasil.append)
    th.run()
    baris = {r: (i, g) for r, i, g in hasil[0]}
    assert baris[10][1] == "2.5000"      # 10 & 11 digabung
    assert baris[11][1] == "0.0000" or baris[11][1] != "-"


def test_thread_tulis_fc16_float_dan_verifikasi(server_uji, client_uji, qapp):
    reg = enkode_nilai_ke_register("12.5", F32)
    log = []
    th = ModbusWriteThread(client_uji, {"jenis": "multi_reg", "alamat": 50, "device_id": 1,
                                        "register_final": reg, "verifikasi": True})
    th.sinyal_log.connect(log.append)
    th.run()
    assert server_uji.baca_holding(1, 50, 2) == reg
    teks = "\n".join(log)
    assert "Transmisi Sukses" in teks and "Verifikasi OK" in teks


def test_thread_tulis_coil_dan_mask(server_uji, client_uji):
    log = []
    th = ModbusWriteThread(client_uji, {"jenis": "multi_coil", "alamat": 8, "device_id": 1,
                                        "daftar_bool": [True, False, True], "verifikasi": True})
    th.sinyal_log.connect(log.append)
    th.run()
    assert server_uji.baca_coil(1, 8, 3) == [True, False, True]
    assert "Verifikasi OK" in "\n".join(log)

    server_uji.isi_holding(1, 20, [0x00F0])
    th2 = ModbusWriteThread(client_uji, {"jenis": "mask", "alamat": 20, "device_id": 1,
                                         "and_mask": 0xFF0F, "or_mask": 0x0005, "verifikasi": True})
    th2.sinyal_log.connect(log.append)
    th2.run()
    assert server_uji.baca_holding(1, 20, 1) == [(0x00F0 & 0xFF0F) | (0x0005 & ~0xFF0F & 0xFFFF)]


def test_thread_tulis_alamat_salah_dilaporkan_manusiawi(server_uji, client_uji):
    log = []
    th = ModbusWriteThread(client_uji, {"jenis": "single_reg", "alamat": 5000, "device_id": 1,
                                        "register_final": [1], "verifikasi": True})
    th.sinyal_log.connect(log.append)
    th.run()
    assert "Illegal Data Address" in "\n".join(log)


def test_statistik_bertambah(server_uji, client_uji):
    statistik_global.reset()
    _jalankan_tag(client_uji, [_tag("A", 1)])
    assert statistik_global.sukses >= 1


def test_polling_pulih_otomatis_setelah_koneksi_putus(server_uji, client_uji, qapp):
    server_uji.isi_holding(1, 0, [7, 8])
    params = {"slave_id": 1, "tipe_reg": "Holding", "reg_awal": 0, "jumlah": 2,
              "encoding": U16, "interval": 0.1}
    data, info = [], []
    th = ModbusPoolerLoggerThread(client_uji, params, "reader", auto_reconnect=True)
    th.sinyal_data.connect(lambda la, nm, enc, tab: data.append(nm))
    th.sinyal_info.connect(lambda pesan, tab: info.append(pesan))
    client_uji.close()                         # koneksi "putus"
    th.start()
    try:
        assert tunggu_sampai(lambda: len(data) >= 1, timeout=8)
        assert data[0] == ["7", "8"]
        assert any(p.startswith("Koneksi terputus") for p in info)
        assert any(p.startswith("Koneksi berhasil disambung kembali") for p in info)
    finally:
        th.apakah_berjalan = False
        th.wait(3000)


# ----------------------------- alur GUI penuh -----------------------------
@pytest.fixture
def jendela_terhubung(qapp, server_uji, client_uji):
    from modbus_app.jendela_utama import ModbusApp
    w = ModbusApp()
    w.client_global = client_uji
    w.chk_skip_confirm_write.setChecked(True)
    yield w
    w.client_global = None
    w.aksi_mode_gelap.setChecked(False)
    w.close()


def test_gui_fc06_dengan_format_float_ditolak(jendela_terhubung, server_uji):
    w = jendela_terhubung
    w.combo_write_type.setCurrentText("Write Single Register (FC 06)")
    w.combo_write_encoding.setCurrentText(F32)
    w.txt_write_payload.setText("3.14")
    w.spin_write_addr.setValue(60)
    w.eksekusi_penulisan_modbus()
    assert w.thread_tulis is None                       # tidak ada penulisan dimulai
    assert "FC 06" in w.txt_write_log.toPlainText() and "FC 16" in w.txt_write_log.toPlainText()
    assert server_uji.baca_holding(1, 60, 2) == [0, 0]  # perangkat tidak tersentuh


@pytest.mark.parametrize("teks", ["yes-no", "2", ""])
def test_gui_coil_tidak_dikenali_ditolak(jendela_terhubung, server_uji, teks):
    w = jendela_terhubung
    w.combo_write_type.setCurrentText("Write Single Coil (FC 05)")
    w.txt_write_payload.setText(teks)
    w.eksekusi_penulisan_modbus()
    assert w.thread_tulis is None and "Error Parsing" in w.txt_write_log.toPlainText()


def test_gui_mask_di_luar_rentang_ditolak(jendela_terhubung):
    w = jendela_terhubung
    w.combo_write_type.setCurrentText("Mask Write Register (FC 22)")
    w.txt_write_payload.setText("0x1FFFF,0")
    w.eksekusi_penulisan_modbus()
    assert w.thread_tulis is None and "rentang" in w.txt_write_log.toPlainText()


def test_gui_penulisan_di_thread_dan_ui_pulih(jendela_terhubung, server_uji):
    w = jendela_terhubung
    w.combo_write_type.setCurrentText("Write Multiple Registers (FC 16)")
    w.combo_write_encoding.setCurrentText(F32)
    w.txt_write_payload.setText("1.5, 2.5")
    w.spin_write_addr.setValue(70)
    w.eksekusi_penulisan_modbus()
    assert w.thread_tulis is not None
    assert tunggu_sampai(lambda: "Verifikasi OK" in w.txt_write_log.toPlainText())
    assert tunggu_sampai(lambda: w.btn_execute_write.isEnabled() and w.btn_toggle_pool.isEnabled())
    assert server_uji.baca_holding(1, 70, 4) == (enkode_nilai_ke_register("1.5", F32)
                                                  + enkode_nilai_ke_register("2.5", F32))


def test_gui_baca_tag_dan_kunci_edit(jendela_terhubung, server_uji):
    w = jendela_terhubung
    server_uji.isi_holding(1, 5, [11, 12])
    w.txt_tag_nama.setText("A"); w.spin_tag_addr.setValue(5); w.tambah_tag()
    w.txt_tag_nama.setText("B"); w.spin_tag_addr.setValue(6); w.tambah_tag()
    w.eksekusi_baca_tag(tunggal=True)
    assert tunggu_sampai(lambda: w.tabel_tag.item(1, 8) is not None and w.tabel_tag.item(1, 8).text() != "-")
    assert w.tabel_tag.item(0, 8).text() == "11.0000" and w.tabel_tag.item(1, 8).text() == "12.0000"
    assert tunggu_sampai(lambda: w.btn_tambah_tag.isEnabled())       # kunci edit dilepas setelah selesai


def test_gui_polling_berhenti_sendiri_mereset_tombol(jendela_terhubung, server_uji, client_uji):
    w = jendela_terhubung
    w.chk_auto_reconnect.setChecked(False)
    w.spin_pool_interval.setValue(0.1)
    w.spin_read_count.setValue(2)
    w.eksekusi_baca_reader(tunggal=False)
    assert w.btn_toggle_pool.text().startswith("■")
    assert not w.btn_toggle_logger.isEnabled()                       # operasi lain terkunci saat polling
    assert tunggu_sampai(lambda: w.tabel_reader_output.rowCount() == 2)

    client_uji.close()                                               # koneksi putus, auto-reconnect mati
    assert tunggu_sampai(lambda: w.btn_toggle_pool.text().startswith("▶"), timeout=8)
    assert w.btn_toggle_logger.isEnabled() and w.btn_single_read.isEnabled()
    assert "TERPUTUS" in w.lbl_indikator.text()


def test_gui_logger_mengunci_pengaturan_dan_menulis_csv(jendela_terhubung, server_uji, tmp_path):
    w = jendela_terhubung
    server_uji.isi_holding(1, 0, [1, 2, 3, 4])
    jalur = str(tmp_path / "log.csv")
    w.txt_csv_path.setText(jalur)
    w.spin_log_count.setValue(4)
    w.combo_log_encoding.setCurrentText(U16)
    w.spin_log_interval.setValue(0.1)
    w.toggle_logger()
    assert not w.spin_log_count.isEnabled() and not w.txt_csv_path.isEnabled()
    assert tunggu_sampai(lambda: len(open(jalur).read().splitlines()) >= 3)
    w.toggle_logger()                                                # hentikan
    assert tunggu_sampai(lambda: w.spin_log_count.isEnabled() and w.btn_toggle_logger.text().startswith("▶"))
    baris = open(jalur).read().splitlines()
    assert baris[0] == "Timestamp,Reg_0,Reg_1,Reg_2,Reg_3"
    assert baris[1].endswith("1,2,3,4")


def test_gui_logger_peringatan_jumlah_bukan_kelipatan(jendela_terhubung, server_uji, tmp_path):
    w = jendela_terhubung
    w.txt_csv_path.setText(str(tmp_path / "x.csv"))
    w.spin_log_count.setValue(5)
    w.combo_log_encoding.setCurrentText(F32)
    w.spin_log_interval.setValue(0.1)
    w.toggle_logger()
    assert "kelipatan 2" in w.txt_logger_monitor.toPlainText()
    w.toggle_logger()
    assert tunggu_sampai(lambda: w.btn_toggle_logger.text().startswith("▶"))
