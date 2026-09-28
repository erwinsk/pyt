import sys
import os
import io
import fitz  # PyMuPDF
from PIL import Image, ImageOps, ImageFilter
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QListWidget, QFileDialog, QLabel, 
                             QSpinBox, QMessageBox, QProgressBar, QTextEdit, QCheckBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

class CompressionThread(QThread):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, files, quality, dpi, is_grayscale, is_sharpen):
        super().__init__()
        self.files = files
        self.quality = quality
        self.dpi = dpi
        self.is_grayscale = is_grayscale
        self.is_sharpen = is_sharpen

    def run(self):
        for i, file_path in enumerate(self.files):
            try:
                original_size = os.path.getsize(file_path) / 1024
                output_path = os.path.join(
                    os.path.dirname(file_path),
                    f"PROCESSED_{os.path.basename(file_path)}"
                )
                
                doc = fitz.open(file_path)
                new_doc = fitz.open()
                
                # Konversi DPI ke Scale Factor (72 adalah standar PDF)
                zoom = self.dpi / 72
                matrix = fitz.Matrix(zoom, zoom)

                for page_num in range(len(doc)):
                    page = doc[page_num]
                    pix = page.get_pixmap(matrix=matrix)
                    
                    # Convert pixmap ke PIL Image
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    
                    if self.is_grayscale:
                        img = ImageOps.grayscale(img)
                    
                    if self.is_sharpen:
                        img = img.filter(ImageFilter.SHARPEN)
                    
                    # Simpan ke buffer memory (tidak perlu temp file di disk)
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=self.quality, optimize=True)
                    
                    # Masukkan kembali ke PDF baru
                    new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
                    new_page.insert_image(new_page.rect, stream=buf.getvalue())

                new_doc.save(output_path, garbage=4, deflate=True)
                new_doc.close()
                doc.close()
                
                final_size = os.path.getsize(output_path) / 1024
                reduction = ((original_size - final_size) / original_size) * 100
                self.log.emit(f"✅ {os.path.basename(file_path)}: {reduction:.1f}% mengecil")
                
                self.progress.emit(int(((i + 1) / len(self.files)) * 100))
            
            except Exception as e:
                self.log.emit(f"❌ Error: {str(e)}")
        
        self.finished.emit("Semua dokumen berhasil diproses!")

class PDFApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True) # Aktifkan Drag & Drop
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle('PDF Image-Based Converter (PyMuPDF Edition)')
        self.setGeometry(100, 100, 550, 600)
        
        layout = QVBoxLayout()

        # Label Instruksi
        self.label = QLabel("Tarik dan Lepaskan file PDF di bawah ini:")
        layout.addWidget(self.label)

        # List Widget untuk Drag & Drop
        self.file_list = QListWidget()
        self.file_list.setToolTip("File yang akan diproses")
        layout.addWidget(self.file_list)

        # Control Panel
        settings_layout = QHBoxLayout()
        
        # Kualitas
        v_q = QVBoxLayout()
        v_q.addWidget(QLabel("Kualitas JPEG (1-100):"))
        self.spin_quality = QSpinBox()
        self.spin_quality.setRange(1, 100)
        self.spin_quality.setValue(60)
        v_q.addWidget(self.spin_quality)
        settings_layout.addLayout(v_q)

        # DPI
        v_d = QVBoxLayout()
        v_d.addWidget(QLabel("Resolusi (DPI):"))
        self.spin_dpi = QSpinBox()
        self.spin_dpi.setRange(72, 600)
        self.spin_dpi.setValue(150)
        v_d.addWidget(self.spin_dpi)
        settings_layout.addLayout(v_d)
        
        layout.addLayout(settings_layout)

        # Fitur Tambahan
        options_layout = QHBoxLayout()
        self.check_gray = QCheckBox("Mode Grayscale")
        self.check_sharp = QCheckBox("Pertajam (Sharpen)")
        options_layout.addWidget(self.check_gray)
        options_layout.addWidget(self.check_sharp)
        layout.addLayout(options_layout)

        # Console Log
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setPlaceholderText("Status log akan muncul di sini...")
        layout.addWidget(self.console)

        # Progress Bar
        self.pbar = QProgressBar()
        layout.addWidget(self.pbar)

        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("Tambah Manual")
        self.btn_add.clicked.connect(self.add_files)
        
        self.btn_clear = QPushButton("Bersihkan List")
        self.btn_clear.clicked.connect(self.file_list.clear)
        
        self.btn_run = QPushButton("PROSES SEKARANG")
        self.btn_run.setStyleSheet("font-weight: bold; background-color: #e1e1e1;")
        self.btn_run.setFixedHeight(40)
        self.btn_run.clicked.connect(self.start_process)
        
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addWidget(self.btn_run)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    # Logic Drag & Drop
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith('.pdf'):
                self.file_list.addItem(path)

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Pilih PDF", "", "PDF Files (*.pdf)")
        if files:
            self.file_list.addItems(files)

    def start_process(self):
        if self.file_list.count() == 0:
            QMessageBox.warning(self, "Peringatan", "List file kosong!")
            return
        
        files = [self.file_list.item(i).text() for i in range(self.file_list.count())]
        self.btn_run.setEnabled(False)
        self.pbar.setValue(0)
        
        self.thread = CompressionThread(
            files, 
            self.spin_quality.value(), 
            self.spin_dpi.value(),
            self.check_gray.isChecked(),
            self.check_sharp.isChecked()
        )
        self.thread.log.connect(lambda m: self.console.append(m))
        self.thread.progress.connect(self.pbar.setValue)
        self.thread.finished.connect(self.on_finished)
        self.thread.start()

    def on_finished(self, msg):
        QMessageBox.information(self, "Selesai", msg)
        self.btn_run.setEnabled(True)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion") # Memastikan tampilan klasik dan bersih
    win = PDFApp()
    win.show()
    sys.exit(app.exec_())