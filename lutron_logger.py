## Python file untuk merekam data perangkat lutron pada file csv, mendukung hingga 3 display (suhu, kelembaban, tekanan)
# Lutron di tes pada 3 perangkat, dengan serial rs232 dan header file 41,42,43
# Lutron MHB-382SD
# Lutron -
# Lutron -
# Dependensi yang diperlukan PySide2, serial

import sys
import serial
import serial.tools.list_ports
import csv
import datetime
import time

from PySide2.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QComboBox, QFileDialog
)
from PySide2.QtCore import QThread, Signal


# ======================
# MAPPING DATA
# ======================

UNIT_MAP = {
    "01": "C",
    "02": "F",
    "04": "%RH",
    "91":"hPa",
    "80":"mmH2O",
    "78":"mmHg"
}

POLARITY_MAP = {
    "0": "+",
    "1": "-"
}


# ======================
# PARSER FRAME
# ======================

def extract_frames(buffer):
    frames = []
    while True:
        start = buffer.find(b'\x02')
        end = buffer.find(b'\r', start + 1)

        if start == -1 or end == -1:
            break

        frame = buffer[start+1:end]
        frames.append(frame)
        buffer = buffer[end+1:]

    return frames, buffer


def parse_frame(frame_bytes):
    try:
        text = frame_bytes.decode("ascii").strip()
    except:
        return None

    if len(text) < 14:
        return None

    header = text[0:2]
    unit_code = text[2:4]
    polarity_code = text[4]
    decimal_code = text[5]
    value_raw = text[6:14]

    try:
        decimal_pos = int(decimal_code)
        value_int = int(value_raw)
    except:
        return None

    value = value_int / (10 ** decimal_pos)

    unit = UNIT_MAP.get(unit_code, "?")
    polarity = POLARITY_MAP.get(polarity_code, "?")

    return header, value, unit, polarity


# ======================
# THREAD SERIAL
# ======================

