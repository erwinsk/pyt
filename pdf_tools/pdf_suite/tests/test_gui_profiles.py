# -*- coding: utf-8 -*-
"""Uji GUI offscreen untuk tiga tingkat pilihan: Tujuan (profil) -> Metode -> Parameter."""
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from core.engines import get_engine
from core.profiles import CATEGORY_LABELS, CUSTOM_ID, FORMAT_NAME, owned_keys


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def make_window():
    from app_context import AppContext
    from main import PDFToolsSuite
    return PDFToolsSuite(AppContext())


@pytest.fixture()
def ui(qapp, workspace, monkeypatch):
    msgs = {"information": [], "warning": [], "question": []}
    monkeypatch.setattr(QMessageBox, "information", staticmethod(
        lambda *a, **k: msgs["information"].append((a[1], a[2])) or QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(
        lambda *a, **k: msgs["warning"].append((a[1], a[2])) or QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: msgs["question"].append((a[1], a[2])) or QMessageBox.Yes))
    w = make_window()
    w.show()
    yield SimpleNamespace(window=w, tab=w.compressor, msgs=msgs, tmp=workspace["tmp"])
    w.compressor.abort_and_wait()
    w.close()


def wait_done(tab, qapp, timeout=240):
    t0 = time.time()
    while tab.runner is not None and time.time() - t0 < timeout:
        qapp.processEvents()
        time.sleep(0.05)
    qapp.processEvents()
    assert tab.runner is None, "job tidak selesai tepat waktu"


def cur(tab):
    return tab.combo_profile.currentData()


def items(tab):
    cb = tab.combo_profile
    return [(cb.itemText(i), cb.itemData(i), bool(cb.model().item(i).flags() & Qt.ItemIsEnabled))
            for i in range(cb.count())]


# ---------------------------------------------------------------- struktur
def test_profile_combo_structure(ui):
    t = ui.tab
    rows = items(t)
    ids = [d for _, d, _ in rows if d]
    assert ids == ["scan_seimbang", "scan_terkecil", "scan_arsip", "scan_cepat",
                   "digital_ringan", "digital_email", "ocr_saja", CUSTOM_ID]
    headers = [(txt, en) for txt, d, en in rows if d is None]
    assert [h[0] for h in headers] == [CATEGORY_LABELS[c] for c in ("scan", "digital", "ocr")]
    assert not any(en for _, en in headers)                      # judul grup tidak bisa dipilih
    assert rows[-1][1] == CUSTOM_ID                              # 'Kustom' selalu terakhir


def test_initial_state_is_a_safe_profile_with_advanced_collapsed(ui):
    t = ui.tab
    # bawaan Ghostscript yang aman (JPEG dipaksa) = profil 'Dokumen digital - Ringan'
    assert t.combo_engine.currentData() == "ghostscript" and cur(t) == "digital_ringan"
    assert not t.btn_adv.isChecked() and not t.adv_box.isVisible()   # cocok profil -> lanjutan dilipat
    assert not t.act_save.isEnabled() and not t.act_delete.isEnabled()
    assert "Metode: Ghostscript" in t.lbl_profile.text()


def test_choosing_the_old_unsafe_value_is_custom_and_opens_advanced(ui):
    t = ui.tab
    t.current_panel()._widgets["jpeg_quality"].setValue(0)           # sengaja memilih 'otomatis Ghostscript'
    assert cur(t) == CUSTOM_ID and t.act_save.isEnabled()


# ---------------------------------------------------- tingkat 1 -> 2 -> 3
def test_apply_profile_sets_method_and_parameters(ui):
    t = ui.tab
    assert t.apply_profile("scan_terkecil")
    assert t.combo_engine.currentData() == "mrc" and cur(t) == "scan_terkecil"
    v = t.current_panel().values()
    assert (v["bg_downsample"], v["bg_rate"], v["fg_rate"]) == (3, 900, 1200)
    assert "Metode: MRC" in t.lbl_profile.text() and "lebih kuat" in t.lbl_profile.text()
    assert not t.act_save.isEnabled()                            # sudah profil: tak perlu disimpan lagi
    assert t.apply_profile("tidak-ada") is False


def test_profile_application_is_reproducible_not_history_dependent(ui):
    t = ui.tab
    t.apply_profile("scan_seimbang")
    p = t.panels["mrc"]
    p._widgets["bg_rate"].setValue(4000)
    p._widgets["denoise"].setCurrentIndex(p._widgets["denoise"].findData("bregman"))
    assert cur(t) == CUSTOM_ID
    t.apply_profile("scan_terkecil")
    t.apply_profile("scan_seimbang")
    defaults = get_engine("mrc").options.defaults()
    assert {k: p.values()[k] for k in owned_keys("mrc")} == {k: defaults[k] for k in owned_keys("mrc")}
    assert cur(t) == "scan_seimbang"


def test_tweaking_a_parameter_goes_custom_and_back(ui):
    t = ui.tab
    t.apply_profile("scan_terkecil")
    w = t.current_panel()._widgets["bg_rate"]
    w.setValue(901)
    assert cur(t) == CUSTOM_ID and "Kustom" in t.lbl_profile.text() and t.act_save.isEnabled()
    w.setValue(900)
    assert cur(t) == "scan_terkecil"                             # kembali sama persis -> profil kembali


def test_changing_ocr_language_does_not_leave_the_profile(ui):
    t = ui.tab
    t.apply_profile("scan_seimbang")
    edit = t.current_panel()._widgets["languages"]._edit
    edit.setText("ind+eng")
    assert cur(t) == "scan_seimbang"
    # dan bahasa dipertahankan saat berganti profil
    t.apply_profile("scan_terkecil")
    assert t.current_panel().values()["languages"] == "ind+eng"


def test_changing_method_resyncs_the_profile(ui):
    t = ui.tab
    t.apply_profile("scan_cepat")
    assert t.combo_engine.currentData() == "full_image" and cur(t) == "scan_cepat"
    t.combo_engine.setCurrentIndex(t.combo_engine.findData("mrc"))     # Tingkat 2 diubah langsung
    assert cur(t) == "scan_seimbang"                                    # panel MRC sedang di bawaannya
    t.combo_engine.setCurrentIndex(t.combo_engine.findData("ghostscript"))
    assert cur(t) == "digital_ringan"                                   # panel Ghostscript di bawaannya
    t.current_panel()._widgets["dpi"].setValue(111)
    assert cur(t) == CUSTOM_ID


def test_reset_parameters_resyncs(ui):
    t = ui.tab
    t.apply_profile("scan_terkecil")
    t.btn_defaults.click()
    assert cur(t) == "scan_seimbang"


def test_combo_activation_wiring(ui):
    t = ui.tab
    cb = t.combo_profile
    cb.activated[int].emit(cb.findData("scan_cepat"))
    assert t.combo_engine.currentData() == "full_image" and cur(t) == "scan_cepat"
    header_idx = next(i for i in range(cb.count()) if cb.itemData(i) is None)
    cb.activated[int].emit(header_idx)                                  # judul grup: tidak mengubah apa pun
    assert cur(t) == "scan_cepat"
    t.btn_adv.setChecked(False)
    cb.activated[int].emit(cb.findData(CUSTOM_ID))                      # memilih 'Kustom' membuka lanjutan
    assert t.btn_adv.isChecked() and cur(t) == "scan_cepat"             # nilai tidak berubah


def test_advanced_toggle(ui):
    t = ui.tab
    t.btn_adv.setChecked(False)
    assert not t.adv_box.isVisible() and t.btn_adv.text().startswith("▸")
    t.btn_adv.setChecked(True)
    assert t.adv_box.isVisible() and t.btn_adv.text().startswith("▾") and "lanjutan" in t.btn_adv.text()


def test_profiles_needing_missing_tools_stay_visible_but_disabled(ui, monkeypatch):
    t = ui.tab
    mrc = get_engine("mrc")
    monkeypatch.setattr(mrc, "availability",
                        lambda tools: (False, ["recode_pdf: pip install archive-pdf-tools"]))
    t.on_tools_changed()
    rows = {d: (txt, en) for txt, d, en in items(t) if d}
    for pid in ("scan_seimbang", "scan_terkecil", "scan_arsip"):
        assert rows[pid][1] is False and "butuh alat" in rows[pid][0], pid
    assert rows["scan_cepat"][1] is True and rows["digital_ringan"][1] is True
    i = t.combo_profile.findData("scan_terkecil")
    tip = t.combo_profile.itemData(i, Qt.ToolTipRole)
    assert "archive-pdf-tools" in tip and "lebih kuat" in tip           # cara memasang ikut tampil
    monkeypatch.undo()
    t.on_tools_changed()
    real_ok = get_engine("mrc").availability(t.ctx.tools)[0]          # kembali mengikuti alat sungguhan
    rows = {d: en for _, d, en in items(t) if d}
    assert rows["scan_terkecil"] is real_ok and rows["scan_cepat"] is True


# ------------------------------------------------------- kelola profil
def test_save_profile_flow(ui, monkeypatch):
    t = ui.tab
    t.apply_profile("scan_terkecil")
    t.current_panel()._widgets["bg_rate"].setValue(1000)
    assert cur(t) == CUSTOM_ID
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Kantor saya", True)))
    t.act_save.trigger()
    assert cur(t).startswith("user:")
    assert t.combo_profile.currentText() == "★ Kantor saya"
    assert t.act_delete.isEnabled() and not t.act_save.isEnabled()
    assert any(txt == CATEGORY_LABELS["user"] for txt, d, _ in items(t) if d is None)
    # persisten antar-instance
    assert [p.name for p in make_window().compressor.ctx.profiles.user()] == ["Kantor saya"]


def test_save_profile_rejections_and_overwrite(ui, monkeypatch):
    t = ui.tab
    t.apply_profile("scan_seimbang")
    t.current_panel()._widgets["bg_rate"].setValue(1100)
    name = {"v": "Scan, cepat - tanpa OCR"}
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (name["v"], True)))
    t.save_profile_dialog()                                             # nama profil bawaan
    assert ui.msgs["warning"] and "bawaan" in ui.msgs["warning"][-1][1]
    assert cur(t) == CUSTOM_ID and not t.ctx.profiles.user()
    name["v"] = "Punya"
    t.save_profile_dialog()
    uid = cur(t)
    t.current_panel()._widgets["bg_rate"].setValue(1200)                # Kustom lagi
    ui.msgs["question"].clear()
    t.save_profile_dialog()                                             # nama sama -> tanya timpa (Ya)
    assert ui.msgs["question"] and "sudah ada" in ui.msgs["question"][-1][1]
    assert cur(t) == uid and len(t.ctx.profiles.user()) == 1
    assert t.ctx.profiles.get(uid).values["bg_rate"] == 1200
    # batal di dialog nama: tidak ada yang berubah
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("x", False)))
    t.current_panel()._widgets["bg_rate"].setValue(1300)
    t.save_profile_dialog()
    assert len(t.ctx.profiles.user()) == 1 and cur(t) == CUSTOM_ID


