"""Tab Float Converter: float32 <-> dua register 16-bit untuk empat urutan byte."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox, QGridLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QWidget

from .inti import URUTAN_FLOAT, float32_ke_register, register_ke_float32


def _ke_int(teks):
    """Bilangan bulat dari teks desimal atau heksadesimal berawalan 0x."""
    t = teks.strip()
    if not t:
        raise ValueError("Isian register kosong.")
    return int(t, 16) if t.lower().startswith("0x") else int(t, 10)


class KonverterMixin:
    """Tab Float Converter (tidak butuh koneksi Modbus)."""

    def buat_tab_float_converter(self):
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.setAlignment(Qt.AlignTop)

        layout.addWidget(QLabel("<b>Register (16-bit) → Float32</b>"), 0, 0, 1, 2)

        layout.addWidget(QLabel("Register 1 (dec / 0xHEX):"), 1, 0)
        self.txt_fc_reg1 = QLineEdit()
        layout.addWidget(self.txt_fc_reg1, 1, 1)

        layout.addWidget(QLabel("Register 2 (dec / 0xHEX):"), 2, 0)
        self.txt_fc_reg2 = QLineEdit()
        layout.addWidget(self.txt_fc_reg2, 2, 1)

        layout.addWidget(QLabel("Urutan Byte/Word:"), 3, 0)
        self.combo_fc_encoding = QComboBox()
        self.combo_fc_encoding.addItems(list(URUTAN_FLOAT))
        self.combo_fc_encoding.setToolTip(
            "ABCD = big-endian standar, DCBA = little-endian penuh,\n"
            "BADC/CDAB = word/byte-swapped (umum pada beberapa merk PLC/sensor)."
        )
        layout.addWidget(self.combo_fc_encoding, 3, 1)

        btn_ke_float = QPushButton("↓ Convert ke Float32")
        btn_ke_float.clicked.connect(self._fc_convert_ke_float)
        layout.addWidget(btn_ke_float, 4, 0, 1, 2)

        self.lbl_fc_hasil_float = QLabel("Hasil: -")
        self.lbl_fc_hasil_float.setStyleSheet("font-weight: bold;")
        self.lbl_fc_hasil_float.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.lbl_fc_hasil_float, 5, 0, 1, 2)

        garis = QLabel("─" * 40)
        garis.setAlignment(Qt.AlignCenter)
        layout.addWidget(garis, 6, 0, 1, 2)

        layout.addWidget(QLabel("<b>Float32 → Register (16-bit)</b>"), 7, 0, 1, 2)

        layout.addWidget(QLabel("Nilai Float32:"), 8, 0)
        self.txt_fc_float = QLineEdit()
        layout.addWidget(self.txt_fc_float, 8, 1)

        btn_ke_reg = QPushButton("↓ Convert ke Register")
        btn_ke_reg.clicked.connect(self._fc_convert_ke_register)
        layout.addWidget(btn_ke_reg, 9, 0, 1, 2)

        self.lbl_fc_hasil_reg = QLabel("Register: -")
        self.lbl_fc_hasil_reg.setStyleSheet("font-weight: bold;")
        self.lbl_fc_hasil_reg.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.lbl_fc_hasil_reg, 10, 0, 1, 2)

        layout.setRowStretch(11, 1)
        self.tabs.addTab(tab, "Float Converter")

    def _fc_convert_ke_float(self):
        try:
            r1 = _ke_int(self.txt_fc_reg1.text())
            r2 = _ke_int(self.txt_fc_reg2.text())
            nilai = register_ke_float32(r1, r2, self.combo_fc_encoding.currentText())
            self.lbl_fc_hasil_float.setText(f"Hasil: {nilai:.6f}")
        except ValueError as e:
            QMessageBox.critical(self, "Error", f"Gagal konversi ke float:\n{e}")

    def _fc_convert_ke_register(self):
        try:
            teks = self.txt_fc_float.text().strip().replace(",", ".")   # koma desimal ala Indonesia
            if not teks:
                raise ValueError("Isian nilai float kosong.")
            r1, r2 = float32_ke_register(float(teks), self.combo_fc_encoding.currentText())
            self.lbl_fc_hasil_reg.setText(f"Register: {r1} , {r2}   (0x{r1:04X} , 0x{r2:04X})")
        except ValueError as e:
            QMessageBox.critical(self, "Error", f"Gagal konversi ke register:\n{e}")
