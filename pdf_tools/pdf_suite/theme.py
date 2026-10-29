# -*- coding: utf-8 -*-
"""Tema aplikasi: satu stylesheet ringan yang warnanya DIAMBIL DARI PALET SISTEM.

Tidak ada warna dasar yang di-hardcode untuk latar/teks/garis: semuanya dicampur dari palet aktif,
sehingga otomatis cocok dengan tema terang maupun gelap desktop. Hanya warna semantik status
(hijau/kuning/merah) yang tetap, lalu disesuaikan kecerahannya menurut tema.
"""
import os
import tempfile
from pathlib import Path
from string import Template

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QPainter, QPalette, QPen, QPixmap
from PyQt5.QtWidgets import QApplication

# Warna semantik status (disesuaikan terang/gelap lewat semantic()).
_SEMANTIC = {
    "ok": QColor(34, 148, 84),
    "warn": QColor(214, 133, 0),
    "bad": QColor(208, 58, 52),
}


def is_dark(palette: QPalette) -> bool:
    return palette.color(QPalette.Window).lightness() < 128


def mix(a: QColor, b: QColor, t: float) -> QColor:
    """Campur a ke arah b sebesar t (0..1)."""
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


def semantic(kind: str, palette: QPalette) -> QColor:
    """Warna teks untuk status: 'ok' | 'warn' | 'bad' | 'info' | 'neutral'."""
    if kind == "info":
        return QColor(palette.color(QPalette.Highlight))
    if kind == "neutral":
        return mix(palette.color(QPalette.Text), palette.color(QPalette.Window), 0.35)
    c = QColor(_SEMANTIC.get(kind, _SEMANTIC["warn"]))
    return c.lighter(135) if is_dark(palette) else c.darker(105)


_QSS = Template("""
QTabWidget::pane { border: 0; border-top: 1px solid $border; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab { background: transparent; color: $muted; border: 0; border-bottom: 2px solid transparent;
               padding: 8px 18px; margin-right: 2px; }
QTabBar::tab:hover:!selected { color: $text; }
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $accent; }
QTabWidget::tab-bar { left: 8px; }

QPushButton, QToolButton { background: $card; border: 1px solid $border; border-radius: 6px; padding: 5px 12px; }
QPushButton:hover, QToolButton:hover { background: $hover; }
QPushButton:pressed, QToolButton:pressed { background: $border; }
QPushButton:disabled, QToolButton:disabled { color: $disabled; background: transparent; }
QPushButton:checked, QToolButton:checked { background: $hover; }
QToolButton::menu-indicator { image: none; width: 0; }

QPushButton#tool, QToolButton#tool { padding: 5px 9px; }
QPushButton#primary { background: $accent; color: $accentText; border: 1px solid $accent;
                      font-weight: 600; padding: 7px 20px; }
QPushButton#primary:hover { background: $accentHover; border-color: $accentHover; }
QPushButton#primary:disabled { background: $border; border-color: $border; color: $disabled; }

QPushButton#link, QToolButton#link { background: transparent; border: 0; padding: 4px 6px; text-align: left; }
QPushButton#link:hover, QToolButton#link:hover { background: $hover; }
QPushButton#link:disabled, QToolButton#link:disabled { color: $disabled; }

QToolButton#chip { border-radius: 11px; padding: 2px 11px; background: transparent; }
QToolButton#chip[state="ok"] { color: $ok; border-color: $okLine; }
QToolButton#chip[state="warn"] { color: $warn; border-color: $warnLine; background: $warnBg; font-weight: 600; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: $card; border: 1px solid $border;
        border-radius: 6px; padding: 4px 8px; min-height: 20px;
        selection-background-color: $accent; selection-color: $accentText; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: $accent; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { color: $disabled; background: transparent; }
QLineEdit:read-only { background: $hover; }
QComboBox { padding-right: 24px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: 0; }
QComboBox::down-arrow { image: url("$chevDown"); width: 10px; height: 10px; }
QComboBox::down-arrow:disabled { image: url("$chevDownDis"); }
QComboBox QAbstractItemView { background: $card; border: 1px solid $border; outline: 0;
        selection-background-color: $selBg; selection-color: $text; }
QSpinBox, QDoubleSpinBox { padding-right: 22px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right;
        width: 20px; border: 0; margin: 3px 3px 0 0; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right;
        width: 20px; border: 0; margin: 0 3px 3px 0; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("$chevUp"); width: 8px; height: 8px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url("$chevDown"); width: 8px; height: 8px; }
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled { image: url("$chevUpDis"); }
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled { image: url("$chevDownDis"); }

QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid $scroll; border-radius: 4px; background: $card; }
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url("$check"); }
QCheckBox::indicator:disabled { border-color: $border; background: transparent; }
QCheckBox::indicator:checked:disabled { background: $disabled; border-color: $disabled; }

QRadioButton { spacing: 8px; }
QRadioButton::indicator { width: 16px; height: 16px; border: 1px solid $scroll; border-radius: 9px; background: $card; }
QRadioButton::indicator:hover { border-color: $accent; }
QRadioButton::indicator:checked { border-color: $accent;
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                    stop:0 $accent, stop:0.42 $accent, stop:0.5 $card, stop:1 $card); }
QRadioButton::indicator:disabled { border-color: $border; background: transparent; }

QFrame#card { background: $card; border: 1px solid $border; border-radius: 10px; }
QLabel#cardTitle { color: $muted; font-weight: 600; font-size: 8pt; }
QLabel#hint { color: $muted; font-size: 8pt; }
QLabel#statusText { color: $muted; }
QLabel#banner { background: $warnBg; border: 1px solid $warnLine; border-radius: 8px; padding: 8px 10px; }

QTableWidget { background: $card; border: 1px solid $border; border-radius: 8px; outline: 0;
               gridline-color: transparent; selection-background-color: $selBg; selection-color: $text; }
QTableWidget::item { border: 0; padding: 0 6px; }
QTableWidget::item:selected { background: $selBg; color: $text; }
QHeaderView { background: transparent; border: 0; }
QHeaderView::section { background: transparent; color: $muted; border: 0; border-bottom: 1px solid $border;
                       padding: 6px 6px; font-weight: 600; font-size: 8pt; }
QTableCornerButton::section { background: transparent; border: 0; }

QListWidget#pages { background: $card; border: 1px solid $border; border-radius: 8px; outline: 0; padding: 4px; }
QListWidget#pages::item { border-radius: 8px; padding: 4px; color: $text; }
QListWidget#pages::item:hover:!selected { background: $hover; }
QListWidget#pages::item:selected { background: $selBg; color: $text; }

QScrollArea#rightScroll { background: transparent; border: 0; }
QScrollArea#rightScroll > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $scroll; border-radius: 3px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: $muted; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $scroll; border-radius: 3px; min-width: 28px; }
QScrollBar::handle:horizontal:hover { background: $muted; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QProgressBar { background: $border; border: 0; border-radius: 3px; min-height: 6px; max-height: 6px; }
QProgressBar::chunk { background: $accent; border-radius: 3px; }

QTextEdit#log { background: $card; border: 1px solid $border; border-radius: 8px; padding: 4px; }
""")


