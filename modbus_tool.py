import sys
import time
import csv
import json
import struct
import os
from datetime import datetime
import serial.tools.list_ports

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QLabel, QLineEdit, QComboBox, QPushButton, QSpinBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QTextEdit, QFileDialog, QCheckBox, QGroupBox,
    QHeaderView, QMessageBox, QProgressBar, QStatusBar, QAction, QMenuBar,
    QSplitter
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QMutex, QTimer
from PyQt5.QtGui import QColor, QFont

# Mutex Global
kunci_komunikasi = QMutex()

# =====================================================================
# PYMODBUS MULTI-VERSION COMPATIBILITY LAYER
# =====================================================================
def get_modbus_device_kwargs(device_id):
    try:
        from pymodbus import __version__
        parts = __version__.split('.')
        v_major = int(parts[0]) if len(parts) > 0 else 0
        v_minor = int(parts[1]) if len(parts) > 1 else 0
    except ImportError:
        v_major, v_minor = 0, 0

    if v_major < 3:
        dev_key = "unit"
    elif v_major == 3 and v_minor < 11:
        dev_key = "slave"
    else:
        dev_key = "device_id"
        
    return {dev_key: device_id}

try:
    from pymodbus.client import ModbusSerialClient, ModbusTcpClient
except ImportError:
    from pymodbus.client.sync import ModbusSerialClient, ModbusTcpClient

def _buat_client_rtu(port, baudrate, parity, stopbits, bytesize, timeout):
    try:
        from pymodbus import __version__
        v_major = int(__version__.split('.')[0])
    except:
        v_major = 0
        
    if v_major >= 3:
        return ModbusSerialClient(
            port=port, baudrate=baudrate, parity=parity,
            stopbits=stopbits, bytesize=bytesize, timeout=timeout
        )
    else:
        return ModbusSerialClient(
            method='rtu', port=port, baudrate=baudrate, parity=parity,
            stopbits=stopbits, bytesize=bytesize, timeout=timeout
        )

def _buat_client_tcp(host, port, timeout):
    return ModbusTcpClient(host=host, port=port, timeout=timeout)


# =====================================================================
# KONSTANTA GLOBAL
# =====================================================================
DAFTAR_ENCODING = [
    "Mentah (16-bit UINT)",
    "Signed 16-bit INT",
    "32-bit FLOAT (ABCD - Big Endian)",
    "32-bit FLOAT (CDAB - Word Swap)",
    "32-bit FLOAT (BADC - Byte Swap)",
    "32-bit FLOAT (DCBA - Little Endian)"
]

WARNA_SUKSES    = "#2ecc71"   
WARNA_GAGAL     = "#e74c3c"   
WARNA_HIGHLIGHT = "#f39c12"   
FILE_PRESET = "modbus_presets.json"


# =====================================================================
# HELPER & DECODER
# =====================================================================
def baca_register_modbus(client, tipe_reg, address, count, device_id):
    kwargs = {'address': address, 'count': count}
    kwargs.update(get_modbus_device_kwargs(device_id))

    if tipe_reg == 'Holding':
        return client.read_holding_registers(**kwargs)
    elif tipe_reg == 'Input':
        return client.read_input_registers(**kwargs)
    elif tipe_reg == 'Coil':
        return client.read_coils(**kwargs)
    else:
        return client.read_discrete_inputs(**kwargs)

def dekode_register_sepasang(r1, r2, jenis_encoding):
    try:
        b_r1 = struct.pack('>H', r1)
        b_r2 = struct.pack('>H', r2)
        A, B = b_r1[0], b_r1[1]
        C, D = b_r2[0], b_r2[1]

        if jenis_encoding == "32-bit FLOAT (ABCD - Big Endian)":
            byte_final = bytes([A, B, C, D])
        elif jenis_encoding == "32-bit FLOAT (CDAB - Word Swap)":
            byte_final = bytes([C, D, A, B])
        elif jenis_encoding == "32-bit FLOAT (BADC - Byte Swap)":
            byte_final = bytes([B, A, D, C])
        elif jenis_encoding == "32-bit FLOAT (DCBA - Little Endian)":
            byte_final = bytes([D, C, B, A])
        else:
            byte_final = bytes([A, B, C, D])

        val = struct.unpack('>f', byte_final)[0]
        return f"{val:.4f}"
    except Exception:
        return "Error Decode"

def enkode_nilai_ke_register(teks_input, jenis_encoding):
    try:
        val_float = float(teks_input)
        if jenis_encoding == 'Mentah (16-bit UINT)':
            return [int(val_float) & 0xFFFF]
        elif jenis_encoding == 'Signed 16-bit INT':
            return list(struct.unpack('>H', struct.pack('>h', int(val_float))))

        byte_mentah = struct.pack('>f', val_float)
        A, B, C, D = byte_mentah[0], byte_mentah[1], byte_mentah[2], byte_mentah[3]

        if jenis_encoding == "32-bit FLOAT (ABCD - Big Endian)":
            byte_final = bytes([A, B, C, D])
        elif jenis_encoding == "32-bit FLOAT (CDAB - Word Swap)":
            byte_final = bytes([C, D, A, B])
        elif jenis_encoding == "32-bit FLOAT (BADC - Byte Swap)":
            byte_final = bytes([B, A, D, C])
        elif jenis_encoding == "32-bit FLOAT (DCBA - Little Endian)":
            byte_final = bytes([D, C, B, A])
        else:
            byte_final = bytes([A, B, C, D])

        return list(struct.unpack('>HH', byte_final))
    except Exception as e:
        raise ValueError(f"Gagal enkode format data: {str(e)}")


# =====================================================================
# THREAD WORKERS
# =====================================================================
class ModbusScannerThread(QThread):
    sinyal_progres = pyqtSignal(int, str)
    sinyal_hasil   = pyqtSignal(list)
    sinyal_selesai = pyqtSignal()
    sinyal_error   = pyqtSignal(str) 

    def __init__(self, client_global, jenis_scan="id", parameter_scan=None):
        super().__init__()
        self.client = client_global
        self.jenis_scan = jenis_scan
        self.parameter_scan = parameter_scan or {}
        self.apakah_berjalan = True

    def run(self):
        if not self.client or not self.client.connected:
            self.sinyal_error.emit("Master Modbus Utama belum terhubung!")
            self.sinyal_selesai.emit()
            return
        hasil = []
        if self.jenis_scan == "id":
            id_awal  = int(self.parameter_scan.get('id_awal', 1))
            id_akhir = int(self.parameter_scan.get('id_akhir', 247))
            tipe_reg = self.parameter_scan.get('tipe_reg', 'Holding')
            reg_uji  = int(self.parameter_scan.get('reg_uji', 0))
            total    = id_akhir - id_awal + 1

            for idx, slave_id in enumerate(range(id_awal, id_akhir + 1)):
                if not self.apakah_berjalan: break
                progres = int(((idx + 1) / total) * 100)
                self.sinyal_progres.emit(progres, f"Memindai Device ID: {slave_id}...")

                kunci_komunikasi.lock()
                try:
                    res = baca_register_modbus(self.client, tipe_reg, reg_uji, 1, slave_id)
                    if res and not res.isError():
                        hasil.append((slave_id, "MERESPON"))
                except Exception as e:
                    self.sinyal_error.emit(f"Error saat scan ID {slave_id}: {str(e)}")
                finally:
                    kunci_komunikasi.unlock()
                time.sleep(0.02)

        elif self.jenis_scan == "register":
            target_device_id = int(self.parameter_scan.get('slave_id', 1))
            tipe_reg  = self.parameter_scan.get('tipe_reg', 'Holding')
            reg_awal  = int(self.parameter_scan.get('reg_awal', 0))
            reg_akhir = int(self.parameter_scan.get('reg_akhir', 100))
            encoding  = self.parameter_scan.get('encoding', 'Mentah (16-bit UINT)')
            
            # Step selalu 1 agar tidak ada register yang terlewat
            langkah = 1
            daftar_reg = list(range(reg_awal, reg_akhir + 1, langkah))

            for idx, reg in enumerate(daftar_reg):
                if not self.apakah_berjalan: break
                progres = int(((idx + 1) / len(daftar_reg)) * 100)
                self.sinyal_progres.emit(progres, f"Memindai Register: {reg}...")
                
                # Coba baca 2 register untuk mendapatkan Float (Jika Holding/Input)
                jumlah_baca = 2 if tipe_reg in ['Holding', 'Input'] else 1
                
                kunci_komunikasi.lock()
                try:
                    res = baca_register_modbus(self.client, tipe_reg, reg, jumlah_baca, target_device_id)
                    if res and not res.isError():
                        if tipe_reg in ['Holding', 'Input']:
                            val_int = str(struct.unpack('h', struct.pack('H', res.registers[0]))[0]) if encoding == 'Signed 16-bit INT' else str(res.registers[0])
                            val_float = "-"
                            # Tambahkan pengecekan idx % 2 == 0
                            if idx % 2 == 0 and len(res.registers) >= 2:
                                val_float = dekode_register_sepasang(res.registers[0], res.registers[1], encoding)
                            hasil.append((reg, val_int, val_float))
                        else:
                            hasil.append((reg, str(res.bits[0]), "-"))
                except Exception as e:
                    self.sinyal_error.emit(f"Error saat scan register {reg}: {str(e)}")
                finally:
                    kunci_komunikasi.unlock()
                time.sleep(0.02)
                
        if self.apakah_berjalan: self.sinyal_progres.emit(100, "Proses Selesai.")
        self.sinyal_hasil.emit(hasil)
        self.sinyal_selesai.emit()


