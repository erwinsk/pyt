# -*- coding: utf-8 -*-
"""Util kecil untuk UI."""
from pathlib import Path

from PyQt5.QtCore import QSize, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QCheckBox, QComboBox, QLabel, QSizePolicy


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


def side_width(total: int) -> int:
    """Lebar kolom pengaturan (kanan): ikut lebar jendela, dibatasi 330-400 px, agar antrean (kiri) tetap lega."""
    return max(330, min(400, int(total * 0.34)))


def make_shrinkable(combo: QComboBox, chars: int = 10):
    """Combobox boleh lebih sempit dari item terpanjangnya (teks dipotong di kolom), tanpa memaksa
    kolom pengaturan melebar. Daftar popup tetap dilebarkan agar teks lengkap terbaca."""
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(chars)
    fit_popup(combo)


def fit_popup(combo: QComboBox):
    fm = combo.fontMetrics()
    widest = max((fm.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())), default=0)
    combo.view().setMinimumWidth(widest + 44)


class WrapLabel(QLabel):
    """Label yang membungkus teks ke lebar yang tersedia dan TIDAK memaksa lebar minimum.
    (QLabel biasa dengan word-wrap melaporkan lebar minimum heuristik yang besar untuk teks panjang,
    sehingga kolom sempit meluber.)"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)

    def minimumSizeHint(self):
        return QSize(40, super().minimumSizeHint().height())


class ShrinkCheck(QCheckBox):
    """Checkbox yang tidak memaksa lebar minimum sebesar teksnya (kolom sempit tidak meluber)."""

    def __init__(self, *args):
        super().__init__(*args)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)   # 'Minimum' bawaan memakai sizeHint sebagai batas

    def minimumSizeHint(self):
        return QSize(60, super().minimumSizeHint().height())