def test_delete_profile_flow(ui, monkeypatch):
    t = ui.tab
    t.apply_profile("scan_terkecil")
    assert not t.act_delete.isEnabled()                                 # profil bawaan tidak bisa dihapus
    t.delete_profile_dialog()
    assert t.ctx.profiles.get("scan_terkecil") is not None
    t.current_panel()._widgets["bg_rate"].setValue(1000)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Sementara", True)))
    t.save_profile_dialog()
    assert t.act_delete.isEnabled()
    t.act_delete.trigger()
    assert not t.ctx.profiles.user() and cur(t) == CUSTOM_ID
    assert t.current_panel().values()["bg_rate"] == 1000                # pengaturan tetap dipakai
    assert t.combo_profile.findData("user:x") == -1


def test_export_and_import_flow(ui, monkeypatch):
    t = ui.tab
    path = ui.tmp / "profil.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(path), "")))
    t.export_profiles_dialog()                                          # belum ada profil -> pesan jelas
    assert not path.exists() and "Belum ada profil" in ui.msgs["warning"][-1][1]

    t.apply_profile("scan_terkecil")
    t.current_panel()._widgets["bg_rate"].setValue(1000)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Bagikan", True)))
    t.save_profile_dialog()
    t.export_profiles_dialog()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == FORMAT_NAME and [p["name"] for p in data["profiles"]] == ["Bagikan"]
    assert "1 profil ditulis" in ui.msgs["information"][-1][1] and str(path) in ui.msgs["information"][-1][1]

    t.ctx.profiles.delete_user(t.ctx.profiles.user()[0].id)
    t._rebuild_profile_items()
    t._sync_profile()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(path), "")))
    t.import_profiles_dialog()
    assert [p.name for p in t.ctx.profiles.user()] == ["Bagikan"]
    assert cur(t).startswith("user:") and "1 profil ditambahkan" in ui.msgs["information"][-1][1]

    # berkas berbahaya: argumen baris perintah dikosongkan dan pengguna diberi tahu
    evil = ui.tmp / "jahat.json"
    evil.write_text(json.dumps({"format": FORMAT_NAME, "version": 1, "profiles": [
        {"name": "Jahat", "engine": "ghostscript", "values": {"dpi": 120, "jpeg_quality": 50,
                                                              "extra_args": "-dNOSAFER -c '(x) pop'"}}]}),
                    encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(evil), "")))
    t.import_profiles_dialog()
    assert "demi keamanan" in ui.msgs["information"][-1][1]
    jahat = next(p for p in t.ctx.profiles.user() if p.name == "Jahat")
    assert t.ctx.profiles.resolve(jahat)["extra_args"] == ""

    # berkas rusak
    junk = ui.tmp / "rusak.json"
    junk.write_text("bukan json", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(junk), "")))
    t.import_profiles_dialog()
    assert "JSON" in ui.msgs["warning"][-1][1]


