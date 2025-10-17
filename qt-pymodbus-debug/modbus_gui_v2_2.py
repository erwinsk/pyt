import sys
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QComboBox, QPushButton, QTextEdit,
    QTableWidget, QTableWidgetItem, QDoubleSpinBox, QMessageBox, QSplitter, QHeaderView, QSpinBox
)
from PyQt5.QtCore import QTimer, Qt

# Pilih versi pymodbus yang digunakan
# from modbus_client import ModbusClient
from modbus_client_v3 import ModbusClient

class ModbusGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Alat Debug Modbus")
        self.resize(1000, 600)
        self.client = None
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.read_loop)
        self.setup_ui()

    def setup_ui(self):
        main_layout = QHBoxLayout()
        left_layout = QVBoxLayout()
        form = QGridLayout()

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["RTU", "TCP"])
        form.addWidget(QLabel("Mode"), 0, 0)
        form.addWidget(self.mode_combo, 0, 1)

        self.port_edit = QLineEdit("/dev/ttyUSB0")
        self.baud_edit = QLineEdit("9600")
        self.host_edit = QLineEdit("127.0.0.1")
        self.tcp_port_edit = QLineEdit("502")

        self.parity_combo = QComboBox()
        self.parity_combo.addItems(["N", "E", "O"])
        self.bytesize_combo = QComboBox()
        self.bytesize_combo.addItems(["7", "8"])
        self.stopbits_combo = QComboBox()
        self.stopbits_combo.addItems(["1", "2"])
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(0.1, 10.0)
        self.timeout_spin.setSingleStep(0.1)
        self.timeout_spin.setValue(1.0)

        form.addWidget(QLabel("Port"), 1, 0)
        form.addWidget(self.port_edit, 1, 1)
        form.addWidget(QLabel("Baudrate"), 1, 2)
        form.addWidget(self.baud_edit, 1, 3)
        form.addWidget(QLabel("Parity"), 1, 4)
        form.addWidget(self.parity_combo, 1, 5)
        form.addWidget(QLabel("Byte Size"), 2, 4)
        form.addWidget(self.bytesize_combo, 2, 5)
        form.addWidget(QLabel("Stop Bits"), 3, 4)
        form.addWidget(self.stopbits_combo, 3, 5)
        form.addWidget(QLabel("Timeout (s)"), 4, 4)
        form.addWidget(self.timeout_spin, 4, 5)

        self.unit_edit = QSpinBox(); self.unit_edit.setRange(0, 256); self.unit_edit.setValue(1)
        self.reg_edit = QSpinBox(); self.reg_edit.setRange(0, 100000)
        self.qty_edit = QSpinBox(); self.qty_edit.setRange(0, 1000); self.qty_edit.setValue(1)
        self.encoding_combo = QComboBox()
        self.encoding_combo.addItems(["float32[ABCD]", "float32[DCBA]", "float32[CDAB]", "float32[BADC]", "u16"])
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.1, 600.0); self.interval_spin.setValue(1.0)
        self.func_combo = QComboBox()
        self.func_combo.addItems(["Holding", "Input", "Coils", "Discrete", "Write Single", "Write Multiple"])
        self.write_value_edit = QLineEdit(); self.write_value_edit.setPlaceholderText("Value for write")

        form.addWidget(QLabel("Host"), 2, 0)
        form.addWidget(self.host_edit, 2, 1)
        form.addWidget(QLabel("TCP Port"), 2, 2)
        form.addWidget(self.tcp_port_edit, 2, 3)
        form.addWidget(QLabel("Unit ID"), 3, 0)
        form.addWidget(self.unit_edit, 3, 1)
        form.addWidget(QLabel("Register"), 3, 2)
        form.addWidget(self.reg_edit, 3, 3)
        form.addWidget(QLabel("Quantity"), 4, 0)
        form.addWidget(self.qty_edit, 4, 1)
        form.addWidget(QLabel("Encoding"), 4, 2)
        form.addWidget(self.encoding_combo, 4, 3)
        form.addWidget(QLabel("Interval (s)"), 5, 0)
        form.addWidget(self.interval_spin, 5, 1)
        form.addWidget(QLabel("Function"), 5, 2)
        form.addWidget(self.func_combo, 5, 3)
        form.addWidget(QLabel("Write Value"), 6, 0)
        form.addWidget(self.write_value_edit, 6, 1)

        left_layout.addLayout(form)

        btn_layout = QHBoxLayout()
        for btn in ["Connect", "Disconnect", "Send Once", "Start Polling", "Stop", "Clear", "Exit"]:
            b = QPushButton(btn)
            setattr(self, btn.replace(" ", "_").lower() + "_btn", b)
            btn_layout.addWidget(b)
        left_layout.addLayout(btn_layout)

        self.log_box = QTextEdit(); self.log_box.setReadOnly(True)
        self.txrx_box = QTextEdit(); self.txrx_box.setReadOnly(True)
        left_layout.addWidget(QLabel("Log")); left_layout.addWidget(self.log_box)
        left_layout.addWidget(QLabel("TX/RX HEX")); left_layout.addWidget(self.txrx_box)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Index", "Value"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Stretch)

        splitter = QSplitter(Qt.Horizontal)
        left_container = QWidget(); left_container.setLayout(left_layout)
        splitter.addWidget(left_container); splitter.addWidget(self.table)
        splitter.setStretchFactor(0, 3); splitter.setStretchFactor(1, 4)
        main_layout.addWidget(splitter)
        self.setLayout(main_layout)

        self.mode_combo.currentIndexChanged.connect(self.update_mode_fields)
        self.update_mode_fields()
        self.func_combo.currentIndexChanged.connect(self.update_function_field)
        self.update_function_field()
        self.update_button_states(False)

        self.connect_btn.clicked.connect(self.connect_modbus)
        self.disconnect_btn.clicked.connect(self.disconnect_modbus)
        self.send_once_btn.clicked.connect(self.read_once)
        self.start_polling_btn.clicked.connect(self.start_polling)
        self.stop_btn.clicked.connect(self.stop_polling)
        self.clear_btn.clicked.connect(self.clear_all)
        self.exit_btn.clicked.connect(self.close)

    def update_mode_fields(self):
        mode = self.mode_combo.currentText().lower()
        if mode == 'rtu':
            for w in [self.port_edit, self.baud_edit, self.parity_combo,
                      self.bytesize_combo, self.stopbits_combo, self.timeout_spin]:
                w.setEnabled(True)
            for w in [self.host_edit, self.tcp_port_edit]:
                w.setEnabled(False)
        else:
            for w in [self.port_edit, self.baud_edit, self.parity_combo,
                      self.bytesize_combo, self.stopbits_combo, self.timeout_spin]:
                w.setEnabled(False)
            for w in [self.host_edit, self.tcp_port_edit]:
                w.setEnabled(True)

    def update_button_states(self, connected=False):
        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)
        self.send_once_btn.setEnabled(connected)
        self.start_polling_btn.setEnabled(connected)
        self.stop_btn.setEnabled(connected)
        self.clear_btn.setEnabled(True)
        self.exit_btn.setEnabled(True)

    def connect_modbus(self):
        mode = self.mode_combo.currentText().lower()
        cfg = {'type': mode}
        if mode == 'rtu':
            cfg.update({
                'port': self.port_edit.text(),
                'baudrate': int(self.baud_edit.text()),
                'parity': self.parity_combo.currentText(),
                'bytesize': int(self.bytesize_combo.currentText()),
                'stopbits': int(self.stopbits_combo.currentText()),
                'timeout': float(self.timeout_spin.value())
            })
        else:
            cfg.update({
                'host': self.host_edit.text(),
                'port': int(self.tcp_port_edit.text()),
                'timeout': float(self.timeout_spin.value())
            })
        self.client = ModbusClient(mode, cfg)
        if self.client.open():
            self.log_box.append(f"[{datetime.now()}] Connected ({mode.upper()})")
            self.update_button_states(True)
        else:
            QMessageBox.warning(self, "Connection Failed", "Cannot open Modbus connection.")
            self.client = None
            self.update_button_states(False)

    def disconnect_modbus(self):
        if self.client:
            self.client.close(); self.client = None
            self.log_box.append(f"[{datetime.now()}] Disconnected")
        self.update_button_states(False)

    def update_function_field(self):
        self.write_value_edit.setEnabled("write" in self.func_combo.currentText().lower())

    def read_once(self):
        if not self.client:
            QMessageBox.warning(self, "Error", "Not connected to Modbus device.")
            return
        unit = int(self.unit_edit.text())
        reg = int(self.reg_edit.text())
        qty = int(self.qty_edit.text())
        encoding = self.encoding_combo.currentText().lower()
        func = self.func_combo.currentText().lower()
        regs = []
        try:
            if func == "holding":
                rr = self.client.read_holding(reg, qty, unit=unit)
            elif func == "input":
                rr = self.client.read_input(reg, qty, unit=unit)
            elif func == "coils":
                rr = self.client.read_coils(reg, qty, unit=unit)
            elif func == "discrete":
                rr = self.client.read_discrete(reg, qty, unit=unit)
            elif func == "write single":
                val = int(self.write_value_edit.text())
                rr = self.client.write_register(reg, val, unit=unit)
            elif func == "write multiple":
                vals = [int(v) for v in self.write_value_edit.text().split(',') if v.strip()]
                rr = self.client.write_registers(reg, vals, unit=unit)
            else:
                return
            regs = getattr(rr, 'registers', [])
            self.display_registers(regs, encoding)
            self.log_box.append(f"[{datetime.now()}] {func.title()} OK")
        except Exception as e:
            self.log_box.append(f"[ERROR] {e}")

    def display_registers(self, regs, encoding):
        self.table.setRowCount(0)
        if not regs:
            self.table.setRowCount(1)
            self.table.setItem(0, 0, QTableWidgetItem("N/A"))
            self.table.setItem(0, 1, QTableWidgetItem("No data"))
            return

        entries = []
        if encoding.startswith('float32'):
            for i in range(0, len(regs), 2):
                try:
                    a = regs[i]
                    b = regs[i + 1] if i + 1 < len(regs) else 0
                    if encoding == 'float32be' or encoding == 'float32[abcd]':
                        v = ModbusClient.decode_float32_from_regs(a, b, encoding='ABCD')
                    elif encoding == 'float32le' or encoding == 'float32[dcba]':
                        v = ModbusClient.decode_float32_from_regs(a, b, encoding='DCBA')
                    elif encoding == 'float32cdab' or encoding == 'float32[cdab]':
                        v = ModbusClient.decode_float32_from_regs(a, b, encoding='CDAB')
                    elif encoding == 'float32badc' or encoding == 'float32[badc]':
                        v = ModbusClient.decode_float32_from_regs(a, b, encoding='BADC')
                    else:
                        # default to ABCD
                        v = ModbusClient.decode_float32_from_regs(a, b, encoding='ABCD')
                except Exception:
                    v = None
                entries.append(v)
        elif encoding == "u16":
            for r in regs: entries.append(ModbusClient.decode_u16(r))

        self.table.setRowCount(len(entries))
        for i, val in enumerate(entries):
            self.table.setItem(i, 0, QTableWidgetItem(str(i)))
            self.table.setItem(i, 1, QTableWidgetItem(str(val)))

    # TX/RX hex log
        def format_hex(data: bytes) -> str:
            if not data:
                return "N/A"
            return ' '.join(f"{b:02X}" for b in data)

        # di display_registers atau read_once
        self.txrx_box.append(f"[TX] {format_hex(self.client.last_tx)}")
        self.txrx_box.append(f"[RX] {format_hex(self.client.last_rx)}")
    def start_polling(self):
        if not self.client:
            QMessageBox.warning(self, "Error", "Connect first.")
            return
        self.poll_timer.start(int(self.interval_spin.value() * 1000))
        self.log_box.append(f"[INFO] Polling started every {self.interval_spin.value():.1f}s")
        self.disconnect_btn.setEnabled(False)

    def stop_polling(self):
        self.poll_timer.stop()
        self.log_box.append("[INFO] Polling stopped")
        self.disconnect_btn.setEnabled(True)

    def read_loop(self):
        try:
            self.read_once()
        except Exception as e:
            self.log_box.append(f"[ERROR] Polling failed: {e}")

    def clear_all(self):
        self.table.setRowCount(0)
        self.log_box.clear()
        self.txrx_box.clear()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = ModbusGUI()
    w.show()
    sys.exit(app.exec_())
