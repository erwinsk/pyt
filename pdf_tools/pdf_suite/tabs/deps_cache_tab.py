# -*- coding: utf-8 -*-
"""Panel 'Dependensi dan cache': status alat eksternal, path kustom, petunjuk instal,
dan pengelolaan cache OCR (hapus manual). Ditampilkan sebagai dialog (ikon ⚙ di jendela utama)."""
import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from core import deps
from core.paths import cache_root, workspace_root
from theme import semantic
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
        root.setContentsMargins(0, 0, 0, 0)
        self.sub_tabs = QTabWidget()
        root.addWidget(self.sub_tabs)

        # ================= Alat eksternal =================
        t1 = QWidget()
        l1 = QVBoxLayout(t1)
        l1.setContentsMargins(0, 12, 0, 0)
        l1.setSpacing(10)
        top = QHBoxLayout()
        self.lbl_os = QLabel(f"Sistem terdeteksi: {self.family}")
        self.lbl_os.setObjectName("statusText")
        self.lbl_langs = QLabel("")
        self.lbl_langs.setObjectName("statusText")
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
        self.tbl_tools.setShowGrid(False)
        self.tbl_tools.setTextElideMode(Qt.ElideMiddle)
        self.tbl_tools.verticalHeader().setVisible(False)
        self.tbl_tools.verticalHeader().setDefaultSectionSize(30)
        h = self.tbl_tools.horizontalHeader()
        h.setHighlightSections(False)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setMinimumSectionSize(70)             # judul kolom (mis. "Lokasi") tidak boleh terpotong
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Interactive)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        h.setSectionResizeMode(4, QHeaderView.Interactive)
        self.tbl_tools.setColumnWidth(2, 130)
        self.tbl_tools.setColumnWidth(4, 210)
        self.tbl_tools.itemSelectionChanged.connect(self.on_tool_selected)
        l1.addWidget(self.tbl_tools, 1)

        # detail alat terpilih
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 10, 12, 12)
        cl.setSpacing(8)
        # Dari mana alat ditemukan / di mana dicari / kenapa gagal dijalankan.
        self.lbl_detail = QLabel("")
        self.lbl_detail.setWordWrap(True)
        self.lbl_detail.setTextFormat(Qt.PlainText)
        self.lbl_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cl.addWidget(self.lbl_detail)
        hint = QHBoxLayout()
        hint.setSpacing(8)
        hint.addWidget(QLabel("Cara memasang"))
        self.edit_hint = QLineEdit()
        self.edit_hint.setReadOnly(True)
        btn_copy = QPushButton("Salin")
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.edit_hint.text()))
        hint.addWidget(self.edit_hint, 1)
        hint.addWidget(btn_copy)
        cl.addLayout(hint)
        self.lbl_note = QLabel("")
        self.lbl_note.setObjectName("hint")
        self.lbl_note.setWordWrap(True)
        cl.addWidget(self.lbl_note)
        cp = QHBoxLayout()
        cp.setSpacing(8)
        cp.addWidget(QLabel("Path kustom"))
        self.edit_path = QLineEdit()
        self.edit_path.setPlaceholderText("Pilih alat di tabel lalu isi path executable-nya (opsional)")
        btn_b = QPushButton("Browse")
        btn_b.clicked.connect(self.browse_path)
        btn_apply = QPushButton("Terapkan")
        btn_apply.clicked.connect(self.apply_path)
        btn_reset = QPushButton("Hapus")
        btn_reset.setToolTip("Hapus path kustom")
        btn_reset.clicked.connect(self.reset_path)
        cp.addWidget(self.edit_path, 1)
        for w in (btn_b, btn_apply, btn_reset):
            cp.addWidget(w)
        cl.addLayout(cp)
        l1.addWidget(card)
        l1.addWidget(self.lbl_langs)
        self.lbl_install_note = QLabel("Aplikasi tidak pernah menjalankan sudo atau memasang paket sendiri — salin perintahnya ke terminal.")
        self.lbl_install_note.setObjectName("hint")
        self.lbl_install_note.setWordWrap(True)
        l1.addWidget(self.lbl_install_note)
        self.sub_tabs.addTab(t1, "Alat eksternal")

        # ================= Cache OCR dan folder kerja =================
        t2 = QWidget()
        l2 = QVBoxLayout(t2)
        l2.setContentsMargins(0, 12, 0, 0)
        l2.setSpacing(10)
        self.lbl_ws = QLabel(f"Folder kerja: {workspace_root()}")
        self.lbl_ws.setObjectName("statusText")
        self.lbl_ws.setWordWrap(True)
        self.lbl_ws.setTextInteractionFlags(Qt.TextSelectableByMouse)
        l2.addWidget(self.lbl_ws)
        self.tbl_cache = QTableWidget(0, 6)
        self.tbl_cache.setHorizontalHeaderLabels(["File sumber", "Jenis", "Halaman", "Ukuran", "Terakhir dipakai", "Parameter OCR"])
        self.tbl_cache.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_cache.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_cache.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tbl_cache.setShowGrid(False)
        self.tbl_cache.setTextElideMode(Qt.ElideMiddle)
        self.tbl_cache.verticalHeader().setVisible(False)
        self.tbl_cache.verticalHeader().setDefaultSectionSize(30)
        hc = self.tbl_cache.horizontalHeader()
        hc.setHighlightSections(False)
        hc.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hc.setMinimumSectionSize(60)
        hc.setSectionResizeMode(0, QHeaderView.Stretch)
        hc.setSectionResizeMode(5, QHeaderView.Stretch)
        for i in (1, 2, 3, 4):
            hc.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        l2.addWidget(self.tbl_cache, 1)
        bt = QHBoxLayout()
        bt.setSpacing(8)
        self.lbl_total = QLabel("")
        self.lbl_total.setObjectName("statusText")
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
        self.lbl_policy.setObjectName("hint")
        self.lbl_policy.setWordWrap(True)
        l2.addWidget(self.lbl_policy)
        self.sub_tabs.addTab(t2, "Cache OCR dan folder kerja")

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
            kind = "warn" if broken else ("ok" if st.found else "bad")
            color = semantic(kind, self.tbl_tools.palette())
            version = (st.warn or st.version) if st.found else ""
            if st.found and not version:
                version = "—"
            cells = [spec.label, status, version, st.path if st.found else "", spec.used_by]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c == 0:
                    it.setData(Qt.UserRole, spec.id)
                if c == 1:
                    it.setForeground(QBrush(color))
                if c in (1, 2, 3):
                    it.setToolTip(deps.describe_status(st))
                elif text:
                    it.setToolTip(text)
                self.tbl_tools.setItem(r, c, it)
            if sel == spec.id:
                self.tbl_tools.selectRow(r)
        langs = self.ctx.languages
        self.lbl_langs.setText("Bahasa Tesseract terpasang: " + (", ".join(langs) if langs else "(tidak terdeteksi)"))
        if self.tbl_tools.currentRow() < 0 and self.tbl_tools.rowCount():
            self.tbl_tools.selectRow(0)

    def focus_first_problem(self):
        """Pilih alat pertama yang tidak ada / gagal jalan, supaya penyebab & cara memasangnya langsung terlihat."""
        for r in range(self.tbl_tools.rowCount()):
            it = self.tbl_tools.item(r, 1)
            if it is not None and not it.text().startswith("✓"):
                self.sub_tabs.setCurrentIndex(0)
                self.tbl_tools.selectRow(r)
                self.tbl_tools.scrollToItem(self.tbl_tools.item(r, 0))
                return True
        return False

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
        self.lbl_note.setVisible(bool(deps.SPEC_BY_ID[tid].note))
        st = self.ctx.tools.get(tid) or deps.ToolStatus(tid, tid)
        self.lbl_detail.setText(deps.describe_status(st))
        kind = "warn" if (st.found and st.warn) else ("neutral" if st.found else "bad")
        self.lbl_detail.setStyleSheet(f"color: {semantic(kind, self.palette()).name()};")
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


class DepsDialog(QDialog):
    """Dialog tak-modal berisi panel Dependensi dan cache (dibuka dari ikon ⚙ / indikator alat)."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dependensi dan cache")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumSize(760, 480)
        self.resize(1000, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 14)
        self.panel = DepsCacheTab(ctx)
        lay.addWidget(self.panel)

    def present(self, focus_problem: bool = False):
        self.show()
        self.raise_()
        self.activateWindow()
        if focus_problem:
            self.panel.focus_first_problem()
