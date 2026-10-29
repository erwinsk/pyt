# -*- coding: utf-8 -*-
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFontDatabase
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSizePolicy, QTextEdit, QToolButton,
                             QVBoxLayout, QWidget)


class ElidedLabel(QLabel):
    """Label satu baris yang dipotong dengan '…' dan TIDAK memaksa lebar minimum (tidak melebarkan jendela)."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setTextFormat(Qt.PlainText)
        self.setMinimumWidth(40)
        self.set_full_text(text)

    def set_full_text(self, text: str):
        self._full = text
        self.setToolTip(text if text else "")
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        self.setText(self.fontMetrics().elidedText(self._full, Qt.ElideRight, max(10, self.width())))


class LogConsole(QTextEdit):
    line_added = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("log")
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.NoWrap)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))   # warna mengikuti tema (lihat theme.py)
        self.document().setMaximumBlockCount(5000)

    def append_line(self, text: str):
        self.append(text)
        self.line_added.emit(text)


class LogDrawer(QWidget):
    """Laci log: satu baris (judul + baris terakhir) saat tertutup, konsol penuh saat dibuka."""

    OPEN_HEIGHT = 150

    def __init__(self, parent=None):
        super().__init__(parent)
        self.console = LogConsole()
        self.console.setFixedHeight(self.OPEN_HEIGHT)
        self.console.setVisible(False)

        self.btn_toggle = QPushButton("▸ Log")
        self.btn_toggle.setObjectName("link")
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setToolTip("Tampilkan / sembunyikan log aktivitas (Ctrl+L). Terbuka otomatis saat ada galat.")
        self.btn_toggle.toggled.connect(self._on_toggled)
        self.lbl_last = ElidedLabel("")
        self.lbl_last.setObjectName("statusText")
        self.btn_clear = QToolButton()
        self.btn_clear.setObjectName("link")
        self.btn_clear.setText("Bersihkan")
        self.btn_clear.setVisible(False)
        self.btn_clear.clicked.connect(self.console.clear)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        head.addWidget(self.btn_toggle)
        head.addWidget(self.lbl_last, 1)
        head.addWidget(self.btn_clear)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addLayout(head)
        lay.addWidget(self.console)

        self.console.line_added.connect(self._on_line)
        self.console.document().contentsChanged.connect(self._on_contents)

    def _on_toggled(self, on: bool):
        self.console.setVisible(on)
        self.btn_clear.setVisible(on)
        self.btn_toggle.setText(("▾ " if on else "▸ ") + "Log")

    def _on_line(self, text: str):
        self.lbl_last.set_full_text(text.strip())

    def _on_contents(self):
        if self.console.document().isEmpty():
            self.lbl_last.set_full_text("")

    def set_open(self, on: bool):
        self.btn_toggle.setChecked(on)

    def toggle(self):
        self.btn_toggle.toggle()

    def is_open(self) -> bool:
        return self.btn_toggle.isChecked()
