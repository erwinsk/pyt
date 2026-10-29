# -*- coding: utf-8 -*-
"""Uji GUI offscreen tab 'Atur Halaman': operasi halaman, undo, drag & drop, simpan/pisah, batal, sandi, tata letak."""
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt5.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt5.QtGui import QDropEvent
from PyQt5.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

from core import arranger as A
from core.pdfcompat import fitz

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def make_pdf(path, labels, size=(200, 300)):
    doc = fitz.open()
    for lab in labels:
        p = doc.new_page(width=size[0], height=size[1])
        p.insert_text((20, 60), lab, fontsize=24)
    doc.save(str(path))
    doc.close()
    return str(path)


def texts(path):
    with fitz.open(path) as d:
        return [p.get_text().strip() for p in d]


@pytest.fixture()
def arr(qapp, workspace, monkeypatch):
    msgs = {"information": [], "warning": [], "question": []}
    monkeypatch.setattr(QMessageBox, "information", staticmethod(
        lambda *a, **k: msgs["information"].append((a[1], a[2])) or QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(
        lambda *a, **k: msgs["warning"].append((a[1], a[2])) or QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: msgs["question"].append((a[1], a[2])) or QMessageBox.Yes))
    from app_context import AppContext
    from main import PDFToolsSuite
    w = PDFToolsSuite(AppContext())
    w.show()
    w.tabs.setCurrentWidget(w.arranger)
    tmp = workspace["tmp"]
    a = make_pdf(tmp / "a.pdf", ["A1", "A2", "A3"])
    b = make_pdf(tmp / "b.pdf", ["B1", "B2"], size=(300, 200))
    yield SimpleNamespace(window=w, tab=w.arranger, msgs=msgs, tmp=tmp, a=a, b=b)
    w.arranger.shutdown()
    w.close()


def wait_job(tab, qapp, timeout=60):
    t0 = time.time()
    while tab.is_busy() and time.time() - t0 < timeout:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()
    assert not tab.is_busy(), "job tidak selesai tepat waktu"


def select(tab, *rows):
    tab.list.clearSelection()
    for r in rows:
        tab.list.item(r).setSelected(True)


def order(tab):
    """['A1', 'A2', ...] label halaman sesuai urutan daftar (dari nama sumber + nomor halaman)."""
    out = []
    for ref in tab._ordered():
        out.append("blank" if ref.src is None else "%s%d" % (tab.sources[ref.src].name[0].upper(), ref.index + 1))
    return out


# ------------------------------------------------------------------------------------------ dasar
def test_tab_registered_in_main_window(arr):
    names = [arr.window.tabs.tabText(i) for i in range(arr.window.tabs.count())]
    assert "Atur Halaman" in names and arr.window.tabs.widget(names.index("Atur Halaman")) is arr.tab


def test_add_pdfs_and_image_builds_list_with_thumbnails(arr, qapp):
    from PIL import Image
    img = arr.tmp / "foto.png"
    Image.new("RGB", (900, 600), (10, 120, 200)).save(img)
    t = arr.tab
    assert t.add_paths([arr.a, arr.b, str(img)]) == 3
    assert t.list.count() == 6 and order(t) == ["A1", "A2", "A3", "B1", "B2", "F1"]
    assert t.lbl_count.text() == "6 halaman"
    t.wait_thumbs()
    assert len(t.thumbs) == 6
    assert all(not t.list.item(r).icon().isNull() for r in range(6))
    ref_img = t._ordered()[5]                                  # gambar: A4 lanskap mengikuti bentuk gambar
    assert ref_img.size == (A.A4[1], A.A4[0])


def test_image_import_options(arr):
    from PIL import Image
    img = arr.tmp / "p.png"
    Image.new("RGB", (400, 800), (200, 10, 10)).save(img)
    t = arr.tab
    t.combo_img.setCurrentIndex(t.combo_img.findData(None))
    t.add_paths([str(img)])
    assert t._ordered()[0].size is None
    t.combo_img.setCurrentIndex(t.combo_img.findData("Letter"))
    t.spin_img_margin.setValue(10)
    t.add_paths([str(img)])
    r = t._ordered()[1]
    assert r.size == (612.0, 792.0) and abs(r.margin - 10 * A.MM) < 0.01


def test_unsupported_and_corrupt_files_are_skipped_with_log(arr):
    t = arr.tab
    (arr.tmp / "x.txt").write_text("hi")
    (arr.tmp / "bad.pdf").write_bytes(b"nope")
    assert t.add_paths([str(arr.tmp / "x.txt"), str(arr.tmp / "bad.pdf")]) == 0
    log = t.console.toPlainText()
    assert "Dilewati" in log and "Gagal" in log and t.list.count() == 0


def test_password_protected_pdf_prompt_flow(arr, monkeypatch):
    enc = str(arr.tmp / "enc.pdf")
    with fitz.open(arr.a) as d:
        d.save(enc, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    t = arr.tab
    answers = iter([("salah", True), ("pw", True)])
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: next(answers)))
    assert t.add_paths([enc]) == 1 and t.list.count() == 3
    # dibatalkan -> dilewati
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
    assert t.add_paths([enc]) == 0 and t.list.count() == 3 and "sandi tidak diberikan" in t.console.toPlainText()


