# -*- coding: utf-8 -*-
from typing import Dict, List

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QKeySequence, QPixmap
from PyQt5.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
<<<<<<< HEAD
                             QPushButton, QRadioButton, QScrollArea, QShortcut, QVBoxLayout, QWidget)
=======
                             QPushButton, QRadioButton, QScrollArea, QShortcut, QSpinBox, QVBoxLayout, QWidget)
>>>>>>> 36ee49d (update pdf tools, arrange pdf)

from core import arranger as A
from widgets.common import WrapLabel


class PageSizeDialog(QDialog):
    """Pilih ukuran halaman hasil + cara menyesuaikan isi, dan berlaku untuk halaman terpilih atau semua."""

    def __init__(self, parent=None, n_selected: int = 0, n_total: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Ukuran halaman")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.combo_preset = QComboBox()
        self.combo_preset.addItem("Kembalikan ukuran asli", None)
        for name in A.PAGE_PRESETS:
            self.combo_preset.addItem(name, name)
        self.combo_preset.addItem("Kustom (mm)…", "custom")
<<<<<<< HEAD
=======
        self.combo_preset.addItem("Relatif terhadap ukuran asli (%)…", "relative")
>>>>>>> 36ee49d (update pdf tools, arrange pdf)
        self.combo_preset.setCurrentIndex(self.combo_preset.findData("A4"))
        form.addRow("Ukuran", self.combo_preset)

        self.spin_w = QDoubleSpinBox()
        self.spin_h = QDoubleSpinBox()
        for s, v in ((self.spin_w, 210.0), (self.spin_h, 297.0)):
            s.setRange(20, 3000)
            s.setDecimals(1)
            s.setSuffix(" mm")
            s.setValue(v)
        self.row_custom = QWidget()
        rc = QHBoxLayout(self.row_custom)
        rc.setContentsMargins(0, 0, 0, 0)
        rc.addWidget(self.spin_w)
        rc.addWidget(QLabel("×"))
        rc.addWidget(self.spin_h)
        self.lbl_custom = QLabel("Lebar × tinggi")           # label & isi baris disembunyikan bersama (Qt5 tidak otomatis)
        form.addRow(self.lbl_custom, self.row_custom)

<<<<<<< HEAD
=======
        self.spin_pct = QSpinBox()
        self.spin_pct.setRange(5, 1000)
        self.spin_pct.setSingleStep(5)
        self.spin_pct.setValue(50)
        self.spin_pct.setSuffix(" %")
        self.lbl_pct = QLabel("Skala")
        form.addRow(self.lbl_pct, self.spin_pct)
        self.lbl_pct_hint = WrapLabel("Dihitung dari ukuran ASLI tiap halaman (bentuknya tidak berubah), jadi menerapkan "
                                      "50% dua kali tetap 50%. Halaman berbeda ukuran tetap berbeda ukuran.")
        self.lbl_pct_hint.setObjectName("hint")
        form.addRow(self.lbl_pct_hint)

>>>>>>> 36ee49d (update pdf tools, arrange pdf)
        self.combo_orient = QComboBox()
        self.combo_orient.addItem("Otomatis (ikuti bentuk halaman)", "auto")
        self.combo_orient.addItem("Potret", "portrait")
        self.combo_orient.addItem("Lanskap", "landscape")
        form.addRow("Orientasi", self.combo_orient)

        self.combo_fit = QComboBox()
        self.combo_fit.addItem("Sesuaikan (proporsi tetap, di tengah)", "fit")
        self.combo_fit.addItem("Regangkan memenuhi halaman", "stretch")
        form.addRow("Isi halaman", self.combo_fit)

        self.spin_margin = QDoubleSpinBox()
        self.spin_margin.setRange(0, 100)
        self.spin_margin.setDecimals(1)
        self.spin_margin.setSuffix(" mm")
        form.addRow("Margin", self.spin_margin)
        lay.addLayout(form)

        self.rb_sel = QRadioButton("Halaman terpilih (%d)" % n_selected)
        self.rb_all = QRadioButton("Semua halaman (%d)" % n_total)
        self.rb_sel.setEnabled(n_selected > 0)
        (self.rb_sel if n_selected > 0 else self.rb_all).setChecked(True)
        lay.addWidget(self.rb_sel)
        lay.addWidget(self.rb_all)

        note = WrapLabel("Ubah ukuran menempelkan halaman sebagai objek: teks dan vektor tetap tajam, "
                         "tetapi tautan/anotasi pada halaman itu tidak terbawa.")
        note.setObjectName("hint")
        lay.addWidget(note)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Terapkan")
        bb.button(QDialogButtonBox.Cancel).setText("Batal")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.combo_preset.currentIndexChanged.connect(self._sync)
        self._sync()

    def _sync(self):
        data = self.combo_preset.currentData()
        self.row_custom.setVisible(data == "custom")
        self.lbl_custom.setVisible(data == "custom")
<<<<<<< HEAD
        for w in (self.combo_orient, self.combo_fit, self.spin_margin):
            w.setEnabled(data is not None)

    def values(self) -> Dict:
        data = self.combo_preset.currentData()
        if data is None:
=======
        for w in (self.spin_pct, self.lbl_pct, self.lbl_pct_hint):
            w.setVisible(data == "relative")
        for w in (self.combo_orient, self.combo_fit, self.spin_margin):
            w.setEnabled(data not in (None, "relative"))      # relatif: bentuk halaman tetap, hanya skala

    def values(self) -> Dict:
        data = self.combo_preset.currentData()
        if data is None or data == "relative":
>>>>>>> 36ee49d (update pdf tools, arrange pdf)
            size = None
        elif data == "custom":
            size = (self.spin_w.value() * A.MM, self.spin_h.value() * A.MM)
        else:
            size = A.PAGE_PRESETS[data]
<<<<<<< HEAD
        return {"size": size, "orientation": self.combo_orient.currentData(), "fit": self.combo_fit.currentData(),
=======
        scale = self.spin_pct.value() / 100.0 if data == "relative" else None
        return {"size": size, "scale": scale, "orientation": self.combo_orient.currentData(), "fit": self.combo_fit.currentData(),
>>>>>>> 36ee49d (update pdf tools, arrange pdf)
                "margin": self.spin_margin.value() * A.MM, "scope": "selected" if self.rb_sel.isChecked() else "all"}


class PreviewDialog(QDialog):
    """Pratinjau halaman besar sebagaimana akan tersimpan (putar + ukuran), dengan navigasi."""

    def __init__(self, parent, refs: List[A.PageRef], sources: Dict[int, A.Source], index: int):
        super().__init__(parent)
        self.refs, self.sources, self.i = refs, sources, max(0, min(index, len(refs) - 1))
        self.resize(720, 820)
        lay = QVBoxLayout(self)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignCenter)
        self.lbl = QLabel()
        self.lbl.setAlignment(Qt.AlignCenter)
        self.scroll.setWidget(self.lbl)
        lay.addWidget(self.scroll, 1)
        bar = QHBoxLayout()
        self.btn_prev = QPushButton("◀ Sebelumnya")
        self.btn_next = QPushButton("Berikutnya ▶")
        self.lbl_info = QLabel()
        self.lbl_info.setObjectName("statusText")
        btn_close = QPushButton("Tutup")
        self.btn_prev.clicked.connect(lambda: self.go(-1))
        self.btn_next.clicked.connect(lambda: self.go(1))
        btn_close.clicked.connect(self.accept)
        bar.addWidget(self.btn_prev)
        bar.addWidget(self.btn_next)
        bar.addWidget(self.lbl_info, 1)
        bar.addWidget(btn_close)
        lay.addLayout(bar)
        QShortcut(QKeySequence(Qt.Key_Left), self, activated=lambda: self.go(-1))
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=lambda: self.go(1))
        self.show_page()

    def go(self, d: int):
        n = self.i + d
        if 0 <= n < len(self.refs):
            self.i = n
            self.show_page()

    def show_page(self):
        ref = self.refs[self.i]
        try:
            w, h, rgb = A.render_page(ref, self.sources, 1000)
            self.lbl.setPixmap(QPixmap.fromImage(QImage(rgb, w, h, w * 3, QImage.Format_RGB888).copy()))
        except Exception as e:
            self.lbl.setText("Gagal menampilkan halaman: %s" % e)
        self.setWindowTitle("Halaman %d dari %d" % (self.i + 1, len(self.refs)))
        self.lbl_info.setText(A.describe_size(ref.display_size()))
        self.btn_prev.setEnabled(self.i > 0)
        self.btn_next.setEnabled(self.i < len(self.refs) - 1)
