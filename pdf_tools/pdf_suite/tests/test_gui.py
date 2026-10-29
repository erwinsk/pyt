# -*- coding: utf-8 -*-
"""Uji GUI offscreen: panel opsi, job lewat tab, cache, batal, persistensi."""
import time

import pytest
from PyQt5.QtWidgets import QApplication, QMessageBox

from core.engines import ENGINES


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def window(qapp, workspace, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    from app_context import AppContext
    from main import PDFToolsSuite
    ctx = AppContext()
    w = PDFToolsSuite(ctx)
    w.show()
    yield w
    w.compressor.abort_and_wait()
    w.close()


def wait_done(tab, qapp, timeout=240):
    t0 = time.time()
    while tab.runner is not None and time.time() - t0 < timeout:
        qapp.processEvents()
        time.sleep(0.05)
    qapp.processEvents()
    assert tab.runner is None, "job tidak selesai tepat waktu"


def leftovers(workspace):
    from core.paths import scratch_root
    sr = scratch_root()
    return (list(sr.iterdir()) if sr.exists() else []) + list(workspace["systmp"].iterdir())


def test_window_structure(window):
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == ["Kompres", "Atur Halaman", "PDF → Gambar"]
    t = window.compressor
    assert [t.combo_engine.itemData(i) for i in range(t.combo_engine.count())] == ["ghostscript", "full_image", "ocrmypdf", "mrc"]


def test_panel_roundtrip_all_engines(window):
    t = window.compressor
    for e in ENGINES:
        p = t.panels[e.id]
        assert p.values() == e.options.defaults(), e.id
        custom = {k: v for k, v in e.options.defaults().items()}
        for opt in e.options:
            if opt.kind == "int":
                custom[opt.key] = int(opt.min if opt.min is not None else 0) + 1
            elif opt.kind == "bool":
                custom[opt.key] = not opt.default
            elif opt.kind == "text":
                custom[opt.key] = "x y"
        p.set_values(custom)
        got = p.values()
        for k, v in e.options.normalize(custom).items():
            assert got[k] == v, (e.id, k, got[k], v)


def test_ocr_markers_only_on_ocr_engines(window):
    t = window.compressor
    assert "↻" in t.panels["mrc"]._labels["languages"].text()
    assert "⚡" in t.panels["mrc"]._labels["bg_downsample"].text()
    assert "↻" not in t.panels["ghostscript"]._labels["dpi"].text()
    t.combo_engine.setCurrentIndex(t.combo_engine.findData("ghostscript"))
    assert t.cache_row.isHidden() and t.lbl_legend.isHidden()
    t.combo_engine.setCurrentIndex(t.combo_engine.findData("mrc"))
    assert not t.cache_row.isHidden() and not t.lbl_legend.isHidden()


def test_enabled_if_and_tool_notes(window):
    from core.deps import ToolStatus
    p = window.compressor.panels["ocrmypdf"]
    p.set_values({"output_type": "pdf"})
    assert not p._widgets["pdfa_image_compression"].isEnabled()
    p.set_values({"output_type": "auto"})
    assert p._widgets["pdfa_image_compression"].isEnabled()
    tools = dict(window.ctx.tools)
    tools["unpaper"] = ToolStatus("unpaper", "unpaper")
    p.refresh_availability(tools)
    assert not p._widgets["clean"].isEnabled() and "unpaper" in p._widgets["clean"].toolTip()


def test_unavailable_engine_disables_start(window):
    from core.deps import ToolStatus
    t = window.compressor
    tools = dict(window.ctx.tools)
    tools["recode_pdf"] = ToolStatus("recode_pdf", "recode")
    window.ctx.tools = tools
    t.combo_engine.setCurrentIndex(t.combo_engine.findData("mrc"))
    t.on_tools_changed()
    assert not t.btn_run.isEnabled() and "belum terpasang" in t.lbl_avail.text()


def test_run_full_image_via_tab(window, qapp, sample_scan, workspace):
    t = window.compressor
    out = workspace["tmp"] / "hasil"; out.mkdir()
    t.edit_out.setText(str(out))
    t.files.add_path(str(sample_scan))
    t.combo_engine.setCurrentIndex(t.combo_engine.findData("full_image"))
    t.start_process()
    assert t.runner is not None and not t.btn_run.isEnabled() and t.btn_cancel.isEnabled()
    wait_done(t, qapp)
    assert t.table.item(0, 6).text() == "selesai"
    outs = list(out.glob("*.pdf"))
    assert len(outs) == 1 and outs[0].name == "scan_full_image.pdf"
    assert t.btn_run.isEnabled() and t.pbar.value() == 100
    assert leftovers(workspace) == []
    # jalankan lagi -> nama unik, tidak menimpa
    t.start_process(); wait_done(t, qapp)
    assert sorted(p.name for p in out.glob("*.pdf")) == ["scan_full_image.pdf", "scan_full_image_2.pdf"]


def test_cache_label_and_delete_button(window, qapp, sample_scan, workspace):
    if not (window.ctx.tools["ocrmypdf"].found and window.ctx.tools["tesseract"].found):
        pytest.skip("ocrmypdf/tesseract belum terpasang")
    t = window.compressor
    out = workspace["tmp"] / "hasil"; out.mkdir()
    t.edit_out.setText(str(out))
    t.files.add_path(str(sample_scan))
    t.combo_engine.setCurrentIndex(t.combo_engine.findData("ocrmypdf"))
    t.panels["ocrmypdf"].set_values({"optimize": "1", "deskew": False})
    t.update_cache_label()
    assert "belum ada" in t.lbl_cache.text()
    t.start_process(); wait_done(t, qapp)
    assert t.table.item(0, 5).text() == "dibuat"
    t.update_cache_label()
    assert "dipakai ulang" in t.lbl_cache.text()
    # ganti parameter kompresi saja -> label tetap 'ada', OCR dipakai ulang
    t.panels["ocrmypdf"].set_values({"optimize": "3", "deskew": False, "jpeg_quality": 40})
    t.update_cache_label()
    assert "dipakai ulang" in t.lbl_cache.text()
    t.start_process(); wait_done(t, qapp)
    assert t.table.item(0, 5).text() == "dipakai"
    # tab Dependensi & Cache menampilkan entri lalu hapus lewat tombol
    dc = window.deps
    dc.populate_cache()
    assert dc.tbl_cache.rowCount() == 1 and "scan.pdf" in dc.tbl_cache.item(0, 0).text()
    t.delete_cache_current()
    assert window.ctx.cache.list() == []
    assert "belum ada" in t.lbl_cache.text()
    assert leftovers(workspace) == []


def test_cancel_via_tab(window, qapp, sample_scan, workspace):
    if not (window.ctx.tools["recode_pdf"].found and window.ctx.tools["tesseract"].found):
        pytest.skip("recode_pdf/tesseract belum terpasang")
    t = window.compressor
    out = workspace["tmp"] / "hasil"; out.mkdir()
    t.edit_out.setText(str(out))
    t.files.add_path(str(sample_scan))
    t.combo_engine.setCurrentIndex(t.combo_engine.findData("mrc"))
    t.start_process()
    t0 = time.time()
    while time.time() - t0 < 2.5:           # biarkan mulai bekerja
        qapp.processEvents(); time.sleep(0.05)
    t.cancel_process()
    wait_done(t, qapp, 60)
    assert t.table.item(0, 6).text() == "dibatalkan"
    assert list(out.iterdir()) == []
    assert leftovers(workspace) == []
    assert t.btn_run.isEnabled() and t.btn_cancel.text() == "Batal"


def test_failure_shown_in_table(window, qapp, sample_text, workspace):
    if not window.ctx.tools["ocrmypdf"].found:
        pytest.skip("ocrmypdf belum terpasang")
    t = window.compressor
    out = workspace["tmp"] / "hasil"; out.mkdir()
    t.edit_out.setText(str(out))
    t.files.add_path(str(sample_text))
    t.combo_engine.setCurrentIndex(t.combo_engine.findData("ocrmypdf"))
    t.start_process(); wait_done(t, qapp)
    assert t.table.item(0, 6).text() == "gagal"
    assert "sudah berisi teks" in t.table.item(0, 6).toolTip()
    assert list(out.iterdir()) == [] and leftovers(workspace) == []


def test_settings_persist(qapp, workspace, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.Ok))
    from app_context import AppContext
    from main import PDFToolsSuite
    w1 = PDFToolsSuite(AppContext())
    t = w1.compressor
    t.combo_engine.setCurrentIndex(t.combo_engine.findData("mrc"))
    t.panels["mrc"].set_values({"bg_downsample": 5, "languages": "eng+osd"})
    t.edit_tpl.setText("{nama}_kecil")
    w1.close()
    w2 = PDFToolsSuite(AppContext())
    t2 = w2.compressor
    assert t2.combo_engine.currentData() == "mrc"
    assert t2.panels["mrc"].values()["bg_downsample"] == 5
    assert t2.panels["mrc"].values()["languages"] == "eng+osd"
    assert t2.edit_tpl.text() == "{nama}_kecil"
    w2.close()


def test_deps_tab_lists_tools_and_hints(window, qapp):
    dc = window.deps
    from core.deps import TOOL_SPECS
    assert dc.tbl_tools.rowCount() == len(TOOL_SPECS)
    dc.tbl_tools.selectRow(0)
    qapp.processEvents()
    assert dc.edit_hint.text()
