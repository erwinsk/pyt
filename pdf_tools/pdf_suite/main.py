# -*- coding: utf-8 -*-
"""
main.py — PDF Tools Suite

Tab:
    1. Compressor          Ghostscript / Full Image / OCRmyPDF / MRC (recode_pdf)
    2. PDF -> Gambar       ekspor tiap halaman ke PNG/JPG
    3. Dependensi & Cache  status alat eksternal + pengelolaan cache OCR

Jalankan dengan:
    python main.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox, QTabWidget

from app_context import AppContext
from core.workspace import sweep_orphans
from tabs.compressor_tab import CompressorTab
from tabs.deps_cache_tab import DepsCacheTab
from tabs.image_export_tab import ImageExportTab


class PDFToolsSuite(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("PDF Tools Suite")
        self.setMinimumSize(760, 760)
        self.resize(900, 900)

        self.tabs = QTabWidget()
        self.compressor = CompressorTab(ctx)
        self.tabs.addTab(self.compressor, "Compressor")
        self.tabs.addTab(ImageExportTab(), "PDF -> Gambar")
        self.tabs.addTab(DepsCacheTab(ctx), "Dependensi && Cache")
        self.setCentralWidget(self.tabs)

    def closeEvent(self, event):
        if self.compressor.is_busy():
            r = QMessageBox.question(self, "Proses berjalan",
                                     "Proses kompresi masih berjalan. Batalkan dan keluar?")
            if r != QMessageBox.Yes:
                event.ignore()
                return
            self.compressor.abort_and_wait()
        self.compressor.save_state()
        self.ctx.shutdown()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    ctx = AppContext()
    sweep_orphans()                 # sisa scratch dari proses yang pernah crash
    ctx.cache.sweep_partial()       # sisa penulisan cache yang terputus
    window = PDFToolsSuite(ctx)
    window.show()
    ctx.refresh_async()             # versi alat + daftar bahasa, tanpa membekukan UI
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
