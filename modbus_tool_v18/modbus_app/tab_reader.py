"""Tab Pembaca Modbus Live (polling)."""
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


class ReaderMixin:
    """Tab Pembaca Modbus Live (polling)."""

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
        # FIX: sama seperti tab lain - rentang dibuka penuh 0-255 (default
        # QSpinBox tanpa setRange() adalah 0-99).
        self.spin_read_slave.setRange(0, 255)
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

        grid_kiri.addWidget(QLabel("Format Nilai:"), 4, 0)
        self.combo_encoding = QComboBox()
        self.combo_encoding.addItems(DAFTAR_ENCODING)
        self.combo_encoding.setToolTip("Format untuk mendekode register bertetangga (float, int32, atau double 64-bit).")
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
        self.tabel_reader_output.setHorizontalHeaderLabels(["Alamat", "Nilai INT", "Nilai Gabungan", "Keterangan"])
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

        if not self.client_global or not client_terhubung(self.client_global):
            self._set_status("Error: Koneksi utama belum aktif.")
            return

        # FIX BUG: penjaga tambahan (selain penguncian tombol di atas) agar
        # "Baca Sekali" tidak pernah menimpa thread_pooler yang masih berjalan
        # (baik dari polling maupun dari klik ganda pada baca sekali).
        if tunggal and self.thread_pooler and self.thread_pooler.isRunning():
            self._set_status("Masih ada pembacaan/polling yang berjalan, tunggu selesai dahulu.")
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

        peringatan = peringatan_jumlah_register(tipe_reg_saat_ini, params['jumlah'], params['encoding'])
        if peringatan:
            self._set_status(f"Peringatan: {peringatan}")

        self.thread_pooler = ModbusPoolerLoggerThread(
            self.client_global, params, "reader", single_shot=tunggal,
            auto_reconnect=self.chk_auto_reconnect.isChecked()
        )
        self.thread_pooler.sinyal_data.connect(lambda la, nm, enc, _: self.perbarui_tabel_reader(la, nm, enc, tipe_reg_saat_ini, target_device_id))
        self.thread_pooler.sinyal_kesalahan.connect(lambda msg, _: self._set_status(f"Pooler: {msg}"))
        self.thread_pooler.sinyal_info.connect(self.proses_info_thread)
        th = self.thread_pooler
        th.finished.connect(lambda th=th: self._thread_selesai(th))
        th.start()

    def perbarui_tabel_reader(self, list_alamat, nilai_mentah, encoding, tipe_reg, device_id=0):
        try: self.tabel_reader_output.itemChanged.disconnect(self.tangkap_perubahan_keterangan_user)
        except TypeError: pass

        jumlah_word = dapatkan_jumlah_word(encoding)
        self._konteks_reader = (device_id, tipe_reg)

        # FIX PERFORMA: sebelumnya tabel di-kosongkan (setRowCount(0)) lalu
        # dibangun ulang total dengan insertRow() pada SETIAP siklus polling
        # (bisa setiap 0.1 detik). Dengan header mode "Stretch", tiap
        # insertRow() memicu kalkulasi ulang tata letak kolom - pada
        # polling interval singkat/jumlah register besar, ini membuat UI
        # terasa lag terus-menerus selama polling berjalan, bukan cuma
        # sesekali. Sekarang baris tabel HANYA dibangun ulang kalau daftar
        # alamat/tipe register/device ID benar-benar berubah (mis. user
        # mengganti konfigurasi baca); selama konfigurasi tetap sama, siklus
        # berikutnya cukup meng-update isi sel yang sudah ada (setText),
        # jauh lebih murah daripada insertRow berulang.
        struktur_baru = (tuple(list_alamat), tipe_reg, device_id)
        perlu_rebuild = getattr(self, '_reader_struktur_terakhir', None) != struktur_baru

        if perlu_rebuild:
            self.tabel_reader_output.setUpdatesEnabled(False)
            self.tabel_reader_output.setRowCount(len(list_alamat))
            for baris in range(len(list_alamat)):
                for kolom in range(4):
                    item = QTableWidgetItem("")
                    if kolom != 3:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.tabel_reader_output.setItem(baris, kolom, item)
            self._reader_struktur_terakhir = struktur_baru

        for idx, addr in enumerate(list_alamat):
            item_addr = self.tabel_reader_output.item(idx, 0)
            item_addr.setText(f"Reg {addr}")

            if tipe_reg in ['Holding', 'Input']:
                if encoding == 'Signed 16-bit INT':
                    val_int = str(struct.unpack('h', struct.pack('H', int(nilai_mentah[idx])))[0])
                else:
                    val_int = str(nilai_mentah[idx])

                val_float = "-"
                if jumlah_word > 1 and idx % jumlah_word == 0 and (idx + jumlah_word) <= len(nilai_mentah):
                    potongan_reg = [int(nilai_mentah[j]) for j in range(idx, idx + jumlah_word)]
                    val_float = dekode_register_multi(potongan_reg, encoding)
            else:
                val_int = str(nilai_mentah[idx])
                val_float = "-"

            item_val_int = self.tabel_reader_output.item(idx, 1)
            item_val_float = self.tabel_reader_output.item(idx, 2)

            kunci_cache_int = f"{device_id}_{tipe_reg}_{addr}_int"
            if kunci_cache_int in self.nilai_sebelumnya and self.nilai_sebelumnya[kunci_cache_int] != val_int:
                item_val_int.setBackground(QColor(WARNA_HIGHLIGHT))
            else:
                item_val_int.setBackground(QColor(Qt.transparent))
            self.nilai_sebelumnya[kunci_cache_int] = val_int

            kunci_cache_float = f"{device_id}_{tipe_reg}_{addr}_flt"
            if kunci_cache_float in self.nilai_sebelumnya and self.nilai_sebelumnya[kunci_cache_float] != val_float:
                item_val_float.setBackground(QColor(WARNA_HIGHLIGHT))
            else:
                item_val_float.setBackground(QColor(Qt.transparent))
            self.nilai_sebelumnya[kunci_cache_float] = val_float

            item_val_int.setText(val_int)
            item_val_float.setText(val_float)

            if perlu_rebuild:
                ket = self.memori_keterangan_user.get(f"{device_id}_{tipe_reg}_{addr}", "")
                self.tabel_reader_output.item(idx, 3).setText(ket)

        if perlu_rebuild:
            self.tabel_reader_output.setUpdatesEnabled(True)

        self.tabel_reader_output.itemChanged.connect(self.tangkap_perubahan_keterangan_user)

    def tangkap_perubahan_keterangan_user(self, item):
        # FIX: Pindah penangkapan keterangan ke indeks kolom ke-3 (karena 1 dan 2 dihuni Int dan Float)
        if item.column() == 3: 
            baris = item.row()
            addr_str = self.tabel_reader_output.item(baris, 0).text().replace("Reg ", "")
            # Pakai konteks tabel saat ini (bukan nilai spinbox/combo yang bisa
            # sudah diubah pengguna selama polling berjalan).
            dev_id, t_reg = self._konteks_reader
            kunci = f"{dev_id}_{t_reg}_{addr_str}"
            self.memori_keterangan_user[kunci] = item.text()
