"""Tab Data Logger CSV serta penanganan pesan thread logger."""
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


class LoggerMixin:
    """Tab Data Logger CSV serta penanganan pesan thread logger."""

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
        # FIX: rentang dibuka penuh 0-255.
        self.spin_log_slave.setRange(0, 255)
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

        grp_rotasi = QGroupBox("Rotasi File CSV")
        grid_rotasi = QGridLayout(grp_rotasi)
        grid_rotasi.addWidget(QLabel("Maks Ukuran (MB):"), 0, 0)
        self.spin_rotasi_mb = QDoubleSpinBox()
        self.spin_rotasi_mb.setRange(0.0, 10000.0)
        self.spin_rotasi_mb.setValue(0.0)
        self.spin_rotasi_mb.setToolTip("0 = nonaktif. Jika terisi, file CSV otomatis diganti dengan file baru saat ukurannya melebihi batas ini, supaya file logger tidak tumbuh tak terbatas.")
        grid_rotasi.addWidget(self.spin_rotasi_mb, 0, 1)
        self.chk_rotasi_harian = QCheckBox("Rotasi harian (file baru tiap ganti tanggal)")
        grid_rotasi.addWidget(self.chk_rotasi_harian, 1, 0, 1, 2)
        grid_kiri.addWidget(grp_rotasi, 8, 0, 1, 2)

        self.btn_toggle_logger = QPushButton("▶ Mulai Perekaman Data")
        self.btn_toggle_logger.clicked.connect(self.toggle_logger)
        grid_kiri.addWidget(self.btn_toggle_logger, 9, 0, 1, 2)
        
        grid_kiri.setRowStretch(10, 1)

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

    def _buat_header_csv_logger(self, reg_awal, jumlah, tipe_reg, encoding):
        """Bangun header CSV dengan pemasangan register yang identik dengan
        logika decode di proses_data_logger_thread, supaya jumlah kolom
        header selalu sinkron dengan jumlah kolom data yang benar-benar ditulis."""
        header = []
        langkah = dapatkan_jumlah_word(encoding) if tipe_reg in ('Holding', 'Input') else 1
        i = 0
        while i < jumlah:
            if langkah > 1 and i + langkah - 1 < jumlah:
                header.append(f"Reg_{reg_awal + i}-{reg_awal + i + langkah - 1}")
                i += langkah
            else:
                header.append(f"Reg_{reg_awal + i}")
                i += 1
        return header

    def _cek_rotasi_csv(self):
        """Rotasi file CSV jika ukurannya melebihi batas atau tanggal sudah
        berganti sejak file dibuat, supaya file logger tidak tumbuh tak
        terbatas saat logging dijalankan berhari-hari."""
        jalur = self.txt_csv_path.text()
        perlu_rotasi = False

        if self.chk_rotasi_harian.isChecked():
            tanggal_hari_ini = datetime.now().strftime("%Y%m%d")
            if getattr(self, '_tanggal_csv_aktif', None) != tanggal_hari_ini:
                if self._tanggal_csv_aktif is not None:
                    perlu_rotasi = True
                self._tanggal_csv_aktif = tanggal_hari_ini

        batas_mb = self.spin_rotasi_mb.value()
        if batas_mb > 0 and os.path.exists(jalur):
            ukuran_mb = os.path.getsize(jalur) / (1024 * 1024)
            if ukuran_mb >= batas_mb:
                perlu_rotasi = True

        if perlu_rotasi:
            base, ext = os.path.splitext(jalur)
            jalur_baru = f"{base}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext or '.csv'}"
            self.txt_csv_path.setText(jalur_baru)
            self._tulis_header_csv_logger(jalur_baru, self._params_logger)
            self._log_dibatasi(self.txt_logger_monitor, f"<i>Rotasi file CSV → {jalur_baru}</i>")

    def _tulis_header_csv_logger(self, jalur_csv, params=None):
        p = params or {
            'reg_awal': self.spin_log_addr.value(), 'jumlah': self.spin_log_count.value(),
            'tipe_reg': self.combo_log_type.currentText(), 'encoding': self.combo_log_encoding.currentText(),
        }
        header = ["Timestamp"] + self._buat_header_csv_logger(
            p['reg_awal'], p['jumlah'], p['tipe_reg'], p['encoding']
        )
        with open(jalur_csv, 'w', newline='') as f:
            csv.writer(f).writerow(header)

    def toggle_logger(self):
        if self.thread_logger and self.thread_logger.isRunning():
            self.thread_logger.apakah_berjalan = False
            self.btn_toggle_logger.setText("▶ Mulai Perekaman Data")
            self.manajemen_interlock_tombol(None, status_reset=True)
            self._set_status("Logging dihentikan.")
            return

        if not self.client_global or not client_terhubung(self.client_global):
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
        # Snapshot parameter yang dipakai sepanjang sesi logging ini.
        self._params_logger = dict(params)

        if self.chk_save_csv.isChecked():
            jalur_csv = self.txt_csv_path.text()
            try:
                file_baru = not os.path.exists(jalur_csv) or os.path.getsize(jalur_csv) == 0
                if file_baru:
                    # FIX BUG: header sebelumnya selalu membuat 1 kolom per
                    # register (mis. 4 register -> 4 kolom "Reg_x"), padahal
                    # kalau encoding-nya 32-bit FLOAT, proses_data_logger_thread
                    # menggabungkan tiap 2 register jadi 1 nilai float, sehingga
                    # baris data yang tersimpan hanya punya separuh kolom dari
                    # header -> data di CSV jadi bergeser/tidak sinkron dengan
                    # header. Header sekarang dibangun dengan logika pemasangan
                    # register yang SAMA PERSIS dengan proses_data_logger_thread.
                    self._tulis_header_csv_logger(jalur_csv, self._params_logger)
                self._tanggal_csv_aktif = datetime.now().strftime("%Y%m%d")
            except Exception as e:
                catat_kesalahan("Tulis header CSV logger", e)
                self._log_dibatasi(self.txt_logger_monitor, f"Gagal tulis header CSV: {str(e)}")
                self.manajemen_interlock_tombol(None, status_reset=True)
                return

        self.txt_logger_monitor.clear()
        self.thread_logger = ModbusPoolerLoggerThread(
            self.client_global, params, "logger",
            auto_reconnect=self.chk_auto_reconnect.isChecked()
        )
        self.thread_logger.sinyal_data.connect(self.proses_data_logger_thread)
        self.thread_logger.sinyal_kesalahan.connect(self.proses_kesalahan_thread)
        self.thread_logger.sinyal_info.connect(self.proses_info_thread)
        th = self.thread_logger
        th.finished.connect(lambda th=th: self._thread_selesai(th))
        self._kunci_konfigurasi_logger(True)
        peringatan = peringatan_jumlah_register(params['tipe_reg'], params['jumlah'], params['encoding'])
        if peringatan:
            self._log_dibatasi(self.txt_logger_monitor, f"<font color='orange'>[Peringatan] {peringatan}</font>")
        th.start()
        
        self.btn_toggle_logger.setText("■ Hentikan Perekaman")
        self._set_status("Data logger berjalan...")

    def proses_data_logger_thread(self, list_alamat, nilai_mentah, encoding, target_tab):
        if target_tab != "logger": return
        stempel = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        hasil_decoded_list = []
        # FIX BUG: sebelumnya hanya mengecek "32-bit" in encoding tanpa memeriksa
        # tipe register. Kalau tipe register yang dipilih Coil/Discrete Input
        # tapi dropdown encoding masih menunjuk salah satu format FLOAT (bekas
        # pilihan sebelumnya), nilai bit (0/1) akan ikut "didekode" seolah-olah
        # pasangan register 16-bit -> menghasilkan angka float yang tidak berarti.
        # Sekarang decode hanya dilakukan jika tipe register-nya Holding/Input,
        # dan jumlah word mengikuti dapatkan_jumlah_word() (mendukung 32-bit
        # FLOAT/INT maupun 64-bit DOUBLE), bukan hardcode 2.
        tipe_logger = (self._params_logger or {}).get('tipe_reg', self.combo_log_type.currentText())
        langkah = dapatkan_jumlah_word(encoding) if tipe_logger in ('Holding', 'Input') else 1

        i = 0
        while i < len(nilai_mentah):
            if langkah > 1 and i + langkah <= len(nilai_mentah):
                potongan = [int(x) for x in nilai_mentah[i:i + langkah]]
                val_str = dekode_register_multi(potongan, encoding)
                hasil_decoded_list.append(val_str)
                i += langkah
            else:
                if encoding == 'Signed 16-bit INT':
                    val_str = str(struct.unpack('h', struct.pack('H', int(nilai_mentah[i])))[0])
                else:
                    val_str = str(nilai_mentah[i])
                hasil_decoded_list.append(val_str)
                i += 1

        str_decoded = ", ".join(hasil_decoded_list)
        self._log_dibatasi(self.txt_logger_monitor, f"[{stempel}] Raw: {nilai_mentah} → Decoded: {str_decoded}")

        if self.chk_save_csv.isChecked():
            try:
                self._cek_rotasi_csv()
                with open(self.txt_csv_path.text(), mode='a', newline='') as f:
                    csv.writer(f).writerow([stempel] + hasil_decoded_list)
            except Exception as e:
                catat_kesalahan("Tulis baris CSV logger", e)
                self._log_dibatasi(self.txt_logger_monitor, f"<font color='red'>Gagal simpan CSV: {str(e)}</font>")

    def proses_kesalahan_thread(self, pesan_kesalahan, target_tab):
        if target_tab == "logger":
            self._log_dibatasi(self.txt_logger_monitor, f"<font color='red'>[Kegagalan] {pesan_kesalahan}</font>")
        elif target_tab == "tag":
            self._log_dibatasi(self.txt_tag_monitor, f"<font color='red'>[Kegagalan] {pesan_kesalahan}</font>")

    def proses_info_thread(self, pesan_info, target_tab):
        if pesan_info.startswith(AWALAN_PESAN_TERPUTUS):
            self._set_indikator("● MENYAMBUNG ULANG…", WARNA_PERINGATAN)
        elif pesan_info.startswith(AWALAN_PESAN_TERSAMBUNG):
            self._perbarui_indikator_koneksi()
        if target_tab == "logger":
            self._log_dibatasi(self.txt_logger_monitor, f"<font color='#3498db'>[Info] {pesan_info}</font>")
        elif target_tab == "reader":
            self._set_status(pesan_info)
        elif target_tab == "tag":
            self._log_dibatasi(self.txt_tag_monitor, f"<font color='#3498db'>[Info] {pesan_info}</font>")
