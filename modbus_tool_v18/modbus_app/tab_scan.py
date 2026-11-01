"""Tab Pemindai Device ID dan Pemindai Peta Register."""
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
from .worker import *  # noqa: F401,F403


class ScanMixin:
    """Tab Pemindai Device ID dan Pemindai Peta Register."""

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
        self.spin_start_id.setRange(1, 255)
        self.spin_start_id.setValue(1)
        grid_kiri.addWidget(self.spin_start_id, 0, 1)

        grid_kiri.addWidget(QLabel("ID Akhir:"), 1, 0)
        self.spin_end_id = QSpinBox()
        self.spin_end_id.setRange(1, 255)
        self.spin_end_id.setValue(10)
        grid_kiri.addWidget(self.spin_end_id, 1, 1)

        grid_kiri.addWidget(QLabel("Tipe Reg Uji:"), 2, 0)
        self.combo_id_scan_reg_type = QComboBox()
        self.combo_id_scan_reg_type.addItems(["Holding", "Input", "Coil", "Discrete Input"])
        grid_kiri.addWidget(self.combo_id_scan_reg_type, 2, 1)

        grid_kiri.addWidget(QLabel("Alamat Reg Uji:"), 3, 0)
        self.spin_test_reg = QSpinBox()
        self.spin_test_reg.setRange(0, 65535)
        self.spin_test_reg.setToolTip("Alamat register yang dicoba dibaca dari tiap Device ID untuk menguji apakah ada perangkat yang merespon.")
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

        panel_kanan = self._bungkus_tabel_dengan_filter(self.tabel_hasil_id, "Cari Device ID...")

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(box_kontrol)
        splitter.addWidget(panel_kanan)
        splitter.setStretchFactor(0, 0) 
        splitter.setStretchFactor(1, 1)
        tata_letak.addWidget(splitter)
        self.tabs.addTab(tab, "Pemindai Device ID")

    def eksekusi_scan_id(self):
        if not self.client_global or not client_terhubung(self.client_global):
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
        # FIX PERFORMA: sebelumnya baris ditambahkan satu-per-satu dengan
        # insertRow() di dalam loop. Dengan mode resize kolom "Stretch",
        # setiap insertRow() memicu kalkulasi ulang tata letak tabel -
        # untuk hasil scan yang banyak (mis. scan 1-255 semuanya merespon),
        # ini membuat UI membeku sesaat saat hasil scan ditampilkan.
        # Sekarang: updates dimatikan sementara + jumlah baris dialokasikan
        # sekaligus di awal (setRowCount), sehingga hanya 1 kali kalkulasi
        # tata letak di akhir, bukan N kali.
        self.tabel_hasil_id.setUpdatesEnabled(False)
        try:
            self.tabel_hasil_id.setRowCount(len(hasil))
            for baris, (slave_id, status) in enumerate(hasil):
                item_id = QTableWidgetItem(str(slave_id))
                item_id.setTextAlignment(Qt.AlignCenter)
                item_status = QTableWidgetItem(status)
                item_status.setTextAlignment(Qt.AlignCenter)
                item_status.setForeground(QColor(WARNA_SUKSES))
                font = QFont(); font.setBold(True); item_status.setFont(font)
                self.tabel_hasil_id.setItem(baris, 0, item_id)
                self.tabel_hasil_id.setItem(baris, 1, item_status)
        finally:
            self.tabel_hasil_id.setUpdatesEnabled(True)

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
        # FIX: sebelumnya tidak diberi setRange() sehingga QSpinBox memakai
        # rentang default 0-99, membuat Target ID tidak bisa diisi lebih
        # dari 99 walau Modbus unit ID valid sampai 255. Sekarang rentang
        # dibuka penuh 0-255.
        self.spin_reg_scan_slave.setRange(0, 255)
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

        grid_kiri.addWidget(QLabel("Format Nilai:"), 4, 0)
        self.combo_reg_scan_enc = QComboBox()
        self.combo_reg_scan_enc.addItems(DAFTAR_ENCODING)
        self.combo_reg_scan_enc.setToolTip("Format untuk mendekode 2/4 register bertetangga (float, int32, atau double 64-bit).")
        grid_kiri.addWidget(self.combo_reg_scan_enc, 4, 1)

        self.btn_start_reg_scan = QPushButton("Mulai Pemindaian")
        self.btn_start_reg_scan.clicked.connect(self.eksekusi_scan_register)
        grid_kiri.addWidget(self.btn_start_reg_scan, 5, 0, 1, 2)

        self.btn_stop_reg_scan = QPushButton("Berhenti")
        self.btn_stop_reg_scan.setEnabled(False)
        self.btn_stop_reg_scan.clicked.connect(self.hentikan_scan_reg_paksa)
        grid_kiri.addWidget(self.btn_stop_reg_scan, 6, 0, 1, 2)
        
        grid_kiri.setRowStretch(7, 1)

        # FIX: Tabel menampung Alamat, INT, dan nilai gabungan (float/int32/double) sekaligus
        self.tabel_hasil_register = QTableWidget(0, 3)
        self.tabel_hasil_register.setHorizontalHeaderLabels(["Alamat Register", "Nilai INT (16-bit)", "Nilai Gabungan (32/64-bit)"])
        self.tabel_hasil_register.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        panel_kanan_reg = self._bungkus_tabel_dengan_filter(self.tabel_hasil_register, "Cari alamat/nilai...")

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(box_kontrol)
        splitter.addWidget(panel_kanan_reg)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        tata_letak.addWidget(splitter)
        self.tabs.addTab(tab, "Pemindai Peta Register")

    def eksekusi_scan_register(self):
        if not self.client_global or not client_terhubung(self.client_global):
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
        # FIX PERFORMA: sama seperti tampilkan_hasil_scan_id - hindari
        # insertRow() satu-per-satu untuk hasil scan yang bisa berjumlah
        # ribuan baris (mis. scan ribuan alamat register).
        self.tabel_hasil_register.setUpdatesEnabled(False)
        try:
            self.tabel_hasil_register.setRowCount(len(hasil))
            for baris, (reg, val_int, val_float) in enumerate(hasil):
                self.tabel_hasil_register.setItem(baris, 0, QTableWidgetItem(str(reg)))
                self.tabel_hasil_register.setItem(baris, 1, QTableWidgetItem(val_int))
                self.tabel_hasil_register.setItem(baris, 2, QTableWidgetItem(val_float))
        finally:
            self.tabel_hasil_register.setUpdatesEnabled(True)
