"""Uji logika penandatanganan di build.py (signtool dipalsukan; tidak perlu Windows)."""
import os
import sys

import pytest

pytest.importorskip("PyInstaller")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build  # noqa: E402


@pytest.fixture
def folder_build(tmp_path):
    for nama in ["App.exe", "python312.dll", "Qt5Core.dll", "sip.pyd", "data.txt", "sub/QtGui.pyd"]:
        jalur = tmp_path / nama
        jalur.parent.mkdir(exist_ok=True)
        jalur.write_bytes(b"x")
    return tmp_path


def test_kumpulkan_pe_hanya_exe_dll_pyd(folder_build):
    nama = sorted(os.path.basename(p) for p in build.kumpulkan_pe(str(folder_build)))
    assert nama == ["App.exe", "Qt5Core.dll", "QtGui.pyd", "python312.dll", "sip.pyd"]


def test_hanya_berkas_belum_bertanda_tangan_yang_ditandatangani(folder_build, monkeypatch):
    berkas = build.kumpulkan_pe(str(folder_build))
    sudah = {b for b in berkas if os.path.basename(b) == "python312.dll"}   # milik penerbit lain
    ditandatangani, perintah_sign = set(sudah), []

    def fake_call(cmd, **kw):                      # signtool verify
        return 0 if cmd[-1] in ditandatangani else 1

    def fake_check_call(cmd, **kw):                # signtool sign
        perintah_sign.append(cmd)
        ditandatangani.update(cmd[cmd.index("/sha1") + 2:])

    monkeypatch.setattr(build, "ADALAH_WINDOWS", True)
    monkeypatch.setattr(build.subprocess, "call", fake_call)
    monkeypatch.setattr(build.subprocess, "check_call", fake_check_call)
    monkeypatch.setenv("SIGN_THUMBPRINT", "ABC123")

    assert build.tanda_tangani(berkas, ukuran_batch=2) is True
    disign = [b for cmd in perintah_sign for b in cmd[cmd.index("ABC123") + 1:]]
    assert sorted(os.path.basename(b) for b in disign) == ["App.exe", "Qt5Core.dll", "QtGui.pyd", "sip.pyd"]
    assert len(perintah_sign) == 2                                          # 4 berkas, batch 2
    assert all("/fd" in c and "/tr" in c and "/td" in c for c in perintah_sign)


def test_penandatanganan_dilewati_tanpa_sertifikat(monkeypatch):
    monkeypatch.delenv("SIGN_THUMBPRINT", raising=False)
    monkeypatch.delenv("SIGN_PFX", raising=False)
    assert build.tanda_tangani(["a.exe"]) is False


def test_gagal_dilaporkan_bila_masih_ada_yang_tak_bertanda_tangan(folder_build, monkeypatch):
    monkeypatch.setattr(build, "ADALAH_WINDOWS", True)
    monkeypatch.setattr(build.subprocess, "call", lambda *a, **k: 1)       # tak pernah sah
    monkeypatch.setattr(build.subprocess, "check_call", lambda *a, **k: 0)
    monkeypatch.setenv("SIGN_THUMBPRINT", "ABC123")
    assert build.tanda_tangani(build.kumpulkan_pe(str(folder_build))) is False


def test_buat_zip_membungkus_seluruh_folder_dengan_induk(tmp_path, monkeypatch):
    app = tmp_path / "dist" / build.NAMA_APP
    (app / "_internal").mkdir(parents=True)
    (app / f"{build.NAMA_APP}.exe").write_bytes(b"exe")
    (app / "_internal" / "lib.dll").write_bytes(b"dll")
    (tmp_path / "PETUNJUK_PENGGUNA.txt").write_text("petunjuk", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    jalur = build.buat_zip()
    assert os.path.basename(jalur).startswith(f"{build.NAMA_APP}_v{build.__version__}_")
    import zipfile
    nama = set(zipfile.ZipFile(jalur).namelist())
    assert f"{build.NAMA_APP}/{build.NAMA_APP}.exe" in nama
    assert f"{build.NAMA_APP}/_internal/lib.dll" in nama
    assert f"{build.NAMA_APP}/PETUNJUK_PENGGUNA.txt" in nama     # petunjuk ikut dibawa
    assert all(n.startswith(build.NAMA_APP + "/") for n in nama)  # satu folder induk


def test_buat_zip_gagal_jika_belum_build(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        build.buat_zip()