class SerialThread(QThread):
    data_received = Signal(str, float, str, str)
    status_changed = Signal(str)
    status_serial = Signal(str)
    connect_btn = Signal(bool)
    start_btn = Signal(bool)
    stop_btn = Signal(bool)

    def __init__(self):
        super().__init__()
        self.debug = False
        self.running = False
        self.logging_enabled = False
        self.port = None
        self.baudrate = 9600
        self.csv_file = None
        self.ser = None

        self.last_upper = None
        self.last_middle = None
        self.last_lower = None
        self.unit_upper = ""
        self.unit_middle = ""
        self.unit_lower = ""
        self.polarity_upper = ""
        self.polarity_middle = ""
        self.polarity_lower = ""

        self.file_handle = None
        self.writer = None

        self.log_interval = 5.0
        self.last_log_time = 0

    def configure_serial(self, port, baudrate):
        self.port = port
        self.baudrate = baudrate

    def set_csv_file(self, file_path):
        self.csv_file = file_path

    def set_interval(self, seconds):
        if self.debug == True : print("interval: ", seconds)
        self.log_interval = seconds

    def run(self):
        buffer = b''

        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=0)

            self.ser.dtr=True
            self.ser.rts=True

            time.sleep(0.2)
            self.ser.reset_input_buffer()

            self.status_serial.emit("Terhubung")
            self.connect_btn.emit(False)

        except Exception:
            self.status_serial.emit("Serial Error")
            self.connect_btn.emit(True)
            return

        self.running = True

        while self.running:
            try:
                data = self.ser.read(self.ser.in_waiting or 1)

                if data:
                    if self.debug == True : print("time: %s data: %s" % (datetime.datetime.now().isoformat(),data))
                    buffer += data
                    frames, buffer = extract_frames(buffer)

                    for frame in frames:
                        result = parse_frame(frame)
                        if not result:
                            continue

                        header, value, unit, polarity = result

                        if header == "41":
                            self.last_upper = value
                            self.unit_upper = unit
                            self.polarity_upper = polarity
                            self.data_received.emit("upper", value, unit, polarity)

                        elif header == "43":
                            self.last_lower = value
                            self.unit_lower = unit
                            self.polarity_lower = polarity
                            self.data_received.emit("lower", value, unit, polarity)

                        elif header == "42":
                            self.last_middle = value
                            self.unit_middle = unit
                            self.polarity_middle = polarity
                            self.data_received.emit("middle", value, unit, polarity)
                        
                 # Logging dipicu saat pasangan lengkap + interval tercapai
                    now = time.time()
                    if (self.logging_enabled and self.writer and
                        now - self.last_log_time >= self.log_interval):

                        if self.last_lower is not None:
                            if self.debug == True : print("Merekam data 3 pada",time.time())
                            self.writer.writerow([
                                datetime.datetime.now().isoformat(),
                                self.last_upper,
                                self.last_middle,
                                self.last_lower,
                                self.unit_upper,
                                self.unit_middle,
                                self.unit_lower,
                                self.polarity_upper,
                                self.polarity_middle,
                                self.polarity_lower
                                 ])
                        elif self.last_middle is not None and self.last_lower is None:
                                if self.debug == True : print("Merekam data 2 pada",time.time())
                                self.writer.writerow([
                                datetime.datetime.now().isoformat(),
                                self.last_upper,
                                self.last_middle,
                                self.unit_upper,
                                self.unit_middle,
                                self.polarity_upper,
                                self.polarity_middle,
                                ])
                        elif self.last_lower is None and self.last_middle is None:
                                if self.debug == True : print("Merekam data 1 pada",time.time())
                                self.writer.writerow([
                                datetime.datetime.now().isoformat(),
                                self.last_upper,
                                self.unit_upper,
                                self.polarity_upper,
                                ])
                        if self.file_handle:
                            self.file_handle.flush()
                        self.last_log_time = now

                time.sleep(0.01)

            except Exception:
                time.sleep(1)

        if self.file_handle:
            self.file_handle.close()

        if self.ser and self.ser.is_open:
            self.ser.close()

        self.status_serial.emit("Tidak Terhubung")

    def start_logging(self):
        if not self.csv_file:
            self.status_changed.emit("CSV belum dipilih")
            self.start_btn.emit(True)
            self.stop_btn.emit(False)
            return

        try:
            self.file_handle = open(self.csv_file, "a", newline="")
            self.writer = csv.writer(self.file_handle)
            if self.last_lower is not None:
                self.writer.writerow(["timestamp","upper","middle","lower","unit_upper","unit_middle","unit_lower","polarity_upper","polarity_middle","polarity_lower"])
            elif self.last_middle is not None and self.last_lower is None:
                self.writer.writerow(["timestamp","upper","middle","unit_upper","unit_middle","polarity_upper","polarity_middle",])
            elif self.last_lower is None and self.last_middle is None:
                self.writer.writerow(["timestamp","upper","unit_upper","polarity_upper",])
            self.logging_enabled = True
            self.last_log_time = 0
            self.status_changed.emit("Merekam")
            self.start_btn.emit(False)
            self.stop_btn.emit(True)

        except Exception:
            self.status_changed.emit("File Error")

    def stop_logging(self):
        self.logging_enabled = False
        if self.file_handle:
            self.file_handle.close()
            self.file_handle = None
            self.writer = None
        self.status_changed.emit("Tidak Merekam")
        self.start_btn.emit(True)

    def stop(self):
        self.running = False


# ======================
# GUI
# ======================

