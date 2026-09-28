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
import fitz  # PyMuPDF
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QFileDialog,
    QLabel, QSpinBox, QMessageBox, QProgressBar, QTextEdit, QComboBox,
    QListWidgetItem, QLineEdit
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal


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
    finished = pyqtSignal(str)

    def __init__(self, tasks, output_root, dpi, fmt):
        super().__init__()
        self.tasks = tasks
        self.output_root = output_root
        self.dpi = dpi
        self.fmt = fmt

    def run(self):
        total = len(self.tasks)
        for i, pdf_path in enumerate(self.tasks):
            try:
                base_name = os.path.splitext(os.path.basename(pdf_path))[0]
                out_folder = os.path.join(self.output_root, base_name)
                self.log.emit(f"Memproses: {os.path.basename(pdf_path)}")
                images = pdf_to_images(pdf_path, out_folder, self.dpi, self.fmt)
                self.log.emit(f"Selesai: {len(images)} halaman -> {out_folder}")
                self.log.emit("-" * 20)
            except Exception as e:
                self.log.emit(f"Error pada {os.path.basename(pdf_path)}: {str(e)}")
            self.progress.emit(int(((i + 1) / total) * 100))
        self.finished.emit("Ekspor selesai.")


class ImageExportTab(QWidget):
    """Tab ekspor PDF -> file gambar (PNG/JPG), satu subfolder per PDF."""

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.output_folder = ""
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Daftar PDF (Drag & Drop):"))
        self.file_list = QListWidget()
        layout.addWidget(self.file_list)

        list_btns = QHBoxLayout()
        self.btn_add = QPushButton("Tambah File")
        self.btn_add.clicked.connect(self.manual_add)
        self.btn_remove = QPushButton("Hapus Terpilih")
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear = QPushButton("Reset Semua")
        self.btn_clear.clicked.connect(self.reset_ui)
        list_btns.addWidget(self.btn_add)
        list_btns.addWidget(self.btn_remove)
        list_btns.addWidget(self.btn_clear)
        layout.addLayout(list_btns)

        # Folder output
        out_layout = QHBoxLayout()
        out_layout.addWidget(QLabel("Folder Output:"))
        self.edit_output = QLineEdit()
        self.edit_output.setPlaceholderText("Pilih folder tujuan (tiap PDF akan dibuatkan subfolder)...")
        self.btn_browse_out = QPushButton("Browse")
        self.btn_browse_out.clicked.connect(self.browse_output_folder)
        out_layout.addWidget(self.edit_output, 1)
        out_layout.addWidget(self.btn_browse_out)
        layout.addLayout(out_layout)

        # Settings
        settings_layout = QHBoxLayout()
        settings_layout.addWidget(QLabel("Format:"))
        self.combo_format = QComboBox()
        self.combo_format.addItems(["png", "jpg"])
        settings_layout.addWidget(self.combo_format)
        settings_layout.addWidget(QLabel("DPI:"))
        self.spin_dpi = QSpinBox()
        self.spin_dpi.setRange(36, 600)
        self.spin_dpi.setValue(150)
        settings_layout.addWidget(self.spin_dpi)
        settings_layout.addStretch(1)
        layout.addLayout(settings_layout)

        # Log & progress
        layout.addWidget(QLabel("Log Aktivitas:"))
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet("background: #1e1e1e; color: #ffffff; font-family: Consolas;")
        layout.addWidget(self.console)
        self.pbar = QProgressBar()
        layout.addWidget(self.pbar)

        self.btn_run = QPushButton("EKSPOR KE GAMBAR")
        self.btn_run.setFixedHeight(45)
        self.btn_run.setStyleSheet("font-weight: bold; background-color: #2c3e50; color: white;")
        self.btn_run.clicked.connect(self.start_process)
        layout.addWidget(self.btn_run)

        self.setLayout(layout)

    def update_indexes(self):
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            path = item.data(Qt.UserRole)
            item.setText(f"[{i+1}] {os.path.basename(path)}")

    def add_pdf_item(self, path):
        if not any(self.file_list.item(i).data(Qt.UserRole) == path for i in range(self.file_list.count())):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, path)
            self.file_list.addItem(item)
            self.update_indexes()

    def remove_selected(self):
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))
        self.update_indexes()

    def reset_ui(self):
        self.file_list.clear()
        self.pbar.setValue(0)
        self.console.clear()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith('.pdf'):
                self.add_pdf_item(path)

    def manual_add(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Pilih PDF", "", "PDF Files (*.pdf)")
        for f in files:
            self.add_pdf_item(f)

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Pilih Folder Output")
        if folder:
            self.edit_output.setText(folder)

    def start_process(self):
        count = self.file_list.count()
        if count == 0:
            return
        output_root = self.edit_output.text().strip()
        if not output_root:
            QMessageBox.warning(self, "Peringatan", "Pilih folder output terlebih dahulu.")
            return

        tasks = [self.file_list.item(i).data(Qt.UserRole) for i in range(count)]

        self.btn_run.setEnabled(False)
        self.pbar.setValue(0)
        self.thread = ImageExportThread(
            tasks, output_root, self.spin_dpi.value(), self.combo_format.currentText()
        )
        self.thread.log.connect(lambda m: self.console.append(m))
        self.thread.progress.connect(self.pbar.setValue)
        self.thread.finished.connect(lambda m: [QMessageBox.information(self, "Selesai", m), self.btn_run.setEnabled(True)])
        self.thread.start()
