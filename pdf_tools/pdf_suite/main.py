# -*- coding: utf-8 -*-
"""
main.py — PDF Tools Suite

Tab:
    1. Kompres             Ghostscript / Full Image / OCRmyPDF / MRC (recode_pdf)
    2. Atur Halaman        gabung/pisah PDF, impor gambar, putar, ubah ukuran halaman
    3. PDF -> Gambar       ekspor tiap halaman ke PNG/JPG
Dependensi dan cache: dialog (ikon ⚙ atau indikator alat di pojok kanan atas).

Jalankan dengan:
    python main.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt5.QtCore import QByteArray, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (QApplication, QHBoxLayout, QMainWindow, QMessageBox, QShortcut, QTabWidget,
                             QToolButton, QWidget)

import theme
from app_context import AppContext
from core import deps
from core.workspace import sweep_orphans
from tabs.arranger_tab import ArrangerTab
from tabs.compressor_tab import CompressorTab
from tabs.deps_cache_tab import DepsDialog
from tabs.image_export_tab import ImageExportTab


class PDFToolsSuite(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("PDF Tools Suite")
        self.setMinimumSize(1000, 600)
        self.resize(1100, 680)
        geo = ctx.settings.get("ui.geometry")
        if isinstance(geo, str) and geo:
            self.restoreGeometry(QByteArray.fromHex(geo.encode("ascii", "ignore")))

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.compressor = CompressorTab(ctx)
        self.arranger = ArrangerTab(ctx)
        self.image_export = ImageExportTab()
        self.tabs.addTab(self.compressor, "Kompres")
        self.tabs.addTab(self.arranger, "Atur Halaman")
        self.tabs.setTabToolTip(1, "Gabung / pisah PDF, impor gambar jadi PDF, putar dan ubah ukuran halaman")
        self.tabs.addTab(self.image_export, "PDF → Gambar")
        self.setCentralWidget(self.tabs)

        # Dependensi dan cache: dialog, jarang dipakai. Indikator di header menjaga alat yang hilang tetap terlihat.
        self.deps_dialog = DepsDialog(ctx, self)
        self.deps = self.deps_dialog.panel
        self.compressor.request_deps.connect(lambda: self.show_deps(True))

        corner = QWidget()
        cl = QHBoxLayout(corner)
        cl.setContentsMargins(0, 2, 10, 2)
        cl.setSpacing(6)
        self.btn_tools = QToolButton()
        self.btn_tools.setObjectName("chip")
        self.btn_tools.clicked.connect(lambda: self.show_deps(True))
        self.btn_settings = QToolButton()
        self.btn_settings.setObjectName("link")
        self.btn_settings.setText("⚙")
        self.btn_settings.setToolTip("Dependensi dan cache (Ctrl+,)")
        self.btn_settings.clicked.connect(lambda: self.show_deps(False))
        cl.addWidget(self.btn_tools)
        cl.addWidget(self.btn_settings)
        self.tabs.setCornerWidget(corner, Qt.TopRightCorner)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=lambda: self.show_deps(False))

        ctx.tools_changed.connect(self.update_tools_chip)
        self.update_tools_chip()

    # ------------------------------------------------------------ alat
    def tool_problems(self):
        """[(label, 'tidak ada' | 'gagal jalan')] untuk alat yang belum siap dipakai."""
        out = []
        for spec in deps.TOOL_SPECS:
            st = self.ctx.tools.get(spec.id)
            if st is None or not st.found:
                out.append((spec.label, "tidak ada"))
            elif st.warn:
                out.append((spec.label, "gagal jalan"))
        return out

    def update_tools_chip(self):
        problems = self.tool_problems()
        total = len(deps.TOOL_SPECS)
        if problems:
            self.btn_tools.setText(f"⚠ {len(problems)} alat bermasalah")
            self.btn_tools.setToolTip("Klik untuk melihat penyebab dan cara memasangnya:\n" +
                                      "\n".join(f"• {name}: {why}" for name, why in problems))
            state = "warn"
        else:
            self.btn_tools.setText(f"✓ {total} alat siap")
            self.btn_tools.setToolTip("Semua alat eksternal terdeteksi. Klik untuk melihat detail.")
            state = "ok"
        self.btn_tools.setProperty("state", state)
        self.btn_tools.style().unpolish(self.btn_tools)    # agar warna chip mengikuti state
        self.btn_tools.style().polish(self.btn_tools)

    def show_deps(self, focus_problem: bool = False):
        self.deps_dialog.present(focus_problem)

    # ----------------------------------------------------------- tutup
    def closeEvent(self, event):
        if self.compressor.is_busy() or self.arranger.is_busy():
            r = QMessageBox.question(self, "Proses berjalan",
                                     "Sebuah proses masih berjalan. Batalkan dan keluar?")
            if r != QMessageBox.Yes:
                event.ignore()
                return
            self.compressor.abort_and_wait()
        self.arranger.shutdown()
        self.compressor.save_state()
        self.ctx.settings.set("ui.geometry", bytes(self.saveGeometry().toHex()).decode("ascii"))
        self.deps_dialog.close()
        self.ctx.shutdown()
        event.accept()


def main():
    app = QApplication(sys.argv)
    theme.apply(app)
    ctx = AppContext()
    sweep_orphans()                 # sisa scratch dari proses yang pernah crash
    ctx.cache.sweep_partial()       # sisa penulisan cache yang terputus
    window = PDFToolsSuite(ctx)
    window.show()
    ctx.refresh_async()             # versi alat + daftar bahasa, tanpa membekukan UI
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
