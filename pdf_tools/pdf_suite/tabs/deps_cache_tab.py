# -*- coding: utf-8 -*-
"""Tab 'Dependensi & Cache': status alat eksternal, path kustom, petunjuk instal,
dan pengelolaan cache OCR (hapus manual)."""
import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QGroupBox, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from core import deps
from core.paths import cache_root, workspace_root
from widgets.common import fmt_size, open_folder


class DepsCacheTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.family = deps.os_family()
        self._build()
        self.populate_tools()
        self.populate_cache()
        self.ctx.tools_changed.connect(self.on_tools_changed)

    def _build(self):
        root = QVBoxLayout(self)

        # ---- alat ----
        g1 = QGroupBox("Alat eksternal")
        l1 = QVBoxLayout(g1)
        top = QHBoxLayout()
        self.lbl_os = QLabel(f"Sistem terdeteksi: {self.family}")
        self.btn_recheck = QPushButton("Periksa ulang")
        self.btn_recheck.clicked.connect(self.recheck)
        top.addWidget(self.lbl_os, 1)
        top.addWidget(self.btn_recheck)
        l1.addLayout(top)
        self.tbl_tools = QTableWidget(0, 5)
        self.tbl_tools.setHorizontalHeaderLabels(["Alat", "Status", "Versi", "Lokasi", "Dipakai oleh"])
        self.tbl_tools.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_tools.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_tools.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl_tools.verticalHeader().setVisible(False)
        h = self.tbl_tools.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        h.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.tbl_tools.itemSelectionChanged.connect(self.on_tool_selected)
        l1.addWidget(self.tbl_tools)

        hint = QHBoxLayout()
        hint.addWidget(QLabel("Cara memasang:"))
        self.edit_hint = QLineEdit()
        self.edit_hint.setReadOnly(True)
        btn_copy = QPushButton("Salin")
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.edit_hint.text()))
        hint.addWidget(self.edit_hint, 1)
        hint.addWidget(btn_copy)
        l1.addLayout(hint)
        self.lbl_note = QLabel("")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet("color: #666;")
        l1.addWidget(self.lbl_note)
        # Dari mana alat ditemukan / di mana dicari / kenapa gagal dijalankan.
        self.lbl_detail = QLabel("")
        self.lbl_detail.setWordWrap(True)
        self.lbl_detail.setTextFormat(Qt.PlainText)
        self.lbl_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        l1.addWidget(self.lbl_detail)

        cp = QHBoxLayout()
        cp.addWidget(QLabel("Path kustom:"))
        self.edit_path = QLineEdit()
        self.edit_path.setPlaceholderText("Pilih alat di tabel lalu isi path executable-nya (opsional)")
        btn_b = QPushButton("Browse")
        btn_b.clicked.connect(self.browse_path)
        btn_apply = QPushButton("Terapkan")
        btn_apply.clicked.connect(self.apply_path)
        btn_reset = QPushButton("Hapus path kustom")
        btn_reset.clicked.connect(self.reset_path)
        for w in (self.edit_path,):
            cp.addWidget(w, 1)
        for w in (btn_b, btn_apply, btn_reset):
            cp.addWidget(w)
        l1.addLayout(cp)
        self.lbl_langs = QLabel("")
        self.lbl_langs.setWordWrap(True)
        l1.addWidget(self.lbl_langs)
        self.lbl_install_note = QLabel("Aplikasi tidak pernah menjalankan sudo atau memasang paket sendiri — salin perintahnya ke terminal.")
        self.lbl_install_note.setStyleSheet("color: #888; font-size: 11px;")
        l1.addWidget(self.lbl_install_note)
        root.addWidget(g1, 3)

        # ---- cache ----
        g2 = QGroupBox("Cache OCR & folder kerja")
        l2 = QVBoxLayout(g2)
        self.lbl_ws = QLabel(f"Folder kerja: {workspace_root()}")
        self.lbl_ws.setWordWrap(True)
        self.lbl_ws.setTextInteractionFlags(Qt.TextSelectableByMouse)
        l2.addWidget(self.lbl_ws)
        self.tbl_cache = QTableWidget(0, 6)
        self.tbl_cache.setHorizontalHeaderLabels(["File sumber", "Jenis", "Halaman", "Ukuran", "Terakhir dipakai", "Parameter OCR"])
        self.tbl_cache.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_cache.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_cache.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tbl_cache.verticalHeader().setVisible(False)
        hc = self.tbl_cache.horizontalHeader()
        hc.setSectionResizeMode(0, QHeaderView.Stretch)
        hc.setSectionResizeMode(5, QHeaderView.Stretch)
        for i in (1, 2, 3, 4):
            hc.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        l2.addWidget(self.tbl_cache)
        bt = QHBoxLayout()
        self.lbl_total = QLabel("")
        b_reload = QPushButton("Muat ulang")
        b_reload.clicked.connect(self.populate_cache)
        b_del = QPushButton("Hapus terpilih")
        b_del.clicked.connect(self.delete_selected)
        b_all = QPushButton("Hapus semua cache")
        b_all.clicked.connect(self.delete_all)
        b_open = QPushButton("Buka folder cache")
        b_open.clicked.connect(self.open_cache)
        bt.addWidget(self.lbl_total, 1)
        for b in (b_reload, b_del, b_all, b_open):
            bt.addWidget(b)
        l2.addLayout(bt)
        self.lbl_policy = QLabel("Cache tidak dihapus otomatis. File sementara (scratch) selalu dibersihkan sendiri setelah tiap proses.")
        self.lbl_policy.setStyleSheet("color: #888; font-size: 11px;")
        l2.addWidget(self.lbl_policy)
        root.addWidget(g2, 2)

    # ---------------------------------------------------------------- alat
    def populate_tools(self):
        sel = self.selected_tool_id()
        self.tbl_tools.setRowCount(0)
        for spec in deps.TOOL_SPECS:
            st = self.ctx.tools.get(spec.id) or deps.ToolStatus(spec.id, spec.label)
            r = self.tbl_tools.rowCount()
            self.tbl_tools.insertRow(r)
            broken = st.found and bool(st.warn)
            status = "⚠ gagal jalan" if broken else ("✓ ada" if st.found else "✗ tidak ada")
            color = "#ef6c00" if broken else ("#2e7d32" if st.found else "#c62828")
            cells = [spec.label, status, (st.warn or st.version) if st.found else "",
                     st.path if st.found else "", spec.used_by]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c == 0:
                    it.setData(Qt.UserRole, spec.id)
                if c == 1:
                    it.setForeground(QBrush(QColor(color)))
                if c in (1, 2, 3):
                    it.setToolTip(deps.describe_status(st))
                self.tbl_tools.setItem(r, c, it)
            if sel == spec.id:
                self.tbl_tools.selectRow(r)
        langs = self.ctx.languages
        self.lbl_langs.setText("Bahasa Tesseract terpasang: " + (", ".join(langs) if langs else "(tidak terdeteksi)"))
        if self.tbl_tools.currentRow() < 0 and self.tbl_tools.rowCount():
            self.tbl_tools.selectRow(0)

    def selected_tool_id(self):
        r = self.tbl_tools.currentRow()
        it = self.tbl_tools.item(r, 0) if r >= 0 else None
        return it.data(Qt.UserRole) if it else None

    def on_tool_selected(self):
        tid = self.selected_tool_id()
        if not tid:
            return
        self.edit_hint.setText(deps.install_hint(tid, self.family))
        self.lbl_note.setText(deps.SPEC_BY_ID[tid].note)
        st = self.ctx.tools.get(tid) or deps.ToolStatus(tid, tid)
        self.lbl_detail.setText(deps.describe_status(st))
        self.lbl_detail.setStyleSheet("color: #ef6c00;" if (st.found and st.warn) else
                                      ("color: #555;" if st.found else "color: #c62828;"))
        self.edit_path.setText(self.ctx.settings.get(f"tools.{tid}", "") or "")

    def on_tools_changed(self):
        self.populate_tools()
        self.btn_recheck.setEnabled(True)
        self.btn_recheck.setText("Periksa ulang")

    def recheck(self):
        self.btn_recheck.setEnabled(False)
        self.btn_recheck.setText("Memeriksa…")
        self.ctx.refresh_async()

    def browse_path(self):
        f, _ = QFileDialog.getOpenFileName(self, "Pilih executable", "", "Semua file (*)")
        if f:
            self.edit_path.setText(f)

    def apply_path(self):
        tid = self.selected_tool_id()
        if not tid:
            return
        path = self.edit_path.text().strip()
        self.ctx.settings.set(f"tools.{tid}", path or None)
        self.recheck()

    def reset_path(self):
        tid = self.selected_tool_id()
        if not tid:
            return
        self.ctx.settings.set(f"tools.{tid}", None)
        self.edit_path.clear()
        self.recheck()

    # --------------------------------------------------------------- cache
    def populate_cache(self):
        entries = self.ctx.cache.list()
        self.tbl_cache.setRowCount(0)
        for e in entries:
            r = self.tbl_cache.rowCount()
            self.tbl_cache.insertRow(r)
            kind = {"hocr": "hOCR (MRC)", "ocr_pdf": "PDF ber-OCR (OCRmyPDF)"}.get(e.kind, e.kind)
            when = datetime.datetime.fromtimestamp(e.last_used).strftime("%Y-%m-%d %H:%M") if e.last_used else ""
            params = ", ".join(f"{k}={v}" for k, v in e.params.items() if k not in ("engine", "stack") and v not in ("", False, 0))
            cells = [e.source_name, kind, str(e.pages), fmt_size(e.size), when, params]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c == 0:
                    it.setData(Qt.UserRole, e.id)
                    it.setToolTip(e.id)
                self.tbl_cache.setItem(r, c, it)
        total = sum(e.size for e in entries)
        self.lbl_total.setText(f"{len(entries)} entri · total {fmt_size(total)}")

    def delete_selected(self):
        rows = sorted({i.row() for i in self.tbl_cache.selectedIndexes()})
        ids = [self.tbl_cache.item(r, 0).data(Qt.UserRole) for r in rows]
        if not ids:
            return
        if QMessageBox.question(self, "Hapus cache", f"Hapus {len(ids)} entri cache terpilih?") != QMessageBox.Yes:
            return
        for i in ids:
            self.ctx.cache.delete(i)
        self.populate_cache()

    def delete_all(self):
        if not self.ctx.cache.list():
            return
        if QMessageBox.question(self, "Hapus semua cache", "Hapus SEMUA cache OCR? OCR harus diulang bila dibutuhkan lagi.") != QMessageBox.Yes:
            return
        self.ctx.cache.delete_all()
        self.populate_cache()

    def open_cache(self):
        root = cache_root()
        root.mkdir(parents=True, exist_ok=True)
        open_folder(root)

    def showEvent(self, event):
        self.populate_cache()
        super().showEvent(event)
