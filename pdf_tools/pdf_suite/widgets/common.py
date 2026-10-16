# -*- coding: utf-8 -*-
"""Util kecil untuk UI."""
from pathlib import Path

from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices


def fmt_size(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return str(n)


def open_folder(path) -> bool:
    p = Path(path)
    if p.is_file():
        p = p.parent
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
