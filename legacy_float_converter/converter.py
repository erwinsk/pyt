import struct
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QComboBox,
    QPushButton, QGridLayout, QMessageBox
)

class ModbusFloatConverter(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modbus Float32 <-> Uint16 Converter")
        self.init_ui()

    def init_ui(self):
        layout = QGridLayout()

        # --- Input Uint16 to Float ---
        layout.addWidget(QLabel("Register 1 (dec):"), 0, 0)
        self.reg1_input = QLineEdit()
        layout.addWidget(self.reg1_input, 0, 1)

        layout.addWidget(QLabel("Register 2 (dec):"), 1, 0)
        self.reg2_input = QLineEdit()
        layout.addWidget(self.reg2_input, 1, 1)

        layout.addWidget(QLabel("Encoding:"), 2, 0)
        self.encoding_box = QComboBox()
        self.encoding_box.addItems(["ABCD", "BADC", "CDAB", "DCBA"])
        layout.addWidget(self.encoding_box, 2, 1)

        btn_to_float = QPushButton("→ Convert to Float32")
        btn_to_float.clicked.connect(self.convert_to_float)
        layout.addWidget(btn_to_float, 3, 0, 1, 2)

        self.float_result = QLabel("Result: -")
        layout.addWidget(self.float_result, 4, 0, 1, 2)

        # --- Separator ---
        layout.addWidget(QLabel("─────────────────────────────────"), 5, 0, 1, 2)

        # --- Float32 to Uint16 ---
        layout.addWidget(QLabel("Float32 value:"), 6, 0)
        self.float_input = QLineEdit()
        layout.addWidget(self.float_input, 6, 1)

        btn_to_uint = QPushButton("→ Convert to Uint16")
        btn_to_uint.clicked.connect(self.convert_to_uint)
        layout.addWidget(btn_to_uint, 7, 0, 1, 2)

        self.uint_result = QLabel("Registers: -")
        layout.addWidget(self.uint_result, 8, 0, 1, 2)

        self.setLayout(layout)

    def convert_to_float(self):
        try:
            r1 = int(self.reg1_input.text())
            r2 = int(self.reg2_input.text())
            encoding = self.encoding_box.currentText()

            # ubah ke bytes sesuai encoding
            bytes_order = {
                "ABCD": [r1 >> 8, r1 & 0xFF, r2 >> 8, r2 & 0xFF],
                "BADC": [r1 & 0xFF, r1 >> 8, r2 & 0xFF, r2 >> 8],
                "CDAB": [r2 >> 8, r2 & 0xFF, r1 >> 8, r1 & 0xFF],
                "DCBA": [r2 & 0xFF, r2 >> 8, r1 & 0xFF, r1 >> 8],
            }[encoding]

            b = bytes(bytes_order)
            f = struct.unpack(">f", b)[0]
            self.float_result.setText(f"Result: {f:.6f}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Gagal konversi ke float:\n{e}")

    def convert_to_uint(self):
        try:
            f = float(self.float_input.text())
            encoding = self.encoding_box.currentText()
            b = struct.pack(">f", f)
            b_list = list(b)

            # urutkan kembali sesuai encoding
            order_map = {
                "ABCD": b_list,
                "BADC": [b_list[1], b_list[0], b_list[3], b_list[2]],
                "CDAB": [b_list[2], b_list[3], b_list[0], b_list[1]],
                "DCBA": [b_list[3], b_list[2], b_list[1], b_list[0]],
            }[encoding]

            r1 = (order_map[0] << 8) + order_map[1]
            r2 = (order_map[2] << 8) + order_map[3]
            self.uint_result.setText(f"Registers: {r1} , {r2}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Gagal konversi ke uint16:\n{e}")

if __name__ == "__main__":
    app = QApplication([])
    w = ModbusFloatConverter()
    w.show()
    app.exec_()
