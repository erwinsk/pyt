import sys
import os
import time
import json
import requests
import logging
from logging.handlers import RotatingFileHandler
import certifi
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLineEdit, QLabel, QFileDialog, 
                             QTextEdit, QSpinBox, QGroupBox, QMessageBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QTextCursor

# Setup SSL untuk PyInstaller
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

class QTextEditLogger(logging.Handler):
    def __init__(self, signal_target):
        super().__init__()
        self.signal_target = signal_target

    def emit(self, record):
        msg = self.format(record)
        self.signal_target.emit(msg)

class MonitorThread(QThread):
    def __init__(self, directory, url, interval):
        super().__init__()
        self.directory = directory
        self.url = url
        self.interval = interval
        self.is_running = True
        self.unsent_data_file = 'unsent_data.json'

    def run(self):
        logging.info("=== MONITORING DIMULAI ===")
        last_file = None
        last_line = None

        while self.is_running:
            try:
                self.send_saved_data()
                current_file = self.get_latest_file(self.directory)

                if current_file and current_file != last_file:
                    logging.info(f"FILE BARU (.txt): {os.path.basename(current_file)}")
                    last_file = current_file
                    last_line = None 

                if last_file:
                    current_last_line = self.get_last_line(last_file)
                    if current_last_line and current_last_line != last_line:
                        last_line = current_last_line
                        data_dict = self.parse_line_to_dict(last_line)
                        
                        if data_dict:
                            # Tampilan Log Visual Padat (2 Baris untuk Parameter)
                            log_view = "\n" + "-"*50 + "\n"
                            log_view += f"TIMESTAMP: {data_dict.get('Timestamp', '-')}\n"
                            
                            params = ["CO2", "SO2", "NOx", "O2", "CO", "HCl", "H2O", "NO2", "NO", "CH4", "N2O", "NH3"]
                            for i, p in enumerate(params):
                                val = data_dict.get(p, 0.0)
                                log_view += f"{p}:{str(val).ljust(7)} "
                                if (i + 1) % 6 == 0: log_view += "\n" # Pecah jadi 6 kolom (total 2 baris)
                            
                            log_view += f"STATUS -> F:{data_dict.get('Failure')} | M:{data_dict.get('Maintenance')} | R:{data_dict.get('Maint. Req.')}\n"
                            logging.info(log_view)
                            
                            try:
                                response = requests.post(self.url, json=data_dict, timeout=10)
                                if response.status_code == 200:
                                    # Menampilkan kode 200 dan isi balasan server
                                    logging.info(f"BERHASIL (200): {response.text}")
                                else:
                                    logging.error(f"GAGAL (Status: {response.status_code}): {response.text}")
                                    self.save_unsent_data(data_dict)
                            except requests.exceptions.RequestException as e:
                                logging.error(f"KONEKSI ERROR: {e}")
                                self.save_unsent_data(data_dict)
                
                time.sleep(self.interval)
            except Exception as e:
                logging.error(f"SYSTEM ERROR: {e}")
                time.sleep(self.interval)

    def get_latest_file(self, directory):
        try:
            files = [f for f in os.listdir(directory) if f.lower().endswith('.txt') and os.path.isfile(os.path.join(directory, f))]
            if not files: return None
            files.sort(key=lambda f: os.path.getmtime(os.path.join(directory, f)), reverse=True)
            return os.path.join(directory, files[0])
        except: return None

    def get_last_line(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
                lines = file.readlines()
                return lines[-1] if lines else None
        except: return None

    def parse_line_to_dict(self, line):
        columns = [col.strip() for col in line.strip().split('\t')]
        if len(columns) < 22: return None
        headers = ["Timestamp", "CO2", "HCl", "H2O", "CO", "SO2", "NO2", "NO", "CH4", "N2O",
                   "NH3", "O2", "NOx", "[]", "[]", "[]", "[]", "[]", "[]", "[]", "[]", "[]", 
                   "Failure", "Maintenance", "Maint. Req."]
        def convert_value(value):
            try:
                val = value.replace(',', '.')
                return float(val)
            except ValueError: return value
        return dict(zip(headers, [convert_value(col) for col in columns]))

    def save_unsent_data(self, data):
        try:
            unsent_data = []
            if os.path.exists(self.unsent_data_file):
                with open(self.unsent_data_file, 'r') as f:
                    unsent_data = json.load(f)
            unsent_data.append(data)
            with open(self.unsent_data_file, 'w') as f:
                json.dump(unsent_data, f)
        except: pass

    def send_saved_data(self):
        if not os.path.exists(self.unsent_data_file): return
        try:
            with open(self.unsent_data_file, 'r') as f:
                unsent_data = json.load(f)
            if not unsent_data: return
            remaining_data = []
            for i, data in enumerate(unsent_data):
                try:
                    response = requests.post(self.url, json=data, timeout=5)
                    if response.status_code == 200: continue 
                    else:
                        logging.info("=== MONITORING DIMULAI ===")
                        remaining_data.extend(unsent_data[i:])
                        break
                except:
                    remaining_data.extend(unsent_data[i:])
                    break
            if not remaining_data: os.remove(self.unsent_data_file)
            else:
                with open(self.unsent_data_file, 'w') as f:
                    json.dump(remaining_data, f)
        except: pass

    def stop(self):
        self.is_running = False
        logging.info("=== MONITORING BERHENTI ===") 

class AppGUI(QWidget):
    log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.initUI()
        self.setup_logging()
        self.load_config()

    def initUI(self):
        self.setWindowTitle('KALINGIN - CEMS MCA16 RATA GATEWAY')
        self.setGeometry(100, 100, 850, 750)
        layout = QVBoxLayout()

        config_group = QGroupBox("Pengaturan Koneksi")
        config_layout = QVBoxLayout()

        self.url_input = QLineEdit("")
        config_layout.addWidget(QLabel("Server URL:"))
        config_layout.addWidget(self.url_input)

        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Pilih direktori file .txt...")
        btn_path = QPushButton("Cari Folder")
        btn_path.clicked.connect(self.browse_folder)
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(btn_path)
        config_layout.addLayout(path_layout)

        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(1, 600); self.spin_interval.setValue(5)
        config_layout.addWidget(QLabel("Interval Refresh (Detik):"))
        config_layout.addWidget(self.spin_interval)

        config_group.setLayout(config_layout)
        layout.addWidget(config_group)

        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setStyleSheet("""
            background-color: #0b0d11; 
            color: #00e676; 
            font-family: 'Courier New'; 
            font-size: 10pt;
            border: 1px solid #333;
        """)
        layout.addWidget(QLabel("Monitor Aktivitas:"))
        layout.addWidget(self.log_display)

        control_layout = QHBoxLayout()
        self.btn_start = QPushButton("START MONITORING")
        self.btn_start.setFixedHeight(40)
        self.btn_start.clicked.connect(self.start_monitoring)
        
        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_monitoring)

        control_layout.addWidget(self.btn_start)
        control_layout.addWidget(self.btn_stop)
        layout.addLayout(control_layout)

        self.setLayout(layout)

    def setup_logging(self):
        file_handler = RotatingFileHandler('app_cems.log', maxBytes=10*1024*1024, backupCount=10)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        
        self.log_signal.connect(self.update_log_display)
        ui_handler = QTextEditLogger(self.log_signal)
        ui_handler.setFormatter(logging.Formatter('%(message)s'))

        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logger.addHandler(file_handler)
        logger.addHandler(ui_handler)

    def update_log_display(self, message):
        self.log_display.append(message)
        self.log_display.moveCursor(QTextCursor.End)

    def browse_folder(self):
        p = QFileDialog.getExistingDirectory(self, "Pilih Folder")
        if p: self.path_input.setText(p)

    def save_config(self):
        config = {'url': self.url_input.text(), 'path': self.path_input.text(), 'interval': self.spin_interval.value()}
        with open('config.json', 'w') as f: json.dump(config, f)

    def load_config(self):
        if os.path.exists('config.json'):
            try:
                with open('config.json', 'r') as f:
                    config = json.load(f)
                    self.url_input.setText(config.get('url', ''))
                    self.path_input.setText(config.get('path', ''))
                    self.spin_interval.setValue(config.get('interval', 5))
            except: pass

    def start_monitoring(self):
        if not os.path.isdir(self.path_input.text()):
            QMessageBox.warning(self, "Error", "Folder tidak valid.")
            return
        self.save_config()
        self.monitor_thread = MonitorThread(self.path_input.text(), self.url_input.text(), self.spin_interval.value())
        self.monitor_thread.start()
        self.btn_start.setEnabled(False); self.btn_stop.setEnabled(True)
        self.btn_start.setText("MONITORING ACTIVE...")

    def stop_monitoring(self):
        if self.monitor_thread:
            self.monitor_thread.stop()
            self.monitor_thread.wait()
        self.btn_start.setEnabled(True); self.btn_stop.setEnabled(False)
        self.btn_start.setText("START MONITORING")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = AppGUI()
    win.show()
    sys.exit(app.exec_())