class ModbusPoolerLoggerThread(QThread):
    sinyal_data      = pyqtSignal(list, list, str, str)
    sinyal_kesalahan = pyqtSignal(str, str)

    def __init__(self, client_global, parameter, target_tab="reader", single_shot=False):
        super().__init__()
        self.client     = client_global
        self.parameter  = parameter
        self.target_tab = target_tab
        self.single_shot = single_shot
        self.apakah_berjalan = True

    def run(self):
        if not self.client or not self.client.connected:
            self.sinyal_kesalahan.emit("Koneksi master tidak aktif.", self.target_tab)
            return

        target_device_id = int(self.parameter['slave_id'])
        tipe_reg         = self.parameter['tipe_reg']
        reg_awal         = int(self.parameter['reg_awal'])
        jumlah           = int(self.parameter['jumlah'])
        encoding         = self.parameter['encoding']
        interval         = float(self.parameter['interval'])

        while self.apakah_berjalan:
            kunci_komunikasi.lock()
            try:
                if self.client.connected:
                    res = baca_register_modbus(self.client, tipe_reg, reg_awal, jumlah, target_device_id)
                    if res and res.isError():
                        self.sinyal_kesalahan.emit(f"Modbus Error: {res}", self.target_tab)
                    elif res:
                        list_alamat = list(range(reg_awal, reg_awal + jumlah))
                        if tipe_reg in ['Holding', 'Input']:
                            nilai_mentah = [str(r) for r in res.registers]
                        else:
                            nilai_mentah = [str(b) for b in res.bits[:jumlah]]
                        self.sinyal_data.emit(list_alamat, nilai_mentah, encoding, self.target_tab)
            except Exception as e:
                self.sinyal_kesalahan.emit(f"Gangguan Aliran Data: {str(e)}", self.target_tab)
            finally:
                kunci_komunikasi.unlock()

            if self.single_shot:
                break

            for _ in range(int(interval * 10)):
                if not self.apakah_berjalan: break
                time.sleep(0.1)


