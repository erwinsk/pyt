# -*- coding: utf-8 -*-
"""Konteks bersama aplikasi: pengaturan, cache OCR, dan status alat eksternal."""
from typing import Dict

from PyQt5.QtCore import QObject, QThread, pyqtSignal

from core import deps
from core.cache import OcrCache
from core.profiles import ProfileStore
from core.settings import Settings


class _DetectWorker(QThread):
    done = pyqtSignal(dict, list)

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings

    def run(self):
        tools = deps.detect_all(self.settings, with_version=True)
        langs = deps.tesseract_languages(tools["tesseract"])
        self.done.emit(tools, langs)


class AppContext(QObject):
    tools_changed = pyqtSignal()

    def __init__(self, settings: Settings = None, cache: OcrCache = None, parent=None):
        super().__init__(parent)
        self.settings = settings or Settings()
        self.cache = cache or OcrCache()
        self.profiles = ProfileStore(self.settings)   # Tingkat 1: Tujuan (profil kompresi)
        # Deteksi cepat (tanpa versi) agar UI langsung bisa dipakai.
        self.tools: Dict[str, deps.ToolStatus] = deps.detect_all(self.settings, with_version=False)
        self.languages = []
        self._worker = None

    def refresh(self, with_version: bool = False):
        """Sinkron — dipakai tes dan saat startup cepat."""
        self.tools = deps.detect_all(self.settings, with_version=with_version)
        self.languages = deps.tesseract_languages(self.tools["tesseract"])
        self.tools_changed.emit()

    def refresh_async(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self._worker = _DetectWorker(self.settings)
        self._worker.done.connect(self._on_detected)
        self._worker.start()

    def _on_detected(self, tools, langs):
        self.tools = tools
        self.languages = langs
        self.tools_changed.emit()

    def shutdown(self):
        if self._worker is not None:
            self._worker.wait(15000)
