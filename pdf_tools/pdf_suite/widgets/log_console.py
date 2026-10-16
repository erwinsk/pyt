# -*- coding: utf-8 -*-
from PyQt5.QtGui import QFontDatabase
from PyQt5.QtWidgets import QTextEdit


class LogConsole(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.NoWrap)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.setStyleSheet("background: #1e1e1e; color: #e8e8e8;")
        self.document().setMaximumBlockCount(5000)

    def append_line(self, text: str):
        self.append(text)
