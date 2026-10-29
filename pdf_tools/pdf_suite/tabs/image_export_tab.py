# -*- coding: utf-8 -*-
"""
image_export_tab.py
Tab "PDF -> Gambar" — GUI baru yang membungkus fungsi pdf_to_images()
yang sebelumnya hanya ada sebagai script CLI di convert_pdf_img_1.py.

Catatan penting (lihat CHANGELOG.md):
convert_pdf_img_2.py TIDAK dipakai sebagai basis tab ini karena isinya
sebenarnya adalah compressor lain (rasterize -> repack ke PDF baru),
bukan fitur ekspor ke file gambar. Fitur ekspor gambar yang asli justru
ada di convert_pdf_img_1.py (fungsi pdf_to_images), makanya itu yang
dipindah ke sini dan dibungkus GUI konsisten dengan tab Compressor.
"""

import os
from core.pdfcompat import fitz  # PyMuPDF (pymupdf / fitz)
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog, QFrame, QGridLayout,
    QLabel, QSpinBox, QMessageBox, QProgressBar, QComboBox, QLineEdit, QSizePolicy, QShortcut
)
from PyQt5.QtCore import QThread, Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence

from widgets.common import WrapLabel, make_shrinkable, open_folder, side_width
from widgets.log_console import ElidedLabel, LogDrawer
from widgets.queue import ImageTable, QueuePanel


def pdf_to_images(pdf_path, output_folder, dpi=150, fmt="png"):
    """
    Ekspor tiap halaman PDF menjadi file gambar terpisah.
    Dipindah & disesuaikan dari convert_pdf_img_1.py (parameter 'scale'
    diganti 'dpi' agar konsisten dengan tab Compressor: zoom = dpi / 72).
    """
    os.makedirs(output_folder, exist_ok=True)
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)

    image_paths = []
    doc = fitz.open(pdf_path)
    try:
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        for page_num in range(len(doc)):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=matrix)
            image_path = os.path.join(output_folder, f"{base_name}_page_{page_num + 1:03d}.{fmt}")
            pix.save(image_path)
            image_paths.append(image_path)
    finally:
        doc.close()
    return image_paths


class ImageExportThread(QThread):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    all_done = pyqtSignal(str)
    file_started = pyqtSignal(int)             # indeks file yang mulai diproses
    file_done = pyqtSignal(int, int, str)      # indeks, jumlah halaman (-1 = gagal), pesan

    def __init__(self, tasks, output_root, dpi, fmt):
        super().__init__()
        self.tasks = tasks
        self.output_root = output_root
        self.dpi = dpi
        self.fmt = fmt

    def run(self):
        total = len(self.tasks)
        for i, pdf_path in enumerate(self.tasks):
            self.file_started.emit(i)
            try:
                base_name = os.path.splitext(os.path.basename(pdf_path))[0]
                out_folder = os.path.join(self.output_root, base_name)
                self.log.emit(f"Memproses: {os.path.basename(pdf_path)}")
                images = pdf_to_images(pdf_path, out_folder, self.dpi, self.fmt)
                self.log.emit(f"Selesai: {len(images)} halaman -> {out_folder}")
                self.log.emit("-" * 20)
                self.file_done.emit(i, len(images), out_folder)
            except Exception as e:
                self.log.emit(f"Error pada {os.path.basename(pdf_path)}: {str(e)}")
                self.file_done.emit(i, -1, str(e))
            self.progress.emit(int(((i + 1) / total) * 100))
        self.all_done.emit("Ekspor selesai.")


