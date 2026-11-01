"""Tab Write Register / Coil."""
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


class WriteMixin:
    """Tab Write Register / Coil."""

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
        # FIX: rentang dibuka penuh 0-255.
        self.spin_write_slave.setRange(0, 255)
        self.spin_write_slave.setValue(1)
        grid_kiri.addWidget(self.spin_write_slave, 0, 1)

        grid_kiri.addWidget(QLabel("Fungsi Tulis:"), 1, 0)
        self.combo_write_type = QComboBox()
        self.combo_write_type.addItems(["Write Single Coil (FC 05)", "Write Single Register (FC 06)", 
                                        "Write Multiple Coils (FC 15)", "Write Multiple Registers (FC 16)",
                                        "Mask Write Register (FC 22)"])
        grid_kiri.addWidget(self.combo_write_type, 1, 1)

        grid_kiri.addWidget(QLabel("Alamat Tujuan:"), 2, 0)
        self.spin_write_addr = QSpinBox()
        self.spin_write_addr.setRange(0, 65535)
        grid_kiri.addWidget(self.spin_write_addr, 2, 1)

        grid_kiri.addWidget(QLabel("Format Data:"), 3, 0)
        self.combo_write_encoding = QComboBox()
        self.combo_write_encoding.addItems(DAFTAR_ENCODING)
        self.combo_write_encoding.setToolTip("Diabaikan untuk Coil dan Mask Write Register.")
        grid_kiri.addWidget(self.combo_write_encoding, 3, 1)

        grid_kiri.addWidget(QLabel("Nilai Input:"), 4, 0)
        self.txt_write_payload = QLineEdit("12.34")
        self.txt_write_payload.setToolTip(
            "Coil: 1/0/true/false/on/off.\n"
            "Register tunggal: satu angka.\n"
            "Multiple Registers/Coils: pisahkan dengan koma, mis. 1,2,3.\n"
            "Mask Write Register: dua angka dipisah koma 'AND_mask,OR_mask' (boleh desimal atau 0xHEX)."
        )
        grid_kiri.addWidget(self.txt_write_payload, 4, 1)

        self.chk_verify_write = QCheckBox("Baca ulang untuk verifikasi setelah menulis")
        self.chk_verify_write.setChecked(True)
        self.chk_verify_write.setToolTip("Setelah menulis, baca kembali alamat yang sama untuk memastikan nilai benar-benar tersimpan di perangkat.")
        grid_kiri.addWidget(self.chk_verify_write, 5, 0, 1, 2)

        self.chk_skip_confirm_write = QCheckBox("Lewati dialog konfirmasi sebelum menulis")
        self.chk_skip_confirm_write.setToolTip("Perintah tulis akan langsung dieksekusi ke perangkat tanpa dialog konfirmasi. Gunakan dengan hati-hati.")
        grid_kiri.addWidget(self.chk_skip_confirm_write, 6, 0, 1, 2)

        self.btn_execute_write = QPushButton("Transmisikan Data")
        self.btn_execute_write.clicked.connect(self.eksekusi_penulisan_modbus)
        grid_kiri.addWidget(self.btn_execute_write, 7, 0, 1, 2)
        
        grid_kiri.setRowStretch(8, 1)

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
        if self.thread_tulis and self.thread_tulis.isRunning():
            self._set_status("Penulisan sebelumnya masih berjalan, tunggu selesai dahulu.")
            return
        if not self.client_global or not client_terhubung(self.client_global):
            QMessageBox.critical(self, "Error", "Master Modbus belum terhubung!")
            return

        tipe_fungsi = self.combo_write_type.currentText()
        encoding = self.combo_write_encoding.currentText()
        input_user = self.txt_write_payload.text()
        waktu_skrg = datetime.now().strftime("%H:%M:%S")

        p = {
            'alamat': self.spin_write_addr.value(),
            'device_id': self.spin_write_slave.value(),
            'verifikasi': self.chk_verify_write.isChecked(),
        }

        # --- Validasi & parsing input (di thread GUI, cepat, tanpa akses bus)
        try:
            if "Single Coil" in tipe_fungsi:
                p['jenis'] = 'single_coil'
                p['nilai_bool'] = parse_nilai_bool(input_user)
            elif "Multiple Coils" in tipe_fungsi:
                elemen = [e for e in input_user.split(",") if e.strip()]
                if not elemen:
                    raise ValueError("Isi minimal satu nilai coil, dipisah koma (mis. 1,0,1).")
                p['jenis'] = 'multi_coil'
                p['daftar_bool'] = [parse_nilai_bool(e) for e in elemen]
            elif "Mask Write" in tipe_fungsi:
                bagian = [b.strip() for b in input_user.split(",")]
                if len(bagian) != 2:
                    raise ValueError("Perlu 2 nilai dipisah koma: AND_mask,OR_mask")
                and_mask, or_mask = int(bagian[0], 0), int(bagian[1], 0)
                for nama_mask, nilai in (("AND_mask", and_mask), ("OR_mask", or_mask)):
                    if not 0 <= nilai <= 0xFFFF:
                        raise ValueError(f"{nama_mask} {nilai} di luar rentang 0-65535 (0xFFFF).")
                p.update(jenis='mask', and_mask=and_mask, or_mask=or_mask)
            elif "Single Register" in tipe_fungsi:
                register_final = enkode_nilai_ke_register(input_user, encoding)
                if len(register_final) != 1:
                    raise ValueError(
                        f"FC 06 hanya menulis 1 register (16-bit), sedangkan format '{encoding}' "
                        f"membutuhkan {len(register_final)} register. Pilih 'Write Multiple Registers "
                        f"(FC 16)' atau ubah format ke 16-bit.")
                p.update(jenis='single_reg', register_final=register_final)
            else:  # Write Multiple Registers (FC 16)
                register_final = []
                for e in input_user.split(","):
                    register_final.extend(enkode_nilai_ke_register(e.strip(), encoding))
                p.update(jenis='multi_reg', register_final=register_final)
        except ValueError as e:
            self._log_dibatasi(self.txt_write_log, f"[{waktu_skrg}] <font color='red'>Error Parsing Data: {e}</font>")
            return

        # Fitur keamanan: minta konfirmasi sebelum benar-benar menulis ke
        # perangkat, karena write yang salah alamat/nilai bisa berdampak ke
        # proses/perangkat industrial yang sedang berjalan.
        if not self.chk_skip_confirm_write.isChecked():
            jawaban = QMessageBox.question(
                self, "Konfirmasi Penulisan",
                f"Anda akan menulis ke:\n\n"
                f"  Fungsi : {tipe_fungsi}\n"
                f"  Slave ID : {p['device_id']}\n"
                f"  Alamat : {p['alamat']}\n"
                f"  Nilai  : {input_user}\n\n"
                f"Lanjutkan menulis ke perangkat?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if jawaban != QMessageBox.Yes:
                self._log_dibatasi(self.txt_write_log, f"[{waktu_skrg}] Penulisan dibatalkan oleh pengguna.")
                return

        # --- Eksekusi di thread terpisah (GUI tidak membeku walau bus sibuk/timeout)
        self.manajemen_interlock_tombol("write")
        self.btn_execute_write.setEnabled(False)
        th = ModbusWriteThread(self.client_global, p)
        self.thread_tulis = th
        th.sinyal_log.connect(lambda pesan: self._log_dibatasi(self.txt_write_log, pesan))
        th.finished.connect(lambda th=th: self._thread_selesai(th))
        th.start()
