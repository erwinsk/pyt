import sys
import os
import io
import subprocess
import fitz  # PyMuPDF
from PIL import Image
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QListWidget, QFileDialog, QLabel, 
                             QSpinBox, QMessageBox, QProgressBar, QTextEdit, 
                             QCheckBox, QListWidgetItem, QComboBox, QSplitter, QLineEdit)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

class PDFProcessorThread(QThread):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, tasks, quality, dpi, is_grayscale, mode, custom_gs_path=None):
        super().__init__()
        self.tasks = tasks
        self.quality = quality
        self.dpi = dpi
        self.is_grayscale = is_grayscale
        self.mode = mode
        self.custom_gs_path = custom_gs_path

    def run(self):
        total_pages = 0
        for file_path in self.tasks:
            try:
                with fitz.open(file_path) as d:
                    total_pages += len(d)
            except: continue
        
        pages_processed = 0

        for file_path in self.tasks:
            try:
                original_size = os.path.getsize(file_path) / 1024
                out_name = f"PROCESSED_{os.path.basename(file_path)}"
                output_path = os.path.join(os.path.dirname(file_path), out_name)
                
                if self.mode == "Ghostscript":
                    self.log.emit(f"Memproses: {os.path.basename(file_path)}")
                    self.run_ghostscript(file_path, output_path)
                    with fitz.open(file_path) as d:
                        pages_processed += len(d)
                    self.progress.emit(int((pages_processed / total_pages) * 100))
                
                else: # Full Image Mode
                    pages_processed = self.run_full_image(file_path, output_path, pages_processed, total_pages)

                final_size = os.path.getsize(output_path) / 1024
                reduction = ((original_size - final_size) / original_size) * 100
                self.log.emit(f"Selesai: {out_name}")
                self.log.emit(f"Status: -{reduction:.1f}% (Final: {final_size:.0f} KB)")
                self.log.emit("-" * 20)
            
            except Exception as e:
                self.log.emit(f"Error pada {os.path.basename(file_path)}: {str(e)}")
        
        self.finished.emit("Proses selesai.")

    def run_ghostscript(self, inp, out):
        gs_setting = "/ebook"
        if self.quality < 35: gs_setting = "/screen"
        elif self.quality > 85: gs_setting = "/printer"
        
        # Daftar executable yang akan dicoba
        gs_names = []
        if self.custom_gs_path and os.path.exists(self.custom_gs_path):
            gs_names.append(self.custom_gs_path)
        
        # Tambahkan nama standar sistem
        gs_names.extend(["gs", "gswin64c", "gswin32c"])
        
        success = False
        last_error = ""
        for name in gs_names:
            try:
                cmd = [
                    name, "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
                    f"-dPDFSETTINGS={gs_setting}",
                    f"-dColorImageResolution={self.dpi}",
                    f"-dGrayImageResolution={self.dpi}",
                    f"-dMonoImageResolution={self.dpi}",
                    f"-sColorConversionStrategy={'Gray' if self.is_grayscale else 'LeaveColorUnchanged'}",
                    "-dNOPAUSE", "-dQUIET", "-dBATCH",
                    f"-sOutputFile={out}", inp
                ]
                subprocess.run(cmd, check=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                success = True
                break
            except Exception as e:
                last_error = str(e)
                continue
                
        if not success:
            raise Exception(f"Ghostscript gagal dijalankan. {last_error}")

    def run_full_image(self, inp, out, pages_processed, total_pages):
        doc = fitz.open(inp)
        new_doc = fitz.open()
        zoom = self.dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        for page in doc:
            pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            if self.is_grayscale: img = img.convert("L")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=self.quality, optimize=True)
            new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(new_page.rect, stream=buf.getvalue())
            pages_processed += 1
            self.progress.emit(int((pages_processed / total_pages) * 100))
        new_doc.save(out, garbage=4, deflate=True)
        new_doc.close()
        doc.close()
        return pages_processed

