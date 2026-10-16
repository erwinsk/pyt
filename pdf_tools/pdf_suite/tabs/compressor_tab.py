# -*- coding: utf-8 -*-
"""Tab Compressor dengan tiga tingkat pilihan:
  1. Tujuan   — profil siap pakai (combo teratas; bisa disimpan/diekspor/diimpor)
  2. Metode   — Ghostscript / Full Image / OCRmyPDF / MRC
  3. Parameter— panel opsi lengkap tiap metode
Tingkat 2-3 ada di bagian 'lanjutan' yang bisa dilipat. Ketiganya selalu konsisten: mengubah
metode/parameter membuat Tujuan berpindah ke 'Kustom' (atau profil lain bila nilainya sama)."""
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QAction, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
                             QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QProgressBar, QPushButton,
                             QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QToolButton, QVBoxLayout,
                             QWidget)

from core.engines import ENGINES, get_engine
from core.profiles import CATEGORY_LABELS, CUSTOM_ID, ProfileError, engine_name
from core.runner import JobRunner, OutputConfig
from widgets.common import open_folder
from widgets.file_list import FileListWidget
from widgets.log_console import LogConsole
from widgets.option_panel import OptionPanel
from widgets.result_table import ResultTable

POLICIES = [("unik", "Buat nama unik (_2, _3 …)"), ("timpa", "Timpa file lama"), ("lewati", "Lewati")]


class CompressorTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.runner = None
        self.panels = {}
        self._applying = False        # True saat profil diterapkan lewat kode (bukan klik pengguna)
        self.setAcceptDrops(True)
        self._cache_timer = QTimer(self)
        self._cache_timer.setSingleShot(True)
        self._cache_timer.setInterval(400)
        self._cache_timer.timeout.connect(self.update_cache_label)
        # Timer milik widget (bukan QTimer.singleShot + lambda): ikut terhapus bersama widget,
        # jadi tidak pernah memanggil objek yang sudah dihancurkan (PyQt5 abort() bila slot
        # melempar exception).
        self._rebalance_timer = QTimer(self)
        self._rebalance_timer.setSingleShot(True)
        self._rebalance_timer.setInterval(0)
        self._rebalance_timer.timeout.connect(self._rebalance)
        self._rebalance_expanded = False
        self._build()
        self._restore()
        self.ctx.tools_changed.connect(self.on_tools_changed)

    # ------------------------------------------------------------------ UI
    def _build(self):
        root = QVBoxLayout(self)
        split = QSplitter(Qt.Vertical)
        self._split = split
        root.addWidget(split)

        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        self.files = FileListWidget()
        self.files.list.setMaximumHeight(90)
        self.files.current_changed.connect(lambda _p: self._cache_timer.start())
        self.files.changed.connect(lambda: self._cache_timer.start())
        self.files.cleared.connect(self._on_cleared)
        tl.addWidget(self.files)

        # ---- Tingkat 1: Tujuan (profil) ----
        prow = QHBoxLayout()
        prow.addWidget(QLabel("Tujuan:"))
        self.combo_profile = QComboBox()
        self.combo_profile.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo_profile.setMinimumContentsLength(32)
        self.combo_profile.activated[int].connect(self._on_profile_activated)
        prow.addWidget(self.combo_profile, 1)
        self.btn_manage = QToolButton()
        self.btn_manage.setText("Kelola ▾")
        self.btn_manage.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.btn_manage)
        self.act_save = QAction("Simpan pengaturan saat ini sebagai profil…", self)
        self.act_delete = QAction("Hapus profil ini", self)
        self.act_export = QAction("Ekspor profil saya…", self)
        self.act_import = QAction("Impor profil…", self)
        self.act_save.triggered.connect(self.save_profile_dialog)
        self.act_delete.triggered.connect(self.delete_profile_dialog)
        self.act_export.triggered.connect(self.export_profiles_dialog)
        self.act_import.triggered.connect(self.import_profiles_dialog)
        menu.addAction(self.act_save)
        menu.addAction(self.act_delete)
        menu.addSeparator()
        menu.addAction(self.act_export)
        menu.addAction(self.act_import)
        self.btn_manage.setMenu(menu)
        prow.addWidget(self.btn_manage)
        tl.addLayout(prow)
        self.lbl_profile = QLabel()
        self.lbl_profile.setWordWrap(True)
        self.lbl_profile.setTextFormat(Qt.PlainText)
        self.lbl_profile.setStyleSheet("color: #555;")
        tl.addWidget(self.lbl_profile)

        # ---- Tingkat 2 + 3: Metode & Parameter (bisa dilipat) ----
        self.btn_adv = QToolButton()
        self.btn_adv.setCheckable(True)
        self.btn_adv.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn_adv.setAutoRaise(True)
        self.btn_adv.toggled.connect(self._toggle_adv)
        tl.addWidget(self.btn_adv)

        self.adv_box = QWidget()
        al = QVBoxLayout(self.adv_box)
        al.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("Metode:"))
        self.combo_engine = QComboBox()
        for e in ENGINES:
            self.combo_engine.addItem(e.name, e.id)
        self.combo_engine.currentIndexChanged.connect(self.on_engine_changed)
        row.addWidget(self.combo_engine, 1)
        self.btn_defaults = QPushButton("Reset parameter")
        self.btn_defaults.clicked.connect(lambda: self.current_panel().reset_defaults())
        row.addWidget(self.btn_defaults)
        al.addLayout(row)
        self.lbl_desc = QLabel()
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet("color: #666;")
        al.addWidget(self.lbl_desc)
        self.lbl_avail = QLabel()
        self.lbl_avail.setWordWrap(True)
        al.addWidget(self.lbl_avail)

        self.stack = QStackedWidget()
        for e in ENGINES:
            panel = OptionPanel(e, self.ctx.tools)
            panel.changed.connect(lambda: self._cache_timer.start())
            panel.changed.connect(self._on_params_changed)
            self.panels[e.id] = panel
            self.stack.addWidget(panel)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.stack)
        scroll.setMinimumHeight(220)
        # Ignored (vertikal): tinggi yang diminta hanya minimumnya, bukan tinggi isi panel; tetap
        # melebar bila ada ruang lebih. Tanpa ini panel atas selalu terlalu tinggi dan perlu digulir.
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        al.addWidget(scroll, 1)
        tl.addWidget(self.adv_box, 1)
        self._rebuild_profile_items()
        self._toggle_adv(False)

        # baris cache OCR
        self.cache_row = QWidget()
        cr = QHBoxLayout(self.cache_row)
        cr.setContentsMargins(0, 0, 0, 0)
        self.chk_cache = QCheckBox("Gunakan cache OCR")
        self.chk_cache.setChecked(True)
        self.chk_cache.setToolTip("Hasil OCR disimpan agar mengubah parameter ⚡ tidak mengulang OCR.\n"
                                  "Cache tidak dihapus otomatis; hapus lewat tombol di sini atau tab Dependensi & Cache.")
        self.lbl_cache = QLabel()
        self.lbl_cache.setStyleSheet("color: #555;")
        self.btn_del_cache = QPushButton("Hapus cache file ini")
        self.btn_del_cache.clicked.connect(self.delete_cache_current)
        cr.addWidget(self.chk_cache)
        cr.addWidget(self.lbl_cache, 1)
        cr.addWidget(self.btn_del_cache)
        tl.addWidget(self.cache_row)
        self.lbl_legend = QLabel("↻ = mengubah ini mengulang OCR   ·   ⚡ = tanpa OCR ulang")
        self.lbl_legend.setStyleSheet("color: #888; font-size: 11px;")
        tl.addWidget(self.lbl_legend)

        # bagian bawah
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        out = QHBoxLayout()
        out.addWidget(QLabel("Folder hasil:"))
        self.edit_out = QLineEdit()
        self.edit_out.setPlaceholderText("Kosong = sama dengan folder file sumber")
        btn_b = QPushButton("Browse")
        btn_b.clicked.connect(self.browse_out)
        out.addWidget(self.edit_out, 1)
        out.addWidget(btn_b)
        self.chk_guard = QCheckBox("Lewati bila tidak lebih kecil")
        self.chk_guard.setChecked(True)
        self.chk_guard.setToolTip("Hasil yang tidak lebih kecil dari file asli tidak disimpan (file asli sudah yang terbaik).\n"
                                  "Tidak berlaku untuk OCRmyPDF: hasilnya boleh sedikit lebih besar karena lapisan teks OCR.")
        out.addWidget(self.chk_guard)
        bl.addLayout(out)
        nm = QHBoxLayout()
        nm.addWidget(QLabel("Nama file:"))
        self.edit_tpl = QLineEdit("{nama}_{engine}")
        self.edit_tpl.setToolTip("{nama} = nama file sumber, {engine} = id metode. Ekstensi .pdf otomatis.")
        self.combo_policy = QComboBox()
        for v, t in POLICIES:
            self.combo_policy.addItem(t, v)
        nm.addWidget(self.edit_tpl, 1)
        nm.addWidget(QLabel("Jika sudah ada:"))
        nm.addWidget(self.combo_policy)
        bl.addLayout(nm)
        self.table = ResultTable()
        self.table.setMinimumHeight(90)
        bl.addWidget(self.table)
        self.console = LogConsole()
        self.console.setMinimumHeight(80)
        bl.addWidget(self.console, 1)
        self.pbar = QProgressBar()
        bl.addWidget(self.pbar)
        btns = QHBoxLayout()
        self.btn_run = QPushButton("MULAI PROSES KOMPRESI")
        self.btn_run.setFixedHeight(42)
        self.btn_run.setStyleSheet("font-weight: bold; background-color: #2c3e50; color: white;")
        self.btn_run.clicked.connect(self.start_process)
        self.btn_cancel = QPushButton("BATAL")
        self.btn_cancel.setFixedHeight(42)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_process)
        self.btn_open = QPushButton("Buka folder hasil")
        self.btn_open.setFixedHeight(42)
        self.btn_open.clicked.connect(self.open_results)
        btns.addWidget(self.btn_run, 3)
        btns.addWidget(self.btn_cancel, 1)
        btns.addWidget(self.btn_open, 1)
        bl.addLayout(btns)

        # Panel atas dibungkus area gulir: bila jendela/panel terlalu pendek untuk seluruh isinya
        # (mis. bagian lanjutan terbuka), muncul scrollbar - bukan widget yang saling menimpa.
        # (main.py menetapkan ukuran minimum jendela eksplisit sehingga Qt tidak otomatis
        # membesarkan jendela mengikuti isi.)
        top_scroll = QScrollArea()
        top_scroll.setWidgetResizable(True)
        top_scroll.setFrameShape(QFrame.NoFrame)
        top_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        top_scroll.setWidget(top)
        self.top_scroll = top_scroll
        split.addWidget(top_scroll)
        split.addWidget(bottom)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

    # ----------------------------------------------------------- state
    def current_engine(self):
        return get_engine(self.combo_engine.currentData())

    def current_panel(self) -> OptionPanel:
        return self.panels[self.combo_engine.currentData()]

    def _restore(self):
        s = self.ctx.settings
        for e in ENGINES:
            saved = s.get(f"engines.{e.id}")
            if isinstance(saved, dict):
                self.panels[e.id].set_values(saved)
        idx = self.combo_engine.findData(s.get("compressor.engine", "ghostscript"))
        self.combo_engine.setCurrentIndex(max(0, idx))
        self.edit_out.setText(s.get("compressor.out_dir", "") or "")
        self.edit_tpl.setText(s.get("compressor.template", "{nama}_{engine}") or "{nama}_{engine}")
        pi = self.combo_policy.findData(s.get("compressor.policy", "unik"))
        self.combo_policy.setCurrentIndex(max(0, pi))
        self.chk_cache.setChecked(bool(s.get("compressor.use_cache", True)))
        self.chk_guard.setChecked(bool(s.get("compressor.size_guard", True)))
        self.on_engine_changed()
        # Bagian lanjutan: ingat pilihan terakhir; bila pengaturan bukan profil mana pun, tampilkan.
        self.btn_adv.setChecked(bool(s.get("compressor.advanced_open", False)) or self._current_profile() is None)

    def save_state(self):
        s = self.ctx.settings
        for e in ENGINES:
            s.set(f"engines.{e.id}", self.panels[e.id].values(), save=False)
        s.set("compressor.engine", self.combo_engine.currentData(), save=False)
        s.set("compressor.out_dir", self.edit_out.text().strip() or None, save=False)
        s.set("compressor.template", self.edit_tpl.text().strip() or "{nama}_{engine}", save=False)
        s.set("compressor.policy", self.combo_policy.currentData(), save=False)
        s.set("compressor.use_cache", self.chk_cache.isChecked(), save=False)
        s.set("compressor.size_guard", self.chk_guard.isChecked(), save=False)
        s.set("compressor.advanced_open", self.btn_adv.isChecked(), save=False)
        s.save()

    # ------------------------------------------------------------ events
    def on_engine_changed(self, *_):
        e = self.current_engine()
        self.stack.setCurrentWidget(self.panels[e.id])
        self.lbl_desc.setText(e.description)
        for w in (self.cache_row, self.lbl_legend):
            w.setVisible(e.uses_ocr)
        self.refresh_availability()
        self._cache_timer.start()
        if not self._applying:
            self._sync_profile()

    def on_tools_changed(self):
        for p in self.panels.values():
            p.refresh_availability(self.ctx.tools)
        self.refresh_availability()
        self._rebuild_profile_items()
        self._sync_profile()
        self._cache_timer.start()

    def refresh_availability(self):
        e = self.current_engine()
        ok, missing = e.availability(self.ctx.tools)
        if ok:
            self.lbl_avail.setText("")
            self.lbl_avail.setVisible(False)
        else:
            self.lbl_avail.setVisible(True)
            self.lbl_avail.setText("<span style='color:#c62828'>Alat belum terpasang:</span><br>" +
                                   "<br>".join(m.replace("<", "&lt;") for m in missing) +
                                   "<br><i>Lihat tab 'Dependensi &amp; Cache'.</i>")
        self.btn_run.setEnabled(ok and self.runner is None)

    def update_cache_label(self):
        e = self.current_engine()
        if not e.uses_ocr:
            return
        path = self.files.current_path()
        if not path or not Path(path).exists():
            self.lbl_cache.setText("Tambahkan file untuk melihat status cache OCR.")
            self.btn_del_cache.setEnabled(False)
            return
        try:
            st = e.cache_status(Path(path), self.current_panel().values(), self.ctx.cache)
        except Exception as ex:  # noqa: BLE001
            st = None
            self.lbl_cache.setText(f"(status cache tidak tersedia: {ex})")
        if st is not None:
            self.lbl_cache.setText(st.text)
        self.btn_del_cache.setEnabled(True)

    def delete_cache_current(self):
        path = self.files.current_path()
        if not path:
            return
        if QMessageBox.question(self, "Hapus cache", f"Hapus semua cache OCR untuk:\n{Path(path).name}?") != QMessageBox.Yes:
            return
        n = self.ctx.cache.delete_for_file(self.ctx.cache.file_hash(path))
        self.console.append_line(f"Cache OCR dihapus ({n} entri) untuk {Path(path).name}.")
        self.update_cache_label()

    def _on_cleared(self):
        self.pbar.setValue(0)
        self.console.clear()
        self.table.setRowCount(0)

    def browse_out(self):
        d = QFileDialog.getExistingDirectory(self, "Pilih folder hasil")
        if d:
            self.edit_out.setText(d)

    def open_results(self):
        folder = self.edit_out.text().strip()
        if not folder:
            p = self.files.current_path()
            folder = str(Path(p).parent) if p else ""
        if folder:
            open_folder(folder)

    # ------------------------------------------------- Tujuan (profil)
    def _current_profile(self):
        """Profil yang nilainya sama persis dengan metode+parameter saat ini, atau None (Kustom)."""
        return self.ctx.profiles.match(self.combo_engine.currentData(), self.current_panel().values())

    def _rebuild_profile_items(self):
        cb = self.combo_profile
        cb.blockSignals(True)
        cb.clear()
        model = cb.model()

        def header(text):
            cb.addItem(text)
            it = model.item(cb.count() - 1)
            it.setFlags(Qt.NoItemFlags)           # judul grup: tidak bisa dipilih
            f = QFont()
            f.setBold(True)
            it.setFont(f)

        def add(p):
            ok, missing = get_engine(p.engine).availability(self.ctx.tools)
            cb.addItem(("★ " if not p.builtin else "") + p.name + ("" if ok else "  (butuh alat)"), p.id)
            it = model.item(cb.count() - 1)
            tip = f"{p.description}\nMetode: {engine_name(p.engine)}"
            if not ok:
                it.setEnabled(False)              # tetap tampil, disertai cara memasang alatnya
                tip += "\n\nAlat belum terpasang:\n" + "\n".join(m.replace("<", "&lt;") for m in missing)
            it.setToolTip(tip)

        profiles = self.ctx.profiles.all()
        for cat in ("scan", "digital", "ocr", "user"):
            group = [p for p in profiles if p.category == cat]
            if group:
                header(CATEGORY_LABELS[cat])
                for p in group:
                    add(p)
        cb.addItem("Kustom (atur manual)", CUSTOM_ID)
        cb.blockSignals(False)

    def _sync_profile(self):
        """Samakan tampilan Tujuan dengan metode+parameter yang sedang aktif."""
        prof = self._current_profile()
        idx = self.combo_profile.findData(prof.id if prof else CUSTOM_ID)
        self.combo_profile.blockSignals(True)
        self.combo_profile.setCurrentIndex(max(0, idx))
        self.combo_profile.blockSignals(False)
        if prof is not None:
            self.lbl_profile.setText(f"{prof.description}\nMetode: {engine_name(prof.engine)}")
        else:
            self.lbl_profile.setText(
                f"Pengaturan manual (Kustom). Metode: {self.current_engine().name}. Ubah nilainya di "
                f"'Metode & parameter'; simpan lewat 'Kelola' bila ingin dipakai lagi.")
        self.act_save.setEnabled(prof is None)
        self.act_delete.setEnabled(prof is not None and not prof.builtin)

    def _on_params_changed(self):
        if self._applying or self.sender() is not self.current_panel():
            return                                # bukan ulah pengguna / bukan panel yang sedang tampil
        self._sync_profile()

    def _on_profile_activated(self, index: int):
        pid = self.combo_profile.itemData(index)
        if not pid:
            self._sync_profile()
        elif pid == CUSTOM_ID:
            self.btn_adv.setChecked(True)         # memilih 'Kustom' = ingin mengatur sendiri
            self._sync_profile()
        else:
            self.apply_profile(pid)

    def apply_profile(self, pid: str) -> bool:
        """Terapkan profil: pilih metode + isi parameter. Nilai per-dokumen (mis. bahasa OCR)
        dipertahankan; parameter lain yang tidak disebut profil kembali ke bawaan metode."""
        prof = self.ctx.profiles.get(pid)
        if prof is None:
            return False
        panel = self.panels[prof.engine]
        self._applying = True
        try:
            self.combo_engine.setCurrentIndex(self.combo_engine.findData(prof.engine))
            panel.set_values(self.ctx.profiles.resolve(prof, panel.values()))
        finally:
            self._applying = False
        self._sync_profile()
        return True

    def _toggle_adv(self, on: bool):
        self.adv_box.setVisible(on)
        self.btn_adv.setText(("▾ " if on else "▸ ") + "Metode && parameter (lanjutan)")
        self._rebalance_expanded = on
        self._rebalance_timer.start()

    def _rebalance(self):
        """Saat bagian lanjutan dibuka, beri panel atas ruang sebesar mungkin (panel hasil di bawah
        cukup di tinggi minimumnya); saat dilipat, kembalikan ke proporsi awal. Pengguna tetap
        bisa menggeser pembatas secara manual."""
        expanded = self._rebalance_expanded
        total = sum(self._split.sizes())
        if total <= 0:
            return
        if expanded:
            bottom = self._split.widget(1).minimumSizeHint().height()
            self._split.setSizes([max(0, total - bottom), bottom])
        else:
            top = int(total * 0.6)
            self._split.setSizes([top, total - top])

    def save_profile_dialog(self):
        e, vals, store = self.current_engine(), self.current_panel().values(), self.ctx.profiles
        name, ok = QInputDialog.getText(self, "Simpan profil", "Nama profil:")
        if not ok:
            return
        try:
            try:
                prof = store.save_user(name, e.id, vals)
            except ProfileError:
                same = store.find_by_name(name)
                if same is not None and not same.builtin and QMessageBox.question(
                        self, "Timpa profil",
                        f"Profil '{same.name}' sudah ada. Timpa dengan pengaturan saat ini?") == QMessageBox.Yes:
                    prof = store.save_user(name, e.id, vals, overwrite=True)
                else:
                    raise
        except ProfileError as ex:
            QMessageBox.warning(self, "Profil tidak disimpan", str(ex))
            return
        self._rebuild_profile_items()
        self._sync_profile()
        self.console.append_line(f"Profil '{prof.name}' disimpan.")

    def delete_profile_dialog(self):
        prof = self._current_profile()
        if prof is None or prof.builtin:
            return
        if QMessageBox.question(self, "Hapus profil", f"Hapus profil '{prof.name}'?") != QMessageBox.Yes:
            return
        self.ctx.profiles.delete_user(prof.id)
        self._rebuild_profile_items()
        self._sync_profile()
        self.console.append_line(f"Profil '{prof.name}' dihapus. Pengaturan saat ini tetap dipakai (Kustom).")

    def export_profiles_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, "Ekspor profil", "profil-kompresi.json",
                                              "Profil kompresi (*.json)")
        if not path:
            return
        try:
            n = self.ctx.profiles.export_user(path)
        except ProfileError as ex:
            QMessageBox.warning(self, "Ekspor gagal", str(ex))
            return
        QMessageBox.information(self, "Ekspor selesai", f"{n} profil ditulis ke:\n{path}")

    def import_profiles_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Impor profil", "", "Profil kompresi (*.json)")
        if not path:
            return
        try:
            rep = self.ctx.profiles.import_file(path)
        except ProfileError as ex:
            QMessageBox.warning(self, "Impor gagal", str(ex))
            return
        self._rebuild_profile_items()
        self._sync_profile()
        (QMessageBox.information if rep.added else QMessageBox.warning)(self, "Hasil impor", rep.summary())

    # ---------------------------------------------------------------- run
    def start_process(self):
        files = self.files.files()
        if not files:
            QMessageBox.information(self, "Info", "Tambahkan file PDF terlebih dahulu.")
            return
        engine = self.current_engine()
        ok, _ = engine.availability(self.ctx.tools)
        if not ok:
            self.refresh_availability()
            return
        values = engine.options.normalize(self.current_panel().values())
        self.save_state()
        cfg = OutputConfig(self.edit_out.text().strip() or None, self.edit_tpl.text().strip(),
                           self.combo_policy.currentData())
        prof = self._current_profile()
        self.console.append_line(f"Tujuan: {prof.name if prof else 'Kustom'}  ·  Metode: {engine.name}")
        self.table.start(files)
        self.pbar.setValue(0)
        self._set_running(True)
        self.runner = JobRunner(engine, values, files, cfg, self.ctx.tools, self.ctx.cache,
                                use_cache=self.chk_cache.isChecked() and engine.uses_ocr,
                                size_guard=self.chk_guard.isChecked())
        self.runner.log.connect(self.console.append_line)
        self.runner.overall.connect(self.pbar.setValue)
        self.runner.file_started.connect(self.table.mark_running)
        self.runner.file_done.connect(self.table.update_result)
        self.runner.all_done.connect(self.on_all_done)
        self.runner.start()

    def cancel_process(self):
        if self.runner:
            self.runner.cancel()
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText("Membatalkan…")

    def on_all_done(self, summary: dict):
        runner, self.runner = self.runner, None
        if runner is not None:
            runner.wait(10000)          # pastikan thread benar-benar selesai sebelum dilepas
            runner.deleteLater()
        self._set_running(False)
        self.btn_cancel.setText("BATAL")
        self.refresh_availability()
        self._cache_timer.start()
        msg = f"Selesai: {summary['ok']} berhasil, {summary['failed']} gagal"
        if summary["skipped"]:
            msg += f", {summary['skipped']} dilewati"
        if summary.get("not_smaller"):
            msg += f", {summary['not_smaller']} tidak dikecilkan (tidak disimpan)"
        if summary["cancelled"]:
            msg = "Dibatalkan. " + msg
        self.console.append_line(msg)
        QMessageBox.information(self, "Selesai", msg)

    def _set_running(self, running: bool):
        self.btn_run.setEnabled(not running)
        self.btn_cancel.setEnabled(running)
        self.files.set_enabled_controls(not running)
        self.combo_engine.setEnabled(not running)
        self.combo_profile.setEnabled(not running)
        self.btn_manage.setEnabled(not running)
        self.stack.setEnabled(not running)

    def is_busy(self) -> bool:
        return self.runner is not None and self.runner.isRunning()

    def abort_and_wait(self):
        if self.runner:
            self.runner.cancel()
            self.runner.wait(20000)

    # ------------------------------------------------------- drag & drop
    def dragEnterEvent(self, event):
        self.files.accept_drag(event)

    def dropEvent(self, event):
        self.files.handle_drop(event)
