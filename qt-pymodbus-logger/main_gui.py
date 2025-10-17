# main_gui_editable.py
# GUI editable config for Modbus Logger (lightweight, no graph)
# Requires: PyQt5, config_manager.py, modbus_worker.py, storage/*.py
# Save this file in the project root next to config_manager.py

import os
import sys
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLabel, QTabWidget, QFormLayout, QLineEdit, QComboBox,
    QSpinBox, QFileDialog, QMessageBox, QCheckBox
)
from PyQt5.QtCore import QThread, pyqtSignal

from config_manager import load_config, save_config
from storage.csv_logger import CSVLogger
from storage.mysql_logger import MySQLLogger
from modbus_worker import ModbusPoller

# Thread wrapper for polling (calls run_once periodically)
class PollThread(QThread):
    logline = pyqtSignal(str)

    def __init__(self, poller, interval_s=1.0):
        super().__init__()
        self.poller = poller
        self.interval_s = max(0.1, float(interval_s))
        self._running = True

    def run(self):
        while self._running:
            try:
                ts, entries = self.poller.run_once()
                values = "; ".join([f"{e['value']:.6g}" for e in entries])
                self.logline.emit(f"[{ts}] {values}")
            except Exception as e:
                self.logline.emit(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error: {e}")
            # sleep using QThread.sleep would block; use wait with milliseconds
            self.msleep(int(self.interval_s * 1000))

    def stop(self):
        self._running = False
        # ensure the thread loop exits quickly
        self.wait(1000)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modbus Logger v1.1")
        self.resize(800, 600)

        # load config
        self.config = load_config()
        self.poll_thread = None
        self.poller = None

        # UI
        self._build_ui()
        self._load_settings_to_form()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        # Tabs: Control + Settings
        self.tabs = QTabWidget()
        self.tab_control = QWidget()
        self.tab_settings = QWidget()

        self.tabs.addTab(self.tab_control, "Control")
        self.tabs.addTab(self.tab_settings, "Settings")

        # Control tab layout
        ctrl_layout = QVBoxLayout(self.tab_control)
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("Start Polling")
        self.btn_stop = QPushButton("Stop Polling")
        self.btn_reload = QPushButton("Reload Config")
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        btn_layout.addWidget(self.btn_reload)

        ctrl_layout.addLayout(btn_layout)
        ctrl_layout.addWidget(QLabel("Log:"))
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        ctrl_layout.addWidget(self.log_edit)

        # Settings tab layout
        sett_layout = QVBoxLayout(self.tab_settings)
        form = QFormLayout()

        # Modbus section
        self.cmb_type = QComboBox(); self.cmb_type.addItems(["rtu", "tcp"])
        self.le_port = QLineEdit()
        self.le_baud = QLineEdit()
        self.cmb_bytesize = QComboBox(); self.cmb_bytesize.addItems(["8","7"])
        self.cmb_parity = QComboBox(); self.cmb_parity.addItems(["N","E","O"])
        self.cmb_stopbits = QComboBox(); self.cmb_stopbits.addItems(["1","2"])
        self.le_timeout = QLineEdit()
        self.le_host = QLineEdit()
        self.le_tcp_port = QLineEdit()
        self.spin_unit = QSpinBox(); self.spin_unit.setRange(0, 247)
        self.le_register = QLineEdit()
        self.le_quantity = QLineEdit()
        self.cmb_encoding = QComboBox(); self.cmb_encoding.addItems([
            "float32be", "float32le", "float32cdab", "float32badc", "u16"
        ])
        self.le_poll_interval = QLineEdit()

        # Logger section
        self.chk_csv = QCheckBox("Enable CSV")
        self.le_csv_path = QLineEdit()
        self.btn_browse_csv = QPushButton("Browse")
        csv_row = QHBoxLayout()
        csv_row.addWidget(self.le_csv_path); csv_row.addWidget(self.btn_browse_csv)

        self.chk_mysql = QCheckBox("Enable MySQL")
        self.le_mysql_host = QLineEdit()
        self.le_mysql_user = QLineEdit()
        self.le_mysql_pass = QLineEdit()
        self.le_mysql_db = QLineEdit()
        self.le_mysql_table = QLineEdit()

        # Save/Reload buttons at settings bottom
        settings_btn_layout = QHBoxLayout()
        self.btn_save_cfg = QPushButton("Save Config")
        self.btn_reload_cfg = QPushButton("Reload Config")
        settings_btn_layout.addWidget(self.btn_save_cfg)
        settings_btn_layout.addWidget(self.btn_reload_cfg)
        self.function = QComboBox()
        self.function.addItems(["holding", "input", "coils", "discrete"])

        # Build form rows
        form.addRow(QLabel("<b>Modbus</b>"))
        form.addRow("Type:", self.cmb_type)
        form.addRow("Serial Port (or Host):", self.le_port)
        form.addRow("Baudrate:", self.le_baud)
        form.addRow("Byte size:", self.cmb_bytesize)
        form.addRow("Parity:", self.cmb_parity)
        form.addRow("Stop bits:", self.cmb_stopbits)
        form.addRow("Timeout (s):", self.le_timeout)
        form.addRow("TCP Host:", self.le_host)
        form.addRow("TCP Port:", self.le_tcp_port)
        form.addRow("Function:", self.function)
        form.addRow("Unit ID:", self.spin_unit)
        form.addRow("Start Register:", self.le_register)
        form.addRow("Quantity:", self.le_quantity)
        form.addRow("Encoding:", self.cmb_encoding)
        form.addRow("Poll interval (s):", self.le_poll_interval)

        form.addRow(QLabel("<b>Logger</b>"))
        form.addRow(self.chk_csv)
        form.addRow("CSV Path:", csv_row)
        form.addRow(self.chk_mysql)
        form.addRow("MySQL Host:", self.le_mysql_host)
        form.addRow("MySQL User:", self.le_mysql_user)
        form.addRow("MySQL Password:", self.le_mysql_pass)
        form.addRow("MySQL Database:", self.le_mysql_db)
        form.addRow("MySQL Table:", self.le_mysql_table)

        sett_layout.addLayout(form)
        sett_layout.addLayout(settings_btn_layout)

        # wire signals
        self.btn_start.clicked.connect(self.start_polling)
        self.btn_stop.clicked.connect(self.stop_polling)
        self.btn_reload.clicked.connect(self.reload_config)
        self.btn_browse_csv.clicked.connect(self.browse_csv)
        self.btn_save_cfg.clicked.connect(self.save_config_from_form)
        self.btn_reload_cfg.clicked.connect(self.load_settings_to_form)

        # finish main layout
        main_layout.addWidget(self.tabs)

    # helper: populate fields from config object
    def _load_settings_to_form(self):
        cfg = self.config
        mod = cfg['Modbus']
        lg = cfg['Logger']
        my = cfg['MYSQL']
        ui = cfg['UI'] if 'UI' in cfg else {}

        # Modbus
        self.cmb_type.setCurrentText(mod.get('type','rtu'))
        self.le_port.setText(mod.get('port','/dev/ttyUSB0'))
        self.le_baud.setText(mod.get('baudrate','9600'))
        self.cmb_bytesize.setCurrentText(mod.get('bytesize','8'))
        self.cmb_parity.setCurrentText(mod.get('parity','N'))
        self.cmb_stopbits.setCurrentText(mod.get('stopbits','1'))
        self.le_timeout.setText(mod.get('timeout','1'))
        self.le_host.setText(mod.get('host','127.0.0.1'))
        self.le_tcp_port.setText(mod.get('tcp_port','502'))
        self.function.setCurrentText(mod.get('function','holding'))
        self.spin_unit.setValue(int(mod.get('unit_id','1')))
        self.le_register.setText(mod.get('register','0'))
        self.le_quantity.setText(mod.get('quantity','2'))
        self.cmb_encoding.setCurrentText(mod.get('encoding','float32be'))
        self.le_poll_interval.setText(mod.get('poll_interval','1.0'))

        # Logger
        self.chk_csv.setChecked(lg.get('enable_csv','true').lower() in ('1','true','yes'))
        self.le_csv_path.setText(lg.get('csv_file','logs/modbus_data.csv'))
        self.chk_mysql.setChecked(lg.get('enable_mysql','false').lower() in ('1','true','yes'))
        self.le_mysql_host.setText(my.get('host','localhost'))
        self.le_mysql_user.setText(my.get('user','root'))
        self.le_mysql_pass.setText(my.get('password',''))
        self.le_mysql_db.setText(my.get('database','modbus'))
        self.le_mysql_table.setText(my.get('table','sensor_data'))

    # called by reload buttons
    def load_settings_to_form(self):
        self.config = load_config()
        self._load_settings_to_form()
        self.log("Config reloaded from file.")

    def browse_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Select CSV file", self.le_csv_path.text(), "CSV Files (*.csv);;All Files (*)")
        if path:
            self.le_csv_path.setText(path)

    # basic validation
    def _validate_form(self):
        # check numbers: baudrate, tcp_port, quantity, poll_interval
        try:
            if self.cmb_type.currentText() == 'rtu':
                int(self.le_baud.text())
            int(self.le_quantity.text())
            float(self.le_poll_interval.text())
            int(self.le_tcp_port.text() or 0)
        except Exception as e:
            return False, str(e)
        return True, ""

    def save_config_from_form(self):
        ok, msg = self._validate_form()
        if not ok:
            QMessageBox.warning(self, "Validation error", f"Invalid input: {msg}")
            return

        # update configparser object
        cfg = self.config
        if 'Modbus' not in cfg:
            cfg['Modbus'] = {}
        if 'Logger' not in cfg:
            cfg['Logger'] = {}
        if 'MYSQL' not in cfg:
            cfg['MYSQL'] = {}
        if 'UI' not in cfg:
            cfg['UI'] = {}

        m = cfg['Modbus']
        m['type'] = self.cmb_type.currentText()
        m['port'] = self.le_port.text()
        m['baudrate'] = self.le_baud.text()
        m['bytesize'] = self.cmb_bytesize.currentText()
        m['parity'] = self.cmb_parity.currentText()
        m['stopbits'] = self.cmb_stopbits.currentText()
        m['timeout'] = self.le_timeout.text()
        m['host'] = self.le_host.text()
        m['tcp_port'] = self.le_tcp_port.text()
        m['function'] = self.function.currentText()
        m['unit_id'] = str(self.spin_unit.value())
        m['register'] = self.le_register.text()
        m['quantity'] = self.le_quantity.text()
        m['encoding'] = self.cmb_encoding.currentText()
        m['poll_interval'] = self.le_poll_interval.text()

        l = cfg['Logger']
        l['enable_csv'] = 'true' if self.chk_csv.isChecked() else 'false'
        l['csv_file'] = self.le_csv_path.text()
        l['enable_mysql'] = 'true' if self.chk_mysql.isChecked() else 'false'

        my = cfg['MYSQL']
        my['host'] = self.le_mysql_host.text()
        my['user'] = self.le_mysql_user.text()
        my['password'] = self.le_mysql_pass.text()
        my['database'] = self.le_mysql_db.text()
        my['table'] = self.le_mysql_table.text()

        ui = cfg['UI']
        ui['enable_graph'] = 'false'  # still disabled in this simple GUI

        try:
            save_config(cfg)
        except Exception as e:
            QMessageBox.critical(self, "Save error", f"Failed to save config: {e}")
            return

        self.log("Config saved to config.ini")
        # reload config object and if polling running, restart poller
        self.config = load_config()
        if self.poll_thread and self.poll_thread.isRunning():
            self.log("Restarting poller with new config...")
            self.stop_polling()
            self.start_polling()

    def reload_config(self):
        self.config = load_config()
        self._load_settings_to_form()
        self.log("Config reloaded from file.")

    def start_polling(self):
        if self.poll_thread and self.poll_thread.isRunning():
            self.log("Polling already running.")
            return

        # create logger instances according to config
        cfg = self.config
        modcfg = cfg['Modbus']
        logcfg = cfg['Logger']

        loggers = []
        if logcfg.get('enable_csv','false').lower() in ('1','true','yes'):
            csv_path = logcfg.get('csv_file','logs/modbus_data.csv')
            # ensure logs directory exists
            d = os.path.dirname(csv_path)
            if d and not os.path.exists(d):
                os.makedirs(d, exist_ok=True)
            loggers.append(CSVLogger(csv_path))
        if logcfg.get('enable_mysql','false').lower() in ('1','true','yes'):
            mysql_conf = cfg['MYSQL']
            mysql_conf = {k: mysql_conf.get(k) for k in ('host','user','password','database','table')}
            loggers.append(MySQLLogger(mysql_conf))

        # create poller
        # Convert configparser section to regular dict for modbus_worker expectation
        moddict = dict(modcfg)
        print(moddict)
        self.poller = ModbusPoller(moddict, logger_list=loggers)

        # start thread
        interval = float(moddict.get('poll_interval', 1.0))
        self.poll_thread = PollThread(self.poller, interval)
        self.poll_thread.logline.connect(self.on_logline)
        self.poll_thread.start()
        self.log("Polling started.")

    def stop_polling(self):
        if not self.poll_thread:
            self.log("Poller not running.")
            return
        try:
            self.poll_thread.stop()
        except Exception:
            pass
        self.poll_thread = None
        self.log("Polling stopped.")

    def on_logline(self, text):
        self.log_edit.append(text)

    def log(self, text):
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.log_edit.append(f"[{ts}] {text}")

    def closeEvent(self, event):
        # stop thread if running
        if self.poll_thread and self.poll_thread.isRunning():
            self.poll_thread.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()