# =====================================================================
# ANTARMUKA UTAMA (GUI)
# =====================================================================
class ModbusApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modbus Tools Kalingin v4.17")
        self.resize(1100, 860)

        self.client_global    = None
        self.thread_pemindai  = None
        self.thread_pooler    = None
        self.thread_logger    = None
        self.memori_keterangan_user = {}
        self.nilai_sebelumnya = {}

        self.inisialisasi_ui()
        self.penyegaran_port_serial()
        self._muat_preset_terakhir()

    def inisialisasi_ui(self):
        widget_utama   = QWidget()
        self.setCentralWidget(widget_utama)
        tata_letak_utama = QVBoxLayout(widget_utama)
        tata_letak_utama.setSpacing(6)

        self._buat_menu_bar()
        self._buat_panel_koneksi(tata_letak_utama)
        self._buat_status_bar()

        self.tabs = QTabWidget()
        tata_letak_utama.addWidget(self.tabs)

        self.buat_tab_slave_id_scanner()
        self.buat_tab_register_scanner()
        self.buat_tab_reader_pooler()
        self.buat_tab_write_payload()
        self.buat_tab_logger()

    def _buat_menu_bar(self):
        menubar = self.menuBar()
        menu_file = menubar.addMenu("File")
        aksi_simpan = QAction("Export Preset Pengaturan...", self)
        aksi_simpan.triggered.connect(self.simpan_preset_koneksi)
        aksi_muat = QAction("Import Preset Pengaturan...", self)
        aksi_muat.triggered.connect(self.muat_preset_koneksi)
        menu_file.addAction(aksi_simpan)
        menu_file.addAction(aksi_muat)

        menu_export = menubar.addMenu("Export Data")
        aksi_exp_id  = QAction("Export Hasil Scan ID ke CSV", self)
        aksi_exp_id.triggered.connect(lambda: self._export_tabel_ke_csv(self.tabel_hasil_id, "scan_id"))
        aksi_exp_reg = QAction("Export Hasil Scan Register ke CSV", self)
        aksi_exp_reg.triggered.connect(lambda: self._export_tabel_ke_csv(self.tabel_hasil_register, "scan_register"))
        menu_export.addAction(aksi_exp_id)
        menu_export.addAction(aksi_exp_reg)

        menu_bantuan = menubar.addMenu("Bantuan")
        aksi_tentang = QAction("Tentang Aplikasi", self)
        aksi_tentang.triggered.connect(self._tampilkan_tentang)
        menu_bantuan.addAction(aksi_tentang)

    def _buat_panel_koneksi(self, tata_letak_utama):
        box_koneksi  = QGroupBox("Konfigurasi Jalur Komunikasi Master")
        box_koneksi.setMaximumHeight(140) 
        layout_utama = QHBoxLayout(box_koneksi)
        layout_utama.setContentsMargins(5, 5, 5, 5) 

        grp_mode = QGroupBox("Metode")
        vbox_mode = QVBoxLayout(grp_mode)
        vbox_mode.setContentsMargins(4, 10, 4, 4)
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["RTU (Serial)", "TCP (Ethernet)"])
        self.combo_mode.currentIndexChanged.connect(self.perubahan_ui_mode)
        vbox_mode.addWidget(self.combo_mode)
        vbox_mode.addStretch()
        layout_utama.addWidget(grp_mode)

        self.grp_rtu = QGroupBox("RTU Serial")
        grid_rtu = QGridLayout(self.grp_rtu)
        grid_rtu.setContentsMargins(2, 2, 2, 2)
        grid_rtu.setVerticalSpacing(2)
        grid_rtu.addWidget(QLabel("Port COM"), 0, 0)
        grid_rtu.addWidget(QLabel("Baud Rate"), 0, 1)
        grid_rtu.addWidget(QLabel("Data Bits"), 0, 2)
        grid_rtu.addWidget(QLabel("Stop Bits"), 0, 3)
        grid_rtu.addWidget(QLabel("Paritas"), 0, 4)

        self.combo_port = QComboBox()
        grid_rtu.addWidget(self.combo_port, 1, 0)
        self.combo_baud = QComboBox()
        self.combo_baud.addItems(["2400", "4800", "9600", "19200", "38400", "57600", "115200"])
        self.combo_baud.setCurrentText("9600")
        grid_rtu.addWidget(self.combo_baud, 1, 1)
        self.combo_bytesize = QComboBox()
        self.combo_bytesize.addItems(["8", "7"])
        grid_rtu.addWidget(self.combo_bytesize, 1, 2)
        self.combo_stopbits = QComboBox()
        self.combo_stopbits.addItems(["1", "2"])
        grid_rtu.addWidget(self.combo_stopbits, 1, 3)
        self.combo_parity = QComboBox()
        self.combo_parity.addItems(["N (None)", "E (Even)", "O (Odd)"])
        grid_rtu.addWidget(self.combo_parity, 1, 4)
        self.btn_refresh_port = QPushButton("Segarkan Port")
        self.btn_refresh_port.clicked.connect(self.penyegaran_port_serial)
        grid_rtu.addWidget(self.btn_refresh_port, 2, 0, 1, 2)
        layout_utama.addWidget(self.grp_rtu)

        self.grp_tcp = QGroupBox("TCP Ethernet")
        grid_tcp = QGridLayout(self.grp_tcp)
        grid_tcp.setContentsMargins(4, 10, 4, 4)
        grid_tcp.addWidget(QLabel("IP Host"), 0, 0)
        grid_tcp.addWidget(QLabel("Port TCP"), 0, 1)
        self.txt_host = QLineEdit("127.0.0.1")
        grid_tcp.addWidget(self.txt_host, 1, 0)
        self.spin_tcp_port = QSpinBox()
        self.spin_tcp_port.setRange(1, 65535)
        self.spin_tcp_port.setValue(502)
        grid_tcp.addWidget(self.spin_tcp_port, 1, 1)
        layout_utama.addWidget(self.grp_tcp)

        grp_timeout = QGroupBox("Timeout(s)")
        vbox_timeout = QVBoxLayout(grp_timeout)
        vbox_timeout.setContentsMargins(4, 10, 4, 4)
        self.spin_timeout = QDoubleSpinBox()
        self.spin_timeout.setRange(0.1, 30.0)
        self.spin_timeout.setValue(1.0)
        vbox_timeout.addWidget(self.spin_timeout)
        vbox_timeout.addStretch()
        layout_utama.addWidget(grp_timeout)

        # ── Kolom Aksi & Indikator (Ditata Secara Proporsional) ─────────
        grp_aksi = QGroupBox("Koneksi")
        vbox_aksi = QVBoxLayout(grp_aksi)
        vbox_aksi.setContentsMargins(2, 2, 2, 2)
        
        # FIX: Tombol Hubungkan & Putuskan diposisikan side-by-side
        hbox_btn = QHBoxLayout()
        
        # Jarak antar tombol 10 pixel
        hbox_btn.setSpacing(10) 

        self.btn_hubungkan = QPushButton("Hubungkan")
        # Mengubah tinggi dan lebar tombol
        self.btn_hubungkan.setFixedSize(100, 35) 
        self.btn_hubungkan.clicked.connect(self.buka_koneksi_modbus)
        
        self.btn_putuskan = QPushButton("Putuskan")
        self.btn_putuskan.setFixedSize(100, 35)
        self.btn_putuskan.setEnabled(False)
        self.btn_putuskan.clicked.connect(self.tutup_koneksi_modbus)
        
        # Mendorong tombol ke tengah
        hbox_btn.addWidget(self.btn_hubungkan)
        hbox_btn.addWidget(self.btn_putuskan)

        self.lbl_indikator = QLabel("● OFFLINE")
        self.lbl_indikator.setAlignment(Qt.AlignCenter)
        self.lbl_indikator.setStyleSheet(f"color: {WARNA_GAGAL}; font-weight: bold; font-size: 13px;")
        
        vbox_aksi.addLayout(hbox_btn)
        vbox_aksi.addSpacing(4)
        vbox_aksi.addWidget(self.lbl_indikator)
        vbox_aksi.addStretch()
        layout_utama.addWidget(grp_aksi)

        tata_letak_utama.addWidget(box_koneksi)
        self.perubahan_ui_mode()

    def _buat_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.lbl_status_teks = QLabel("Sistem Berhenti / Belum Terkoneksi.")
        self.status_bar.addWidget(self.lbl_status_teks, 1)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumWidth(200)
        self.status_bar.addPermanentWidget(self.progress_bar)

    def _set_status(self, pesan, progres=-1):
        self.lbl_status_teks.setText(pesan)
        if progres >= 0:
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(progres)
        else:
            self.progress_bar.setVisible(False)

    def penyegaran_port_serial(self):
        self.combo_port.clear()
        ports_terdeteksi = {}

        # 1) Deteksi via pyserial (comports()).
        #    Di banyak board Linux embedded (termasuk Rockchip), pyserial hanya
        #    mengenali port yang punya symlink 'device' lengkap di sysfs — biasanya
        #    UART via USB (ttyUSBx/ttyACMx). UART bawaan board seperti ttyS0-ttyS4
        #    sering TIDAK ikut terdeteksi walau nodenya benar-benar ada di /dev.
        try:
            for p in serial.tools.list_ports.comports():
                ports_terdeteksi[p.device] = p.description
        except Exception as e:
            self._log_gagal_deteksi_port(str(e))

        # 2) FIX: fallback pemindaian manual ke /dev untuk pola UART yang umum
        #    dipakai di board embedded (termasuk Rockchip ttyS0-ttyS4), supaya
        #    port yang terlewat oleh pyserial tetap muncul di daftar.
        pola_tambahan = [
            "/dev/ttyS*",      # UART bawaan SoC (mis. Rockchip ttyS0-ttyS4)
            "/dev/ttyUSB*",    # USB-to-serial (FTDI, CH340, dst)
            "/dev/ttyACM*",    # USB CDC-ACM
            "/dev/ttyAMA*",    # UART PL011 (mis. Raspberry Pi/board ARM lain)
            "/dev/ttyFIQ*",    # UART fastcall khusus sebagian board Rockchip
        ]
        try:
            import glob
            for pola in pola_tambahan:
                for dev in glob.glob(pola):
                    if dev not in ports_terdeteksi:
                        ports_terdeteksi[dev] = "Terdeteksi manual (UART board)"
        except Exception as e:
            self._log_gagal_deteksi_port(str(e))

        for dev in sorted(ports_terdeteksi.keys()):
            self.combo_port.addItem(dev)

        if self.combo_port.count() == 0:
            self.combo_port.addItem("Tidak Ada Port")

    def _log_gagal_deteksi_port(self, pesan_error):
        # Tidak menghentikan aplikasi hanya karena satu metode deteksi gagal
        # (mis. karena permission), tetapi tetap diberi tahu ke status bar.
        try:
            self._set_status(f"Peringatan saat memindai port: {pesan_error}")
        except Exception:
            pass

    def perubahan_ui_mode(self):
        is_rtu = "RTU" in self.combo_mode.currentText()
        self.grp_rtu.setVisible(is_rtu)
        self.grp_tcp.setVisible(not is_rtu)

    def dapatkan_konfigurasi_koneksi(self):
        paritas_map = {"N (None)": "N", "E (Even)": "E", "O (Odd)": "O"}
        return {
            'mode':     'RTU' if "RTU" in self.combo_mode.currentText() else 'TCP',
            'port':     self.combo_port.currentText(),
            'baudrate': self.combo_baud.currentText(),
            'parity':   paritas_map.get(self.combo_parity.currentText(), 'N'),
            'stopbits': self.combo_stopbits.currentText(),
            'bytesize': self.combo_bytesize.currentText(),
            'host':     self.txt_host.text(),
            'tcp_port': self.spin_tcp_port.value(),
            'timeout':  self.spin_timeout.value()
        }

    def box_pengunci_koneksi(self, disabled):
        self.combo_mode.setEnabled(not disabled)
        self.combo_port.setEnabled(not disabled)
        self.combo_baud.setEnabled(not disabled)
        self.combo_parity.setEnabled(not disabled)
        self.combo_stopbits.setEnabled(not disabled)
        self.combo_bytesize.setEnabled(not disabled)
        self.txt_host.setEnabled(not disabled)
        self.spin_tcp_port.setEnabled(not disabled)
        self.spin_timeout.setEnabled(not disabled)
        self.btn_refresh_port.setEnabled(not disabled)

    def buka_koneksi_modbus(self):
        config = self.dapatkan_konfigurasi_koneksi()
        if config['mode'] == 'RTU' and config['port'] == "Tidak Ada Port":
            QMessageBox.warning(self, "Port Tidak Tersedia",
                                 "Tidak ada port serial yang terdeteksi. "
                                 "Klik 'Segarkan Port' atau periksa hak akses /dev/ttyS*.")
            return
        try:
            if config['mode'] == 'RTU':
                self.client_global = _buat_client_rtu(
                    port=config['port'], baudrate=int(config['baudrate']),
                    parity=config['parity'], stopbits=int(config['stopbits']),
                    bytesize=int(config['bytesize']), timeout=float(config['timeout'])
                )
            else:
                self.client_global = _buat_client_tcp(
                    host=config['host'], port=int(config['tcp_port']), timeout=float(config['timeout'])
                )

            if self.client_global.connect():
                self.btn_hubungkan.setEnabled(False)
                self.btn_putuskan.setEnabled(True)
                self.box_pengunci_koneksi(True)
                if config['mode'] == 'RTU':
                    self._set_status("Menunggu inisialisasi sinkronisasi perangkat...")
                    QTimer.singleShot(2000, self._selesai_koneksi_rtu)
                else:
                    self._selesai_koneksi_rtu()
            else:
                self._set_status("Gagal membuka komunikasi fisik ke perangkat.")
        except Exception as e:
            QMessageBox.critical(self, "Error Koneksi", f"Gagal Inisialisasi: {str(e)}")

    def _selesai_koneksi_rtu(self):
        self.lbl_indikator.setText("● ONLINE")
        self.lbl_indikator.setStyleSheet(f"color: {WARNA_SUKSES}; font-weight: bold;")
        self._set_status("Koneksi berhasil dibuka.")

    def tutup_koneksi_modbus(self):
        self.matikan_semua_thread_aktif()
        if self.client_global:
            self.client_global.close()
        self.client_global = None
        self.btn_hubungkan.setEnabled(True)
        self.btn_putuskan.setEnabled(False)
        self.box_pengunci_koneksi(False)
        self.lbl_indikator.setText("● OFFLINE")
        self.lbl_indikator.setStyleSheet(f"color: {WARNA_GAGAL}; font-weight: bold;")
        self._set_status("Koneksi diputus.")

    def simpan_preset_koneksi(self):
        config = self.dapatkan_konfigurasi_koneksi()
        jalur, _ = QFileDialog.getSaveFileName(self, "Export Preset Pengaturan", "modbus_presets.json", "JSON Files (*.json)")
        if not jalur: return
        try:
            with open(jalur, 'w') as f:
                json.dump(config, f, indent=4)
            QMessageBox.information(self, "Berhasil", "Preset pengaturan berhasil diekspor.")
            with open(FILE_PRESET, 'w') as f:
                 json.dump(config, f)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Gagal mengekspor: {str(e)}")

    def muat_preset_koneksi(self):
        jalur, _ = QFileDialog.getOpenFileName(self, "Import Preset Pengaturan", "", "JSON Files (*.json)")
        if not jalur: return
        try:
            self._terapkan_preset_dari_file(jalur)
            QMessageBox.information(self, "Berhasil", "Preset pengaturan berhasil dimuat.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Gagal memuat preset: {str(e)}")

    def _muat_preset_terakhir(self):
        try:
            self._terapkan_preset_dari_file(FILE_PRESET)
        except: pass

    def _terapkan_preset_dari_file(self, jalur):
        if not os.path.exists(jalur): return
        with open(jalur, 'r') as f:
            config = json.load(f)
        if config.get('mode') == 'RTU':
            self.combo_mode.setCurrentText("RTU (Serial)")
        else:
            self.combo_mode.setCurrentText("TCP (Ethernet)")
        
        idx = self.combo_baud.findText(str(config.get('baudrate', '9600')))
        if idx >= 0: self.combo_baud.setCurrentIndex(idx)
        parity_rev = {"N": "N (None)", "E": "E (Even)", "O": "O (Odd)"}
        self.combo_parity.setCurrentText(parity_rev.get(config.get('parity', 'N'), 'N (None)'))
        self.combo_stopbits.setCurrentText(str(config.get('stopbits', '1')))
        self.combo_bytesize.setCurrentText(str(config.get('bytesize', '8')))
        self.txt_host.setText(config.get('host', '127.0.0.1'))
        self.spin_tcp_port.setValue(int(config.get('tcp_port', 502)))
        self.spin_timeout.setValue(float(config.get('timeout', 1.0)))

        # FIX: preset port serial sebelumnya tidak pernah diterapkan kembali
        # (kolom 'port' pada config diabaikan sepenuhnya). Kini dicoba dipilih
        # ulang jika port tersebut masih terdeteksi di combo_port.
        port_tersimpan = config.get('port', '')
        if port_tersimpan:
            idx_port = self.combo_port.findText(port_tersimpan)
            if idx_port >= 0:
                self.combo_port.setCurrentIndex(idx_port)

    def manajemen_interlock_tombol(self, tab_aktif, status_reset=False):
        kondisi = status_reset
        if tab_aktif != "scan_id": self.btn_start_id_scan.setEnabled(kondisi)
        if tab_aktif != "scan_reg": self.btn_start_reg_scan.setEnabled(kondisi)
        if tab_aktif != "pool": 
            self.btn_toggle_pool.setEnabled(kondisi)
            self.btn_single_read.setEnabled(kondisi)
        if tab_aktif != "log": self.btn_toggle_logger.setEnabled(kondisi)
        if tab_aktif != "write": self.btn_execute_write.setEnabled(kondisi)


    # ==================================================================
    # TAB 1: DEVICE ID SCANNER
    # ==================================================================
    def buat_tab_slave_id_scanner(self):
        tab = QWidget()
        tata_letak = QHBoxLayout(tab)
        
        box_kontrol = QGroupBox("Pengaturan ID")
        box_kontrol.setMaximumWidth(320)
        grid_kiri = QGridLayout(box_kontrol)
        
        grid_kiri.addWidget(QLabel("ID Awal:"), 0, 0)
        self.spin_start_id = QSpinBox()
        self.spin_start_id.setRange(1, 247)
        self.spin_start_id.setValue(1)
        grid_kiri.addWidget(self.spin_start_id, 0, 1)

        grid_kiri.addWidget(QLabel("ID Akhir:"), 1, 0)
        self.spin_end_id = QSpinBox()
        self.spin_end_id.setRange(1, 247)
        self.spin_end_id.setValue(10)
        grid_kiri.addWidget(self.spin_end_id, 1, 1)

        grid_kiri.addWidget(QLabel("Tipe Reg Uji:"), 2, 0)
        self.combo_id_scan_reg_type = QComboBox()
        self.combo_id_scan_reg_type.addItems(["Holding", "Input", "Coil", "Discrete Input"])
        grid_kiri.addWidget(self.combo_id_scan_reg_type, 2, 1)

        grid_kiri.addWidget(QLabel("Alamat Reg Uji:"), 3, 0)
        self.spin_test_reg = QSpinBox()
        self.spin_test_reg.setRange(0, 65535)
        grid_kiri.addWidget(self.spin_test_reg, 3, 1)

        self.btn_start_id_scan = QPushButton("Mulai Scan")
        self.btn_start_id_scan.clicked.connect(self.eksekusi_scan_id)
        grid_kiri.addWidget(self.btn_start_id_scan, 4, 0, 1, 2)
        
        self.btn_stop_id_scan = QPushButton("Berhenti")
        self.btn_stop_id_scan.setEnabled(False)
        self.btn_stop_id_scan.clicked.connect(self.hentikan_scan_id_paksa)
        grid_kiri.addWidget(self.btn_stop_id_scan, 5, 0, 1, 2)
        
        btn_export_id = QPushButton("Export CSV")
        btn_export_id.clicked.connect(lambda: self._export_tabel_ke_csv(self.tabel_hasil_id, "scan_id_hasil"))
        grid_kiri.addWidget(btn_export_id, 6, 0, 1, 2)
        
        grid_kiri.setRowStretch(7, 1) 

        self.tabel_hasil_id = QTableWidget(0, 2)
        self.tabel_hasil_id.setHorizontalHeaderLabels(["Device ID", "Status Komunikasi"])
        self.tabel_hasil_id.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(box_kontrol)
        splitter.addWidget(self.tabel_hasil_id)
        splitter.setStretchFactor(0, 0) 
        splitter.setStretchFactor(1, 1)
        tata_letak.addWidget(splitter)
        self.tabs.addTab(tab, "Pemindai Device ID")

    def eksekusi_scan_id(self):
        if not self.client_global or not self.client_global.connected:
            self._set_status("Error: Hubungkan koneksi utama terlebih dahulu!")
            return
        if self.spin_start_id.value() > self.spin_end_id.value():
            QMessageBox.warning(self, "Parameter Salah", "ID Awal harus <= ID Akhir.")
            return

        self.manajemen_interlock_tombol("scan_id")
        self.btn_stop_id_scan.setEnabled(True)
        params = {
            'id_awal': self.spin_start_id.value(),
            'id_akhir': self.spin_end_id.value(),
            'tipe_reg': self.combo_id_scan_reg_type.currentText(),
            'reg_uji': self.spin_test_reg.value()
        }
        self.tabel_hasil_id.setRowCount(0)
        self.thread_pemindai = ModbusScannerThread(self.client_global, "id", params)
        self.thread_pemindai.sinyal_progres.connect(lambda p, s: self._set_status(f"[{p}%] {s}", p))
        self.thread_pemindai.sinyal_hasil.connect(self.tampilkan_hasil_scan_id)
        self.thread_pemindai.sinyal_selesai.connect(self.selesai_scan_id_callback)
        self.thread_pemindai.sinyal_error.connect(lambda msg: self._set_status(f"{msg}"))
        self.thread_pemindai.start()

    def hentikan_scan_id_paksa(self):
        if self.thread_pemindai and self.thread_pemindai.isRunning():
            self.thread_pemindai.apakah_berjalan = False
            self.btn_stop_id_scan.setEnabled(False)

    def selesai_scan_id_callback(self):
        self.btn_stop_id_scan.setEnabled(False)
        self.manajemen_interlock_tombol(None, status_reset=True)
        self._set_status(f"Scan ID selesai. {self.tabel_hasil_id.rowCount()} device ditemukan.")

    def tampilkan_hasil_scan_id(self, hasil):
        for slave_id, status in hasil:
            baris = self.tabel_hasil_id.rowCount()
            self.tabel_hasil_id.insertRow(baris)
            item_id = QTableWidgetItem(str(slave_id))
            item_id.setTextAlignment(Qt.AlignCenter)
            item_status = QTableWidgetItem(status)
            item_status.setTextAlignment(Qt.AlignCenter)
            item_status.setForeground(QColor(WARNA_SUKSES))
            font = QFont(); font.setBold(True); item_status.setFont(font)
            self.tabel_hasil_id.setItem(baris, 0, item_id)
            self.tabel_hasil_id.setItem(baris, 1, item_status)


    # ==================================================================
    # TAB 2: REGISTER MAP SCANNER (MENAMPILKAN INT & FLOAT SECARA BERSAMAAN)
    # ==================================================================
    def buat_tab_register_scanner(self):
        tab = QWidget()
        tata_letak = QHBoxLayout(tab)
        box_kontrol = QGroupBox("Pengaturan Register")
        box_kontrol.setMaximumWidth(320)
        grid_kiri = QGridLayout(box_kontrol)

        grid_kiri.addWidget(QLabel("Target ID:"), 0, 0)
        self.spin_reg_scan_slave = QSpinBox()
        self.spin_reg_scan_slave.setValue(1)
        grid_kiri.addWidget(self.spin_reg_scan_slave, 0, 1)

        grid_kiri.addWidget(QLabel("Jenis Register:"), 1, 0)
        self.combo_reg_scan_type = QComboBox()
        self.combo_reg_scan_type.addItems(["Holding", "Input", "Coil", "Discrete Input"])
        grid_kiri.addWidget(self.combo_reg_scan_type, 1, 1)

        grid_kiri.addWidget(QLabel("Alamat Awal:"), 2, 0)
        self.spin_reg_scan_start = QSpinBox()
        self.spin_reg_scan_start.setRange(0, 65535)
        grid_kiri.addWidget(self.spin_reg_scan_start, 2, 1)

        grid_kiri.addWidget(QLabel("Alamat Akhir:"), 3, 0)
        self.spin_reg_scan_end = QSpinBox()
        self.spin_reg_scan_end.setRange(0, 65535)
        self.spin_reg_scan_end.setValue(100)
        grid_kiri.addWidget(self.spin_reg_scan_end, 3, 1)

        grid_kiri.addWidget(QLabel("Format FLOAT:"), 4, 0)
        self.combo_reg_scan_enc = QComboBox()
        self.combo_reg_scan_enc.addItems(DAFTAR_ENCODING)
        grid_kiri.addWidget(self.combo_reg_scan_enc, 4, 1)

        self.btn_start_reg_scan = QPushButton("Mulai Pemindaian")
        self.btn_start_reg_scan.clicked.connect(self.eksekusi_scan_register)
        grid_kiri.addWidget(self.btn_start_reg_scan, 5, 0, 1, 2)

        self.btn_stop_reg_scan = QPushButton("Berhenti")
        self.btn_stop_reg_scan.setEnabled(False)
        self.btn_stop_reg_scan.clicked.connect(self.hentikan_scan_reg_paksa)
        grid_kiri.addWidget(self.btn_stop_reg_scan, 6, 0, 1, 2)
        
        grid_kiri.setRowStretch(7, 1)

        # FIX: Tabel menampung Alamat, INT, dan FLOAT sekaligus
        self.tabel_hasil_register = QTableWidget(0, 3)
        self.tabel_hasil_register.setHorizontalHeaderLabels(["Alamat Register", "Nilai INT (16-bit)", "Nilai FLOAT (32-bit)"])
        self.tabel_hasil_register.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(box_kontrol)
        splitter.addWidget(self.tabel_hasil_register)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        tata_letak.addWidget(splitter)
        self.tabs.addTab(tab, "Pemindai Peta Register")

    def eksekusi_scan_register(self):
        if not self.client_global or not self.client_global.connected:
            self._set_status("Error: Koneksi utama belum aktif!")
            return
        if self.spin_reg_scan_start.value() > self.spin_reg_scan_end.value():
            QMessageBox.warning(self, "Parameter Salah", "Alamat Awal tidak boleh > Akhir.")
            return

        self.manajemen_interlock_tombol("scan_reg")
        self.btn_stop_reg_scan.setEnabled(True)
        params = {
            'slave_id': self.spin_reg_scan_slave.value(),
            'tipe_reg': self.combo_reg_scan_type.currentText(),
            'reg_awal': self.spin_reg_scan_start.value(),
            'reg_akhir': self.spin_reg_scan_end.value(),
            'encoding': self.combo_reg_scan_enc.currentText()
        }
        self.tabel_hasil_register.setRowCount(0)

        self.thread_pemindai = ModbusScannerThread(self.client_global, "register", params)
        self.thread_pemindai.sinyal_progres.connect(lambda p, s: self._set_status(f"[{p}%] {s}", p))
        self.thread_pemindai.sinyal_hasil.connect(self.tampilkan_hasil_scan_register)
        self.thread_pemindai.sinyal_selesai.connect(self.selesai_scan_reg_callback)
        self.thread_pemindai.sinyal_error.connect(lambda msg: self._set_status(f"{msg}"))
        self.thread_pemindai.start()

    def hentikan_scan_reg_paksa(self):
        if self.thread_pemindai and self.thread_pemindai.isRunning():
            self.thread_pemindai.apakah_berjalan = False
            self.btn_stop_reg_scan.setEnabled(False)

    def selesai_scan_reg_callback(self):
        self.btn_stop_reg_scan.setEnabled(False)
        self.manajemen_interlock_tombol(None, status_reset=True)
        self._set_status(f"Scan register selesai. {self.tabel_hasil_register.rowCount()} ditemukan.")

    def tampilkan_hasil_scan_register(self, hasil):
        for reg, val_int, val_float in hasil:
            baris = self.tabel_hasil_register.rowCount()
            self.tabel_hasil_register.insertRow(baris)
            self.tabel_hasil_register.setItem(baris, 0, QTableWidgetItem(str(reg)))
            self.tabel_hasil_register.setItem(baris, 1, QTableWidgetItem(val_int))
            self.tabel_hasil_register.setItem(baris, 2, QTableWidgetItem(val_float))


    # ==================================================================
    # TAB 3: DATA READER (POOLER) & INT FLOAT DECODE BERSAMAAN
    # ==================================================================
    def buat_tab_reader_pooler(self):
        tab = QWidget()
        tata_letak = QHBoxLayout(tab)
        box_konfig = QGroupBox("Pengaturan Pembacaan")
        box_konfig.setMaximumWidth(320)
        grid_kiri = QGridLayout(box_konfig)

        grid_kiri.addWidget(QLabel("Target ID:"), 0, 0)
        self.spin_read_slave = QSpinBox()
        self.spin_read_slave.setValue(1)
        grid_kiri.addWidget(self.spin_read_slave, 0, 1)

        grid_kiri.addWidget(QLabel("Jenis Reg:"), 1, 0)
        self.combo_read_type = QComboBox()
        self.combo_read_type.addItems(["Holding", "Input", "Coil", "Discrete Input"])
        grid_kiri.addWidget(self.combo_read_type, 1, 1)

        grid_kiri.addWidget(QLabel("Alamat Awal:"), 2, 0)
        self.spin_read_addr = QSpinBox()
        self.spin_read_addr.setRange(0, 65535)
        grid_kiri.addWidget(self.spin_read_addr, 2, 1)

        grid_kiri.addWidget(QLabel("Jumlah Baris:"), 3, 0)
        self.spin_read_count = QSpinBox()
        self.spin_read_count.setRange(1, 125)
        self.spin_read_count.setValue(4)
        grid_kiri.addWidget(self.spin_read_count, 3, 1)

        grid_kiri.addWidget(QLabel("Format FLOAT:"), 4, 0)
        self.combo_encoding = QComboBox()
        self.combo_encoding.addItems(DAFTAR_ENCODING)
        grid_kiri.addWidget(self.combo_encoding, 4, 1)

        grid_kiri.addWidget(QLabel("Interval (s):"), 5, 0)
        self.spin_pool_interval = QDoubleSpinBox()
        self.spin_pool_interval.setRange(0.1, 10.0)
        self.spin_pool_interval.setValue(1.0)
        grid_kiri.addWidget(self.spin_pool_interval, 5, 1)

        self.btn_single_read = QPushButton("Baca Sekali (Tunggal)")
        self.btn_single_read.clicked.connect(lambda: self.eksekusi_baca_reader(tunggal=True))
        grid_kiri.addWidget(self.btn_single_read, 6, 0, 1, 2)

        self.btn_toggle_pool = QPushButton("▶ Mulai Polling Otomatis")
        self.btn_toggle_pool.clicked.connect(lambda: self.eksekusi_baca_reader(tunggal=False))
        grid_kiri.addWidget(self.btn_toggle_pool, 7, 0, 1, 2)
        
        grid_kiri.setRowStretch(8, 1)

        # FIX: Tabel Reader Live yang menampilkan gabungan int & float secara bersamaan
        self.tabel_reader_output = QTableWidget(0, 4)
        self.tabel_reader_output.setHorizontalHeaderLabels(["Alamat", "Nilai INT", "Nilai FLOAT", "Keterangan"])
        self.tabel_reader_output.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(box_konfig)
        splitter.addWidget(self.tabel_reader_output)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        tata_letak.addWidget(splitter)
        self.tabs.addTab(tab, "Pembaca Modbus Live")

    def eksekusi_baca_reader(self, tunggal=False):
        if not tunggal and self.thread_pooler and self.thread_pooler.isRunning():
            self.thread_pooler.apakah_berjalan = False
            self.btn_toggle_pool.setText("▶ Mulai Polling Otomatis")
            self.manajemen_interlock_tombol(None, status_reset=True)
            self._set_status("Polling dihentikan.")
            return

        if not self.client_global or not self.client_global.connected:
            self._set_status("Error: Koneksi utama belum aktif.")
            return

        target_device_id = self.spin_read_slave.value()
        tipe_reg_saat_ini = self.combo_read_type.currentText()
        params = {
            'slave_id': target_device_id,
            'tipe_reg': tipe_reg_saat_ini,
            'reg_awal': self.spin_read_addr.value(),
            'jumlah': self.spin_read_count.value(),
            'encoding': self.combo_encoding.currentText(),
            'interval': self.spin_pool_interval.value()
        }

        if not tunggal:
            self.manajemen_interlock_tombol("pool")
            self.btn_toggle_pool.setText("■ Hentikan Polling")
            self._set_status("Polling berkala aktif...")
        else:
            self._set_status("Melakukan pembacaan tunggal...")

        self.thread_pooler = ModbusPoolerLoggerThread(self.client_global, params, "reader", single_shot=tunggal)
        self.thread_pooler.sinyal_data.connect(lambda la, nm, enc, _: self.perbarui_tabel_reader(la, nm, enc, tipe_reg_saat_ini, target_device_id))
        self.thread_pooler.sinyal_kesalahan.connect(lambda msg, _: self._set_status(f"Pooler: {msg}"))
        self.thread_pooler.start()

    def perbarui_tabel_reader(self, list_alamat, nilai_mentah, encoding, tipe_reg, device_id=0):
        try: self.tabel_reader_output.itemChanged.disconnect(self.tangkap_perubahan_keterangan_user)
        except TypeError: pass

        self.tabel_reader_output.setRowCount(0)
        
        # Eksekusi tampilan data di mana kita memecah ke dalam nilai INT (1 Reg) dan Float (2 Reg overlap)
        for idx, addr in enumerate(list_alamat):
            baris = self.tabel_reader_output.rowCount()
            self.tabel_reader_output.insertRow(baris)
            
            item_addr = QTableWidgetItem(f"Reg {addr}")
            item_addr.setFlags(item_addr.flags() & ~Qt.ItemIsEditable)
            self.tabel_reader_output.setItem(baris, 0, item_addr)

            if tipe_reg in ['Holding', 'Input']:
                if encoding == 'Signed 16-bit INT':
                    val_int = str(struct.unpack('h', struct.pack('H', int(nilai_mentah[idx])))[0])
                else:
                    val_int = str(nilai_mentah[idx])
                
                val_float = "-"
                # Decode float dengan register saat ini dan berikutnya (menghasilkan nilai overlap perbaris)
                if idx % 2 == 0 and (idx + 1) < len(nilai_mentah):
                    val_float = dekode_register_sepasang(int(nilai_mentah[idx]), int(nilai_mentah[idx+1]), encoding)
                else:
                    val_float = "-"
            else:
                val_int = str(nilai_mentah[idx])
                val_float = "-"

            item_val_int = QTableWidgetItem(val_int)
            item_val_int.setFlags(item_val_int.flags() & ~Qt.ItemIsEditable)
            item_val_float = QTableWidgetItem(val_float)
            item_val_float.setFlags(item_val_float.flags() & ~Qt.ItemIsEditable)
            
            kunci_cache_int = f"{device_id}_{tipe_reg}_{addr}_int"
            if kunci_cache_int in self.nilai_sebelumnya and self.nilai_sebelumnya[kunci_cache_int] != val_int:
                item_val_int.setBackground(QColor(WARNA_HIGHLIGHT))
            self.nilai_sebelumnya[kunci_cache_int] = val_int

            kunci_cache_float = f"{device_id}_{tipe_reg}_{addr}_flt"
            if kunci_cache_float in self.nilai_sebelumnya and self.nilai_sebelumnya[kunci_cache_float] != val_float:
                item_val_float.setBackground(QColor(WARNA_HIGHLIGHT))
            self.nilai_sebelumnya[kunci_cache_float] = val_float

            self.tabel_reader_output.setItem(baris, 1, item_val_int)
            self.tabel_reader_output.setItem(baris, 2, item_val_float)

            ket = self.memori_keterangan_user.get(f"{device_id}_{tipe_reg}_{addr}", "")
            self.tabel_reader_output.setItem(baris, 3, QTableWidgetItem(ket))

        self.tabel_reader_output.itemChanged.connect(self.tangkap_perubahan_keterangan_user)

    def tangkap_perubahan_keterangan_user(self, item):
        # FIX: Pindah penangkapan keterangan ke indeks kolom ke-3 (karena 1 dan 2 dihuni Int dan Float)
        if item.column() == 3: 
            baris = item.row()
            addr_str = self.tabel_reader_output.item(baris, 0).text().replace("Reg ", "")
            dev_id = self.spin_read_slave.value()
            t_reg = self.combo_read_type.currentText()
            kunci = f"{dev_id}_{t_reg}_{addr_str}"
            self.memori_keterangan_user[kunci] = item.text()


    # ==================================================================
    # TAB 4: WRITE PAYLOAD
    # ==================================================================
    def buat_tab_write_payload(self):
        tab = QWidget()
        tata_letak = QHBoxLayout(tab)
        box_nulis = QGroupBox("Kontrol Transmisi")
        box_nulis.setMaximumWidth(320)
        grid_kiri = QGridLayout(box_nulis)

        grid_kiri.addWidget(QLabel("Target ID:"), 0, 0)
        self.spin_write_slave = QSpinBox()
        self.spin_write_slave.setValue(1)
        grid_kiri.addWidget(self.spin_write_slave, 0, 1)

        grid_kiri.addWidget(QLabel("Fungsi Tulis:"), 1, 0)
        self.combo_write_type = QComboBox()
        self.combo_write_type.addItems(["Write Single Coil (FC 05)", "Write Single Register (FC 06)", 
                                        "Write Multiple Coils (FC 15)", "Write Multiple Registers (FC 16)"])
        grid_kiri.addWidget(self.combo_write_type, 1, 1)

        grid_kiri.addWidget(QLabel("Alamat Tujuan:"), 2, 0)
        self.spin_write_addr = QSpinBox()
        self.spin_write_addr.setRange(0, 65535)
        grid_kiri.addWidget(self.spin_write_addr, 2, 1)

        grid_kiri.addWidget(QLabel("Format Data:"), 3, 0)
        self.combo_write_encoding = QComboBox()
        self.combo_write_encoding.addItems(DAFTAR_ENCODING)
        grid_kiri.addWidget(self.combo_write_encoding, 3, 1)

        grid_kiri.addWidget(QLabel("Nilai Input:"), 4, 0)
        self.txt_write_payload = QLineEdit("12.34")
        grid_kiri.addWidget(self.txt_write_payload, 4, 1)

        self.btn_execute_write = QPushButton("Transmisikan Data")
        self.btn_execute_write.clicked.connect(self.eksekusi_penulisan_modbus)
        grid_kiri.addWidget(self.btn_execute_write, 5, 0, 1, 2)
        
        grid_kiri.setRowStretch(6, 1)

        box_log_nulis = QGroupBox("Terminal Validasi")
        tata_letak_log = QVBoxLayout(box_log_nulis)
        self.txt_write_log = QTextEdit()
        self.txt_write_log.setReadOnly(True)
        tata_letak_log.addWidget(self.txt_write_log)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(box_nulis)
        splitter.addWidget(box_log_nulis)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        tata_letak.addWidget(splitter)
        self.tabs.addTab(tab, "Write Register / Coil")

    def eksekusi_penulisan_modbus(self):
        if not self.client_global or not self.client_global.connected:
            QMessageBox.critical(self, "Error", "Master Modbus belum terhubung!")
            return

        tipe_fungsi = self.combo_write_type.currentText()
        alamat_tujuan = self.spin_write_addr.value()
        target_device_id = self.spin_write_slave.value()
        input_user = self.txt_write_payload.text()
        waktu_skrg = datetime.now().strftime("%H:%M:%S")
        register_final = []
        val_bool = False

        if "Coil" in tipe_fungsi:
            val_bool = input_user.lower() in ['1', 'true', 'on']
        else:
            try:
                if "Multiple" in tipe_fungsi and "," in input_user:
                    elemen = input_user.split(",")
                    for e in elemen:
                        register_final.extend(enkode_nilai_ke_register(e.strip(), self.combo_write_encoding.currentText()))
                else:
                    register_final = enkode_nilai_ke_register(input_user, self.combo_write_encoding.currentText())
            except ValueError as e:
                self.txt_write_log.append(f"[{waktu_skrg}] <font color='red'>Error Parsing Data: {str(e)}</font>")
                return

        self.manajemen_interlock_tombol("write")
        kunci_komunikasi.lock()
        try:
            kwargs = {'address': alamat_tujuan}
            kwargs.update(get_modbus_device_kwargs(target_device_id))

            if "Single Coil" in tipe_fungsi:
                kwargs['value'] = val_bool
                res = self.client_global.write_coil(**kwargs)
            elif "Single Register" in tipe_fungsi:
                kwargs['value'] = register_final[0]
                res = self.client_global.write_register(**kwargs)
            elif "Multiple Coils" in tipe_fungsi:
                elemen = [e for e in input_user.split(",") if e.strip()]
                kwargs['values'] = [x.lower() in ['1', 'true', 'on'] for x in elemen]
                res = self.client_global.write_coils(**kwargs)
            elif "Multiple Registers" in tipe_fungsi:
                kwargs['values'] = register_final
                res = self.client_global.write_registers(**kwargs)
            else:
                res = None

            if res and res.isError():
                self.txt_write_log.append(f"[{waktu_skrg}] <font color='red'>Gagal! Respons Modbus Error: {res}</font>")
            elif res:
                # Tangkap nilai data yang dieksekusi berdasarkan jenis perintah
                if "Single Coil" in tipe_fungsi:
                    data_kirim = str(val_bool)
                elif "Single Register" in tipe_fungsi:
                    data_kirim = str(register_final[0])
                elif "Multiple Coils" in tipe_fungsi:
                    data_kirim = str(kwargs.get('values', []))
                else:
                    # Untuk Multiple Registers
                    data_kirim = str(register_final)
                
                # Tampilkan data_kirim pada log interface
                self.txt_write_log.append(f"[{waktu_skrg}] <font color='green'>Transmisi Sukses → Addr: {alamat_tujuan} | ID: {target_device_id} | Data: {data_kirim}</font>")
        except Exception as e:
            self.txt_write_log.append(f"[{waktu_skrg}] <font color='red'>Kesalahan Hardware: {str(e)}</font>")
        finally:
            kunci_komunikasi.unlock()
            self.manajemen_interlock_tombol(None, status_reset=True)


    # ==================================================================
    # TAB 5: AUTOMATED LOGGER KE CSV
    # ==================================================================
    def buat_tab_logger(self):
        tab = QWidget()
        tata_letak = QHBoxLayout(tab) 

        box_kontrol = QGroupBox("Pengaturan Data Logger")
        box_kontrol.setMaximumWidth(320)
        grid_kiri = QGridLayout(box_kontrol)
        
        grid_kiri.addWidget(QLabel("Target ID:"), 0, 0)
        self.spin_log_slave = QSpinBox()
        self.spin_log_slave.setValue(1)
        grid_kiri.addWidget(self.spin_log_slave, 0, 1)

        grid_kiri.addWidget(QLabel("Jenis Reg:"), 1, 0)
        self.combo_log_type = QComboBox()
        self.combo_log_type.addItems(["Holding", "Input", "Coil", "Discrete Input"])
        grid_kiri.addWidget(self.combo_log_type, 1, 1)

        grid_kiri.addWidget(QLabel("Alamat Awal:"), 2, 0)
        self.spin_log_addr = QSpinBox()
        self.spin_log_addr.setRange(0, 65535)
        grid_kiri.addWidget(self.spin_log_addr, 2, 1)

        grid_kiri.addWidget(QLabel("Jumlah:"), 3, 0)
        self.spin_log_count = QSpinBox()
        self.spin_log_count.setRange(1, 125)
        grid_kiri.addWidget(self.spin_log_count, 3, 1)

        grid_kiri.addWidget(QLabel("Format:"), 4, 0)
        self.combo_log_encoding = QComboBox()
        self.combo_log_encoding.addItems(DAFTAR_ENCODING)
        grid_kiri.addWidget(self.combo_log_encoding, 4, 1)

        grid_kiri.addWidget(QLabel("Interval (s):"), 5, 0)
        self.spin_log_interval = QDoubleSpinBox()
        self.spin_log_interval.setRange(0.1, 3600.0)
        self.spin_log_interval.setValue(2.0)
        grid_kiri.addWidget(self.spin_log_interval, 5, 1)

        grid_kiri.addWidget(QLabel("File CSV:"), 6, 0)
        layout_csv = QHBoxLayout()
        self.txt_csv_path = QLineEdit("modbus_log_terbaru.csv")
        layout_csv.addWidget(self.txt_csv_path)
        btn_browse = QPushButton("...")
        btn_browse.setMaximumWidth(40)
        btn_browse.clicked.connect(self._pilih_file_csv)
        layout_csv.addWidget(btn_browse)
        grid_kiri.addLayout(layout_csv, 6, 1)

        self.chk_save_csv = QCheckBox("Simpan CSV")
        self.chk_save_csv.setChecked(True)
        grid_kiri.addWidget(self.chk_save_csv, 7, 0, 1, 2)

        self.btn_toggle_logger = QPushButton("▶ Mulai Perekaman Data")
        self.btn_toggle_logger.clicked.connect(self.toggle_logger)
        grid_kiri.addWidget(self.btn_toggle_logger, 8, 0, 1, 2)
        
        grid_kiri.setRowStretch(9, 1)

        box_monitor = QGroupBox("Monitor Live Data")
        tata_letak_monitor = QVBoxLayout(box_monitor)
        self.txt_logger_monitor = QTextEdit()
        self.txt_logger_monitor.setReadOnly(True)
        tata_letak_monitor.addWidget(self.txt_logger_monitor)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(box_kontrol)
        splitter.addWidget(box_monitor)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        tata_letak.addWidget(splitter)
        self.tabs.addTab(tab, "Data Logger CSV")

    def _pilih_file_csv(self):
        jalur, _ = QFileDialog.getSaveFileName(self, "Simpan Log Sebagai", "modbus_log.csv", "CSV Files (*.csv)")
        if jalur: self.txt_csv_path.setText(jalur)

    def toggle_logger(self):
        if self.thread_logger and self.thread_logger.isRunning():
            self.thread_logger.apakah_berjalan = False
            self.btn_toggle_logger.setText("▶ Mulai Perekaman Data")
            self.manajemen_interlock_tombol(None, status_reset=True)
            self._set_status("Logging dihentikan.")
            return

        if not self.client_global or not self.client_global.connected:
            self._set_status("Error: Koneksi utama belum aktif!")
            return

        self.manajemen_interlock_tombol("log")
        params = {
            'slave_id': self.spin_log_slave.value(),
            'tipe_reg': self.combo_log_type.currentText(),
            'reg_awal': self.spin_log_addr.value(),
            'jumlah': self.spin_log_count.value(),
            'encoding': self.combo_log_encoding.currentText(),
            'interval': self.spin_log_interval.value()
        }

        if self.chk_save_csv.isChecked():
            jalur_csv = self.txt_csv_path.text()
            try:
                file_baru = not os.path.exists(jalur_csv) or os.path.getsize(jalur_csv) == 0
                if file_baru:
                    with open(jalur_csv, 'w', newline='') as f:
                        jumlah_final = self.spin_log_count.value()
                        reg_awal = self.spin_log_addr.value()
                        header = ["Timestamp"] + [f"Reg_{reg_awal + i}" for i in range(jumlah_final)]
                        csv.writer(f).writerow(header)
            except Exception as e:
                self.txt_logger_monitor.append(f"Gagal tulis header CSV: {str(e)}")
                self.manajemen_interlock_tombol(None, status_reset=True)
                return

        self.txt_logger_monitor.clear()
        self.thread_logger = ModbusPoolerLoggerThread(self.client_global, params, "logger")
        self.thread_logger.sinyal_data.connect(self.proses_data_logger_thread)
        self.thread_logger.sinyal_kesalahan.connect(self.proses_kesalahan_thread)
        self.thread_logger.start()
        
        self.btn_toggle_logger.setText("■ Hentikan Perekaman")
        self._set_status("Data logger berjalan...")

    def proses_data_logger_thread(self, list_alamat, nilai_mentah, encoding, target_tab):
        if target_tab != "logger": return
        stempel = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        hasil_decoded_list = []
        is_float = "32-bit" in encoding and len(nilai_mentah) >= 2

        i = 0
        while i < len(nilai_mentah):
            if is_float and i + 1 < len(nilai_mentah):
                val_str = dekode_register_sepasang(int(nilai_mentah[i]), int(nilai_mentah[i+1]), encoding)
                hasil_decoded_list.append(val_str)
                i += 2
            else:
                if encoding == 'Signed 16-bit INT':
                    val_str = str(struct.unpack('h', struct.pack('H', int(nilai_mentah[i])))[0])
                else:
                    val_str = str(nilai_mentah[i])
                hasil_decoded_list.append(val_str)
                i += 1

        str_decoded = ", ".join(hasil_decoded_list)
        self.txt_logger_monitor.append(f"[{stempel}] Raw: {nilai_mentah} → Decoded: {str_decoded}")

        if self.chk_save_csv.isChecked():
            try:
                with open(self.txt_csv_path.text(), mode='a', newline='') as f:
                    csv.writer(f).writerow([stempel] + hasil_decoded_list)
            except Exception as e:
                self.txt_logger_monitor.append(f"<font color='red'>Gagal simpan CSV: {str(e)}</font>")

    def proses_kesalahan_thread(self, pesan_kesalahan, target_tab):
        if target_tab == "logger":
            self.txt_logger_monitor.append(f"<font color='red'>[Kegagalan] {pesan_kesalahan}</font>")

    def _tampilkan_tentang(self):
        QMessageBox.about(self, "Tentang Aplikasi", "<b>All-In-One Modbus Industrial Tool v15.1</b><br><br>"
                          "Aplikasi Master Modbus dengan Dukungan Semua Versi PyModbus")


    # ==================================================================
    # EXPORT CSV
    # ==================================================================
    def _export_tabel_ke_csv(self, tabel: QTableWidget, nama_file_default: str):
        """Export isi QTableWidget ke file CSV yang dipilih user."""
        if tabel.rowCount() == 0:
            QMessageBox.information(self, "Export CSV", "Tidak ada data untuk diekspor.")
            return

        jalur, _ = QFileDialog.getSaveFileName(
            self,
            "Simpan Data sebagai CSV",
            f"{nama_file_default}.csv",
            "CSV Files (*.csv)"
        )
        if not jalur:
            return

        try:
            with open(jalur, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)

                # Tulis header dari kolom tabel
                headers = []
                for col in range(tabel.columnCount()):
                    item = tabel.horizontalHeaderItem(col)
                    headers.append(item.text() if item else f"Kolom {col + 1}")
                writer.writerow(headers)

                # Tulis setiap baris data
                for row in range(tabel.rowCount()):
                    baris = []
                    for col in range(tabel.columnCount()):
                        item = tabel.item(row, col)
                        baris.append(item.text() if item else "")
                    writer.writerow(baris)

            self._set_status(f"Export berhasil → {jalur}")
            QMessageBox.information(self, "Export CSV", f"Data berhasil diekspor ke:\n{jalur}")

        except Exception as e:
            QMessageBox.warning(self, "Gagal Export", f"Terjadi kesalahan saat menyimpan:\n{str(e)}")

    # ==================================================================
    # CLOSE EVENT
    # ==================================================================
    def matikan_semua_thread_aktif(self):
        for th in [self.thread_pemindai, self.thread_pooler, self.thread_logger]:
            if th and th.isRunning():
                th.apakah_berjalan = False
                th.wait(1000)

    def closeEvent(self, event):
        self.matikan_semua_thread_aktif()
        if self.client_global:
            self.client_global.close()
        event.accept()


# =====================================================================
# ENTRY POINT
# =====================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ModbusApp()
    window.show()
    sys.exit(app.exec_())
