# -*- coding: utf-8 -*-
"""Antrean file terpadu: SATU tabel yang menggantikan daftar file + tabel hasil.

Baris = file PDF (drag & drop / tombol Tambah). Kolom hasil (ukuran, hemat, status per file)
terisi di baris yang sama saat proses berjalan, jadi nama file tidak lagi muncul dua kali.
Dipakai tab Kompres (CompressTable) dan PDF -> Gambar (ImageTable).
"""
import os
from typing import List

from PyQt5.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QKeySequence, QPainter, QPalette, QPen
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QHBoxLayout, QHeaderView,
                             QLabel, QPushButton, QShortcut, QStyle, QStyledItemDelegate,
                             QStyleOptionViewItem, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from theme import mix, semantic
from .common import fmt_size, open_folder

# teks status -> jenis warna pil
STATUS_KIND = {
    "selesai": "ok",
    "gagal": "bad",
    "dibatalkan": "warn",
    "tidak dikecilkan": "warn",
    "dilewati": "warn",
    "berjalan…": "info",
    "menunggu": "neutral",
    "siap": "neutral",
}


class StatusDelegate(QStyledItemDelegate):
    """Menggambar status sebagai 'pil' berwarna. Teks item tetap berisi status apa adanya."""

    PAD_X, H = 8, 20

    def _font(self, opt):
        f = QFont(opt.font)
        if f.pointSizeF() > 0:
            f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
        return f

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)   # latar + seleksi
        if not text:
            return
        pal = opt.palette
        color = semantic(STATUS_KIND.get(text, "neutral"), pal)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(self._font(opt))
        fm = painter.fontMetrics()
        avail = opt.rect.width() - 8 - 2 * self.PAD_X
        shown = fm.elidedText(text, Qt.ElideRight, max(10, avail))
        w = fm.horizontalAdvance(shown) + 2 * self.PAD_X
        r = QRect(opt.rect.left() + 4, opt.rect.center().y() - self.H // 2 + 1, w, self.H)
        bg = QColor(color)
        bg.setAlpha(46)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(r, self.H / 2, self.H / 2)
        painter.setPen(color)
        painter.drawText(r, Qt.AlignCenter, shown)
        painter.restore()

    def sizeHint(self, option, index):
        text = index.data(Qt.DisplayRole) or ""
        fm = option.fontMetrics
        return QSize(fm.horizontalAdvance(text) + 2 * self.PAD_X + 14, 30)


class QueueTable(QTableWidget):
    """Tabel antrean dasar. Kolom 0 = nama file (path penuh di UserRole), kolom terakhir = status."""

    changed = pyqtSignal()
    current_changed = pyqtSignal(str)
    cleared = pyqtSignal()

    EMPTY_TITLE = "Seret file PDF ke sini"
    EMPTY_HINT = "atau klik “Tambah PDF”"

    def __init__(self, columns: List[str], parent=None):
        super().__init__(0, len(columns), parent)
        self.status_col = len(columns) - 1
        self._locked = False
        self.setHorizontalHeaderLabels(columns)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideMiddle)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(32)
        h = self.horizontalHeader()
        h.setHighlightSections(False)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setMinimumSectionSize(44)
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(columns)):
            h.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.setItemDelegateForColumn(self.status_col, StatusDelegate(self))
        self.currentCellChanged.connect(self._on_current_cell)
        sc = QShortcut(QKeySequence.Delete, self)
        sc.setContext(Qt.WidgetShortcut)
        sc.activated.connect(self.remove_selected)

    # ---- data ----
    def _on_current_cell(self, row, _col, prev_row, _prev_col):
        if row != prev_row:
            self.current_changed.emit(self._path_at(row))

    def _path_at(self, row: int) -> str:
        it = self.item(row, 0) if row >= 0 else None
        return it.data(Qt.UserRole) if it else ""

    def files(self) -> List[str]:
        return [self._path_at(r) for r in range(self.rowCount())]

    def current_path(self) -> str:
        p = self._path_at(self.currentRow())
        if p:
            return p
        fs = self.files()
        return fs[0] if fs else ""

    def set_locked(self, locked: bool):
        """Saat proses berjalan baris tidak boleh berubah (indeks baris = indeks job)."""
        self._locked = locked

    def add_path(self, path: str) -> bool:
        if self._locked or not path.lower().endswith(".pdf") or path in self.files():
            return False
        r = self.rowCount()
        self.insertRow(r)
        name = QTableWidgetItem(os.path.basename(path))
        name.setData(Qt.UserRole, path)
        name.setToolTip(path)
        self.setItem(r, 0, name)
        for c in range(1, self.columnCount()):
            self.setItem(r, c, QTableWidgetItem(""))
        self._init_row(r)
        if self.currentRow() < 0:
            self.setCurrentCell(0, 0)
        self.changed.emit()
        return True

    def _init_row(self, r: int):
        self._set(r, self.status_col, "siap")

    def remove_selected(self):
        if self._locked:
            return
        for r in sorted({i.row() for i in self.selectedIndexes()}, reverse=True):
            self.removeRow(r)
        self.changed.emit()

    def reset(self):
        if self._locked:
            return
        self.setRowCount(0)
        self.changed.emit()
        self.cleared.emit()

    def _set(self, r, c, text, data=None, tip=None):
        it = QTableWidgetItem(text)
        if data is not None:
            it.setData(Qt.UserRole, data)
        if tip:
            it.setToolTip(tip)
        self.setItem(r, c, it)
        return it

    # ---- tampilan kosong ----
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.rowCount():
            return
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        win, txt = pal.color(QPalette.Window), pal.color(QPalette.Text)
        r = self.viewport().rect().adjusted(14, 14, -14, -14)
        p.setPen(QPen(mix(win, txt, 0.28), 1.4, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 10, 10)
        title_f = QFont(self.font())
        title_f.setPointSizeF(title_f.pointSizeF() + 1.5)
        title_f.setBold(True)
        p.setFont(title_f)
        h_t = p.fontMetrics().height()
        p.setFont(self.font())
        h_h = p.fontMetrics().height()
        top = r.center().y() - (h_t + 6 + h_h) // 2
        p.setFont(title_f)
        p.setPen(mix(txt, win, 0.20))
        p.drawText(QRect(r.left(), top, r.width(), h_t), Qt.AlignCenter, self.EMPTY_TITLE)
        p.setFont(self.font())
        p.setPen(mix(txt, win, 0.45))
        p.drawText(QRect(r.left(), top + h_t + 6, r.width(), h_h), Qt.AlignCenter, self.EMPTY_HINT)
        p.end()


class CompressTable(QueueTable):
    """Antrean tab Kompres: kolom hasil terisi per file."""

    COLS = ["File", "Asli", "Hasil", "Hemat", "Waktu", "OCR", "Status"]
    COL_ORIG, COL_NEW, COL_SAVING, COL_TIME, COL_CACHE, COL_STATUS = 1, 2, 3, 4, 5, 6

    def __init__(self, parent=None):
        super().__init__(self.COLS, parent)
        self.horizontalHeaderItem(self.COL_CACHE).setToolTip("Status cache OCR: dipakai ulang / baru dibuat")
        for c in (1, 2, 3, 4):
            self.horizontalHeaderItem(c).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.cellDoubleClicked.connect(self._open)

    def _set(self, r, c, text, data=None, tip=None):
        it = super()._set(r, c, text, data, tip)
        if c in (1, 2, 3, 4):
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return it

    def start(self, files=None):
        """Kosongkan kolom hasil semua baris; semuanya kembali 'menunggu'. (Daftar baris tidak diubah.)"""
        for r in range(self.rowCount()):
            for c in range(1, self.columnCount()):
                self._set(r, c, "")
            self._set(r, self.COL_STATUS, "menunggu")

    def mark_running(self, r, *_):
        if 0 <= r < self.rowCount():
            self._set(r, self.COL_STATUS, "berjalan…")
            self.scrollToItem(self.item(r, 0))

    def update_result(self, r, res: dict):
        if not (0 <= r < self.rowCount()):
            return
        self._set(r, 1, fmt_size(res.get("orig", 0)))
        if res.get("status") in ("selesai", "tidak dikecilkan"):
            self._set(r, 2, fmt_size(res.get("new", 0)), res.get("out") or None)
            self._set(r, 3, "%.1f%%" % res.get("saving", 0))
        self._set(r, 4, "%.1f dtk" % res.get("seconds", 0))
        c = res.get("cache")
        self._set(r, 5, "—" if c is None else ("dipakai" if c else "dibuat"))
        self._set(r, self.COL_STATUS, res.get("status", ""), tip=res.get("message") or None)

    def set_cache_column_visible(self, visible: bool):
        """Kolom OCR hanya berguna untuk metode ber-OCR; sembunyikan agar kolom lain lebih lega."""
        self.setColumnHidden(self.COL_CACHE, not visible)

    def _open(self, row, _col):
        it = self.item(row, self.COL_NEW)
        out = it.data(Qt.UserRole) if it else None
        if out:
            open_folder(out)


class ImageTable(QueueTable):
    """Antrean tab PDF -> Gambar: jumlah halaman + status per file."""

    COLS = ["File", "Halaman", "Status"]

    def __init__(self, parent=None):
        super().__init__(self.COLS, parent)
        self.horizontalHeaderItem(1).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def _set(self, r, c, text, data=None, tip=None):
        it = super()._set(r, c, text, data, tip)
        if c == 1:
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return it

    def start(self):
        for r in range(self.rowCount()):
            self._set(r, 1, "")
            self._set(r, 2, "menunggu")

    def mark_running(self, r):
        if 0 <= r < self.rowCount():
            self._set(r, 2, "berjalan…")
            self.scrollToItem(self.item(r, 0))

    def mark_done(self, r, pages: int, message: str):
        if not (0 <= r < self.rowCount()):
            return
        if pages >= 0:
            self._set(r, 1, str(pages))
            self._set(r, 2, "selesai", tip=message or None)
        else:
            self._set(r, 2, "gagal", tip=message or None)


class QueuePanel(QWidget):
    """Antrean + bilah alat (Tambah / Hapus / Reset). API sama dengan FileListWidget lama."""

    changed = pyqtSignal()
    current_changed = pyqtSignal(str)
    cleared = pyqtSignal()

    def __init__(self, table: QueueTable, parent=None):
        super().__init__(parent)
        self.table = table
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.btn_add = QPushButton("＋ Tambah PDF")
        self.btn_add.setToolTip("Pilih file PDF (Ctrl+O). Bisa juga diseret ke jendela ini.")
        self.btn_add.clicked.connect(self.manual_add)
        self.btn_remove = QPushButton("Hapus")
        self.btn_remove.setToolTip("Hapus file terpilih dari antrean (Del)")
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear = QPushButton("Reset")
        self.btn_clear.setToolTip("Kosongkan seluruh antrean")
        self.btn_clear.clicked.connect(self.reset)
        self.lbl_count = QLabel()
        self.lbl_count.setObjectName("statusText")
        for b in (self.btn_add, self.btn_remove, self.btn_clear):
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(self.lbl_count)
        lay.addLayout(bar)
        lay.addWidget(table, 1)
        table.changed.connect(self._on_changed)
        table.current_changed.connect(self.current_changed)
        table.cleared.connect(self.cleared)
        self._refresh_bar()

    def _refresh_bar(self):
        n = self.table.rowCount()
        self.lbl_count.setText(f"{n} file" if n else "Belum ada file")
        self.btn_remove.setEnabled(n > 0 and not self.table._locked)
        self.btn_clear.setEnabled(n > 0 and not self.table._locked)

    def _on_changed(self):
        self._refresh_bar()
        self.changed.emit()

    # ---- API yang sama dengan FileListWidget lama ----
    def files(self) -> List[str]:
        return self.table.files()

    def current_path(self) -> str:
        return self.table.current_path()

    def add_path(self, path: str) -> bool:
        return self.table.add_path(path)

    def remove_selected(self):
        self.table.remove_selected()

    def reset(self):
        self.table.reset()

    def manual_add(self):
        if self.table._locked:
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Pilih PDF", "", "PDF Files (*.pdf)")
        for f in files:
            self.add_path(f)

    def set_enabled_controls(self, enabled: bool):
        """Tabel tetap aktif (agar status terbaca); yang dikunci hanyalah perubahan isi antrean."""
        self.table.set_locked(not enabled)
        self.btn_add.setEnabled(enabled)
        self._refresh_bar()

    # ---- drag & drop (didelegasikan oleh tab) ----
    @staticmethod
    def accept_drag(event):
        if event.mimeData().hasUrls():
            event.accept()

    def handle_drop(self, event):
        for url in event.mimeData().urls():
            self.add_path(url.toLocalFile())