# ------------------------------------------------------------ tata letak
def _overlaps(widgets):
    """Pasangan widget (terlihat) yang persegi panjangnya saling menimpa, dalam koordinat jendela."""
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
@pytest.mark.parametrize("profile", ["dokumen_ringan", "scan_terkecil"])
def test_layout_never_overlaps_and_settings_column_fits(ui, qapp, size, profile):
    """Regresi tata letak: pada beberapa ukuran jendela, bagian utama tidak saling menimpa dan
    kolom pengaturan tidak meluber ke samping (tanpa itu kontrol terpotong di kolom sempit)."""
    w, t = ui.window, ui.tab
    w.resize(*size)
    t.apply_profile(profile)
    t.btn_adv.setChecked(True)
    for _ in range(6):
        qapp.processEvents()
    parts = [t.files, t.right_scroll, t.btn_open, t.pbar, t.lbl_status, t.btn_cancel, t.btn_run, t.drawer]
    assert _overlaps(parts) == []
    body = t.right_scroll.widget()
    assert body.width() <= t.right_scroll.viewport().width() + 1        # tidak ada kontrol terpotong di kanan
    assert t.right_scroll.horizontalScrollBar().maximum() == 0
    t.btn_adv.setChecked(False)
    for _ in range(4):
        qapp.processEvents()
    assert not t.adv_box.isVisible()


