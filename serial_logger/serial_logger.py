import sys, os, csv, time, serial, serial.tools.list_ports
from PyQt5 import uic
from PyQt5.QtWidgets import QApplication, QWidget, QFileDialog, QMessageBox
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QTextCursor


# ---------- Thread pembaca serial ----------
class SerialReader(QThread):
    data_received = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(self, port, baudrate):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.running = True

    def run(self):
        try:
            ser = serial.Serial(self.port, self.baudrate, timeout=1)
            while self.running:
                if ser.in_waiting:
                    line = ser.readline().decode(errors='ignore').strip()
                    if line:
                        self.data_received.emit(line)
            ser.close()
        except serial.SerialException as e:
            self.error_signal.emit(str(e))

    def stop(self):
        self.running = False


# ---------- GUI utama ----------
class SerialLogger(QWidget):
    def __init__(self):
        super().__init__()
        # 💡 Load file .ui langsung
        uic.loadUi("serial_logger.ui", self)

        self.reader = None
        self.logging = False
        self.logfile = None
        self.writer = None
        self.max_lines = 100
        self.lines = []

        # isi baud rate
        self.baudBox.addItems([
            "1200","2400","4800","9600","14400","19200",
            "38400","57600","115200","230400","460800","921600"
        ])

        # sambungkan sinyal tombol
        self.refresh_ports_btn.clicked.connect(self.refresh_ports)
        self.connectBtn.clicked.connect(self.toggle_connection)
        self.startBtn.clicked.connect(self.toggle_logging)
        self.browseBtn.clicked.connect(self.select_file)

        self.refresh_ports()

    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.portBox.clear()
        self.portBox.addItems(ports or ["(no port found)"])

    def toggle_connection(self):
        if self.reader and self.reader.isRunning():
            self.reader.stop()
            self.reader.wait()
            self.reader = None
            self.connectBtn.setText("Connect")
            self.append_text("[Disconnected]")
        else:
            port = self.portBox.currentText()
            if not port or "no port" in port:
                QMessageBox.warning(self, "Warning", "No serial port selected.")
                return
            baud = int(self.baudBox.currentText())
            self.reader = SerialReader(port, baud)
            self.reader.data_received.connect(self.on_data)
            self.reader.error_signal.connect(self.on_error)
            self.reader.start()
            self.connectBtn.setText("Disconnect")
            self.append_text(f"[Connected to {port} @ {baud}]")

    def on_error(self, msg):
        QMessageBox.critical(self, "Serial Error", msg)
        self.toggle_connection()

    def toggle_logging(self):
        if self.logging:
            self.stop_logging()
        else:
            self.start_logging()

    def start_logging(self):
        filename = self.filepathEdit.text().strip()
        if not filename:
            QMessageBox.warning(self, "Warning", "Please select a log file path.")
            return
        try:
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            self.logfile = open(filename, "a", newline="")
            self.writer = csv.writer(self.logfile)
            self.logging = True
            self.startBtn.setText("Stop Logging")
            self.append_text(f"[Logging started → {filename}]")
        except Exception as e:
            QMessageBox.critical(self, "File Error", str(e))

    def stop_logging(self):
        if self.logfile:
            self.logfile.close()
        self.logging = False
        self.startBtn.setText("Start Logging")
        self.append_text("[Logging stopped]")

    def on_data(self, line):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        text_line = f"{timestamp} | {line}"
        self.lines.append(text_line)
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]
        self.text.setPlainText("\n".join(self.lines))
        self.text.moveCursor(QTextCursor.End)
        if self.logging and self.writer:
            self.writer.writerow([timestamp, line])
            self.logfile.flush()
            self.append_text(f"[Wrote to CSV] {line}", debug=True)

    def append_text(self, text, debug=False):
        prefix = "[DEBUG] " if debug else ""
        self.lines.append(prefix + text)
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]
        self.text.setPlainText("\n".join(self.lines))
        self.text.moveCursor(QTextCursor.End)

    def select_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Log As", self.filepathEdit.text(), "CSV Files (*.csv)")
        if path:
            self.filepathEdit.setText(path)

    def closeEvent(self, event):
        if self.reader and self.reader.isRunning():
            self.reader.stop()
            self.reader.wait()
        if self.logging and self.logfile:
            self.logfile.close()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = SerialLogger()
    win.show()
    sys.exit(app.exec_())
