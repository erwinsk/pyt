"""Jendela utama: panel koneksi, menu, preset, interlock, dan perakitan semua tab."""
import sys
import os
import csv
import json
import time
import copy
import struct
import logging
import threading
import traceback
from datetime import datetime

import serial.tools.list_ports

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QLabel, QLineEdit, QComboBox, QPushButton, QSpinBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QTextEdit, QFileDialog, QCheckBox, QGroupBox,
    QHeaderView, QMessageBox, QProgressBar, QStatusBar, QAction, QMenuBar,
    QSplitter, QInputDialog
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QMutex, QTimer
from PyQt5.QtGui import QColor, QFont, QPalette

from .konfigurasi import *  # noqa: F401,F403
from .inti import *  # noqa: F401,F403
from .inti import _buat_client_rtu, _buat_client_tcp
from .worker import *  # noqa: F401,F403
from .tab_scan import ScanMixin
from .tab_reader import ReaderMixin
from .tab_write import WriteMixin
from .tab_logger import LoggerMixin
from .tab_tag import TagMixin


class ModbusApp(ScanMixin, ReaderMixin, WriteMixin, LoggerMixin, TagMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modbus Tools Kalingin v18.0")
        self.resize(1100, 860)

        self.client_global    = None
        self.thread_pemindai  = None
        self.thread_pooler    = None
        self.thread_logger    = None
        self.thread_tag       = None
        self.thread_tulis     = None
        self._params_logger   = None          # snapshot parameter logger saat start
        self._konteks_reader  = (1, 'Holding')  # (device_id, tipe_reg) tabel reader saat ini
        self.memori_keterangan_user = {}
        self.nilai_sebelumnya = {}
        self.daftar_tag       = []   # daftar dict tag untuk tab "Daftar Tag"
        self.mode_gelap       = False
        self._rotasi_csv_hitungan = 0
        self._tanggal_csv_aktif = None

        self.inisialisasi_ui()
        self.penyegaran_port_serial()
        self._muat_preset_terakhir()

        # Timer untuk memperbarui label statistik komunikasi secara berkala
        self.timer_statistik = QTimer(self)
        self.timer_statistik.timeout.connect(self._perbarui_label_statistik)
        self.timer_statistik.start(1000)

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
        self.buat_tab_daftar_tag()

    def _buat_menu_bar(self):
        menubar = self.menuBar()
        menu_file = menubar.addMenu("File")
        aksi_simpan = QAction("Export Preset Koneksi...", self)
        aksi_simpan.setToolTip("Simpan hanya pengaturan koneksi (port/baud/host/dll)")
        aksi_simpan.triggered.connect(self.simpan_preset_koneksi)
        aksi_muat = QAction("Import Preset Koneksi...", self)
        aksi_muat.triggered.connect(self.muat_preset_koneksi)
        menu_file.addAction(aksi_simpan)
        menu_file.addAction(aksi_muat)
        menu_file.addSeparator()

        aksi_simpan_job = QAction("Export Preset Pekerjaan (Lengkap)...", self)
        aksi_simpan_job.setToolTip("Simpan koneksi + semua pengaturan tab (scan, reader, write, logger, daftar tag)")
        aksi_simpan_job.triggered.connect(self.simpan_preset_pekerjaan)
        aksi_muat_job = QAction("Import Preset Pekerjaan (Lengkap)...", self)
        aksi_muat_job.triggered.connect(self.muat_preset_pekerjaan)
        menu_file.addAction(aksi_simpan_job)
        menu_file.addAction(aksi_muat_job)
        menu_file.addSeparator()

        aksi_keluar = QAction("Keluar", self)
        aksi_keluar.setShortcut("Ctrl+Q")
        aksi_keluar.setToolTip("Tutup aplikasi (semua koneksi/thread yang aktif akan dihentikan lebih dahulu).")
        aksi_keluar.triggered.connect(self.close)
        menu_file.addAction(aksi_keluar)

        menu_export = menubar.addMenu("Export Data")
        aksi_exp_id  = QAction("Export Hasil Scan ID ke CSV", self)
        aksi_exp_id.triggered.connect(lambda: self._export_tabel_ke_csv(self.tabel_hasil_id, "scan_id"))
        aksi_exp_reg = QAction("Export Hasil Scan Register ke CSV", self)
        aksi_exp_reg.triggered.connect(lambda: self._export_tabel_ke_csv(self.tabel_hasil_register, "scan_register"))
        menu_export.addAction(aksi_exp_id)
        menu_export.addAction(aksi_exp_reg)

        menu_tampilan = menubar.addMenu("Tampilan")
        self.aksi_mode_gelap = QAction("Mode Gelap", self, checkable=True)
        self.aksi_mode_gelap.toggled.connect(self.toggle_mode_gelap)
        menu_tampilan.addAction(self.aksi_mode_gelap)

        menu_bantuan = menubar.addMenu("Bantuan")
        aksi_tentang = QAction("Tentang Aplikasi", self)
        aksi_tentang.triggered.connect(self._tampilkan_tentang)
        menu_bantuan.addAction(aksi_tentang)
        aksi_buka_log = QAction("Buka Folder Log/Config...", self)
        aksi_buka_log.triggered.connect(self._buka_folder_config)
        menu_bantuan.addAction(aksi_buka_log)

    def toggle_mode_gelap(self, aktif):
        self.mode_gelap = aktif
        app = QApplication.instance()
        if aktif:
            palet = QPalette()
            palet.setColor(QPalette.Window, QColor(45, 45, 48))
            palet.setColor(QPalette.WindowText, Qt.white)
            palet.setColor(QPalette.Base, QColor(30, 30, 30))
            palet.setColor(QPalette.AlternateBase, QColor(45, 45, 48))
            palet.setColor(QPalette.ToolTipBase, Qt.white)
            palet.setColor(QPalette.ToolTipText, Qt.white)
            palet.setColor(QPalette.Text, Qt.white)
            palet.setColor(QPalette.Button, QColor(45, 45, 48))
            palet.setColor(QPalette.ButtonText, Qt.white)
            palet.setColor(QPalette.Highlight, QColor(38, 79, 120))
            palet.setColor(QPalette.HighlightedText, Qt.white)
            app.setPalette(palet)
        else:
            app.setPalette(QApplication.style().standardPalette())

    def _buka_folder_config(self):
        try:
            import subprocess
            if sys.platform.startswith('win'):
                os.startfile(DIR_CONFIG)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', DIR_CONFIG])
            else:
                subprocess.Popen(['xdg-open', DIR_CONFIG])
        except Exception as e:
            QMessageBox.information(self, "Folder Config", f"Lokasi folder:\n{DIR_CONFIG}\n\n(Gagal membuka otomatis: {e})")

    def _perbarui_label_statistik(self):
        if hasattr(self, 'lbl_statistik'):
            self.lbl_statistik.setText(statistik_global.ringkasan())

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
        self.spin_timeout.setToolTip("Batas waktu menunggu balasan perangkat sebelum dianggap gagal.")
        vbox_timeout.addWidget(self.spin_timeout)
        vbox_timeout.addStretch()
        layout_utama.addWidget(grp_timeout)

        grp_retry = QGroupBox("Retry")
        vbox_retry = QVBoxLayout(grp_retry)
        vbox_retry.setContentsMargins(4, 10, 4, 4)
        self.spin_retries = QSpinBox()
        self.spin_retries.setRange(0, 10)
        self.spin_retries.setValue(3)
        self.spin_retries.setToolTip("Jumlah percobaan ulang otomatis oleh pymodbus jika 1 permintaan gagal (berguna untuk bus RS-485 yang noisy).")
        vbox_retry.addWidget(self.spin_retries)
        vbox_retry.addStretch()
        layout_utama.addWidget(grp_retry)

        grp_reconnect = QGroupBox("Auto-Reconnect")
        vbox_reconnect = QVBoxLayout(grp_reconnect)
        vbox_reconnect.setContentsMargins(4, 10, 4, 4)
        self.chk_auto_reconnect = QCheckBox("Aktif")
        self.chk_auto_reconnect.setChecked(True)
        self.chk_auto_reconnect.setToolTip("Jika koneksi terputus saat polling/logging berjalan, coba sambung ulang otomatis (backoff bertahap).")
        vbox_reconnect.addWidget(self.chk_auto_reconnect)
        vbox_reconnect.addStretch()
        layout_utama.addWidget(grp_reconnect)

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

        # Statistik kesehatan komunikasi (sukses/gagal/timeout), berguna
        # untuk diagnosa kualitas bus RS-485/TCP tanpa perlu buka log file.
        self.lbl_statistik = QLabel(statistik_global.ringkasan())
        self.lbl_statistik.setToolTip("Statistik kumulatif permintaan Modbus sejak aplikasi dibuka. Klik untuk reset.")
        self.lbl_statistik.mousePressEvent = lambda ev: self._reset_statistik()
        self.status_bar.addPermanentWidget(self.lbl_statistik)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumWidth(200)
        self.status_bar.addPermanentWidget(self.progress_bar)

    def _reset_statistik(self):
        statistik_global.reset()
        self._perbarui_label_statistik()

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
            'timeout':  self.spin_timeout.value(),
            'retries':  self.spin_retries.value(),
            'auto_reconnect': self.chk_auto_reconnect.isChecked(),
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
        self.spin_retries.setEnabled(not disabled)
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
                    bytesize=int(config['bytesize']), timeout=float(config['timeout']),
                    retries=int(config['retries'])
                )
            else:
                self.client_global = _buat_client_tcp(
                    host=config['host'], port=int(config['tcp_port']), timeout=float(config['timeout']),
                    retries=int(config['retries'])
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

    def _set_indikator(self, teks, warna):
        self.lbl_indikator.setText(teks)
        self.lbl_indikator.setStyleSheet(f"color: {warna}; font-weight: bold; font-size: 13px;")

    def _perbarui_indikator_koneksi(self):
        """Sinkronkan label indikator dengan keadaan client yang sebenarnya."""
        if self.client_global is None:
            self._set_indikator("● OFFLINE", WARNA_GAGAL)
        elif client_terhubung(self.client_global):
            self._set_indikator("● ONLINE", WARNA_SUKSES)
        else:
            self._set_indikator("● TERPUTUS", WARNA_GAGAL)

    def _selesai_koneksi_rtu(self):
        self._perbarui_indikator_koneksi()
        self._set_status("Koneksi berhasil dibuka.")

    def tutup_koneksi_modbus(self):
        self.matikan_semua_thread_aktif()
        if self.client_global:
            self.client_global.close()
        self.client_global = None
        self.btn_hubungkan.setEnabled(True)
        self.btn_putuskan.setEnabled(False)
        self.box_pengunci_koneksi(False)
        self._reset_teks_tombol_operasi()
        self._segarkan_interlock()
        self._perbarui_indikator_koneksi()
        self._set_status("Koneksi diputus.")

    def simpan_preset_koneksi(self):
        config = self.dapatkan_konfigurasi_koneksi()
        jalur, _ = QFileDialog.getSaveFileName(self, "Export Preset Pengaturan", "modbus_presets.json", "JSON Files (*.json)")
        if not jalur: return
        try:
            tulis_json_atomik(jalur, config, indent=4)
            QMessageBox.information(self, "Berhasil", "Preset pengaturan berhasil diekspor.")
            tulis_json_atomik(FILE_PRESET, config)
        except Exception as e:
            catat_kesalahan("Simpan preset koneksi", e)
            QMessageBox.warning(self, "Error", f"Gagal mengekspor: {str(e)}")

    def muat_preset_koneksi(self):
        jalur, _ = QFileDialog.getOpenFileName(self, "Import Preset Pengaturan", "", "JSON Files (*.json)")
        if not jalur: return
        try:
            self._terapkan_preset_dari_file(jalur)
            QMessageBox.information(self, "Berhasil", "Preset pengaturan berhasil dimuat.")
        except Exception as e:
            catat_kesalahan("Muat preset koneksi", e)
            QMessageBox.warning(self, "Error", f"Gagal memuat preset: {str(e)}")

    def _muat_preset_terakhir(self):
        """Muat pengaturan sesi sebelumnya: preset pekerjaan lengkap (hasil
        simpan otomatis saat keluar) bila ada, jika tidak preset koneksi."""
        try:
            if os.path.exists(FILE_JOB_PRESET):
                with open(FILE_JOB_PRESET, 'r', encoding='utf-8') as f:
                    self._terapkan_preset_pekerjaan(json.load(f))
            else:
                self._terapkan_preset_dari_file(FILE_PRESET)
        except Exception as e:
            # Error di sini dicatat ke log aplikasi (bukan ditelan diam-diam)
            # agar jelas kenapa pengaturan terakhir tidak termuat.
            catat_kesalahan("Muat preset terakhir", e)

    def _simpan_otomatis(self):
        """Simpan pengaturan saat aplikasi ditutup supaya sesi berikutnya
        langsung memakai pengaturan terakhir (tidak perlu export manual)."""
        try:
            data = self._kumpulkan_preset_pekerjaan()
            tulis_json_atomik(FILE_JOB_PRESET, data)
            tulis_json_atomik(FILE_PRESET, data['koneksi'])
        except Exception as e:
            catat_kesalahan("Simpan otomatis pengaturan", e)

    def _terapkan_preset_dari_file(self, jalur):
        if not os.path.exists(jalur): return
        with open(jalur, 'r', encoding='utf-8') as f:
            config = json.load(f)
        self._terapkan_konfigurasi_koneksi(config)

    def _terapkan_konfigurasi_koneksi(self, config):
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
        self.spin_retries.setValue(int(config.get('retries', 3)))
        self.chk_auto_reconnect.setChecked(bool(config.get('auto_reconnect', True)))

        # Pilih ulang port serial tersimpan jika masih terdeteksi di combo_port.
        port_tersimpan = config.get('port', '')
        if port_tersimpan:
            idx_port = self.combo_port.findText(port_tersimpan)
            if idx_port >= 0:
                self.combo_port.setCurrentIndex(idx_port)

    # ==================================================================
    # PRESET PEKERJAAN (LENGKAP) - koneksi + semua pengaturan tab
    # ==================================================================
    def _kumpulkan_preset_pekerjaan(self):
        return {
            'koneksi': self.dapatkan_konfigurasi_koneksi(),
            'scan_id': {
                'id_awal': self.spin_start_id.value(),
                'id_akhir': self.spin_end_id.value(),
                'tipe_reg': self.combo_id_scan_reg_type.currentText(),
                'reg_uji': self.spin_test_reg.value(),
            },
            'scan_register': {
                'slave_id': self.spin_reg_scan_slave.value(),
                'tipe_reg': self.combo_reg_scan_type.currentText(),
                'reg_awal': self.spin_reg_scan_start.value(),
                'reg_akhir': self.spin_reg_scan_end.value(),
                'encoding': self.combo_reg_scan_enc.currentText(),
            },
            'reader': {
                'slave_id': self.spin_read_slave.value(),
                'tipe_reg': self.combo_read_type.currentText(),
                'reg_awal': self.spin_read_addr.value(),
                'jumlah': self.spin_read_count.value(),
                'encoding': self.combo_encoding.currentText(),
                'interval': self.spin_pool_interval.value(),
            },
            'write': {
                'slave_id': self.spin_write_slave.value(),
                'tipe_fungsi': self.combo_write_type.currentText(),
                'alamat': self.spin_write_addr.value(),
                'encoding': self.combo_write_encoding.currentText(),
            },
            'logger': {
                'slave_id': self.spin_log_slave.value(),
                'tipe_reg': self.combo_log_type.currentText(),
                'reg_awal': self.spin_log_addr.value(),
                'jumlah': self.spin_log_count.value(),
                'encoding': self.combo_log_encoding.currentText(),
                'interval': self.spin_log_interval.value(),
                'csv_path': self.txt_csv_path.text(),
                'simpan_csv': self.chk_save_csv.isChecked(),
                'rotasi_mb': self.spin_rotasi_mb.value(),
                'rotasi_harian': self.chk_rotasi_harian.isChecked(),
            },
            'daftar_tag': self.daftar_tag,
            'tampilan': {'mode_gelap': self.mode_gelap},
        }

    def _terapkan_preset_pekerjaan(self, data):
        koneksi = data.get('koneksi')
        if koneksi:
            self._terapkan_konfigurasi_koneksi(koneksi)

        si = data.get('scan_id', {})
        self.spin_start_id.setValue(int(si.get('id_awal', self.spin_start_id.value())))
        self.spin_end_id.setValue(int(si.get('id_akhir', self.spin_end_id.value())))
        if 'tipe_reg' in si: self.combo_id_scan_reg_type.setCurrentText(si['tipe_reg'])
        self.spin_test_reg.setValue(int(si.get('reg_uji', self.spin_test_reg.value())))

        sr = data.get('scan_register', {})
        self.spin_reg_scan_slave.setValue(int(sr.get('slave_id', self.spin_reg_scan_slave.value())))
        if 'tipe_reg' in sr: self.combo_reg_scan_type.setCurrentText(sr['tipe_reg'])
        self.spin_reg_scan_start.setValue(int(sr.get('reg_awal', self.spin_reg_scan_start.value())))
        self.spin_reg_scan_end.setValue(int(sr.get('reg_akhir', self.spin_reg_scan_end.value())))
        if 'encoding' in sr: self.combo_reg_scan_enc.setCurrentText(sr['encoding'])

        rd = data.get('reader', {})
        self.spin_read_slave.setValue(int(rd.get('slave_id', self.spin_read_slave.value())))
        if 'tipe_reg' in rd: self.combo_read_type.setCurrentText(rd['tipe_reg'])
        self.spin_read_addr.setValue(int(rd.get('reg_awal', self.spin_read_addr.value())))
        self.spin_read_count.setValue(int(rd.get('jumlah', self.spin_read_count.value())))
        if 'encoding' in rd: self.combo_encoding.setCurrentText(rd['encoding'])
        self.spin_pool_interval.setValue(float(rd.get('interval', self.spin_pool_interval.value())))

        wr = data.get('write', {})
        self.spin_write_slave.setValue(int(wr.get('slave_id', self.spin_write_slave.value())))
        if 'tipe_fungsi' in wr: self.combo_write_type.setCurrentText(wr['tipe_fungsi'])
        self.spin_write_addr.setValue(int(wr.get('alamat', self.spin_write_addr.value())))
        if 'encoding' in wr: self.combo_write_encoding.setCurrentText(wr['encoding'])

        lg = data.get('logger', {})
        self.spin_log_slave.setValue(int(lg.get('slave_id', self.spin_log_slave.value())))
        if 'tipe_reg' in lg: self.combo_log_type.setCurrentText(lg['tipe_reg'])
        self.spin_log_addr.setValue(int(lg.get('reg_awal', self.spin_log_addr.value())))
        self.spin_log_count.setValue(int(lg.get('jumlah', self.spin_log_count.value())))
        if 'encoding' in lg: self.combo_log_encoding.setCurrentText(lg['encoding'])
        self.spin_log_interval.setValue(float(lg.get('interval', self.spin_log_interval.value())))
        if 'csv_path' in lg: self.txt_csv_path.setText(lg['csv_path'])
        self.chk_save_csv.setChecked(bool(lg.get('simpan_csv', self.chk_save_csv.isChecked())))
        self.spin_rotasi_mb.setValue(float(lg.get('rotasi_mb', self.spin_rotasi_mb.value())))
        self.chk_rotasi_harian.setChecked(bool(lg.get('rotasi_harian', self.chk_rotasi_harian.isChecked())))

        self.daftar_tag = data.get('daftar_tag', [])
        self._render_ulang_tabel_tag()

        tampilan = data.get('tampilan', {})
        if 'mode_gelap' in tampilan:
            self.aksi_mode_gelap.setChecked(bool(tampilan['mode_gelap']))

    def simpan_preset_pekerjaan(self):
        jalur, _ = QFileDialog.getSaveFileName(self, "Export Preset Pekerjaan", "modbus_job_preset.json", "JSON Files (*.json)")
        if not jalur: return
        try:
            data = self._kumpulkan_preset_pekerjaan()
            tulis_json_atomik(jalur, data, indent=4)
            tulis_json_atomik(FILE_JOB_PRESET, data)
            QMessageBox.information(self, "Berhasil", "Preset pekerjaan lengkap berhasil diekspor.")
        except Exception as e:
            catat_kesalahan("Simpan preset pekerjaan", e)
            QMessageBox.warning(self, "Error", f"Gagal mengekspor preset pekerjaan: {str(e)}")

    def muat_preset_pekerjaan(self):
        if self._operasi_aktif():
            QMessageBox.information(self, "Operasi Berjalan",
                                    "Hentikan scan/polling/logging yang sedang berjalan sebelum memuat preset.")
            return
        jalur, _ = QFileDialog.getOpenFileName(self, "Import Preset Pekerjaan", "", "JSON Files (*.json)")
        if not jalur: return
        try:
            with open(jalur, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._terapkan_preset_pekerjaan(data)
            QMessageBox.information(self, "Berhasil", "Preset pekerjaan lengkap berhasil dimuat.")
        except Exception as e:
            catat_kesalahan("Muat preset pekerjaan", e)
            QMessageBox.warning(self, "Error", f"Gagal memuat preset pekerjaan: {str(e)}")

    def _operasi_aktif(self, abaikan=None):
        """Nama operasi jangka-panjang yang sedang berjalan (atau None).
        'abaikan' dipakai oleh handler `finished` supaya thread yang baru saja
        berakhir tidak terhitung walau isRunning() belum sempat False."""
        def hidup(th):
            return th is not None and th is not abaikan and th.isRunning()

        th = self.thread_pemindai
        if hidup(th):
            return "scan_id" if th.jenis_scan == "id" else "scan_reg"
        if hidup(self.thread_pooler) and not self.thread_pooler.single_shot:
            return "pool"
        if hidup(self.thread_logger):
            return "log"
        if hidup(self.thread_tag) and not self.thread_tag.single_shot:
            return "tag"
        if hidup(self.thread_tulis):
            return "write"
        return None

    def _segarkan_interlock(self, abaikan=None):
        self.manajemen_interlock_tombol(None, status_reset=True, abaikan=abaikan)

    def manajemen_interlock_tombol(self, tab_aktif, status_reset=False, abaikan=None):
        # Saat diminta "reset" (aktifkan semua tombol), tetap hormati operasi
        # lain yang masih berjalan: tombol operasi lain tidak boleh aktif
        # selama polling/logging/scan sedang memakai bus.
        if status_reset:
            operasi = self._operasi_aktif(abaikan)
            if operasi:
                tab_aktif, status_reset = operasi, False
        kondisi = status_reset
        if tab_aktif != "scan_id": self.btn_start_id_scan.setEnabled(kondisi)
        if tab_aktif != "scan_reg": self.btn_start_reg_scan.setEnabled(kondisi)
        if tab_aktif != "pool":
            self.btn_toggle_pool.setEnabled(kondisi)
        # "Baca Sekali" memakai objek thread yang SAMA (self.thread_pooler)
        # dengan polling otomatis, jadi selalu ikut dikunci setiap ada
        # operasi lain (termasuk polling) yang sedang berjalan.
        self.btn_single_read.setEnabled(kondisi)
        if tab_aktif != "log": self.btn_toggle_logger.setEnabled(kondisi)
        if tab_aktif != "write": self.btn_execute_write.setEnabled(kondisi)
        if hasattr(self, 'btn_tag_baca_semua') and tab_aktif != "tag":
            self.btn_tag_baca_semua.setEnabled(kondisi)
        if hasattr(self, 'btn_tag_toggle_polling') and tab_aktif != "tag":
            self.btn_tag_toggle_polling.setEnabled(kondisi)

    def _reset_teks_tombol_operasi(self):
        self.btn_toggle_pool.setText("▶ Mulai Polling Otomatis")
        self.btn_toggle_logger.setText("▶ Mulai Perekaman Data")
        self.btn_tag_toggle_polling.setText("▶ Mulai Polling Semua Tag")

    def _kunci_konfigurasi_logger(self, kunci):
        """Selama logging berjalan, pengaturan logger dikunci supaya header
        CSV, decode, dan file tujuan tetap konsisten dengan yang dipakai saat start."""
        for w in (self.spin_log_slave, self.combo_log_type, self.spin_log_addr, self.spin_log_count,
                  self.combo_log_encoding, self.spin_log_interval, self.txt_csv_path,
                  self.chk_save_csv, self.spin_rotasi_mb, self.chk_rotasi_harian):
            w.setEnabled(not kunci)

    def _thread_selesai(self, th):
        """Dipanggil saat sebuah thread worker benar-benar berakhir -- baik
        dihentikan pengguna, selesai (baca sekali), maupun berhenti sendiri
        karena error/koneksi putus. Memastikan tombol, teks, dan indikator
        tidak tertinggal dalam keadaan 'sedang berjalan'."""
        if th is self.thread_pooler and not th.single_shot:
            self.btn_toggle_pool.setText("▶ Mulai Polling Otomatis")
        elif th is self.thread_logger:
            self.btn_toggle_logger.setText("▶ Mulai Perekaman Data")
            self._kunci_konfigurasi_logger(False)
        elif th is self.thread_tag:
            if not th.single_shot:
                self.btn_tag_toggle_polling.setText("▶ Mulai Polling Semua Tag")
            self._atur_edit_tag_aktif(True)
        self._segarkan_interlock(abaikan=th)
        self._perbarui_indikator_koneksi()

    def _log_dibatasi(self, text_edit: QTextEdit, baris_html: str, batas_baris: int = 500):
        """Tambahkan baris ke QTextEdit monitor dengan batas jumlah baris.
        FIX PERFORMA: sebelumnya semua log (logger, write, tag) memakai
        append() polos tanpa batas. Pada sesi logging/polling yang berjalan
        lama (berjam-jam), dokumen QTextEdit terus membesar tanpa henti -
        setiap append() ke dokumen yang sudah besar menjadi semakin lambat
        (Qt harus mengelola undo-stack & layout dari seluruh dokumen), dan
        memori RAM ikut naik terus. Sekarang baris terlama otomatis dibuang
        setelah jumlah baris melewati batas, sehingga biaya append() tetap
        konstan berapa lama pun aplikasi berjalan."""
        text_edit.append(baris_html)
        dokumen = text_edit.document()
        if dokumen.blockCount() > batas_baris:
            kursor = text_edit.textCursor()
            kursor.movePosition(kursor.Start)
            kelebihan = dokumen.blockCount() - batas_baris
            for _ in range(kelebihan):
                kursor.select(kursor.BlockUnderCursor)
                kursor.removeSelectedText()
                kursor.deleteChar()  # buang newline sisa blok yang dihapus

    def _tampilkan_tentang(self):
        QMessageBox.about(
            self, "Tentang Aplikasi",
            "<b>All-In-One Modbus Industrial Tool v18.0</b><br><br>"
            "Aplikasi Master Modbus dengan Dukungan Semua Versi PyModbus (2.x &amp; 3.x)<br><br>"
            "Fitur pada versi ini:<br>"
            "• Kompatibel pymodbus 2.x maupun 3.x (client_terhubung)<br>"
            "• Unit/Slave ID mendukung penuh 0-255 di semua tab<br>"
            "• Auto-reconnect dengan backoff saat koneksi terputus<br>"
            "• Konfirmasi &amp; verifikasi baca-ulang sebelum/sesudah menulis<br>"
            "• Filter pencarian (debounced) pada tabel hasil scan<br>"
            "• Tipe data 32-bit INT &amp; 64-bit DOUBLE, Mask Write Register (FC 22)<br>"
            "• Statistik kesehatan komunikasi (sukses/gagal/timeout)<br>"
            "• Preset pekerjaan lengkap, rotasi file CSV, mode gelap<br>"
            "• Tab Daftar Tag untuk multi-read alamat non-kontinu dengan skala/offset<br>"
            "• Tabel &amp; log dioptimasi (update-in-place, batch render, log dibatasi)<br>"
            "• Penulisan di thread terpisah, pembacaan tag per blok, simpan otomatis pengaturan<br>"
            "• Daftar Tag: edit, urutkan, impor/ekspor CSV<br><br>"
            f"Folder konfigurasi &amp; log: {DIR_CONFIG}"
        )

    # ==================================================================
    # EXPORT CSV
    # ==================================================================
    def _bungkus_tabel_dengan_filter(self, tabel: QTableWidget, placeholder="Ketik untuk memfilter baris..."):
        """Bungkus sebuah QTableWidget dengan kotak pencarian di atasnya.
        Memudahkan menelusuri hasil scan yang jumlah barisnya banyak
        (mis. scan 255 Device ID atau ribuan alamat register)."""
        wadah = QWidget()
        layout = QVBoxLayout(wadah)
        layout.setContentsMargins(0, 0, 0, 0)
        kotak_filter = QLineEdit()
        kotak_filter.setPlaceholderText(placeholder)

        # FIX PERFORMA: sebelumnya filter dijalankan langsung di setiap
        # textChanged (tiap ketikan 1 huruf), padahal filter memeriksa
        # SEMUA baris x SEMUA kolom tabel. Untuk tabel besar (mis. hasil
        # scan register 0-65535), ini membuat UI terasa tersendat/lag
        # setiap kali mengetik di kotak pencarian. Sekarang pencarian
        # di-debounce: baru dijalankan 250ms setelah pengguna berhenti
        # mengetik, sehingga tabel besar tetap terasa responsif saat diketik.
        timer_debounce = QTimer(wadah)
        timer_debounce.setSingleShot(True)
        timer_debounce.setInterval(250)
        timer_debounce.timeout.connect(lambda: self._filter_baris_tabel(tabel, kotak_filter.text()))
        kotak_filter.textChanged.connect(lambda _teks: timer_debounce.start())

        layout.addWidget(kotak_filter)
        layout.addWidget(tabel)
        return wadah

    def _filter_baris_tabel(self, tabel: QTableWidget, teks: str):
        teks = teks.strip().lower()
        tabel.setUpdatesEnabled(False)
        try:
            for baris in range(tabel.rowCount()):
                if not teks:
                    tabel.setRowHidden(baris, False)
                    continue
                cocok = False
                for kolom in range(tabel.columnCount()):
                    item = tabel.item(baris, kolom)
                    if item and teks in item.text().lower():
                        cocok = True
                        break
                tabel.setRowHidden(baris, not cocok)
        finally:
            tabel.setUpdatesEnabled(True)

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

    def matikan_semua_thread_aktif(self):
        # FIX: batas tunggu sebelumnya tetap 1000ms walau timeout komunikasi
        # yang dikonfigurasi user bisa sampai 30 detik. Kalau sebuah thread
        # sedang menunggu balasan Modbus (blocking read) lebih dari 1 detik,
        # thread itu belum sempat berhenti saat closeEvent tetap melanjutkan
        # menutup koneksi -> thread latar masih memakai client yang sudah
        # ditutup dan berisiko exception/crash saat aplikasi keluar.
        # Sekarang batas tunggu disesuaikan dengan timeout komunikasi yang aktif.
        #
        # FIX Stabilitas: sebelumnya tiap thread di-stop lalu langsung
        # di-wait() satu-per-satu secara berurutan, sehingga total waktu
        # tunggu saat menutup aplikasi bisa mencapai N x batas_tunggu_ms jika
        # beberapa thread aktif bersamaan. Sekarang sinyal berhenti dikirim
        # ke SEMUA thread terlebih dahulu, baru menunggu satu-per-satu -
        # secara praktis semua thread berhenti kurang lebih bersamaan.
        #
        # FIX: satu request yang gagal bisa memakan timeout x (retries + 1),
        # bukan hanya satu timeout. Batas tunggu harus mencakup itu, kalau
        # tidak client bisa ditutup saat thread masih mengirim request.
        batas_tunggu_ms = int(self.spin_timeout.value() * 1000 * (self.spin_retries.value() + 1)) + 500
        daftar_thread = [self.thread_pemindai, self.thread_pooler, self.thread_logger,
                         self.thread_tag, self.thread_tulis]
        for th in daftar_thread:
            if th and th.isRunning() and hasattr(th, 'apakah_berjalan'):
                th.apakah_berjalan = False
        for th in daftar_thread:
            if th and th.isRunning():
                th.wait(batas_tunggu_ms)

    def closeEvent(self, event):
        self._simpan_otomatis()
        self.matikan_semua_thread_aktif()
        if self.client_global:
            self.client_global.close()
        event.accept()



def jalankan():
    """Titik masuk aplikasi GUI."""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ModbusApp()
    window.show()
    return app.exec_()
