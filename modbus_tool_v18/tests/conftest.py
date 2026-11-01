"""Fixture bersama: isolasi folder konfigurasi, Qt offscreen, dan server Modbus TCP uji."""
import os
import sys
import tempfile
import time

import pytest

# Isolasi: folder konfigurasi/log dialihkan ke direktori sementara SEBELUM modul aplikasi diimpor.
_TMP_HOME = tempfile.mkdtemp(prefix="modbus_uji_")
os.environ["HOME"] = _TMP_HOME
os.environ["APPDATA"] = _TMP_HOME
os.environ["XDG_CONFIG_HOME"] = _TMP_HOME
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def qapp():
    pytest.importorskip("PyQt5")
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def tunggu_sampai(kondisi, timeout=8.0, app=None):
    """Proses event Qt sampai kondisi() benar atau timeout (detik)."""
    from PyQt5.QtWidgets import QApplication
    app = app or QApplication.instance()
    batas = time.time() + timeout
    while time.time() < batas:
        if app is not None:
            app.processEvents()
        if kondisi():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def server_uji():
    from server_modbus import ServerModbusUji
    srv = ServerModbusUji(daftar_id=(1, 4)).start()
    yield srv
    srv.stop()


@pytest.fixture
def client_uji(server_uji):
    from modbus_app.inti import _buat_client_tcp
    client = _buat_client_tcp("127.0.0.1", server_uji.port, timeout=0.3, retries=3)
    assert client.connect()
    yield client
    client.close()


@pytest.fixture(autouse=True)
def bersihkan_preset():
    """Hapus file preset/simpan-otomatis sebelum & sesudah tiap tes agar tes saling terisolasi."""
    from modbus_app.konfigurasi import FILE_JOB_PRESET, FILE_PRESET

    def hapus():
        for jalur in (FILE_JOB_PRESET, FILE_PRESET):
            try:
                os.remove(jalur)
            except OSError:
                pass

    hapus()
    yield
    hapus()