def test_footer_and_queue_fit_at_minimum_size(ui, qapp, sample_scan):
    w, t = ui.window, ui.tab
    w.resize(w.minimumWidth(), w.minimumHeight())
    t.files.add_path(str(sample_scan))
    for _ in range(4):
        qapp.processEvents()
    assert t.table.horizontalScrollBar().maximum() == 0                 # kolom antrean muat tanpa gulir samping
    assert t.table.columnWidth(0) >= 120                                # nama file tidak menciut jadi '…'


def test_missing_tool_message_is_visible_even_when_advanced_is_collapsed(ui, qapp):
    from core.deps import ToolStatus
    t = ui.tab
    tools = dict(ui.window.ctx.tools)
    tools["recode_pdf"] = ToolStatus("recode_pdf", "recode")
    ui.window.ctx.tools = tools
    t.btn_adv.setChecked(False)
    t.combo_engine.setCurrentIndex(t.combo_engine.findData("mrc"))
    t.on_tools_changed()
    qapp.processEvents()
    assert t.lbl_avail.isVisible() and "belum terpasang" in t.lbl_avail.text() and not t.adv_box.isVisible()
    assert "recode_pdf" in t.lbl_avail.text() and "Buka Dependensi" in t.lbl_avail.text()
    ui.window.update_tools_chip()
    assert ui.window.btn_tools.property("state") == "warn" and "bermasalah" in ui.window.btn_tools.text()


def test_dependency_link_and_chip_open_the_deps_dialog(ui, qapp):
    w = ui.window
    assert not w.deps_dialog.isVisible()
    ui.tab.request_deps.emit()
    qapp.processEvents()
    assert w.deps_dialog.isVisible()
    w.deps_dialog.close()
    w.btn_tools.click()
    qapp.processEvents()
    assert w.deps_dialog.isVisible()
    w.deps_dialog.close()