# --------------------------------------------------------------------------------- operasi + undo
def test_rotate_only_selected_and_undo_redo(arr):
    t = arr.tab
    t.add_paths([arr.a])
    t.rotate(90)                                              # tanpa pilihan: tidak melakukan apa pun
    assert [r.rotation for r in t._ordered()] == [0, 0, 0] and "Pilih halaman" in t.lbl_status.full_text()
    select(t, 0, 2)
    t.rotate(90)
    t.rotate(90)
    assert [r.rotation for r in t._ordered()] == [180, 0, 180]
    assert "180°" in t.list.item(0).text()
    t.rotate(-90)
    assert [r.rotation for r in t._ordered()] == [90, 0, 90]
    t.undo()
    assert [r.rotation for r in t._ordered()] == [180, 0, 180]
    t.undo()
    t.undo()
    assert [r.rotation for r in t._ordered()] == [0, 0, 0]
    t.redo()
    assert [r.rotation for r in t._ordered()] == [90, 0, 90]


def test_delete_duplicate_and_undo(arr):
    t = arr.tab
    t.add_paths([arr.a, arr.b])
    select(t, 1, 3)
    t.delete_selected()
    assert order(t) == ["A1", "A3", "B2"]
    t.undo()
    assert order(t) == ["A1", "A2", "A3", "B1", "B2"]
    select(t, 0, 4)
    t.duplicate()
    assert order(t) == ["A1", "A1", "A2", "A3", "B1", "B2", "B2"]
    assert [r for r in t.list.selected_rows()] == [1, 6]      # salinan yang terpilih
    t.undo()
    assert t.list.count() == 5


def test_shift_move_and_reverse(arr):
    t = arr.tab
    t.add_paths([arr.a, arr.b])
    select(t, 2)
    t.shift(-1)
    assert order(t) == ["A1", "A3", "A2", "B1", "B2"] and t.list.selected_rows() == [1]
    select(t, 0, 1)
    t.shift(-1)                                               # sudah di tepi kiri: tidak berubah & tidak masuk undo
    assert order(t) == ["A1", "A3", "A2", "B1", "B2"]
    n_undo = len(t._undo)
    t.shift(-1)
    assert len(t._undo) == n_undo
    select(t, 0, 2)
    t.shift(1)                                                # blok non-kontigu bergeser masing-masing
    assert order(t) == ["A3", "A1", "B1", "A2", "B2"]
    select(t, 0)
    t.move_edge(False)
    assert order(t) == ["A1", "B1", "A2", "B2", "A3"]
    select(t, 4)
    t.move_edge(True)
    assert order(t) == ["A3", "A1", "B1", "A2", "B2"]
    t.reverse_all()
    assert order(t) == ["B2", "A2", "B1", "A1", "A3"]
    t.undo()
    assert order(t) == ["A3", "A1", "B1", "A2", "B2"]


@pytest.mark.parametrize("sel,target,expected", [
    ([0], 3, ["B", "C", "A", "D", "E"]),
    ([4], 0, ["E", "A", "B", "C", "D"]),
    ([1, 3], 5, ["A", "C", "E", "B", "D"]),
    ([1, 3], 0, ["B", "D", "A", "C", "E"]),
    ([2], 2, None), ([2], 3, None),                            # menjatuhkan di tempat sendiri = tidak berubah
])
def test_move_selected_to_semantics(arr, sel, target, expected):
    t = arr.tab
    make_pdf(arr.tmp / "m.pdf", list("ABCDE"))
    t.add_paths([str(arr.tmp / "m.pdf")])
    select(t, *sel)
    labels = lambda: ["ABCDE"[r.index] for r in t._ordered()]
    changed = t.list.move_selected_to(target)
    assert changed == (expected is not None)
    assert labels() == (expected or list("ABCDE"))


