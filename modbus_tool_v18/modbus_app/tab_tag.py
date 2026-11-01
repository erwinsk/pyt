"""Tab Daftar Tag (multi-read non-kontinu, skala/offset, impor/ekspor)."""
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


class TagMixin:
    """Tab Daftar Tag (multi-read non-kontinu, skala/offset, impor/ekspor)."""

    # ==================================================================
    # TAB BARU: DAFTAR TAG (multi-read alamat non-kontinu + skala/offset)
    # ==================================================================
    def buat_tab_daftar_tag(self):
        tab = QWidget()
        tata_letak = QHBoxLayout(tab)

        box_kontrol = QGroupBox("Definisi Tag")
        box_kontrol.setMaximumWidth(320)
        grid_kiri = QGridLayout(box_kontrol)

        grid_kiri.addWidget(QLabel("Nama Tag:"), 0, 0)
        self.txt_tag_nama = QLineEdit("Tag_1")
        grid_kiri.addWidget(self.txt_tag_nama, 0, 1)

        grid_kiri.addWidget(QLabel("Slave ID:"), 1, 0)
        self.spin_tag_slave = QSpinBox()
        self.spin_tag_slave.setRange(0, 255)
        self.spin_tag_slave.setValue(1)
        grid_kiri.addWidget(self.spin_tag_slave, 1, 1)

        grid_kiri.addWidget(QLabel("Tipe Register:"), 2, 0)
        self.combo_tag_type = QComboBox()
        self.combo_tag_type.addItems(["Holding", "Input", "Coil", "Discrete Input"])
        grid_kiri.addWidget(self.combo_tag_type, 2, 1)

        grid_kiri.addWidget(QLabel("Alamat:"), 3, 0)
        self.spin_tag_addr = QSpinBox()
        self.spin_tag_addr.setRange(0, 65535)
        grid_kiri.addWidget(self.spin_tag_addr, 3, 1)

        grid_kiri.addWidget(QLabel("Format Nilai:"), 4, 0)
        self.combo_tag_encoding = QComboBox()
        self.combo_tag_encoding.addItems(DAFTAR_ENCODING)
        self.combo_tag_encoding.setToolTip("Diabaikan untuk tipe Coil/Discrete Input.")
        grid_kiri.addWidget(self.combo_tag_encoding, 4, 1)

        grid_kiri.addWidget(QLabel("Skala (×):"), 5, 0)
        self.spin_tag_skala = QDoubleSpinBox()
        self.spin_tag_skala.setRange(-1000000.0, 1000000.0)
        self.spin_tag_skala.setDecimals(4)
        self.spin_tag_skala.setValue(1.0)
        self.spin_tag_skala.setToolTip("Nilai mentah dikalikan faktor ini, mis. 0.1 untuk sensor yang mengirim suhu x10.")
        grid_kiri.addWidget(self.spin_tag_skala, 5, 1)

        grid_kiri.addWidget(QLabel("Offset (+):"), 6, 0)
        self.spin_tag_offset = QDoubleSpinBox()
        self.spin_tag_offset.setRange(-1000000.0, 1000000.0)
        self.spin_tag_offset.setDecimals(4)
        self.spin_tag_offset.setValue(0.0)
        self.spin_tag_offset.setToolTip("Ditambahkan setelah dikalikan skala: nilai_akhir = nilai_mentah × skala + offset.")
        grid_kiri.addWidget(self.spin_tag_offset, 6, 1)

        self.btn_tambah_tag = QPushButton("+ Tambah Tag")
        self.btn_tambah_tag.clicked.connect(self.tambah_tag)
        grid_kiri.addWidget(self.btn_tambah_tag, 7, 0, 1, 2)

        self.btn_ubah_tag = QPushButton("Simpan Perubahan ke Tag Terpilih")
        self.btn_ubah_tag.setToolTip("Pilih satu baris tag di tabel, ubah isian di atas, lalu klik tombol ini.")
        self.btn_ubah_tag.clicked.connect(self.perbarui_tag_terpilih)
        grid_kiri.addWidget(self.btn_ubah_tag, 8, 0, 1, 2)

        self.btn_hapus_tag = QPushButton("Hapus Tag Terpilih")
        self.btn_hapus_tag.clicked.connect(self.hapus_tag_terpilih)
        grid_kiri.addWidget(self.btn_hapus_tag, 9, 0, 1, 2)

        hbox_urut = QHBoxLayout()
        self.btn_tag_naik = QPushButton("▲ Naik")
        self.btn_tag_naik.clicked.connect(lambda: self.pindah_tag(-1))
        self.btn_tag_turun = QPushButton("▼ Turun")
        self.btn_tag_turun.clicked.connect(lambda: self.pindah_tag(+1))
        hbox_urut.addWidget(self.btn_tag_naik)
        hbox_urut.addWidget(self.btn_tag_turun)
        grid_kiri.addLayout(hbox_urut, 10, 0, 1, 2)

        hbox_csv = QHBoxLayout()
        self.btn_tag_impor = QPushButton("Impor CSV...")
        self.btn_tag_impor.clicked.connect(self.impor_tag_csv)
        self.btn_tag_ekspor = QPushButton("Ekspor CSV...")
        self.btn_tag_ekspor.clicked.connect(self.ekspor_tag_csv)
        hbox_csv.addWidget(self.btn_tag_impor)
        hbox_csv.addWidget(self.btn_tag_ekspor)
        grid_kiri.addLayout(hbox_csv, 11, 0, 1, 2)

        grid_kiri.addWidget(QLabel("Interval Polling (s):"), 12, 0)
        self.spin_tag_interval = QDoubleSpinBox()
        self.spin_tag_interval.setRange(0.2, 3600.0)
        self.spin_tag_interval.setValue(2.0)
        grid_kiri.addWidget(self.spin_tag_interval, 12, 1)

        self.btn_tag_baca_semua = QPushButton("Baca Semua Tag (Sekali)")
        self.btn_tag_baca_semua.clicked.connect(lambda: self.eksekusi_baca_tag(tunggal=True))
        grid_kiri.addWidget(self.btn_tag_baca_semua, 13, 0, 1, 2)

        self.btn_tag_toggle_polling = QPushButton("▶ Mulai Polling Semua Tag")
        self.btn_tag_toggle_polling.clicked.connect(lambda: self.eksekusi_baca_tag(tunggal=False))
        grid_kiri.addWidget(self.btn_tag_toggle_polling, 14, 0, 1, 2)

        grid_kiri.setRowStretch(15, 1)

        # Tombol yang mengubah daftar tag dikunci selama pembacaan tag berjalan
        # (thread membaca salinan daftar & tabel harus tetap sejajar dengannya).
        self._widget_edit_tag = [self.btn_tambah_tag, self.btn_ubah_tag, self.btn_hapus_tag,
                                 self.btn_tag_naik, self.btn_tag_turun, self.btn_tag_impor]

        panel_kanan = QWidget()
        layout_kanan = QVBoxLayout(panel_kanan)
        layout_kanan.setContentsMargins(0, 0, 0, 0)

        self.tabel_tag = QTableWidget(0, 9)
        self.tabel_tag.setHorizontalHeaderLabels(
            ["Nama", "Slave ID", "Tipe", "Alamat", "Encoding", "Skala", "Offset", "Nilai Mentah", "Nilai Akhir"]
        )
        # FIX PERFORMA: mode ResizeToContents menghitung ulang lebar semua
        # kolom setiap kali ISI SEL berubah - karena tabel ini diperbarui
        # tiap siklus polling (kolom Nilai Mentah/Nilai Akhir), mode ini
        # membuat UI terasa berat pada interval polling singkat/tag banyak.
        # Sekarang kolom di-pas-kan sekali di awal (lihat
        # _render_ulang_tabel_tag), lalu mode diganti ke Interactive supaya
        # pembaruan nilai berikutnya tidak memicu kalkulasi ulang lebar kolom.
        self.tabel_tag.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tabel_tag.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabel_tag.itemSelectionChanged.connect(self._muat_tag_terpilih_ke_form)
        layout_kanan.addWidget(self.tabel_tag, 2)

        box_monitor_tag = QGroupBox("Monitor / Log Tag")
        layout_monitor_tag = QVBoxLayout(box_monitor_tag)
        self.txt_tag_monitor = QTextEdit()
        self.txt_tag_monitor.setReadOnly(True)
        layout_monitor_tag.addWidget(self.txt_tag_monitor)
        layout_kanan.addWidget(box_monitor_tag, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(box_kontrol)
        splitter.addWidget(panel_kanan)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        tata_letak.addWidget(splitter)
        self.tabs.addTab(tab, "Daftar Tag (Multi-Read)")

    def _atur_edit_tag_aktif(self, aktif):
        for w in getattr(self, '_widget_edit_tag', []):
            w.setEnabled(aktif)

    def _baris_tag_terpilih(self):
        return sorted({idx.row() for idx in self.tabel_tag.selectedIndexes()})

    def _tag_dari_form(self):
        nama = self.txt_tag_nama.text().strip()
        if not nama:
            QMessageBox.warning(self, "Nama Kosong", "Nama tag tidak boleh kosong.")
            return None
        return {
            'nama': nama,
            'slave_id': self.spin_tag_slave.value(),
            'tipe_reg': self.combo_tag_type.currentText(),
            'alamat': self.spin_tag_addr.value(),
            'encoding': self.combo_tag_encoding.currentText(),
            'skala': self.spin_tag_skala.value(),
            'offset': self.spin_tag_offset.value(),
        }

    def _muat_tag_terpilih_ke_form(self):
        baris = self._baris_tag_terpilih()
        if len(baris) != 1 or baris[0] >= len(self.daftar_tag):
            return
        tag = self.daftar_tag[baris[0]]
        self.txt_tag_nama.setText(tag.get('nama', ''))
        self.spin_tag_slave.setValue(int(tag.get('slave_id', 1)))
        self.combo_tag_type.setCurrentText(tag.get('tipe_reg', 'Holding'))
        self.spin_tag_addr.setValue(int(tag.get('alamat', 0)))
        self.combo_tag_encoding.setCurrentText(tag.get('encoding', DAFTAR_ENCODING[0]))
        self.spin_tag_skala.setValue(float(tag.get('skala', 1.0)))
        self.spin_tag_offset.setValue(float(tag.get('offset', 0.0)))

    def tambah_tag(self):
        tag = self._tag_dari_form()
        if tag is None:
            return
        self.daftar_tag.append(tag)
        self._render_ulang_tabel_tag()
        self.tabel_tag.selectRow(len(self.daftar_tag) - 1)

    def perbarui_tag_terpilih(self):
        baris = self._baris_tag_terpilih()
        if len(baris) != 1 or baris[0] >= len(self.daftar_tag):
            QMessageBox.information(self, "Pilih Satu Tag", "Pilih tepat satu baris tag di tabel untuk diubah.")
            return
        tag = self._tag_dari_form()
        if tag is None:
            return
        self.daftar_tag[baris[0]] = tag
        self._render_ulang_tabel_tag()
        self.tabel_tag.selectRow(baris[0])

    def hapus_tag_terpilih(self):
        baris_terpilih = sorted(self._baris_tag_terpilih(), reverse=True)
        if not baris_terpilih:
            QMessageBox.information(self, "Tidak Ada Pilihan", "Pilih dulu satu atau lebih baris tag yang ingin dihapus.")
            return
        for baris in baris_terpilih:
            if 0 <= baris < len(self.daftar_tag):
                del self.daftar_tag[baris]
        self._render_ulang_tabel_tag()

    def pindah_tag(self, arah):
        baris = self._baris_tag_terpilih()
        if len(baris) != 1:
            QMessageBox.information(self, "Pilih Satu Tag", "Pilih tepat satu baris tag untuk dipindah.")
            return
        asal, tujuan = baris[0], baris[0] + arah
        if not (0 <= tujuan < len(self.daftar_tag)):
            return
        self.daftar_tag[asal], self.daftar_tag[tujuan] = self.daftar_tag[tujuan], self.daftar_tag[asal]
        self._render_ulang_tabel_tag()
        self.tabel_tag.selectRow(tujuan)

    def ekspor_tag_csv(self):
        if not self.daftar_tag:
            QMessageBox.information(self, "Ekspor Tag", "Daftar tag masih kosong.")
            return
        jalur, _ = QFileDialog.getSaveFileName(self, "Ekspor Daftar Tag", "daftar_tag.csv", "CSV Files (*.csv)")
        if not jalur:
            return
        try:
            with open(jalur, 'w', newline='', encoding='utf-8') as f:
                penulis = csv.DictWriter(f, fieldnames=KOLOM_TAG_CSV, extrasaction='ignore')
                penulis.writeheader()
                penulis.writerows(self.daftar_tag)
            self._set_status(f"Daftar tag diekspor → {jalur}")
        except Exception as e:
            catat_kesalahan("Ekspor tag CSV", e)
            QMessageBox.warning(self, "Gagal Ekspor", f"Terjadi kesalahan saat menyimpan:\n{e}")

    def impor_tag_csv(self):
        jalur, _ = QFileDialog.getOpenFileName(self, "Impor Daftar Tag", "", "CSV Files (*.csv)")
        if not jalur:
            return
        baru, gagal = [], []
        try:
            with open(jalur, 'r', newline='', encoding='utf-8-sig') as f:
                for nomor, baris in enumerate(csv.DictReader(f), start=2):
                    try:
                        baru.append(normalisasi_tag(baris))
                    except (ValueError, TypeError) as e:
                        gagal.append(f"baris {nomor}: {e}")
        except Exception as e:
            catat_kesalahan("Impor tag CSV", e)
            QMessageBox.warning(self, "Gagal Impor", f"Terjadi kesalahan saat membaca file:\n{e}")
            return
        if not baru:
            detail = "\n".join(gagal[:10]) or "File tidak berisi baris data."
            QMessageBox.warning(self, "Impor Tag", f"Tidak ada tag valid yang bisa diimpor.\n\n{detail}")
            return

        kotak = QMessageBox(self)
        kotak.setWindowTitle("Impor Tag")
        teks = f"{len(baru)} tag valid ditemukan"
        if gagal:
            teks += f", {len(gagal)} baris dilewati:\n" + "\n".join(gagal[:5])
        teks += "\n\nTambahkan ke daftar yang ada, atau ganti seluruh daftar?"
        kotak.setText(teks)
        btn_tambah = kotak.addButton("Tambahkan", QMessageBox.AcceptRole)
        btn_ganti = kotak.addButton("Ganti Semua", QMessageBox.DestructiveRole)
        kotak.addButton("Batal", QMessageBox.RejectRole)
        kotak.exec_()
        if kotak.clickedButton() is btn_tambah:
            self.daftar_tag.extend(baru)
        elif kotak.clickedButton() is btn_ganti:
            self.daftar_tag = baru
        else:
            return
        self._render_ulang_tabel_tag()

    def _render_ulang_tabel_tag(self):
        self.tabel_tag.setUpdatesEnabled(False)
        try:
            self.tabel_tag.setRowCount(0)
            for tag in self.daftar_tag:
                baris = self.tabel_tag.rowCount()
                self.tabel_tag.insertRow(baris)
                nilai_kolom = [
                    tag.get('nama', ''), str(tag.get('slave_id', '')), tag.get('tipe_reg', ''),
                    str(tag.get('alamat', '')), tag.get('encoding', ''), str(tag.get('skala', '')),
                    str(tag.get('offset', '')), '-', '-'
                ]
                for kolom, teks in enumerate(nilai_kolom):
                    item = QTableWidgetItem(teks)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.tabel_tag.setItem(baris, kolom, item)
            # Pas-kan lebar kolom SEKALI di sini (bukan otomatis terus-menerus
            # lewat ResizeToContents) - lihat catatan performa di atas.
            self.tabel_tag.resizeColumnsToContents()
        finally:
            self.tabel_tag.setUpdatesEnabled(True)

    def eksekusi_baca_tag(self, tunggal=False):
        if not tunggal and self.thread_tag and self.thread_tag.isRunning():
            self.thread_tag.apakah_berjalan = False
            self.btn_tag_toggle_polling.setText("▶ Mulai Polling Semua Tag")
            self.manajemen_interlock_tombol(None, status_reset=True)
            self._set_status("Polling daftar tag dihentikan.")
            return

        if not self.client_global or not client_terhubung(self.client_global):
            self._set_status("Error: Koneksi utama belum aktif.")
            return

        if not self.daftar_tag:
            QMessageBox.information(self, "Daftar Tag Kosong", "Tambahkan minimal satu tag terlebih dahulu.")
            return

        if tunggal and self.thread_tag and self.thread_tag.isRunning():
            self._set_status("Masih ada pembacaan tag yang berjalan, tunggu selesai dahulu.")
            return

        if not tunggal:
            self.manajemen_interlock_tombol("tag")
            self.btn_tag_toggle_polling.setText("■ Hentikan Polling")
            self._set_status("Polling daftar tag aktif...")
        else:
            self._set_status("Membaca semua tag...")

        self.thread_tag = TagListReaderThread(
            self.client_global, self.daftar_tag, single_shot=tunggal,
            interval=self.spin_tag_interval.value(),
            auto_reconnect=self.chk_auto_reconnect.isChecked()
        )
        self.thread_tag.sinyal_hasil.connect(self.proses_hasil_tag_thread)
        self.thread_tag.sinyal_kesalahan.connect(self.proses_kesalahan_thread)
        self.thread_tag.sinyal_info.connect(self.proses_info_thread)
        th = self.thread_tag
        th.finished.connect(lambda th=th: self._thread_selesai(th))
        self._atur_edit_tag_aktif(False)
        th.start()

    def proses_hasil_tag_thread(self, hasil):
        stempel = datetime.now().strftime("%H:%M:%S")
        # FIX PERFORMA: reuse item sel yang sudah ada (setText) alih-alih
        # membuat objek QTableWidgetItem baru setiap siklus polling.
        self.tabel_tag.setUpdatesEnabled(False)
        try:
            for baris, item_hasil in enumerate(hasil):
                if baris >= self.tabel_tag.rowCount():
                    break
                item_mentah = self.tabel_tag.item(baris, 7)
                if item_mentah is None:
                    item_mentah = QTableWidgetItem()
                    item_mentah.setFlags(item_mentah.flags() & ~Qt.ItemIsEditable)
                    self.tabel_tag.setItem(baris, 7, item_mentah)
                item_mentah.setText(item_hasil['nilai_mentah'])

                item_akhir = self.tabel_tag.item(baris, 8)
                if item_akhir is None:
                    item_akhir = QTableWidgetItem()
                    item_akhir.setFlags(item_akhir.flags() & ~Qt.ItemIsEditable)
                    self.tabel_tag.setItem(baris, 8, item_akhir)
                item_akhir.setText(item_hasil['nilai_akhir'])
                item_akhir.setBackground(QColor(WARNA_GAGAL) if item_hasil['status'] == 'ERROR' else QColor(Qt.transparent))
        finally:
            self.tabel_tag.setUpdatesEnabled(True)
        self._log_dibatasi(self.txt_tag_monitor, f"[{stempel}] Pembacaan {len(hasil)} tag selesai.")