def _chevron(path: Path, color: QColor, up: bool):
    """Gambar panah kecil (chevron) 16x16 berwarna `color` ke file PNG (dipakai stylesheet)."""
    pm = QPixmap(16, 16)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color, 1.9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    y1, y2 = (10.5, 5.5) if up else (5.5, 10.5)
    p.drawPolyline(QPointF(3.8, y1), QPointF(8.0, y2), QPointF(12.2, y1))
    p.end()
    pm.save(str(path), "PNG")


def _check_file(d: Path, color: QColor) -> str:
    f = d / f"check_{color.name()[1:]}.png"
    if not f.exists():
        pm = QPixmap(16, 16)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(color, 2.1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(QPointF(3.8, 8.4), QPointF(6.8, 11.4), QPointF(12.4, 4.9))
        p.end()
        pm.save(str(f), "PNG")
    return f.as_posix()


def _chevron_files(palette: QPalette) -> dict:
    """Panah untuk combobox/spinbox. Nama file memuat kode warna agar cache gambar Qt tidak basi saat tema berganti."""
    d = Path(tempfile.gettempdir()) / "pdfsuite_icons"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    text, window = palette.color(QPalette.Text), palette.color(QPalette.Window)
    on, off = mix(text, window, 0.25), mix(text, window, 0.65)
    out = {}
    for key, color, up in (("chevDown", on, False), ("chevUp", on, True),
                           ("chevDownDis", off, False), ("chevUpDis", off, True)):
        f = d / f"{key}_{color.name()[1:]}.png"
        if not f.exists():
            _chevron(f, color, up)
        out[key] = f.as_posix()
    out["check"] = _check_file(d, palette.color(QPalette.HighlightedText))
    return out


def build_qss(palette: QPalette) -> str:
    c = palette.color
    text, window, base = c(QPalette.Text), c(QPalette.Window), c(QPalette.Base)
    accent = c(QPalette.Highlight)
    dark = is_dark(palette)
    warn = semantic("warn", palette)
    ok = semantic("ok", palette)
    vals = {
        "text": text.name(),
        "card": base.name(),
        "border": mix(window, text, 0.16).name(),
        "muted": mix(text, window, 0.42).name(),
        "disabled": mix(text, window, 0.62).name(),
        "hover": mix(window, text, 0.07).name(),
        "scroll": mix(window, text, 0.28).name(),
        "selBg": mix(base, accent, 0.20 if dark else 0.16).name(),
        "accent": accent.name(),
        "accentHover": (accent.lighter(115) if dark else accent.darker(112)).name(),
        "accentText": c(QPalette.HighlightedText).name(),
        "ok": ok.name(),
        "okLine": mix(ok, window, 0.55).name(),
        "warn": warn.name(),
        "warnLine": mix(warn, window, 0.45).name(),
        "warnBg": mix(window, warn, 0.14).name(),
    }
    vals.update(_chevron_files(palette))
    return _QSS.substitute(vals)


def apply(app: QApplication):
    """Pasang gaya Fusion + stylesheet berbasis palet. Panggil sekali setelah QApplication dibuat.
    Stylesheet dibangun ulang otomatis bila palet sistem berganti (mis. tema terang <-> gelap).

    Sengaja memakai sinyal paletteChanged (fungsi biasa), BUKAN filter event Python pada QApplication:
    filter semacam itu masih dipanggil saat QApplication dihancurkan dan menyebabkan segfault acak saat keluar."""
    app.setStyle("Fusion")
    last = {"qss": ""}

    def refresh(*_):
        qss = build_qss(app.palette())
        if qss != last["qss"]:          # tanpa pengecekan ini setStyleSheet bisa memicu putaran tanpa akhir
            last["qss"] = qss
            app.setStyleSheet(qss)

    refresh()
    app.paletteChanged.connect(refresh)