class MainWindow(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Lutron Logger Kalingin")

        self.serial_thread = SerialThread()

        self.port_combo = QComboBox()
        self.refresh_ports_btn = QPushButton()
        self.refresh_ports_btn.setIcon(self.style().standardIcon(self.style().SP_BrowserReload))
        self.refresh_ports_btn.clicked.connect(self.refresh_ports)
        self.refresh_ports()

        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600","19200","38400","57600","115200"])

        self.interval_combo = QComboBox()
        self.interval_combo.addItems(["1","2","5","10","30","60","120"])

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.connect_serial)

        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.disconnect_serial)

        self.file_btn = QPushButton("Pilih CSV")
        self.file_btn.clicked.connect(self.select_file)

        self.start_btn = QPushButton("Start Logging")
        self.start_btn.clicked.connect(self.start_logging)

        self.stop_btn = QPushButton("Stop Logging")
        self.stop_btn.clicked.connect(self.stop_logging)
        self.stop_btn.setEnabled(False)

        self.exit_btn = QPushButton("Tutup Logger")
        self.exit_btn.clicked.connect(self.close)

        self.upper_label = QLabel("--")
        self.upper_label.setStyleSheet("font-size: 36px;")

        self.middle_label = QLabel("--")
        self.middle_label.setStyleSheet("font-size: 28px;")

        self.lower_label = QLabel("--")
        self.lower_label.setStyleSheet("font-size: 28px;")

        self.status_label = QLabel("File Log: Tidak Merekam")
        self.status_serial = QLabel("Koneksi: Terputus")

        layout = QVBoxLayout()

        row1 = QHBoxLayout()
        row1.addWidget(self.port_combo, stretch=1)
        row1.addWidget(self.refresh_ports_btn, stretch=0)
        row1.addWidget(self.baud_combo, stretch=0)

        row2 = QHBoxLayout()
        row2.addWidget(self.connect_btn)
        row2.addWidget(self.disconnect_btn)

        layout.addLayout(row1)
        layout.addLayout(row2)

        layout.addWidget(QLabel("Interval Logging (detik)"))
        layout.addWidget(self.interval_combo)

        layout.addWidget(self.file_btn)
        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.status_serial)
        layout.addWidget(self.status_label)

        layout.addWidget(QLabel("Display 1 (Header 41)"))
        layout.addWidget(self.upper_label)

        layout.addWidget(QLabel("Display 2 (Header 42)"))
        layout.addWidget(self.middle_label)

        layout.addWidget(QLabel("Display 3 (Header 43)"))
        layout.addWidget(self.lower_label)

        layout.addWidget(self.exit_btn)

        self.setLayout(layout)

        self.serial_thread.data_received.connect(self.update_display)
        self.serial_thread.status_changed.connect(self.update_status)
        self.serial_thread.status_serial.connect(self.update_status_serial)
        self.serial_thread.connect_btn.connect(self.connect_serial)
        self.serial_thread.start_btn.connect(self.start_btn.setEnabled)
        self.serial_thread.stop_btn.connect(self.stop_btn.setEnabled)

    def refresh_ports(self):
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for p in ports:
            self.port_combo.addItem(p.device)

    def select_file(self):
        file_name, _ = QFileDialog.getSaveFileName(self, "Pilih File CSV", "", "CSV Files (*.csv)")
        if file_name:
            self.serial_thread.set_csv_file(file_name)
            self.file_btn.setText(file_name)

    def connect_serial(self, enabled):
        port = self.port_combo.currentText()
        baudrate = int(self.baud_combo.currentText())
        self.serial_thread.configure_serial(port, baudrate)
        self.serial_thread.start()
        self.connect_btn.setEnabled(enabled)

    def disconnect_serial(self):
        self.serial_thread.stop()
        self.serial_thread.wait()
        self.connect_btn.setEnabled(True)

    def start_logging(self):
        interval = float(self.interval_combo.currentText())
        self.serial_thread.set_interval(interval)
        self.serial_thread.start_logging()
        #self.start_btn.setEnabled(False)

    def stop_logging(self):
        self.serial_thread.stop_logging()
        #self.start_btn.setEnabled(True)

    def update_display(self, display, value, unit, polarity):
        text = f"{polarity}{value:.2f} {unit}"
        if display == "upper":
            self.upper_label.setText(text)
        elif display == "lower":
            self.lower_label.setText(text)
        elif display == "middle":
            self.middle_label.setText(text)

    def update_status(self, status):
        self.status_label.setText(f"File Log: {status}")
        
    def update_status_serial(self, status):
        self.status_serial.setText(f"Koneksi: {status}")

    def closeEvent(self, event):
        self.serial_thread.stop()
        self.serial_thread.wait()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(380, 450)
    window.show()
    sys.exit(app.exec_())