def test_chip_reports_ready_when_all_tools_found(ui):
    from core import deps as D
    w = ui.window
    w.ctx.tools = {s.id: D.ToolStatus(s.id, s.label, found=True, path="/x", version="1") for s in D.TOOL_SPECS}
    w.update_tools_chip()
    assert w.btn_tools.property("state") == "ok" and w.btn_tools.text() == f"✓ {len(D.TOOL_SPECS)} alat siap"


def test_queue_is_single_table_with_per_file_status(ui, sample_scan, sample_text):
    t = ui.tab
    t.files.add_path(str(sample_scan))
    t.files.add_path(str(sample_text))
    assert t.table.rowCount() == 2 and t.files.files() == [str(sample_scan), str(sample_text)]
    assert [t.table.item(r, 6).text() for r in range(2)] == ["siap", "siap"]
    assert not t.files.add_path(str(sample_scan))                       # duplikat ditolak
    t.table.set_locked(True)
    assert not t.files.add_path(str(sample_scan.parent / "lain.pdf"))    # terkunci saat proses
    t.table.set_locked(False)
    t.table.selectRow(0)
    t.files.remove_selected()
    assert t.files.files() == [str(sample_text)]
    t.files.reset()
    assert t.table.rowCount() == 0


def test_log_drawer_opens_on_failure(ui, qapp, sample_text, workspace):
    t = ui.tab
    assert not t.drawer.is_open()
    t.console.append_line("baris pertama")
    assert t.drawer.lbl_last.full_text() == "baris pertama"
    t._on_file_done(0, {"status": "gagal"}) if t.table.rowCount() else None
    t.table.start()
    t.files.add_path(str(sample_text))
    t._on_file_done(0, {"status": "gagal", "orig": 1})
    assert t.drawer.is_open()


def test_image_tab_has_per_file_status(ui, qapp, sample_scan, workspace, monkeypatch):
    img = ui.window.image_export
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.Ok))
    out = workspace["tmp"] / "gambar"
    img.files.add_path(str(sample_scan))
    img.files.add_path(str(sample_scan.parent / "hilang.pdf"))
    img.edit_output.setText(str(out))
    img.start_process()
    t0 = time.time()
    while not img.btn_run.isEnabled() and time.time() - t0 < 60:
        qapp.processEvents()
        time.sleep(0.05)
    assert img.btn_run.isEnabled()
    assert img.table.item(0, 2).text() == "selesai" and int(img.table.item(0, 1).text()) >= 1
    assert img.table.item(1, 2).text() == "gagal" and img.drawer.is_open()
    assert list((out / sample_scan.stem).glob("*.png"))


def test_closing_window_with_pending_layout_timer_does_not_crash(qapp, workspace):
    """Regresi: QTimer.singleShot(0, lambda: self...) yang masih tertunda saat jendela dihancurkan
    memanggil objek mati -> RuntimeError di slot Qt -> PyQt5 abort() (proses mati, bukan tes gagal)."""
    import gc

    from PyQt5.QtCore import QEvent
    w = make_window()
    w.show()
    w.compressor.btn_adv.setChecked(True)            # memulai timer penataan ulang yang tertunda
    w.close()
    w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    del w
    gc.collect()
    for _ in range(3):
        qapp.processEvents()


# ------------------------------------------------------------ persistensi
def test_selection_and_panel_state_persist_across_restart(ui, qapp):
    t = ui.tab
    t.apply_profile("scan_terkecil")
    t.btn_adv.setChecked(False)
    t.save_state()
    w2 = make_window()
    try:
        t2 = w2.compressor
        assert t2.combo_engine.currentData() == "mrc" and cur(t2) == "scan_terkecil"
        assert not t2.btn_adv.isChecked()                               # cocok profil + terakhir dilipat
    finally:
        w2.close()
    # pengaturan yang BUKAN profil selalu membuka bagian lanjutan walau terakhir dilipat
    t.current_panel()._widgets["bg_rate"].setValue(1234)
    t.btn_adv.setChecked(False)
    t.save_state()
    w3 = make_window()
    try:
        assert cur(w3.compressor) == CUSTOM_ID and w3.compressor.btn_adv.isChecked()
    finally:
        w3.close()


