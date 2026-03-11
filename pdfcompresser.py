import sys
import os
import io
import fitz  # PyMuPDF
from PIL import Image
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QListWidget, QFileDialog, QLabel, 
                             QSpinBox, QMessageBox, QProgressBar, QTextEdit)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

class CompressionThread(QThread):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, files, quality, dpi):
        super().__init__()
        self.files = files
        self.quality = quality
        self.dpi = dpi

    def run(self):
        for i, file_path in enumerate(self.files):
            try:
                original_size = os.path.getsize(file_path) / 1024
                output_path = os.path.join(
                    os.path.dirname(file_path),
                    f"compressed_{os.path.basename(file_path)}"
                )
                
                doc = fitz.open(file_path)
                
                # Cek jika PDF terproteksi
                if doc.is_encrypted:
                    self.log.emit(f"⚠️ Skip: {os.path.basename(file_path)} terproteksi password.")
                    continue

                new_doc = fitz.open()
                zoom = self.dpi / 72
                matrix = fitz.Matrix(zoom, zoom)

                for page in doc:
                    pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=self.quality, optimize=True)
                    
                    new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
                    new_page.insert_image(new_page.rect, stream=buf.getvalue())

                new_doc.save(output_path, garbage=4, deflate=True)
                new_doc.close()
                doc.close()
                
                final_size = os.path.getsize(output_path) / 1024
                reduction = ((original_size - final_size) / original_size) * 100
                self.log.emit(f"✅ Berhasil: {os.path.basename(file_path)} ({reduction:.1f}% lebih kecil)")
                
                self.progress.emit(int(((i + 1) / len(self.files)) * 100))
            
            except Exception as e:
                self.log.emit(f"❌ Error pada {os.path.basename(file_path)}: {str(e)}")
        
        self.finished.emit("Proses Selesai")

class PDFCompressorApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True) # Mengaktifkan fitur Drag & Drop
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle('Industrial PDF Compressor Pro v3')
        self.setGeometry(100, 100, 600, 600)
        
        # Modern Dark Theme Palette
        self.setStyleSheet("""
            QWidget {
                background-color: #121212;
                color: #E0E0E0;
                font-family: 'Segoe UI', Roboto, Arial;
                font-size: 10pt;
            }
            QLabel {
                color: #FFFFFF;
                font-weight: bold;
                margin-top: 5px;
            }
            QListWidget {
                background-color: #1E1E1E;
                border: 2px solid #333333;
                border-radius: 5px;
                color: #00FF41; /* Matrix Green untuk daftar file agar kontras */
            }
            QSpinBox {
                background-color: #2D2D2D;
                border: 1px solid #444444;
                padding: 5px;
                color: white;
            }
            QTextEdit {
                background-color: #000000;
                border: 1px solid #333333;
                color: #00FF41;
                font-family: 'Consolas', 'Courier New';
            }
            QProgressBar {
                border: 1px solid #444444;
                border-radius: 5px;
                text-align: center;
                background-color: #1E1E1E;
            }
            QProgressBar::chunk {
                background-color: #27ae60;
            }
            QPushButton {
                background-color: #333333;
                border: 1px solid #555555;
                padding: 8px;
                border-radius: 4px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #444444;
                border: 1px solid #27ae60;
            }
            #btnRun {
                background-color: #27ae60;
                color: white;
                font-weight: bold;
            }
            #btnRun:hover {
                background-color: #2ecc71;
            }
            #dropLabel {
                color: #AAAAAA;
                border: 2px dashed #333333;
                padding: 20px;
                margin-bottom: 10px;
            }
        """)

        layout = QVBoxLayout()

        # Drop Area
        self.label_info = QLabel("TARIK DOKUMEN KE SINI")
        self.label_info.setObjectName("dropLabel")
        self.label_info.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label_info)
        
        # List File
        self.file_list = QListWidget()
        layout.addWidget(self.file_list)

        # Settings
        ctrl_layout = QHBoxLayout()
        
        vbox_q = QVBoxLayout()
        vbox_q.addWidget(QLabel("KUALITAS GAMBAR (1-100)"))
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(40)
        vbox_q.addWidget(self.quality_spin)
        ctrl_layout.addLayout(vbox_q)

        vbox_d = QVBoxLayout()
        vbox_d.addWidget(QLabel("RESOLUSI (DPI)"))
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 300)
        self.dpi_spin.setValue(150)
        vbox_d.addWidget(self.dpi_spin)
        ctrl_layout.addLayout(vbox_d)

        layout.addLayout(ctrl_layout)

        # Log Console
        layout.addWidget(QLabel("STATUS LOG"))
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        layout.addWidget(self.console)

        # Progress
        self.pbar = QProgressBar()
        layout.addWidget(self.pbar)

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("TAMBAH BERKAS")
        self.btn_add.clicked.connect(self.add_files)
        
        self.btn_clear = QPushButton("RESET")
        self.btn_clear.clicked.connect(self.reset_all)
        
        self.btn_run = QPushButton("MULAI KOMPRES")
        self.btn_run.setObjectName("btnRun")
        self.btn_run.setFixedHeight(45)
        self.btn_run.clicked.connect(self.start_compression)
        
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addWidget(self.btn_run, 2) # Beri proporsi lebih besar
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    # --- DRAG AND DROP HANDLERS ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith('.pdf'):
                self.file_list.addItem(file_path)

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Pilih PDF", "", "PDF Files (*.pdf)")
        if files:
            self.file_list.addItems(files)

    def reset_all(self):
        self.file_list.clear()
        self.console.clear()
        self.pbar.setValue(0)

    def start_compression(self):
        if self.file_list.count() == 0:
            return
        
        files = [self.file_list.item(i).text() for i in range(self.file_list.count())]
        self.btn_run.setEnabled(False)
        self.console.append("🚀 Memulai proses kompresi...")
        
        self.thread = CompressionThread(files, self.quality_spin.value(), self.dpi_spin.value())
        self.thread.log.connect(lambda m: self.console.append(m))
        self.thread.progress.connect(self.pbar.setValue)
        self.thread.finished.connect(lambda m: [QMessageBox.information(self, "Selesai", m), self.btn_run.setEnabled(True)])
        self.thread.start()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = PDFCompressorApp()
    ex.show()
    sys.exit(app.exec_())