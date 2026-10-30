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
    img = t.list.viewport().grab().toImage()
    pix = [img.pixelColor(x, y) for y in range(0, img.height(), 2) for x in range(0, img.width(), 2)]
    assert sum(1 for c in pix if (c.red(), c.green(), c.blue()) == (160, 160, 160)) > 30      # bingkai halaman terlukis
    assert sum(1 for c in pix if max(c.red(), c.green(), c.blue()) < 90) > 5                   # isi halaman (teks) terlukis
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
    assert t.lbl_zoom.text() == "100%"
    t.zoom_step(-1)
    assert t.list.thumb_side() == 120 and t.list.iconSize().height() == 120 and t.lbl_zoom.text() == "86%"


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


# ====================================================================== seret-urut dengan event mouse
from PyQt5.QtCore import QEvent, QPoint
from PyQt5.QtGui import QKeyEvent, QMouseEvent, QWheelEvent


def mouse(lst, kind, pos, buttons=Qt.LeftButton, mods=Qt.NoModifier):
    btn = Qt.LeftButton if kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick) else Qt.NoButton
    QApplication.sendEvent(lst.viewport(), QMouseEvent(kind, QPoint(pos.x(), pos.y()), btn, buttons, mods))


def drag(tab, from_row, to_pos, steps=4, release=True, mods=Qt.NoModifier):
    """Tekan di tengah item `from_row`, gerakkan bertahap ke `to_pos`, (opsional) lepas."""
    lst = tab.list
    start = lst.visualItemRect(lst.item(from_row)).center()
    mouse(lst, QEvent.MouseButtonPress, start, mods=mods)
    for i in range(1, steps + 1):
        p = QPoint(start.x() + (to_pos.x() - start.x()) * i // steps, start.y() + (to_pos.y() - start.y()) * i // steps)
        mouse(lst, QEvent.MouseMove, p, mods=mods)
    if release:
        mouse(lst, QEvent.MouseButtonRelease, to_pos, mods=mods)
    return start


def left_of(tab, row):
    r = tab.list.visualItemRect(tab.list.item(row))
    return QPoint(r.left() + 4, r.center().y())


def right_of(tab, row):
    r = tab.list.visualItemRect(tab.list.item(row))
    return QPoint(r.right() - 4, r.center().y())


@pytest.fixture()
def shown(arr, qapp):
    arr.window.resize(1100, 700)
    arr.tab.add_paths([arr.a, arr.b])                # A1 A2 A3 B1 B2
    qapp.processEvents()
    return arr


def test_mouse_drag_single_item_reorders_and_undo_restores(shown, qapp):
    t = shown.tab
    drag(t, 4, left_of(t, 0))                         # B2 -> sebelum A1
    assert order(t) == ["B2", "A1", "A2", "A3", "B1"]
    assert t.list.selected_rows() == [0] and not t.list.is_dragging()
    t.undo()
    assert order(t) == ["A1", "A2", "A3", "B1", "B2"]
    t.redo()
    assert order(t) == ["B2", "A1", "A2", "A3", "B1"]


def test_mouse_drag_to_right_half_and_to_end(shown):
    t = shown.tab
    drag(t, 0, right_of(t, 2))                        # A1 -> sesudah A3
    assert order(t) == ["A2", "A3", "A1", "B1", "B2"]
    drag(t, 0, right_of(t, 4))                        # A2 -> paling akhir
    assert order(t) == ["A3", "A1", "B1", "B2", "A2"]


def test_mouse_drag_moves_whole_multi_selection(shown):
    t = shown.tab
    select(t, 0, 1)
    drag(t, 0, right_of(t, 4))                        # tekan item terpilih -> pilihan TIDAK runtuh, keduanya ikut
    assert order(t) == ["A3", "B1", "B2", "A1", "A2"]
    assert t.list.selected_rows() == [3, 4]
    select(t, 1, 3)                                   # non-kontigu: tetap berurutan relatif
    drag(t, 3, left_of(t, 0))
    assert order(t) == ["B1", "A1", "A3", "B2", "A2"]


def test_mouse_drag_shows_drop_line_and_cleans_up(shown, qapp):
    t = shown.tab
    drag(t, 0, left_of(t, 3), release=False)
    assert t.list.is_dragging() and t.list._drop_target == 3
    t.list.repaint()                                  # menggambar garis penanda tanpa galat
    mouse(t.list, QEvent.MouseButtonRelease, left_of(t, 3))
    assert not t.list.is_dragging() and t.list._drop_target is None and t.list._press_item is None


def test_mouse_drag_escape_cancels(shown):
    t = shown.tab
    drag(t, 4, left_of(t, 0), release=False)
    assert t.list.is_dragging()
    QApplication.sendEvent(t.list, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert not t.list.is_dragging()
    mouse(t.list, QEvent.MouseButtonRelease, left_of(t, 0))
    assert order(t) == ["A1", "A2", "A3", "B1", "B2"] and not t._undo[1:]      # tidak berubah


def test_tiny_movement_is_a_click_not_a_drag(shown):
    t = shown.tab
    select(t, 0, 1, 2)
    c = t.list.visualItemRect(t.list.item(1)).center()
    mouse(t.list, QEvent.MouseButtonPress, c)
    mouse(t.list, QEvent.MouseMove, QPoint(c.x() + 2, c.y()))
    mouse(t.list, QEvent.MouseButtonRelease, QPoint(c.x() + 2, c.y()))
    assert order(t) == ["A1", "A2", "A3", "B1", "B2"]
    assert t.list.selected_rows() == [1]                # klik pada item terpilih: pilihan mengerucut ke item itu


def test_click_selection_semantics_unchanged(shown):
    t = shown.tab
    c = lambda r: t.list.visualItemRect(t.list.item(r)).center()
    mouse(t.list, QEvent.MouseButtonPress, c(1)); mouse(t.list, QEvent.MouseButtonRelease, c(1))
    assert t.list.selected_rows() == [1]
    mouse(t.list, QEvent.MouseButtonPress, c(3), mods=Qt.ControlModifier)
    mouse(t.list, QEvent.MouseButtonRelease, c(3), mods=Qt.ControlModifier)
    assert t.list.selected_rows() == [1, 3]             # Ctrl+klik menambah
    mouse(t.list, QEvent.MouseButtonPress, c(0), mods=Qt.ShiftModifier)
    mouse(t.list, QEvent.MouseButtonRelease, c(0), mods=Qt.ShiftModifier)
    assert t.list.selected_rows() == [0, 1, 2, 3]       # Shift+klik: rentang dari item aktif
    # Ctrl+seret tidak mengurutkan ulang
    n_before = order(t)
    drag(t, 0, right_of(t, 4), mods=Qt.ControlModifier)
    assert order(t) == n_before


def test_double_click_opens_preview_even_on_selected_item(shown, monkeypatch):
    import tabs.arranger_tab as at
    opened = []
    monkeypatch.setattr(at.PreviewDialog, "exec_", lambda self: opened.append(self.i) or 0)   # dialog modal: jangan blokir tes
    t = shown.tab
    seen = []
    t.list.itemDoubleClicked.connect(lambda it: seen.append(t.list.row(it)))
    for pre_selected in (False, True):
        seen.clear()
        t.list.clearSelection()
        if pre_selected:
            select(t, 2)
        c = t.list.visualItemRect(t.list.item(2)).center()
        mouse(t.list, QEvent.MouseButtonPress, c)
        mouse(t.list, QEvent.MouseButtonRelease, c)
        mouse(t.list, QEvent.MouseButtonDblClick, c)
        mouse(t.list, QEvent.MouseButtonRelease, c)
        assert seen == [2], "pre_selected=%s" % pre_selected
        assert opened[-1] == 2                              # pratinjau benar-benar dibuka untuk halaman itu


def test_drag_autoscrolls_near_edges(arr, qapp):
    t = arr.tab
    arr.window.resize(1000, 600)
    make_pdf(arr.tmp / "many.pdf", ["P%d" % i for i in range(80)])
    t.add_paths([str(arr.tmp / "many.pdf")])
    qapp.processEvents()
    bar = t.list.verticalScrollBar()
    assert bar.maximum() > 0 and bar.value() == 0
    vp = t.list.viewport()
    start = t.list.visualItemRect(t.list.item(0)).center()
    mouse(t.list, QEvent.MouseButtonPress, start)
    mouse(t.list, QEvent.MouseMove, QPoint(start.x() + 40, start.y() + 40))
    mouse(t.list, QEvent.MouseMove, QPoint(start.x() + 40, vp.height() - 4))      # dekat tepi bawah
    assert t.list.is_dragging()
    before = bar.value()
    for _ in range(5):
        t.list._autoscroll_tick()
    assert bar.value() > before
    mouse(t.list, QEvent.MouseMove, QPoint(start.x() + 40, 3))                     # dekat tepi atas
    mid = bar.value()
    for _ in range(3):
        t.list._autoscroll_tick()
    assert bar.value() < mid
    mouse(t.list, QEvent.MouseButtonRelease, QPoint(start.x() + 40, 3))
    assert not t.list.is_dragging()


def test_drag_is_cancelled_when_list_gets_disabled(shown):
    t = shown.tab
    drag(t, 0, left_of(t, 3), release=False)
    assert t.list.is_dragging()
    t.list.setEnabled(False)                           # mis. pekerjaan simpan dimulai
    assert not t.list.is_dragging()
    t.list.setEnabled(True)


def test_right_click_and_empty_area_do_not_start_drag(shown):
    t = shown.tab
    c = t.list.visualItemRect(t.list.item(0)).center()
    QApplication.sendEvent(t.list.viewport(), QMouseEvent(QEvent.MouseButtonPress, QPoint(c.x(), c.y()), Qt.RightButton, Qt.RightButton, Qt.NoModifier))
    QApplication.sendEvent(t.list.viewport(), QMouseEvent(QEvent.MouseMove, QPoint(c.x() + 100, c.y()), Qt.NoButton, Qt.RightButton, Qt.NoModifier))
    assert not t.list.is_dragging()
    QApplication.sendEvent(t.list.viewport(), QMouseEvent(QEvent.MouseButtonRelease, QPoint(c.x() + 100, c.y()), Qt.RightButton, Qt.NoButton, Qt.NoModifier))
    assert order(t) == ["A1", "A2", "A3", "B1", "B2"]


# ====================================================================================== zoom + / −
def widest_cell_fits(t):
    return t.list.gridSize().width() + 2 * t.list.spacing() <= t.list.viewport().width()


@pytest.mark.parametrize("max_side,first,last", [(1000, 80, 1000), (300, 80, 300), (100, 80, 100), (60, 60, 60)])
def test_zoom_levels_function(max_side, first, last):
    from tabs.arranger_tab import zoom_levels
    lv = zoom_levels(max_side)
    assert lv[0] == first and lv[-1] == last and lv == sorted(set(lv))
    for a_, b_ in zip(lv, lv[1:]):
        assert b_ <= max(a_ * 1.3, a_ + 25) or b_ == last       # langkah wajar, tidak melompat jauh
    if max_side >= 240:
        assert {140, 240} <= set(lv)


def test_zoom_goes_beyond_old_limit_up_to_full_viewer_width(arr, qapp):
    """Dulu mentok 171% (240 px). Sekarang sampai halaman terlebar = lebar area tampilan, tidak lebih."""
    t = arr.tab
    arr.window.resize(1100, 700)
    t.add_paths([arr.a])                                        # hanya halaman potret
    qapp.processEvents()
    assert t.lbl_zoom.text() == "100%" and t.btn_zoom_in.isEnabled() and t.btn_zoom_out.isEnabled()
    t.btn_zoom_in.click()
    assert t.list.thumb_side() == 170 and t.lbl_zoom.text() == "121%"
    for _ in range(30):
        t.btn_zoom_in.click()
    assert t.list.thumb_side() == t._max_side() > 240          # melewati batas lama
    assert not t.btn_zoom_in.isEnabled() and t.btn_zoom_out.isEnabled()
    assert "maksimum" in t.btn_zoom_in.toolTip()
    assert widest_cell_fits(t) and t.list.horizontalScrollBar().maximum() == 0   # tidak melebihi lebar tampilan
    # halaman potret: sisi terpanjang (tinggi) boleh melebihi lebar tampilan, tetapi LEBAR halaman = lebar area
    page_w = t.list.thumb_side() * t._max_aspect()
    assert abs(page_w - t._avail_width()) <= 2
    for _ in range(40):
        t.btn_zoom_out.click()
    assert t.list.thumb_side() == 80 and not t.btn_zoom_out.isEnabled() and t.lbl_zoom.text() == "57%"


def test_zoom_max_depends_on_page_shape_and_window(arr, qapp):
    t = arr.tab
    arr.window.resize(1100, 700)
    t.add_paths([arr.a])                                        # potret 200x300
    qapp.processEvents()
    portrait_max = t._max_side()
    assert abs(portrait_max - t._avail_width() / (200 / 300)) <= 2
    t.add_paths([arr.b])                                        # + lanskap 300x200: kini lebar = sisi terpanjang
    qapp.processEvents()
    assert t._max_side() == t._avail_width() and t._max_side() < portrait_max
    narrow_avail = t._avail_width()
    arr.window.resize(1366, 700)
    qapp.processEvents()
    assert t._avail_width() > narrow_avail and t._max_side() == t._avail_width()     # jendela lebih lebar -> zoom maks lebih besar


def test_zoom_preference_clamped_on_shrink_and_restored_on_grow(arr, qapp):
    t = arr.tab
    arr.window.resize(1366, 700)
    t.add_paths([arr.a])
    qapp.processEvents()
    for _ in range(40):
        t.btn_zoom_in.click()
    big = t.list.thumb_side()
    assert big == t._max_side()
    arr.window.resize(1000, 700)                                # persempit: zoom ikut turun, tetap muat
    qapp.processEvents()
    small = t.list.thumb_side()
    assert small < big and small == t._max_side() and widest_cell_fits(t)
    arr.window.resize(1366, 700)                                # lebarkan lagi: kembali ke pilihan semula
    qapp.processEvents()
    assert t.list.thumb_side() == big
    t.btn_zoom_out.click()                                      # mengecil dari ukuran efektif, bukan dari nilai lama
    assert t.list.thumb_side() < big


def test_portrait_only_cells_are_narrower_than_square(arr, qapp):
    t = arr.tab
    t.add_paths([arr.a])
    qapp.processEvents()
    assert t.list.box_width() < t.list.thumb_side()             # sel potret lebih sempit -> lebih banyak halaman per baris
    t.add_paths([arr.b])
    qapp.processEvents()
    assert t.list.box_width() >= t.list.thumb_side()            # ada lanskap: sel selebar sisi terpanjang


def make_line_pdf(path):
    doc = fitz.open()
    p = doc.new_page(width=200, height=300)
    p.draw_line((100, 20), (100, 280), color=(0, 0, 0), width=1)      # garis 1 pt: kabur di thumbnail kecil
    doc.save(str(path))
    doc.close()
    return str(path)


def darkest(img):
    return min(img.pixelColor(x, y).red() for y in range(img.height()) for x in range(0, img.width()))


def test_hires_render_makes_large_zoom_sharp(arr, qapp):
    t = arr.tab
    arr.window.resize(1100, 700)
    t.add_paths([make_line_pdf(arr.tmp / "line.pdf")])
    t.wait_thumbs()
    key = next(iter(t.thumbs))
    assert max(t.thumbs[key].width(), t.thumbs[key].height()) == 240
    for _ in range(30):
        t.btn_zoom_in.click()
    side = t.list.thumb_side()
    assert side > 400
    t._request_hires()
    t.wait_thumbs()
    hi = t.hires[key]
    assert max(hi.width(), hi.height()) >= side * 0.95
    ref, img = t._provide(t.list.item(0).data(Qt.UserRole))
    assert img is hi                                            # yang dilukis adalah versi tajam
    assert darkest(hi) < 60 < darkest(t.thumbs[key])            # garis 1 pt: hitam di hires, kabur di thumbnail kecil
    assert not t.list.viewport().grab().isNull()


def test_no_hires_at_small_zoom_and_only_visible_pages_get_hires(arr, qapp):
    t = arr.tab
    arr.window.resize(1000, 600)
    make_pdf(arr.tmp / "long.pdf", ["P%d" % i for i in range(120)])
    t.add_paths([str(arr.tmp / "long.pdf")])
    t.wait_thumbs()
    from tabs.arranger_tab import HiResWorker
    t._request_hires()
    assert not [w for w in t._workers if isinstance(w, HiResWorker)] and not t.hires      # zoom kecil: tidak perlu
    for _ in range(30):
        t.btn_zoom_in.click()
    qapp.processEvents()
    t._request_hires()
    t.wait_thumbs()
    assert 0 < len(t.hires) < 12                                # hanya halaman yang terlihat (+ satu layar), bukan 120
    visible_rows = [r for r in range(t.list.count()) if -t.list.viewport().height() <= t.list.visualItemRect(t.list.item(r)).top() <= 2 * t.list.viewport().height()]
    keys = {(t._ref(t.list.item(r)).src, t._ref(t.list.item(r)).index) for r in visible_rows}
    assert set(t.hires) <= keys


def test_hires_cache_is_bounded_lru(arr, qapp, monkeypatch):
    import tabs.arranger_tab as at
    from PyQt5.QtGui import QImage
    monkeypatch.setattr(at, "HIRES_MAX_ENTRIES", 3)
    t = arr.tab
    for i in range(7):
        t._on_hires(1, i, 50, QImage(50, 50, QImage.Format_RGB888))
    assert list(t.hires) == [(1, 4), (1, 5), (1, 6)]            # yang paling lama dibuang
    monkeypatch.setattr(at, "HIRES_MAX_BYTES", 2 * 50 * 50 * 3 + 10)
    t._on_hires(1, 7, 50, QImage(50, 50, QImage.Format_RGB888))
    assert len(t.hires) <= 2 and (1, 7) in t.hires              # batas byte juga dihormati
    t._on_hires(1, 7, 20, QImage(20, 20, QImage.Format_RGB888))
    assert t.hires[(1, 7)].width() == 50                        # hasil lebih kecil tidak menimpa yang lebih tajam


def test_painting_rotated_resized_and_blank_pages_at_large_zoom(arr, qapp):
    t = arr.tab
    arr.window.resize(1100, 700)
    t.add_paths([arr.a, arr.b])
    t.wait_thumbs()
    select(t, 0)
    t.rotate(90)
    select(t, 1)
    t.set_size_for_test = None
    ref = t._ref(t.list.item(1))
    ref.set_page_size(A.PAGE_PRESETS["Letter"], "auto", "fit", 12)
    select(t, 3)
    t.insert_blank()
    for _ in range(30):
        t.btn_zoom_in.click()
    t.list.scrollToItem(t.list.item(0))
    qapp.processEvents()
    assert not t.list.viewport().grab().isNull()
    t.zoom_step(-1)
    t.zoom_step(-1)
    assert not t.list.viewport().grab().isNull()


def test_closing_window_while_hires_is_rendering_is_safe(qapp, workspace):
    from app_context import AppContext
    from main import PDFToolsSuite
    p = make_pdf(workspace["tmp"] / "bigdoc.pdf", ["P%d" % i for i in range(60)])
    w = PDFToolsSuite(AppContext())
    w.show()
    w.tabs.setCurrentWidget(w.arranger)
    t = w.arranger
    t.add_paths([p])
    t.wait_thumbs()
    for _ in range(30):
        t.btn_zoom_in.click()
    t._request_hires()                                          # worker resolusi tinggi sedang berjalan
    w.close()
    assert all(not wk.isRunning() for wk in t._workers) and not t.hires


def test_zoom_by_ctrl_wheel_and_shortcut(arr, qapp):
    t = arr.tab
    t.add_paths([arr.a])
    ev = QWheelEvent(QPointF(20, 20), QPointF(20, 20), QPoint(0, 0), QPoint(0, 120), Qt.NoButton, Qt.ControlModifier,
                     Qt.NoScrollPhase, False)
    QApplication.sendEvent(t.list.viewport(), ev)
    assert t.list.thumb_side() == 170
    ev = QWheelEvent(QPointF(20, 20), QPointF(20, 20), QPoint(0, 0), QPoint(0, -120), Qt.NoButton, Qt.ControlModifier,
                     Qt.NoScrollPhase, False)
    QApplication.sendEvent(t.list.viewport(), ev)
    QApplication.sendEvent(t.list.viewport(), ev)
    assert t.list.thumb_side() == 120
    ev = QWheelEvent(QPointF(20, 20), QPointF(20, 20), QPoint(0, 0), QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    QApplication.sendEvent(t.list.viewport(), ev)             # tanpa Ctrl: menggulir biasa, bukan zoom
    assert t.list.thumb_side() == 120


# ============================================================================ ukuran relatif (%)
def test_resize_dialog_relative_mode_values_and_ui(arr):
    from widgets.arranger_dialogs import PageSizeDialog
    d = PageSizeDialog(None, 2, 5)
    d.show()
    assert d.spin_pct.isHidden()
    d.combo_preset.setCurrentIndex(d.combo_preset.findData("relative"))
    assert not d.spin_pct.isHidden() and not d.lbl_pct_hint.isHidden() and d.row_custom.isHidden()
    assert not d.combo_orient.isEnabled() and not d.combo_fit.isEnabled() and not d.spin_margin.isEnabled()
    d.spin_pct.setValue(75)
    v = d.values()
    assert v["scale"] == 0.75 and v["size"] is None and v["scale"] is not None
    d.combo_preset.setCurrentIndex(d.combo_preset.findData("A4"))
    assert d.values()["scale"] is None and d.spin_pct.isHidden() and d.combo_orient.isEnabled()
    d.close()


def test_resize_relative_applies_per_page_relative_to_original(arr, qapp, monkeypatch):
    from widgets.arranger_dialogs import PageSizeDialog
    pct = {"v": 50}

    def fake_exec(self):
        self.combo_preset.setCurrentIndex(self.combo_preset.findData("relative"))
        self.spin_pct.setValue(pct["v"])
        return QDialog.Accepted
    monkeypatch.setattr(PageSizeDialog, "exec_", fake_exec)
    t = arr.tab
    t.add_paths([arr.a, arr.b])                         # A: 200x300 potret; B: 300x200 lanskap
    select(t, 0, 3)
    t.resize_dialog()
    refs = t._ordered()
    assert refs[0].size == (100.0, 150.0) and refs[3].size == (150.0, 100.0)     # tiap halaman 50% dari ASLInya
    assert refs[1].size is None
    assert "50%" in t.list.item(0).text() and "50%" in t.list.item(3).text()
    assert "Skala: 50%" in t.list.item(0).toolTip()
    n_undo = len(t._undo)
    t.resize_dialog()                                    # ulangi 50%: tetap 50% dan TIDAK mencatat undo sia-sia
    assert t._ordered()[0].size == (100.0, 150.0) and len(t._undo) == n_undo
    pct["v"] = 200
    t.resize_dialog()
    assert t._ordered()[0].size == (400.0, 600.0)
    select(t, 0)
    t.rotate(90)                                         # putar: ukuran tertukar, skala tetap
    assert t._ordered()[0].size == (600.0, 400.0) and "200%" in t.list.item(0).text()
    t.undo()                                             # urungkan putaran
    assert t._ordered()[0].size == (400.0, 600.0)
    t.undo()                                             # urungkan 200% -> kembali 50%
    assert t._ordered()[0].size == (100.0, 150.0)
    # simpan: ukuran halaman hasil sesuai skala
    t.edit_out.setText(str(arr.tmp / "skala.pdf"))
    t.save_pdf()
    wait_job(t, qapp)
    with fitz.open(arr.tmp / "skala.pdf") as d:
        assert [(round(p.rect.width), round(p.rect.height)) for p in d] == [(100, 150), (200, 300), (200, 300), (150, 100), (300, 200)]
    select(t, 0)
    t.reset_selected()
    assert t._ordered()[0].size is None and t._ordered()[0].scale == 0
