"""Uji logging berpembatas dan penulisan JSON atomik."""
import json
import os

from modbus_app import konfigurasi as kfg


def test_catat_kesalahan_membatasi_error_berulang(monkeypatch):
    pesan = []
    monkeypatch.setattr(kfg.logger_aplikasi, "error", lambda m, *a, **k: pesan.append(m))
    kfg._status_error_terakhir.clear()
    for _ in range(5):
        kfg.catat_kesalahan("uji-konteks", RuntimeError("x"))
    assert len(pesan) == 1                      # 4 sisanya ditahan

    # simulasikan jeda terlewati -> dicatat lagi, beserta jumlah yang ditahan
    kunci = "uji-konteks|RuntimeError"
    waktu, tertahan = kfg._status_error_terakhir[kunci]
    assert tertahan == 4
    kfg._status_error_terakhir[kunci] = (waktu - kfg.JEDA_LOG_ERROR_SAMA_DETIK - 1, tertahan)
    kfg.catat_kesalahan("uji-konteks", RuntimeError("x"))
    assert len(pesan) == 2 and "4 kejadian serupa ditahan" in pesan[1]


def test_konteks_atau_jenis_berbeda_tetap_dicatat(monkeypatch):
    pesan = []
    monkeypatch.setattr(kfg.logger_aplikasi, "error", lambda m, *a, **k: pesan.append(m))
    kfg._status_error_terakhir.clear()
    kfg.catat_kesalahan("a", RuntimeError("x"))
    kfg.catat_kesalahan("b", RuntimeError("x"))
    kfg.catat_kesalahan("a", ValueError("x"))
    assert len(pesan) == 3


def test_logger_memakai_rotating_handler():
    from logging.handlers import RotatingFileHandler
    assert any(isinstance(h, RotatingFileHandler) for h in kfg.logger_aplikasi.handlers)


def test_tulis_json_atomik(tmp_path):
    jalur = str(tmp_path / "p.json")
    kfg.tulis_json_atomik(jalur, {"a": 1, "b": [1, 2]}, indent=2)
    assert json.load(open(jalur, encoding="utf-8")) == {"a": 1, "b": [1, 2]}
    assert not os.path.exists(jalur + ".tmp")
    kfg.tulis_json_atomik(jalur, {"a": 2})
    assert json.load(open(jalur, encoding="utf-8")) == {"a": 2}
