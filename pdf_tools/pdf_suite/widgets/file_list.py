# -*- coding: utf-8 -*-
"""Daftar PDF bersama (drag & drop) — dipakai tab Compressor dan PDF -> Gambar."""
import os
from typing import List

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                             QPushButton, QVBoxLayout, QWidget)


class FileListWidget(QWidget):
    changed = pyqtSignal()
    current_changed = pyqtSignal(str)
    cleared = pyqtSignal()

    def __init__(self, title: str = "Daftar PDF (Drag & Drop):", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel(title))
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.currentItemChanged.connect(lambda cur, _prev: self.current_changed.emit(self._path(cur)))
        lay.addWidget(self.list)
        btns = QHBoxLayout()
        self.btn_add = QPushButton("Tambah File")
        self.btn_add.clicked.connect(self.manual_add)
        self.btn_remove = QPushButton("Hapus Terpilih")
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear = QPushButton("Reset Semua")
        self.btn_clear.clicked.connect(self.reset)
        for b in (self.btn_add, self.btn_remove, self.btn_clear):
            btns.addWidget(b)
        lay.addLayout(btns)

    @staticmethod
    def _path(item) -> str:
        return item.data(Qt.UserRole) if item else ""

    def files(self) -> List[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def current_path(self) -> str:
        p = self._path(self.list.currentItem())
        if p:
            return p
        fs = self.files()
        return fs[0] if fs else ""

    def _renumber(self):
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setText(f"[{i + 1}] {os.path.basename(it.data(Qt.UserRole))}")
            it.setToolTip(it.data(Qt.UserRole))

    def add_path(self, path: str) -> bool:
        if not path.lower().endswith(".pdf") or path in self.files():
            return False
        it = QListWidgetItem()
        it.setData(Qt.UserRole, path)
        self.list.addItem(it)
        self._renumber()
        if self.list.currentItem() is None:
            self.list.setCurrentRow(0)
        self.changed.emit()
        return True

    def remove_selected(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))
        self._renumber()
        self.changed.emit()

    def reset(self):
        self.list.clear()
        self.changed.emit()
        self.cleared.emit()

    def manual_add(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Pilih PDF", "", "PDF Files (*.pdf)")
        for f in files:
            self.add_path(f)

    def set_enabled_controls(self, enabled: bool):
        for w in (self.list, self.btn_add, self.btn_remove, self.btn_clear):
            w.setEnabled(enabled)

    # ---- drag & drop (didelegasikan oleh tab) ----
    @staticmethod
    def accept_drag(event):
        if event.mimeData().hasUrls():
            event.accept()

    def handle_drop(self, event):
        for url in event.mimeData().urls():
            self.add_path(url.toLocalFile())