def test_drop_row_from_cursor_position_and_undo_via_signals(arr, qapp):
    t = arr.tab
    arr.window.resize(1100, 700)
    t.add_paths([arr.a, arr.b])
    qapp.processEvents()
    rect = lambda r: t.list.visualItemRect(t.list.item(r))
    c = rect(2).center()
    left, right = type(c)(rect(2).left() + 5, c.y()), type(c)(rect(2).right() - 5, c.y())
    assert t.list._drop_row(left) == 2 and t.list._drop_row(right) == 3
    end = rect(t.list.count() - 1)
    assert t.list._drop_row(type(c)(end.right() - 3, end.center().y())) == t.list.count()
    assert t.list._drop_row(type(c)(5, rect(0).top() - 2)) == 0
    # urutan lengkap seperti saat drop: sinyal -> pindah -> sinyal; undo mengembalikan
    select(t, 4)
    t.list.about_to_reorder.emit()
    t.list.move_selected_to(0)
    t.list.reordered.emit()
    assert order(t) == ["B2", "A1", "A2", "A3", "B1"]
    t.undo()
    assert order(t) == ["A1", "A2", "A3", "B1", "B2"]


def test_external_file_drop_adds_pages(arr, qapp):
    t = arr.tab
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(arr.a)])
    ev = QDropEvent(QPointF(10, 10), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    t.list.dropEvent(ev)
    assert order(t) == ["A1", "A2", "A3"]


def test_insert_blank_and_reset(arr):
    t = arr.tab
    t.add_paths([arr.b])
    select(t, 0)
    t.insert_blank()
    assert order(t) == ["B1", "blank", "B2"]
    assert t._ordered()[1].display_size() == (300, 200)       # ukuran mengikuti halaman sebelumnya
    select(t, 0)
    t.rotate(90)
    assert t._ordered()[0].rotation == 90
    t.reset_selected()
    assert t._ordered()[0].rotation == 0 and t._ordered()[0].size is None


def test_resize_dialog_applies_to_scope(arr, monkeypatch):
    from widgets.arranger_dialogs import PageSizeDialog

    def fake_exec(self):
        self.combo_preset.setCurrentIndex(self.combo_preset.findData("Letter"))
        self.spin_margin.setValue(5)
        return QDialog.Accepted
    monkeypatch.setattr(PageSizeDialog, "exec_", fake_exec)
    t = arr.tab
    t.add_paths([arr.a, arr.b])
    select(t, 3, 4)                                           # B (lanskap)
    t.resize_dialog()
    refs = t._ordered()
    assert [r.size for r in refs[:3]] == [None] * 3
    assert refs[3].size == (792.0, 612.0) and abs(refs[3].margin - 5 * A.MM) < 0.01     # otomatis lanskap
    assert "Letter" in t.list.item(3).text()
    t.undo()
    assert [r.size for r in t._ordered()] == [None] * 5


def test_resize_dialog_values_and_restore(arr):
    from widgets.arranger_dialogs import PageSizeDialog
    d = PageSizeDialog(None, 2, 5)
    d.combo_preset.setCurrentIndex(d.combo_preset.findData("custom"))
    d.spin_w.setValue(100)
    d.spin_h.setValue(150)
    d.combo_fit.setCurrentIndex(1)
    v = d.values()
    assert abs(v["size"][0] - 100 * A.MM) < 0.01 and v["fit"] == "stretch" and v["scope"] == "selected"
    d.combo_preset.setCurrentIndex(d.combo_preset.findData(None))
    assert d.values()["size"] is None and not d.combo_orient.isEnabled()
    d2 = PageSizeDialog(None, 0, 5)
    assert not d2.rb_sel.isEnabled() and d2.values()["scope"] == "all"


def test_preview_dialog_and_zoom(arr, qapp):
    from widgets.arranger_dialogs import PreviewDialog
    t = arr.tab
    t.add_paths([arr.a, arr.b])
    select(t, 1)
    t.rotate(90)
    dlg = PreviewDialog(t, t._snapshot(), dict(t.sources), 1)
    assert dlg.windowTitle() == "Halaman 2 dari 5" and not dlg.lbl.pixmap().isNull()
    assert dlg.lbl.pixmap().width() > dlg.lbl.pixmap().height()        # halaman 2 diputar -> lanskap
    dlg.go(1)
    assert dlg.windowTitle() == "Halaman 3 dari 5"
    t.slider.setValue(100)
    t._apply_zoom()
    assert t.list.thumb_side() == 100 and t.list.iconSize().width() == 100


# ------------------------------------------------------------------------------- simpan / pisah
def test_save_merged_pdf_end_to_end(arr, qapp):
    from PIL import Image
    img = arr.tmp / "foto.png"
    Image.new("RGB", (800, 400), (30, 160, 60)).save(img)
    t = arr.tab
    t.add_paths([arr.a, arr.b, str(img)])
    t.wait_thumbs()
    select(t, 0)
    t.rotate(90)
    t.list.clearSelection()
    select(t, 4)
    t.move_edge(True)                                        # B2 ke depan
    out = arr.tmp / "hasil" / "gabung.pdf"
    t.edit_out.setText(str(out))
    t.save_pdf()
    assert t.is_busy() and not t.list.isEnabled() and t.btn_cancel.isEnabled()
    t.rotate(90)                                             # saat sibuk: diabaikan
    wait_job(t, qapp)
    assert t.list.isEnabled() and t.pbar.value() == 100
    assert texts(str(out))[:5] == ["B2", "A1", "A2", "A3", "B1"]
    with fitz.open(out) as d:
        assert d.page_count == 6 and d[1].rotation == 90 and len(d[5].get_images()) == 1
        assert (round(d[5].rect.width), round(d[5].rect.height)) == (842, 595)
    assert arr.msgs["information"] and t.btn_open.isEnabled()
    assert "Tersimpan" in t.console.toPlainText()
    assert not [f for f in os.listdir(out.parent) if f.startswith(".arr_")]


def test_save_selected_only_and_adds_pdf_extension(arr, qapp):
    t = arr.tab
    t.add_paths([arr.a])
    select(t, 0, 2)
    t.chk_sel.setChecked(True)
    t.edit_out.setText(str(arr.tmp / "sebagian"))
    t.save_pdf()
    wait_job(t, qapp)
    assert texts(str(arr.tmp / "sebagian.pdf")) == ["A1", "A3"]
    t.list.clearSelection()
    t.edit_out.setText(str(arr.tmp / "x.pdf"))
    t.save_pdf()                                             # tidak ada yang terpilih
    assert not t.is_busy() and not (arr.tmp / "x.pdf").exists() and "Tidak ada halaman terpilih" in t.lbl_status.full_text()


def test_save_dialog_used_when_path_empty_and_overwrite_confirmed(arr, qapp, monkeypatch):
    t = arr.tab
    t.add_paths([arr.a])
    target = arr.tmp / "dari_dialog.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    t.save_pdf()
    wait_job(t, qapp)
    assert target.exists() and t.edit_out.text() == str(target)
    target.write_bytes(b"OLD")
    arr.msgs["question"].clear()
    t.save_pdf()                                             # path diketik -> tanya timpa (stub menjawab Yes)
    wait_job(t, qapp)
    assert arr.msgs["question"] and texts(str(target)) == ["A1", "A2", "A3"]


def test_refuses_to_overwrite_a_source_file(arr, qapp):
    t = arr.tab
    t.add_paths([arr.a])
    before = Path(arr.a).read_bytes()
    t.edit_out.setText(arr.a)
    t.save_pdf()
    assert not t.is_busy() and arr.msgs["warning"] and Path(arr.a).read_bytes() == before


@pytest.mark.parametrize("mode,kw,expected", [
    ("each", {}, [["A1"], ["A2"], ["A3"], ["B1"], ["B2"]]),
    ("every", {"n": 2}, [["A1", "A2"], ["A3", "B1"], ["B2"]]),
    ("ranges", {"ranges": "1-2, 5"}, [["A1", "A2"], ["B2"]]),
    ("source", {}, [["A1", "A2", "A3"], ["B1", "B2"]]),
])
def test_split_modes_end_to_end(arr, qapp, mode, kw, expected):
    t = arr.tab
    t.add_paths([arr.a, arr.b])
    t.combo_mode.setCurrentIndex(t.combo_mode.findData(mode))
    t.spin_n.setValue(kw.get("n", 2))
    t.edit_ranges.setText(kw.get("ranges", ""))
    out = arr.tmp / "split"
    t.edit_dir.setText(str(out))
    t.split_pages()
    wait_job(t, qapp)
    files = sorted(out.glob("*.pdf"))
    assert [texts(str(f)) for f in files] == expected
    assert all(f.name.startswith("a_") for f in files)        # {nama} = sumber pertama
    assert "file dibuat" in t.lbl_status.full_text() or len(files) == 1


def test_split_default_folder_template_and_never_overwrites(arr, qapp):
    t = arr.tab
    t.add_paths([arr.a])
    t.edit_tpl.setText("bagian_{awal}-{akhir}")
    t.combo_mode.setCurrentIndex(t.combo_mode.findData("every"))
    t.spin_n.setValue(2)
    t.split_pages()                                           # folder kosong = folder sumber
    wait_job(t, qapp)
    assert (arr.tmp / "bagian_1-2.pdf").exists() and (arr.tmp / "bagian_3-3.pdf").exists()
    t.split_pages()                                           # kedua kali: tidak menimpa
    wait_job(t, qapp)
    assert (arr.tmp / "bagian_1-2_2.pdf").exists() and texts(str(arr.tmp / "bagian_1-2.pdf")) == ["A1", "A2"]


def test_split_invalid_input_shows_warning_and_creates_nothing(arr):
    t = arr.tab
    t.add_paths([arr.a])
    t.combo_mode.setCurrentIndex(t.combo_mode.findData("ranges"))
    t.edit_ranges.setText("1-99")
    t.edit_dir.setText(str(arr.tmp / "none"))
    t.split_pages()
    assert arr.msgs["warning"] and not t.is_busy() and not (arr.tmp / "none").exists()
    arr.msgs["warning"].clear()
    t.combo_mode.setCurrentIndex(t.combo_mode.findData("each"))
    t.edit_tpl.setText("{salah}")
    t.split_pages()
    assert arr.msgs["warning"] and not t.is_busy()


def test_cancel_job_leaves_no_files_and_unlocks(arr, qapp, monkeypatch):
    t = arr.tab
    make_pdf(arr.tmp / "big.pdf", ["P"] * 120)
    t.add_paths([str(arr.tmp / "big.pdf")])
    orig = A._emit_page
    monkeypatch.setattr(A, "_emit_page", lambda *a, **k: (time.sleep(0.02), orig(*a, **k))[1])
    out = arr.tmp / "cancel"
    t.edit_dir.setText(str(out))
    t.combo_mode.setCurrentIndex(t.combo_mode.findData("every"))
    t.spin_n.setValue(40)
    t.split_pages()
    time.sleep(0.15)
    t.cancel_job()
    wait_job(t, qapp)
    assert t.list.isEnabled() and "Dibatalkan" in t.lbl_status.full_text()
    assert not list(out.glob("*")) and t.pbar.value() == 0


def test_failed_job_reports_error_and_opens_log(arr, qapp, monkeypatch):
    t = arr.tab
    t.add_paths([arr.a])
    Path(arr.a).unlink()                                      # sumber hilang sebelum disimpan
    t.edit_out.setText(str(arr.tmp / "g.pdf"))
    t.save_pdf()
    wait_job(t, qapp)
    assert arr.msgs["warning"] and t.drawer.is_open() and t.list.isEnabled()
    assert not (arr.tmp / "g.pdf").exists() and "GAGAL" in t.console.toPlainText()


# ------------------------------------------------------------------------------ tata letak & tutup
def _overlaps(widgets):
    rects = []
    for w in widgets:
        if w.isVisible():
            tl = w.mapTo(w.window(), w.rect().topLeft())
            rects.append((w, tl.x(), tl.y(), w.width(), w.height()))
    bad = []
    for i, (w1, x1, y1, a1, b1) in enumerate(rects):
        for (w2, x2, y2, a2, b2) in rects[i + 1:]:
            if x1 < x2 + a2 - 1 and x2 < x1 + a1 - 1 and y1 < y2 + b2 - 1 and y2 < y1 + b1 - 1:
                bad.append((w1.objectName() or type(w1).__name__, w2.objectName() or type(w2).__name__))
    return bad


@pytest.mark.parametrize("size", [(1000, 600), (1100, 680), (1366, 700)])
def test_layout_no_overlap_and_toolbar_buttons_not_squeezed(arr, qapp, size):
    import theme
    theme.apply(qapp)                                         # QSS sungguhan memengaruhi lebar tombol
    try:
        w, t = arr.window, arr.tab
        w.resize(*size)
        t.add_paths([arr.a, arr.b])
        for _ in range(6):
            qapp.processEvents()
        assert _overlaps([t.toolbar, t.list, t.right_scroll, t.btn_open, t.pbar, t.lbl_status, t.btn_cancel, t.drawer]) == []
        body = t.right_scroll.widget()
        assert body.width() <= t.right_scroll.viewport().width() + 1
        assert t.right_scroll.horizontalScrollBar().maximum() == 0
        for b in t.toolbar.findChildren(type(t.btn_add)) + [t.btn_more]:
            assert b.width() >= b.sizeHint().width() - 1, "tombol '%s' menciut" % b.text()
        assert t.toolbar.layout().minimumSize().width() <= t.toolbar.width()
    finally:
        qapp.setStyleSheet("")


def test_closing_window_while_thumbnails_load_is_safe(qapp, workspace, monkeypatch):
    from app_context import AppContext
    from main import PDFToolsSuite
    tmp = workspace["tmp"]
    p = make_pdf(tmp / "many.pdf", ["P%d" % i for i in range(150)])
    w = PDFToolsSuite(AppContext())
    w.show()
    w.arranger.add_paths([p])
    w.close()                                                 # thread thumbnail masih berjalan
    assert all(not wk.isRunning() for wk in w.arranger._workers)
    assert w.arranger.list.count() == 0


def test_closing_window_with_running_job_asks_and_aborts(arr, qapp, monkeypatch):
    t = arr.tab
    make_pdf(arr.tmp / "big.pdf", ["P"] * 100)
    t.add_paths([str(arr.tmp / "big.pdf")])
    orig = A._emit_page
    monkeypatch.setattr(A, "_emit_page", lambda *a, **k: (time.sleep(0.02), orig(*a, **k))[1])
    t.edit_out.setText(str(arr.tmp / "z.pdf"))
    t.save_pdf()
    assert t.is_busy()
    arr.window.close()                                        # stub question -> Yes
    assert not t.is_busy() or not t._job.isRunning()
    assert not (arr.tmp / "z.pdf").exists()


# ------------------------------------------------------------------- regresi crash saat keluar
CHILD = r'''
import os, sys, tempfile, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, %(root)r)
tmp = tempfile.mkdtemp()
os.environ["PDFSUITE_WORKSPACE"] = tmp + "/ws"
os.environ["PDFSUITE_CONFIG"] = tmp + "/cfg"
from PyQt5.QtWidgets import QApplication
app = QApplication([])
import theme
theme.apply(app)
from app_context import AppContext
from main import PDFToolsSuite
w = PDFToolsSuite(AppContext())
w.show()
for _ in range(5):                  # beberapa putaran event loop dengan jeda: pemicu crash lama
    app.processEvents()
    time.sleep(0.02)
w.close()
'''


def test_app_exits_cleanly_with_theme_applied():
    """Regresi: filter event Python pada QApplication menyebabkan segfault ACAK saat keluar (±50%).
    Diulang beberapa kali agar kebetulan lolos sangat kecil kemungkinannya."""
    code = CHILD % {"root": str(ROOT)}
    env = dict(os.environ, XDG_RUNTIME_DIR=os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    for i in range(12):
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)
        assert r.returncode == 0, "run %d keluar dengan kode %s\n%s" % (i, r.returncode, r.stderr[-400:])


def test_theme_follows_palette_change_at_runtime(qapp):
    from PyQt5.QtGui import QColor, QPalette
    import theme
    old_pal, old_qss = QPalette(qapp.palette()), qapp.styleSheet()
    try:
        theme.apply(qapp)
        light = qapp.styleSheet()
        dark = QPalette(old_pal)
        dark.setColor(QPalette.Window, QColor(30, 30, 33))
        dark.setColor(QPalette.Base, QColor(22, 22, 25))
        dark.setColor(QPalette.Text, QColor(235, 235, 235))
        qapp.setPalette(dark)
        qapp.processEvents()
        assert qapp.styleSheet() != light and "#161619" in qapp.styleSheet().lower()
    finally:
        qapp.setPalette(old_pal)
        qapp.setStyleSheet(old_qss)
