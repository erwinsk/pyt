# -*- coding: utf-8 -*-
"""
main.py — PDF Tools Suite
Menggabungkan 2 aplikasi PDF yang sebelumnya terpisah menjadi 1 aplikasi
dengan tab:
    1. Compressor      (dari ultimate-pdf-compresor.py, + opsi Sharpen)
    2. PDF -> Gambar   (GUI baru untuk fungsi pdf_to_images dari convert_pdf_img_1.py)

Jalankan dengan:
    python main.py
"""

import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QTabWidget

from tabs.compressor_tab import CompressorTab
from tabs.image_export_tab import ImageExportTab


class PDFToolsSuite(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Tools Suite")
        self.setMinimumSize(650, 700)

        tabs = QTabWidget()
        tabs.addTab(CompressorTab(), "Compressor")
        tabs.addTab(ImageExportTab(), "PDF -> Gambar")
        self.setCentralWidget(tabs)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = PDFToolsSuite()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
