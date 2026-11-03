"""Tab Daftar Perintah (Write): perintah tulis tersimpan yang bisa dijalankan ulang."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget
)

from .konfigurasi import DAFTAR_ENCODING
from .inti import JENIS_FUNGSI_TULIS, susun_parameter_tulis

KOLOM_AKSI_PERINTAH = 6


class PerintahMixin:
    """Tab Daftar Perintah (Write). Pola sama dengan tab Daftar Tag, tetapi untuk
    perintah TULIS: perintah disimpan sekali lalu dijalankan kapan saja dengan
    satu klik, tanpa mengisi ulang form di tab 'Write Register / Coil'."""

    def buat_tab_daftar_perintah_write(self):
        tab = QWidget()
        tata_letak = QHBoxLayout(tab)

        box_kontrol = QGroupBox("Definisi Perintah")
        box_kontrol.setMaximumWidth(320)
        grid_kiri = QGridLayout(box_kontrol)

        grid_kiri.addWidget(QLabel("Nama Perintah:"), 0, 0)
        self.txt_perintah_nama = QLineEdit("Perintah_1")
        grid_kiri.addWidget(self.txt_perintah_nama, 0, 1)

        grid_kiri.addWidget(QLabel("Slave ID:"), 1, 0)
        self.spin_perintah_slave = QSpinBox()
        self.spin_perintah_slave.setRange(0, 255)
        self.spin_perintah_slave.setValue(1)
        grid_kiri.addWidget(self.spin_perintah_slave, 1, 1)

        grid_kiri.addWidget(QLabel("Fungsi Tulis:"), 2, 0)
        self.combo_perintah_type = QComboBox()
        self.combo_perintah_type.addItems(JENIS_FUNGSI_TULIS)
        grid_kiri.addWidget(self.combo_perintah_type, 2, 1)

        grid_kiri.addWidget(QLabel("Alamat Tujuan:"), 3, 0)
        self.spin_perintah_addr = QSpinBox()
        self.spin_perintah_addr.setRange(0, 65535)
        grid_kiri.addWidget(self.spin_perintah_addr, 3, 1)

        grid_kiri.addWidget(QLabel("Format Data:"), 4, 0)
        self.combo_perintah_encoding = QComboBox()
        self.combo_perintah_encoding.addItems(DAFTAR_ENCODING)
        self.combo_perintah_encoding.setToolTip("Diabaikan untuk Coil dan Mask Write Register.")
        grid_kiri.addWidget(self.combo_perintah_encoding, 4, 1)

        grid_kiri.addWidget(QLabel("Nilai:"), 5, 0)
        self.txt_perintah_nilai = QLineEdit("0")
        self.txt_perintah_nilai.setToolTip(
            "Coil: 1/0/true/false/on/off.\n"
            "Register tunggal: satu angka.\n"
            "Multiple Registers/Coils: pisahkan dengan koma, mis. 1,2,3.\n"
            "Mask Write Register: dua angka dipisah koma 'AND_mask,OR_mask' (boleh desimal atau 0xHEX)."
        )
        grid_kiri.addWidget(self.txt_perintah_nilai, 5, 1)

        self.chk_perintah_verify = QCheckBox("Baca ulang untuk verifikasi")
        self.chk_perintah_verify.setChecked(True)
        grid_kiri.addWidget(self.chk_perintah_verify, 6, 0, 1, 2)

        self.chk_perintah_skip_confirm = QCheckBox("Lewati dialog konfirmasi saat dijalankan")
        self.chk_perintah_skip_confirm.setToolTip(
            "Kalau dicentang, klik 'Jalankan' di tabel langsung eksekusi tanpa dialog konfirmasi. "
            "Gunakan dengan hati-hati.")
        grid_kiri.addWidget(self.chk_perintah_skip_confirm, 7, 0, 1, 2)

        self.btn_tambah_perintah = QPushButton("+ Simpan Perintah Baru")
        self.btn_tambah_perintah.clicked.connect(self.tambah_perintah_write)
        grid_kiri.addWidget(self.btn_tambah_perintah, 8, 0, 1, 2)

        self.btn_ubah_perintah = QPushButton("Perbarui Perintah Terpilih")
        self.btn_ubah_perintah.setToolTip(
            "Pilih satu baris di tabel kanan (datanya dimuat ke form ini), ubah seperlunya, lalu klik tombol ini.")
        self.btn_ubah_perintah.clicked.connect(self.perbarui_perintah_terpilih)
        grid_kiri.addWidget(self.btn_ubah_perintah, 9, 0, 1, 2)

        self.btn_hapus_perintah = QPushButton("Hapus Perintah Terpilih")
        self.btn_hapus_perintah.clicked.connect(self.hapus_perintah_terpilih)
        grid_kiri.addWidget(self.btn_hapus_perintah, 10, 0, 1, 2)

        hbox_urut = QHBoxLayout()
        self.btn_perintah_naik = QPushButton("▲ Naik")
        self.btn_perintah_naik.clicked.connect(lambda: self.pindah_perintah(-1))
        self.btn_perintah_turun = QPushButton("▼ Turun")
        self.btn_perintah_turun.clicked.connect(lambda: self.pindah_perintah(+1))
        hbox_urut.addWidget(self.btn_perintah_naik)
        hbox_urut.addWidget(self.btn_perintah_turun)
        grid_kiri.addLayout(hbox_urut, 11, 0, 1, 2)

        grid_kiri.setRowStretch(12, 1)

        panel_kanan = QWidget()
        layout_kanan = QVBoxLayout(panel_kanan)
        layout_kanan.setContentsMargins(0, 0, 0, 0)

        self.tabel_perintah = QTableWidget(0, 7)
        self.tabel_perintah.setHorizontalHeaderLabels(
            ["Nama", "Slave ID", "Fungsi", "Alamat", "Format", "Nilai", "Aksi"]
        )
        self.tabel_perintah.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tabel_perintah.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabel_perintah.itemSelectionChanged.connect(self._muat_perintah_terpilih_ke_form)
        layout_kanan.addWidget(self.tabel_perintah, 2)

        box_log_perintah = QGroupBox("Terminal Validasi")
        layout_log_perintah = QVBoxLayout(box_log_perintah)
        self.txt_perintah_log = QTextEdit()
        self.txt_perintah_log.setReadOnly(True)
        layout_log_perintah.addWidget(self.txt_perintah_log)
        layout_kanan.addWidget(box_log_perintah, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(box_kontrol)
        splitter.addWidget(panel_kanan)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        tata_letak.addWidget(splitter)
        self.tabs.addTab(tab, "Daftar Perintah (Write)")

    # ------------------------------------------------------------------
    def _baris_perintah_terpilih(self):
        return sorted({idx.row() for idx in self.tabel_perintah.selectedIndexes()})

    def _perintah_dari_form(self):
        """Kumpulkan isian form menjadi dict perintah. Mengembalikan None (setelah
        memberi tahu pengguna) bila nama kosong atau nilai tidak bisa diurai --
        perintah yang pasti gagal dijalankan tidak perlu disimpan."""
        data = {
            'nama': self.txt_perintah_nama.text().strip(),
            'slave_id': self.spin_perintah_slave.value(),
            'tipe_fungsi': self.combo_perintah_type.currentText(),
            'alamat': self.spin_perintah_addr.value(),
            'encoding': self.combo_perintah_encoding.currentText(),
            'nilai': self.txt_perintah_nilai.text(),
            'verifikasi': self.chk_perintah_verify.isChecked(),
            'lewati_konfirmasi': self.chk_perintah_skip_confirm.isChecked(),
        }
        if not data['nama']:
            QMessageBox.warning(self, "Nama Kosong", "Nama perintah tidak boleh kosong.")
            return None
        try:
            susun_parameter_tulis(data['tipe_fungsi'], data['nilai'], data['encoding'],
                                  data['alamat'], data['slave_id'], data['verifikasi'])
        except ValueError as e:
            QMessageBox.warning(self, "Nilai Tidak Valid", f"Perintah belum bisa disimpan:\n\n{e}")
            return None
        return data

    def _muat_perintah_terpilih_ke_form(self):
        baris = self._baris_perintah_terpilih()
        if len(baris) != 1 or baris[0] >= len(self.daftar_perintah_write):
            return
        p = self.daftar_perintah_write[baris[0]]
        self.txt_perintah_nama.setText(p.get('nama', ''))
        self.spin_perintah_slave.setValue(int(p.get('slave_id', 1)))
        self.combo_perintah_type.setCurrentText(p.get('tipe_fungsi', JENIS_FUNGSI_TULIS[0]))
        self.spin_perintah_addr.setValue(int(p.get('alamat', 0)))
        self.combo_perintah_encoding.setCurrentText(p.get('encoding', DAFTAR_ENCODING[0]))
        self.txt_perintah_nilai.setText(str(p.get('nilai', '')))
        self.chk_perintah_verify.setChecked(bool(p.get('verifikasi', True)))
        self.chk_perintah_skip_confirm.setChecked(bool(p.get('lewati_konfirmasi', False)))

    def tambah_perintah_write(self):
        data = self._perintah_dari_form()
        if data is None:
            return
        self.daftar_perintah_write.append(data)
        self._render_ulang_tabel_perintah()
        self.tabel_perintah.selectRow(len(self.daftar_perintah_write) - 1)

    def perbarui_perintah_terpilih(self):
        baris = self._baris_perintah_terpilih()
        if len(baris) != 1 or baris[0] >= len(self.daftar_perintah_write):
            QMessageBox.information(
                self, "Pilih Satu Perintah",
                "Pilih tepat satu baris perintah di tabel (datanya akan dimuat ke form), "
                "ubah nilainya, lalu klik tombol ini.")
            return
        data = self._perintah_dari_form()
        if data is None:
            return
        self.daftar_perintah_write[baris[0]] = data
        self._render_ulang_tabel_perintah()
        self.tabel_perintah.selectRow(baris[0])
        self._set_status(f"Perintah '{data['nama']}' berhasil diperbarui.")

    def hapus_perintah_terpilih(self):
        baris_terpilih = sorted(self._baris_perintah_terpilih(), reverse=True)
        if not baris_terpilih:
            QMessageBox.information(self, "Tidak Ada Pilihan",
                                    "Pilih dulu satu atau lebih baris perintah yang ingin dihapus.")
            return
        for baris in baris_terpilih:
            if 0 <= baris < len(self.daftar_perintah_write):
                del self.daftar_perintah_write[baris]
        self._render_ulang_tabel_perintah()

    def pindah_perintah(self, arah):
        baris = self._baris_perintah_terpilih()
        if len(baris) != 1:
            QMessageBox.information(self, "Pilih Satu Perintah", "Pilih tepat satu baris perintah untuk dipindah.")
            return
        asal, tujuan = baris[0], baris[0] + arah
        if not (0 <= tujuan < len(self.daftar_perintah_write)):
            return
        d = self.daftar_perintah_write
        d[asal], d[tujuan] = d[tujuan], d[asal]
        self._render_ulang_tabel_perintah()
        self.tabel_perintah.selectRow(tujuan)

    def _render_ulang_tabel_perintah(self):
        self.tabel_perintah.setUpdatesEnabled(False)
        try:
            self.tabel_perintah.setRowCount(0)
            for perintah in self.daftar_perintah_write:
                baris = self.tabel_perintah.rowCount()
                self.tabel_perintah.insertRow(baris)
                nilai_kolom = [
                    perintah.get('nama', ''), str(perintah.get('slave_id', '')),
                    perintah.get('tipe_fungsi', ''), str(perintah.get('alamat', '')),
                    perintah.get('encoding', ''), str(perintah.get('nilai', '')),
                ]
                for kolom, teks in enumerate(nilai_kolom):
                    item = QTableWidgetItem(teks)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.tabel_perintah.setItem(baris, kolom, item)

                # `r=baris` WAJIB: tanpa itu semua tombol memakai nomor baris terakhir loop.
                btn_jalankan = QPushButton("▶ Jalankan")
                btn_jalankan.setToolTip(f"Jalankan perintah '{perintah.get('nama', '')}' ini sekarang.")
                btn_jalankan.clicked.connect(lambda checked=False, r=baris: self.jalankan_perintah_tunggal(r))
                self.tabel_perintah.setCellWidget(baris, KOLOM_AKSI_PERINTAH, btn_jalankan)
            self.tabel_perintah.resizeColumnsToContents()
        finally:
            self.tabel_perintah.setUpdatesEnabled(True)
        self._atur_tombol_perintah(self._operasi_aktif() is None)

    def _atur_tombol_perintah(self, aktif):
        """Aktif/nonaktifkan semua tombol 'Jalankan' (ikut interlock operasi bus)."""
        for baris in range(self.tabel_perintah.rowCount()):
            tombol = self.tabel_perintah.cellWidget(baris, KOLOM_AKSI_PERINTAH)
            if tombol is not None:
                tombol.setEnabled(aktif)

    def jalankan_perintah_tunggal(self, baris):
        if not (0 <= baris < len(self.daftar_perintah_write)):
            return
        p = self.daftar_perintah_write[baris]
        self._mulai_penulisan(
            tipe_fungsi=p.get('tipe_fungsi', ''),
            alamat=int(p.get('alamat', 0)),
            device_id=int(p.get('slave_id', 1)),
            input_user=str(p.get('nilai', '')),
            encoding=p.get('encoding', DAFTAR_ENCODING[0]),
            verifikasi=bool(p.get('verifikasi', True)),
            minta_konfirmasi=not p.get('lewati_konfirmasi', False),
            log_widget=self.txt_perintah_log,
            nama_perintah=p.get('nama', ''),
        )
