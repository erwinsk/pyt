# -*- coding: utf-8 -*-
"""Uji deteksi alat: instalasi pengguna (pip --user / pipx) yang tidak ada di PATH, alat yang
ditemukan tetapi gagal dijalankan, dan penjelasannya di tab Dependensi."""
import os
import stat
from pathlib import Path

import pytest
from PyQt5.QtCore import Qt

from core import deps
from core.engines import get_engine

posix_only = pytest.mark.skipif(os.name == "nt", reason="memakai skrip shell sebagai alat palsu")
SPEC = deps.SPEC_BY_ID["recode_pdf"]


def fake_tool(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / name
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


@pytest.fixture()
def world(tmp_path, monkeypatch):
    """Lingkungan bersih: PATH kosong, folder Python aplikasi kosong, satu folder instalasi pengguna."""
    empty, pybin, userbin = tmp_path / "emptybin", tmp_path / "pybin", tmp_path / "ub" / "bin"
    for d in (empty, pybin, userbin):
        d.mkdir(parents=True)
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setattr(deps.sys, "executable", str(pybin / "python"))
    monkeypatch.setattr(deps, "user_script_dirs", lambda: [userbin])
    return {"path": empty, "venv": pybin, "user": userbin}


# ------------------------------------------------------------- folder pengguna
def test_user_script_dirs_lists_userbase_and_local_bin(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(deps.site, "getuserbase", lambda: str(tmp_path / "base"))
    monkeypatch.setattr(deps.sysconfig, "get_path", lambda *a, **k: (_ for _ in ()).throw(KeyError("x")))
    dirs = deps.user_script_dirs()
    sub = "Scripts" if os.name == "nt" else "bin"
    assert tmp_path / "base" / sub in dirs
    assert tmp_path / "home" / ".local" / "bin" in dirs
    assert len(dirs) == len(set(dirs))                              # tanpa duplikat


@posix_only
def test_tool_only_in_user_dir_is_found(world):
    """Regresi: `pip install --user archive-pdf-tools` menaruh `recode_pdf` di ~/.local/bin; bila folder itu
    tidak ada di PATH (zsh, peluncur desktop) alat dilaporkan 'tidak ada' padahal terpasang."""
    fake_tool(world["user"], "recode_pdf", 'echo "internetarchivepdf 9.9"')
    assert deps.resolve(SPEC) == ([str(world["user"] / "recode_pdf")], "user")
    st = deps.detect_tool(SPEC)
    assert st.found and st.source == "user" and st.version == "internetarchivepdf 9.9" and not st.warn
    assert st.path == str(world["user"] / "recode_pdf") and st.searched == []


@posix_only
def test_search_order_custom_then_path_then_venv_then_user(world, tmp_path):
    user = fake_tool(world["user"], "recode_pdf", "echo user")
    assert deps.resolve(SPEC)[1] == "user"
    venv = fake_tool(world["venv"], "recode_pdf", "echo venv")
    assert deps.resolve(SPEC) == ([str(venv)], "venv")              # folder Python aplikasi mengalahkan user
    onpath = fake_tool(world["path"], "recode_pdf", "echo path")
    assert deps.resolve(SPEC) == ([str(onpath)], "path")            # PATH mengalahkan keduanya
    custom = fake_tool(tmp_path / "elsewhere", "mine", "echo custom")
    assert deps.resolve(SPEC, str(custom)) == ([str(custom)], "custom")
    assert user.exists()


@posix_only
def test_non_executable_file_in_user_dir_is_ignored(world):
    p = world["user"] / "recode_pdf"
    p.write_text("bukan executable")
    assert deps.resolve(SPEC) is None


def test_env_for_tools_includes_user_dir(world):
    st = deps.ToolStatus("recode_pdf", "r", found=True, cmd=[str(world["user"] / "recode_pdf")], source="user")
    env = deps.env_for_tools({"recode_pdf": st}, base={"PATH": "/usr/bin"})
    assert env["PATH"].split(os.pathsep)[0] == str(world["user"])


# ------------------------------------------------------- tidak ditemukan: di mana dicari
def test_not_found_explains_where_it_looked(world):
    st = deps.detect_tool(SPEC)
    assert not st.found
    text = deps.describe_status(st)
    assert text.startswith("Tidak ditemukan. Dicari di:") and "PATH" in text
    assert str(world["user"]) in text and "pip --user" in text and "Path kustom" in text
    # alat yang punya cadangan `python -m` menyebutkannya sebagai tempat pencarian; yang tidak punya, tidak
    assert any("python -m ocrmypdf" in p for p in deps.search_places(deps.SPEC_BY_ID["ocrmypdf"]))
    assert not any("python -m" in p for p in deps.search_places(SPEC))


# --------------------------------------------------- ditemukan tetapi gagal dijalankan
@posix_only
def test_python_crash_is_reported_as_warning_not_as_missing(world):
    fake_tool(world["user"], "recode_pdf",
              "echo 'Traceback (most recent call last):' >&2\n"
              "echo '  File \"x.py\", line 1, in <module>' >&2\n"
              "echo \"ModuleNotFoundError: No module named 'numpy'\" >&2\nexit 1")
    st = deps.detect_tool(SPEC)
    assert st.found and st.warn == "ModuleNotFoundError: No module named 'numpy'"
    assert st.version == ""
    text = deps.describe_status(st)
    assert "gagal dijalankan" in text and "numpy" in text and "--version" in text and st.path in text


@posix_only
def test_nonzero_exit_without_traceback_is_not_a_warning(world):
    """jbig2 menampilkan bantuan dengan kode keluar bukan-nol; itu bukan kegagalan."""
    fake_tool(world["user"], "recode_pdf", "echo 'usage: recode_pdf [options]' >&2\nexit 2")
    st = deps.detect_tool(SPEC)
    assert st.found and st.warn == "" and st.version.startswith("usage:")


@posix_only
def test_os_refusing_to_run_is_reported(world):
    fake_p = world["user"] / "recode_pdf"
    fake_p.write_text("#!/tidak/ada/interpreter\n")
    fake_p.chmod(0o755)
    st = deps.detect_tool(SPEC)
    assert st.found and st.warn                                      # mis. 'bad interpreter'


@posix_only
def test_with_version_false_never_runs_the_tool(world, tmp_path):
    marker = tmp_path / "ran"
    fake_tool(world["user"], "recode_pdf", f"touch {marker}")
    st = deps.detect_tool(SPEC, with_version=False)
    assert st.found and not marker.exists() and st.warn == ""


def test_crashing_tool_makes_engine_unavailable_with_the_reason():
    eng = get_engine("mrc")
    tools = {t: deps.ToolStatus(t, t, found=True, cmd=["/x/" + t], path="/x/" + t) for t in eng.required_tools}
    ok, missing = eng.availability(tools)
    assert ok and missing == []
    tools["recode_pdf"].warn = "ImportError: libfoo.so"
    ok, missing = eng.availability(tools)
    assert not ok and len(missing) == 1
    assert "recode_pdf" in missing[0] and "gagal dijalankan" in missing[0] and "libfoo" in missing[0]
    assert "/x/recode_pdf" in missing[0]


# ------------------------------------------------------------------- tab Dependensi
@pytest.fixture(scope="module")
def qapp():
    from PyQt5.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


@pytest.fixture()
def tab(qapp, workspace):
    from app_context import AppContext
    from main import PDFToolsSuite
    w = PDFToolsSuite(AppContext())
    w.show()
    yield SimpleTab(w)
    w.compressor.abort_and_wait()
    w.close()


class SimpleTab:
    def __init__(self, window):
        self.window = window
        self.deps = window.deps
        self.compressor = window.compressor
        self.ctx = window.compressor.ctx

    def select(self, tool_id):
        for r in range(self.deps.tbl_tools.rowCount()):
            if self.deps.tbl_tools.item(r, 0).data(Qt.UserRole) == tool_id:
                self.deps.tbl_tools.selectRow(r)
                return r
        raise AssertionError(tool_id)

    def row(self, r):
        return [self.deps.tbl_tools.item(r, c).text() for c in range(5)]


def test_tab_explains_a_missing_tool(tab):
    tab.ctx.tools["recode_pdf"] = deps.ToolStatus("recode_pdf", "r", searched=["PATH (3 folder)", "/home/x/.local/bin (pip --user)"])
    tab.deps.populate_tools()
    r = tab.select("recode_pdf")
    assert tab.row(r)[1] == "✗ tidak ada"
    t = tab.deps.lbl_detail.text()
    assert t.startswith("Tidak ditemukan. Dicari di:") and "/home/x/.local/bin" in t


def test_tab_shows_a_tool_found_in_the_user_dir(tab):
    tab.ctx.tools["recode_pdf"] = deps.ToolStatus("recode_pdf", "r", found=True, cmd=["/home/x/.local/bin/recode_pdf"],
                                                  path="/home/x/.local/bin/recode_pdf", version="internetarchivepdf 1.5.7",
                                                  source="user")
    tab.deps.populate_tools()
    r = tab.select("recode_pdf")
    row = tab.row(r)
    assert row[1] == "✓ ada" and row[2] == "internetarchivepdf 1.5.7" and row[3].endswith("recode_pdf")
    assert "tidak ada di PATH" in tab.deps.lbl_detail.text()


def test_tab_and_profiles_surface_a_crashing_tool(tab):
    tab.ctx.tools["recode_pdf"] = deps.ToolStatus("recode_pdf", "r", found=True, cmd=["/p/recode_pdf"], path="/p/recode_pdf",
                                                  source="user", warn="ModuleNotFoundError: No module named 'skimage'")
    tab.deps.populate_tools()
    r = tab.select("recode_pdf")
    row = tab.row(r)
    assert row[1] == "⚠ gagal jalan" and "skimage" in row[2]
    assert "gagal dijalankan" in tab.deps.lbl_detail.text() and "--version" in tab.deps.lbl_detail.text()
    # profil MRC ikut dinonaktifkan dan alasannya tampil di tooltip, bukan gagal di tengah proses
    c = tab.compressor
    c.on_tools_changed()
    i = c.combo_profile.findData("scan_seimbang")
    assert "butuh alat" in c.combo_profile.itemText(i)
    assert "gagal dijalankan" in c.combo_profile.itemData(i, Qt.ToolTipRole) and "skimage" in c.combo_profile.itemData(i, Qt.ToolTipRole)
