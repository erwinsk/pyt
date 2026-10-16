# -*- coding: utf-8 -*-
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem
import os

from .common import fmt_size, open_folder

COLS = ["File", "Asli", "Hasil", "Hemat", "Waktu", "OCR cache", "Status"]


class ResultTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, len(COLS), parent)
        self.setHorizontalHeaderLabels(COLS)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.verticalHeader().setVisible(False)
        h = self.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(COLS)):
            h.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.cellDoubleClicked.connect(self._open)

    def start(self, files):
        self.setRowCount(0)
        for f in files:
            r = self.rowCount()
            self.insertRow(r)
            self._set(r, 0, os.path.basename(f), f)
            for c in range(1, len(COLS)):
                self._set(r, c, "")
            self._set(r, 6, "menunggu")

    def _set(self, r, c, text, data=None):
        it = QTableWidgetItem(text)
        if data is not None:
            it.setData(Qt.UserRole, data)
        if c in (1, 2, 3, 4):
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setItem(r, c, it)

    def mark_running(self, r):
        if 0 <= r < self.rowCount():
            self._set(r, 6, "berjalan…")

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
        status = res.get("status", "")
        it = QTableWidgetItem(status)
        color = {"selesai": "#2e7d32", "gagal": "#c62828", "dibatalkan": "#ef6c00", "tidak dikecilkan": "#ef6c00"}.get(status)
        if color:
            it.setForeground(QBrush(QColor(color)))
        if res.get("message"):
            it.setToolTip(res["message"])
        self.setItem(r, 6, it)

    def _open(self, row, _col):
        it = self.item(row, 2)
        out = it.data(Qt.UserRole) if it else None
        if out:
            open_folder(out)