def test_controls_are_locked_while_running(ui):
    t = ui.tab
    t._set_running(True)
    assert not t.combo_profile.isEnabled() and not t.btn_manage.isEnabled() and not t.combo_engine.isEnabled()
    t._set_running(False)
    assert t.combo_profile.isEnabled() and t.btn_manage.isEnabled() and t.combo_engine.isEnabled()


# ------------------------------------------------- run nyata lewat profil
def run_profile(ui, qapp, pid, src):
    t = ui.tab
    out = ui.tmp / f"out_{pid}"
    t.edit_out.setText(str(out))
    assert t.apply_profile(pid)
    t.files.add_path(str(src))
    t.start_process()
    wait_done(t, qapp)
    return out


def test_run_scan_cepat_profile_via_tab(ui, qapp, sample_scan):
    out = run_profile(ui, qapp, "scan_cepat", sample_scan)
    produced = list(out.glob("*.pdf"))
    assert len(produced) == 1
    assert 0 < produced[0].stat().st_size < Path(sample_scan).stat().st_size
    log = ui.tab.console.toPlainText()
    assert "Tujuan: Scan, cepat - tanpa OCR" in log and "Metode: Full Image" in log


def test_run_digital_profile_via_tab(ui, qapp, tools, sample_scan):
    if not tools["gs"].found:
        pytest.skip("Ghostscript belum terpasang")
    out = run_profile(ui, qapp, "digital_ringan", sample_scan)
    produced = list(out.glob("*.pdf"))
    assert len(produced) == 1 and produced[0].stat().st_size < Path(sample_scan).stat().st_size
    assert "Tujuan: Dokumen digital - Ringan" in ui.tab.console.toPlainText()


def test_run_logs_custom_when_no_profile_matches(ui, qapp, sample_scan):
    t = ui.tab
    t.combo_engine.setCurrentIndex(t.combo_engine.findData("full_image"))
    t.current_panel()._widgets["quality"].setValue(41)
    assert cur(t) == CUSTOM_ID
    t.edit_out.setText(str(ui.tmp / "out_custom"))
    t.files.add_path(str(sample_scan))
    t.start_process()
    wait_done(t, qapp)
    assert "Tujuan: Kustom" in t.console.toPlainText()


# ------------------------------------------------------- pengaman ukuran (GUI)
def test_size_guard_checkbox_default_and_persistence(ui):
    t = ui.tab
    assert t.chk_guard.isChecked()                                     # aman secara bawaan
    assert "OCRmyPDF" in t.chk_guard.toolTip()                         # pengecualiannya dijelaskan
    t.chk_guard.setChecked(False)
    t.save_state()
    w2 = make_window()
    try:
        assert not w2.compressor.chk_guard.isChecked()
    finally:
        w2.close()


def test_result_that_is_not_smaller_is_reported_and_not_saved(ui, qapp, sample_text):
    t = ui.tab
    out = ui.tmp / "out_guard"
    t.edit_out.setText(str(out))
    t.apply_profile("scan_cepat")                                      # rasterisasi: teks vektor kecil membesar
    t.files.add_path(str(sample_text))
    t.start_process()
    wait_done(t, qapp)
    assert t.table.item(0, 6).text() == "tidak dikecilkan"
    assert t.table.item(0, 2).text() and t.table.item(0, 3).text().startswith("-")   # ukuran & hemat negatif tampil
    assert "tidak lebih kecil" in t.table.item(0, 6).toolTip()
    assert not out.exists() or not list(out.glob("*"))
    assert "tidak dikecilkan" in ui.msgs["information"][-1][1]
    log = t.console.toPlainText()
    assert "Tidak dikecilkan" in log


def test_guard_off_in_ui_saves_the_larger_result(ui, qapp, sample_text):
    t = ui.tab
    out = ui.tmp / "out_noguard"
    t.edit_out.setText(str(out))
    t.apply_profile("scan_cepat")
    t.chk_guard.setChecked(False)
    t.files.add_path(str(sample_text))
    t.start_process()
    wait_done(t, qapp)
    assert t.table.item(0, 6).text() == "selesai" and len(list(out.glob("*.pdf"))) == 1