class ImageExportTab(QWidget):
    """Tab ekspor PDF -> file gambar (PNG/JPG), satu subfolder per PDF."""

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.output_folder = ""
        self.thread = None
        self._failed = 0
        self.init_ui()

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(10)
        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body, 1)

        # kiri: antrean dengan status per file
        self.table = ImageTable()
        self.files = QueuePanel(self.table)
        body.addWidget(self.files, 1)

        # kanan: pengaturan
        self._right = right = QWidget()
        right.setFixedWidth(side_width(1060))
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 10, 12, 12)
        cl.setSpacing(8)
        title = QLabel("KELUARAN")
        title.setObjectName("cardTitle")
        cl.addWidget(title)
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(8)
        g.setColumnStretch(1, 1)
        g.addWidget(QLabel("Folder"), 0, 0)
        self.edit_output = QLineEdit()
        self.edit_output.setPlaceholderText("Pilih folder tujuan…")
        self.edit_output.setToolTip("Tiap PDF akan dibuatkan subfolder sendiri di dalam folder ini.")
        self.btn_browse_out = QPushButton("…")
        self.btn_browse_out.setToolTip("Pilih folder output")
        self.btn_browse_out.setFixedWidth(38)
        self.btn_browse_out.clicked.connect(self.browse_output_folder)
        g.addWidget(self.edit_output, 0, 1)
        g.addWidget(self.btn_browse_out, 0, 2)
        g.addWidget(QLabel("Format"), 1, 0)
        self.combo_format = QComboBox()
        self.combo_format.addItems(["png", "jpg"])
        make_shrinkable(self.combo_format, 6)
        g.addWidget(self.combo_format, 1, 1, 1, 2)
        g.addWidget(QLabel("DPI"), 2, 0)
        self.spin_dpi = QSpinBox()
        self.spin_dpi.setRange(36, 600)
        self.spin_dpi.setValue(150)
        self.spin_dpi.setToolTip("Resolusi gambar. Lebih tinggi = lebih tajam tetapi file lebih besar.")
        g.addWidget(self.spin_dpi, 2, 1, 1, 2)
        cl.addLayout(g)
        hint = WrapLabel("Setiap PDF diekspor ke subfolder bernama sama dengan file-nya, satu gambar per halaman.")
        hint.setObjectName("hint")
        cl.addWidget(hint)
        rl.addWidget(card)
        rl.addStretch(1)
        body.addWidget(right)

        # footer: progres + aksi
        foot = QHBoxLayout()
        foot.setSpacing(10)
        self.btn_open = QPushButton("Buka folder output")
        self.btn_open.clicked.connect(self.open_output)
        self.pbar = QProgressBar()
        self.pbar.setTextVisible(False)
        self.pbar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.lbl_status = ElidedLabel("Siap")
        self.lbl_status.setObjectName("statusText")
        self.btn_run = QPushButton("Mulai ekspor")
        self.btn_run.setObjectName("primary")
        self.btn_run.setToolTip("Mulai ekspor (Ctrl+Enter)")
        self.btn_run.clicked.connect(self.start_process)
        for b in (self.btn_open, self.btn_run):
            b.setMinimumHeight(34)
        mid = QVBoxLayout()          # status di atas progres: hemat lebar, tidak saling menimpa
        mid.setSpacing(5)
        mid.addWidget(self.lbl_status)
        mid.addWidget(self.pbar)
        foot.addWidget(self.btn_open)
        foot.addSpacing(4)
        foot.addLayout(mid, 1)
        foot.addWidget(self.btn_run)
        root.addLayout(foot)

        self.drawer = LogDrawer()
        self.console = self.drawer.console
        root.addWidget(self.drawer)

        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.files.manual_add)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._shortcut_run)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._shortcut_run)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.drawer.toggle)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._right.setFixedWidth(side_width(self.width()))

    def _shortcut_run(self):
        if self.btn_run.isEnabled():
            self.start_process()

    def dragEnterEvent(self, event):
        self.files.accept_drag(event)

    def dropEvent(self, event):
        self.files.handle_drop(event)

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Pilih Folder Output")
        if folder:
            self.edit_output.setText(folder)

    def open_output(self):
        folder = self.edit_output.text().strip()
        if folder and os.path.isdir(folder):
            open_folder(folder)

    def start_process(self):
        tasks = self.files.files()
        if not tasks:
            return
        output_root = self.edit_output.text().strip()
        if not output_root:
            QMessageBox.warning(self, "Peringatan", "Pilih folder output terlebih dahulu.")
            return

        self.btn_run.setEnabled(False)
        self.files.set_enabled_controls(False)      # baris tidak boleh berubah selama ekspor
        self._failed = 0
        self.table.start()
        self.pbar.setValue(0)
        self.lbl_status.set_full_text("Memproses… 0%")
        self.thread = ImageExportThread(
            tasks, output_root, self.spin_dpi.value(), self.combo_format.currentText()
        )
        self.thread.log.connect(lambda m: self.console.append_line(m))
        self.thread.progress.connect(self._on_progress)
        self.thread.file_started.connect(self.table.mark_running)
        self.thread.file_done.connect(self._on_file_done)
        self.thread.all_done.connect(self._on_all_done)
        self.thread.start()

    def _on_progress(self, v: int):
        self.pbar.setValue(v)
        self.lbl_status.set_full_text(f"Memproses… {v}%")

    def _on_file_done(self, r: int, pages: int, message: str):
        self.table.mark_done(r, pages, message)
        if pages < 0:
            self._failed += 1
            self.drawer.set_open(True)       # galat: laci log terbuka otomatis

    def _on_all_done(self, m: str):
        self.files.set_enabled_controls(True)
        self.btn_run.setEnabled(True)
        done = len(self.files.files()) - self._failed
        self.lbl_status.set_full_text(m if not self._failed else f"{m} {done} berhasil, {self._failed} gagal.")
        QMessageBox.information(self, "Selesai", m)
