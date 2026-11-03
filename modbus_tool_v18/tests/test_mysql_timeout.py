"""Regresi: server MySQL yang menerima TCP tetapi tidak menjawab tidak boleh membuat aplikasi macet."""
import socket
import threading
import time

import pytest

pymysql = pytest.importorskip("pymysql")

from modbus_app.inti import MySQLDataLogger  # noqa: E402


def test_connect_meneruskan_batas_waktu_ke_pymysql(monkeypatch):
    diterima = {}
    monkeypatch.setattr(pymysql, "connect", lambda **kw: diterima.update(kw) or object())
    MySQLDataLogger("h", 3306, "u", "p", "d", "t")._connect()
    assert diterima["connect_timeout"] == MySQLDataLogger.TIMEOUT_KONEKSI_DETIK
    assert diterima["read_timeout"] == MySQLDataLogger.TIMEOUT_BACA_TULIS_DETIK
    assert diterima["write_timeout"] == MySQLDataLogger.TIMEOUT_BACA_TULIS_DETIK


def test_batas_waktu_bisa_diatur_dan_bawaan_wajar():
    pencatat = MySQLDataLogger("h", 3306, "u", "p", "d", "t", timeout_koneksi=2, timeout_baca_tulis=3)
    assert (pencatat.timeout_koneksi, pencatat.timeout_baca_tulis) == (2, 3)
    bawaan = MySQLDataLogger("h", 3306, "u", "p", "d", "t")
    assert 0 < bawaan.timeout_koneksi <= 10 and 0 < bawaan.timeout_baca_tulis <= 30


def test_server_macet_menghasilkan_galat_bukan_menggantung():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    port = srv.getsockname()[1]
    tahan = []
    threading.Thread(target=lambda: [tahan.append(srv.accept()) for _ in range(3)], daemon=True).start()

    hasil = {}

    def coba():
        awal = time.time()
        try:
            MySQLDataLogger("127.0.0.1", port, "u", "p", "d", "t", timeout_baca_tulis=1).siapkan_tabel(["a"])
            hasil["galat"] = None
        except Exception as e:      # noqa: BLE001
            hasil["galat"] = e
        hasil["lama"] = time.time() - awal

    th = threading.Thread(target=coba, daemon=True)
    th.start()
    th.join(8)
    srv.close()
    assert not th.is_alive(), "siapkan_tabel menggantung pada server yang tidak menjawab"
    assert hasil["galat"] is not None and hasil["lama"] < 6