class ClassicPDFCompressor(QWidget):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle('Ultimate PDF Compressor (Custom GS)')
        self.setMinimumSize(600, 650)
        main_layout = QVBoxLayout()
        self.splitter = QSplitter(Qt.Vertical)

        # Top Widget
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.addWidget(QLabel("Daftar PDF (Drag & Drop):"))
        self.file_list = QListWidget()
        top_layout.addWidget(self.file_list)
        
        list_btns = QHBoxLayout()
        self.btn_add = QPushButton("Tambah File")
        self.btn_add.clicked.connect(self.manual_add)
        self.btn_remove = QPushButton("Hapus Terpilih")
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear = QPushButton("Reset Semua")
        self.btn_clear.clicked.connect(self.reset_ui)
        list_btns.addWidget(self.btn_add); list_btns.addWidget(self.btn_remove); list_btns.addWidget(self.btn_clear)
        top_layout.addLayout(list_btns)

        # Ghostscript Custom Path UI
        gs_path_layout = QHBoxLayout()
        self.chk_custom_gs = QCheckBox("Gunakan Custom GS Path")
        self.chk_custom_gs.toggled.connect(self.toggle_gs_path)
        self.edit_gs_path = QLineEdit()
        self.edit_gs_path.setPlaceholderText("Pilih lokasi gswin64c.exe atau gs...")
        self.edit_gs_path.setEnabled(False)
        self.btn_browse_gs = QPushButton("Browse")
        self.btn_browse_gs.setEnabled(False)
        self.btn_browse_gs.clicked.connect(self.browse_gs_exe)
        
        gs_path_layout.addWidget(self.chk_custom_gs)
        gs_path_layout.addWidget(self.edit_gs_path, 1)
        gs_path_layout.addWidget(self.btn_browse_gs)
        top_layout.addLayout(gs_path_layout)

        # Settings
        settings_layout = QHBoxLayout()
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Ghostscript", "Full Image"])
        settings_layout.addWidget(QLabel("Metode:")); settings_layout.addWidget(self.combo_mode, 1)
        settings_layout.addWidget(QLabel("Qual:")); self.spin_q = QSpinBox(); self.spin_q.setRange(1, 100); self.spin_q.setValue(60)
        settings_layout.addWidget(self.spin_q)
        settings_layout.addWidget(QLabel("DPI:")); self.spin_d = QSpinBox(); self.spin_d.setRange(10, 300); self.spin_d.setValue(150)
        settings_layout.addWidget(self.spin_d)
        self.chk_gray = QCheckBox("B/W"); settings_layout.addWidget(self.chk_gray)
        top_layout.addLayout(settings_layout)

        # Bottom Widget
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.addWidget(QLabel("Log Aktivitas:"))
        self.console = QTextEdit(); self.console.setReadOnly(True)
        self.console.setStyleSheet("background: #1e1e1e; color: #ffffff; font-family: Consolas;")
        bottom_layout.addWidget(self.console)
        self.pbar = QProgressBar(); bottom_layout.addWidget(self.pbar)
        self.btn_run = QPushButton("MULAI PROSES KOMPRESI")
        self.btn_run.setFixedHeight(45); self.btn_run.setStyleSheet("font-weight: bold; background-color: #2c3e50; color: white;")
        self.btn_run.clicked.connect(self.start_process)
        bottom_layout.addWidget(self.btn_run)

        self.splitter.addWidget(top_widget); self.splitter.addWidget(bottom_widget)
        self.splitter.setStretchFactor(0, 2); self.splitter.setStretchFactor(1, 1)
        main_layout.addWidget(self.splitter)
        self.setLayout(main_layout)

    def toggle_gs_path(self, checked):
        self.edit_gs_path.setEnabled(checked)
        self.btn_browse_gs.setEnabled(checked)

    def browse_gs_exe(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Pilih Executable Ghostscript", "", "Executable (*.exe);;All Files (*)")
        if fname: self.edit_gs_path.setText(fname)

    def update_indexes(self):
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            path = item.data(Qt.UserRole)
            item.setText(f"[{i+1}] {os.path.basename(path)}")

    def add_pdf_item(self, path):
        if not any(self.file_list.item(i).data(Qt.UserRole) == path for i in range(self.file_list.count())):
            item = QListWidgetItem(); item.setData(Qt.UserRole, path)
            self.file_list.addItem(item); self.update_indexes()

    def remove_selected(self):
        for item in self.file_list.selectedItems(): self.file_list.takeItem(self.file_list.row(item))
        self.update_indexes()

    def reset_ui(self):
        self.file_list.clear(); self.pbar.setValue(0); self.console.clear()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.accept()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith('.pdf'): self.add_pdf_item(path)

    def manual_add(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Pilih PDF", "", "PDF Files (*.pdf)")
        for f in files: self.add_pdf_item(f)

    def start_process(self):
        count = self.file_list.count()
        if count == 0: return
        tasks = [self.file_list.item(i).data(Qt.UserRole) for i in range(count)]
        custom_gs = self.edit_gs_path.text() if self.chk_custom_gs.isChecked() else None
        
        self.btn_run.setEnabled(False); self.pbar.setValue(0)
        self.thread = PDFProcessorThread(tasks, self.spin_q.value(), self.spin_d.value(), 
                                         self.chk_gray.isChecked(), self.combo_mode.currentText(), custom_gs)
        self.thread.log.connect(lambda m: self.console.append(m))
        self.thread.progress.connect(self.pbar.setValue)
        self.thread.finished.connect(lambda m: [QMessageBox.information(self, "Selesai", m), self.btn_run.setEnabled(True)])
        self.thread.start()

if __name__ == '__main__':
    app = QApplication(sys.argv); app.setStyle("Fusion")
    win = ClassicPDFCompressor(); win.show()
    sys.exit(app.exec_())