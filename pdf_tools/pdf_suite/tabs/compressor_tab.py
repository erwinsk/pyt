# -*- coding: utf-8 -*-
"""Tab Kompres. Tata letak horizontal: antrean file di kiri, pengaturan (kartu) di kanan, log laci di footer.

Tiga tingkat pilihan tetap sama:
  1. Tujuan   — profil siap pakai (combo teratas; bisa disimpan/diekspor/diimpor)
  2. Metode   — Ghostscript / Full Image / OCRmyPDF / MRC
  3. Parameter— panel opsi lengkap tiap metode
Tingkat 2-3 ada di bagian 'lanjutan' yang bisa dilipat. Ketiganya selalu konsisten: mengubah
metode/parameter membuat Tujuan berpindah ke 'Kustom' (atau profil lain bila nilainya sama)."""
import html
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtWidgets import (QAction, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                             QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QProgressBar, QPushButton,
                             QScrollArea, QShortcut, QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout,
                             QWidget)

from core.engines import ENGINES, get_engine
from core.profiles import CATEGORY_LABELS, CUSTOM_ID, ProfileError, engine_name
from core.runner import JobRunner, OutputConfig
from widgets.common import WrapLabel, ShrinkCheck, fit_popup, make_shrinkable, open_folder, side_width
from widgets.log_console import ElidedLabel, LogDrawer
from widgets.option_panel import OptionPanel
from widgets.queue import CompressTable, QueuePanel

POLICIES = [("unik", "Buat nama unik (_2, _3 …)"), ("timpa", "Timpa file lama"), ("lewati", "Lewati")]


class CompressorTab(QWidget):
    request_deps = pyqtSignal()        # pengguna minta dialog Dependensi (mis. dari pesan alat belum terpasang)

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
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setSingleShot(True)
        self._reveal_timer.setInterval(30)
        self._reveal_timer.timeout.connect(self._reveal_adv)
        self._build()
        self._restore()
        self.ctx.tools_changed.connect(self.on_tools_changed)

    # ------------------------------------------------------------------ UI
    @staticmethod
    def _card(title: str = ""):
        f = QFrame()
        f.setObjectName("card")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)
        if title:
            t = QLabel(title.upper())
            t.setObjectName("cardTitle")
            lay.addWidget(t)
        return f, lay

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(10)
        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body, 1)

        # ================= KIRI: antrean (daftar file + hasil dalam satu tabel) =================
        self.table = CompressTable()
        self.files = QueuePanel(self.table)
        self.files.current_changed.connect(lambda _p: self._cache_timer.start())
        self.files.changed.connect(lambda: self._cache_timer.start())
        self.files.cleared.connect(self._on_cleared)
        body.addWidget(self.files, 1)

        # ================= KANAN: pengaturan (kartu), bisa digulir =================
        self.right_scroll = QScrollArea()
        self.right_scroll.setObjectName("rightScroll")
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setFrameShape(QFrame.NoFrame)
        self.right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.right_scroll.setFixedWidth(side_width(1060))   # disesuaikan di resizeEvent
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 6, 0)
        rl.setSpacing(10)
        self.right_scroll.setWidget(right)
        body.addWidget(self.right_scroll)

        # Pesan alat belum terpasang: SELALU terlihat di sini (tidak ikut terlipat), lengkap dengan tautan.
        self.lbl_avail = WrapLabel()
        self.lbl_avail.setObjectName("banner")
        self.lbl_avail.setTextFormat(Qt.RichText)
        self.lbl_avail.linkActivated.connect(lambda _l: self.request_deps.emit())
        self.lbl_avail.setVisible(False)
        rl.addWidget(self.lbl_avail)

        # ---- Tingkat 1: Tujuan (profil) ----
        c_goal, gl = self._card("Tujuan")
        prow = QHBoxLayout()
        prow.setSpacing(6)
        self.combo_profile = QComboBox()
        make_shrinkable(self.combo_profile, 6)
        self.combo_profile.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
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
        gl.addLayout(prow)
        self.lbl_profile = WrapLabel()
        self.lbl_profile.setObjectName("hint")
        self.lbl_profile.setTextFormat(Qt.PlainText)
        gl.addWidget(self.lbl_profile)
        rl.addWidget(c_goal)

        # ---- Keluaran (ringkas) ----
        c_out, ol = self._card("Keluaran")
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(8)
        g.setColumnStretch(1, 1)
        g.addWidget(QLabel("Folder"), 0, 0)
        self.edit_out = QLineEdit()
        self.edit_out.setPlaceholderText("Kosong = folder file sumber")
        self.edit_out.setToolTip("Folder tujuan hasil. Kosong = sama dengan folder file sumber.")
        btn_b = QPushButton("…")
        btn_b.setToolTip("Pilih folder hasil")
        btn_b.setFixedWidth(38)
        btn_b.clicked.connect(self.browse_out)
        g.addWidget(self.edit_out, 0, 1)
        g.addWidget(btn_b, 0, 2)
        g.addWidget(QLabel("Nama"), 1, 0)
        self.edit_tpl = QLineEdit("{nama}_{engine}")
        self.edit_tpl.setToolTip("{nama} = nama file sumber, {engine} = id metode. Ekstensi .pdf otomatis.")
        g.addWidget(self.edit_tpl, 1, 1, 1, 2)
        g.addWidget(QLabel("Jika ada"), 2, 0)
        self.combo_policy = QComboBox()
        self.combo_policy.setToolTip("Tindakan bila file hasil dengan nama yang sama sudah ada.")
        for v, t in POLICIES:
            self.combo_policy.addItem(t, v)
        make_shrinkable(self.combo_policy, 6)
        g.addWidget(self.combo_policy, 2, 1, 1, 2)
        ol.addLayout(g)
        self.chk_guard = ShrinkCheck("Lewati bila tidak lebih kecil")
        self.chk_guard.setChecked(True)
        self.chk_guard.setToolTip("Hasil yang tidak lebih kecil dari file asli tidak disimpan (file asli sudah yang terbaik).\n"
                                  "Tidak berlaku untuk OCRmyPDF: hasilnya boleh sedikit lebih besar karena lapisan teks OCR.")
        ol.addWidget(self.chk_guard)
        rl.addWidget(c_out)

        # ---- Cache OCR (hanya untuk metode ber-OCR) ----
        self.cache_row, cl = self._card("Cache OCR")
        self.chk_cache = ShrinkCheck("Gunakan cache OCR")
        self.chk_cache.setChecked(True)
        self.chk_cache.setToolTip("Hasil OCR disimpan agar mengubah parameter ⚡ tidak mengulang OCR.\n"
                                  "Cache tidak dihapus otomatis; hapus lewat tombol di sini atau dialog Dependensi dan cache (ikon ⚙).")
        cl.addWidget(self.chk_cache)
        crow = QHBoxLayout()
        crow.setSpacing(8)
        self.lbl_cache = WrapLabel()
        self.lbl_cache.setObjectName("hint")
        self.btn_del_cache = QPushButton("Hapus cache file ini")
        self.btn_del_cache.clicked.connect(self.delete_cache_current)
        crow.addWidget(self.lbl_cache, 1)
        crow.addWidget(self.btn_del_cache, 0, Qt.AlignTop)
        cl.addLayout(crow)
        rl.addWidget(self.cache_row)

        # ---- Tingkat 2 + 3: Metode & Parameter (bisa dilipat) ----
        self.btn_adv = QPushButton()
        self.btn_adv.setObjectName("link")
        self.btn_adv.setCheckable(True)
        self.btn_adv.toggled.connect(self._toggle_adv)
        rl.addWidget(self.btn_adv)

        self.adv_box, al = self._card("Metode")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.combo_engine = QComboBox()
        for e in ENGINES:
            self.combo_engine.addItem(e.name, e.id)
        make_shrinkable(self.combo_engine, 6)
        self.combo_engine.currentIndexChanged.connect(self.on_engine_changed)
        row.addWidget(self.combo_engine, 1)
        self.btn_defaults = QPushButton("Reset")
        self.btn_defaults.setToolTip("Kembalikan parameter metode ini ke nilai bawaan")
        self.btn_defaults.clicked.connect(lambda: self.current_panel().reset_defaults())
        row.addWidget(self.btn_defaults)
        al.addLayout(row)
        self.lbl_desc = WrapLabel()
        self.lbl_desc.setObjectName("hint")
        al.addWidget(self.lbl_desc)
        self.lbl_legend = WrapLabel("↻ = mengubah ini mengulang OCR   ·   ⚡ = tanpa OCR ulang")
        self.lbl_legend.setObjectName("hint")
        al.addWidget(self.lbl_legend)

        self.stack = QStackedWidget()
        for e in ENGINES:
            panel = OptionPanel(e, self.ctx.tools)
            panel.changed.connect(lambda: self._cache_timer.start())
            panel.changed.connect(self._on_params_changed)
            self.panels[e.id] = panel
            self.stack.addWidget(panel)
        al.addWidget(self.stack)
        rl.addWidget(self.adv_box)
        rl.addStretch(1)
        self._rebuild_profile_items()
        self._toggle_adv(False)

        # ================= FOOTER: progres + aksi =================
        foot = QHBoxLayout()
        foot.setSpacing(10)
        self.btn_open = QPushButton("Buka folder hasil")
        self.btn_open.clicked.connect(self.open_results)
        self.pbar = QProgressBar()
        self.pbar.setTextVisible(False)
        self.pbar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.lbl_status = ElidedLabel("Siap")
        self.lbl_status.setObjectName("statusText")
        self.btn_cancel = QPushButton("Batal")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_process)
        self.btn_run = QPushButton("Mulai kompres")
        self.btn_run.setObjectName("primary")
        self.btn_run.setToolTip("Mulai proses (Ctrl+Enter)")
        self.btn_run.clicked.connect(self.start_process)
        for b in (self.btn_open, self.btn_cancel, self.btn_run):
            b.setMinimumHeight(34)
        mid = QVBoxLayout()          # status di atas progres: hemat lebar, tidak saling menimpa
        mid.setSpacing(5)
        mid.addWidget(self.lbl_status)
        mid.addWidget(self.pbar)
        foot.addWidget(self.btn_open)
        foot.addSpacing(4)
        foot.addLayout(mid, 1)
        foot.addWidget(self.btn_cancel)
        foot.addWidget(self.btn_run)
        root.addLayout(foot)
        self.pbar.valueChanged.connect(self._on_progress)

        # ================= LOG: laci satu baris =================
        self.drawer = LogDrawer()
        self.console = self.drawer.console
        root.addWidget(self.drawer)

        # pintasan papan ketik
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.files.manual_add)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._shortcut_run)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._shortcut_run)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.drawer.toggle)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.right_scroll.setFixedWidth(side_width(self.width()))

    def _shortcut_run(self):
        if self.btn_run.isEnabled():
            self.start_process()

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
        self.table.set_cache_column_visible(e.uses_ocr)
        self._fit_stack()
        self.refresh_availability()
        self._cache_timer.start()
        if not self._applying:
            self._sync_profile()

    def _fit_stack(self):
        """Tinggi tumpukan panel = tinggi panel yang tampil, bukan yang tertinggi di antara semua metode."""
        cur = self.panels[self.combo_engine.currentData()]
        for p in self.panels.values():
            p.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred if p is cur else QSizePolicy.Ignored)
        self.stack.updateGeometry()

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
            self.lbl_avail.setText("<b>Alat belum terpasang:</b><br>" +
                                   "<br>".join(html.escape(m, quote=False) for m in missing) +
                                   "<br><a href='deps'>Buka Dependensi</a> untuk melihat cara memasangnya.")
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
        self.lbl_status.set_full_text("Siap")

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
        fit_popup(cb)

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
        if on:
            self._reveal_timer.start()      # gulir kolom kanan agar bagian yang baru dibuka terlihat

    def _reveal_adv(self):
        bar = self.right_scroll.verticalScrollBar()
        bar.setValue(max(0, self.btn_adv.y() - 6))

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
        self.lbl_status.set_full_text("Memproses… 0%")
        self._set_running(True)
        self.runner = JobRunner(engine, values, files, cfg, self.ctx.tools, self.ctx.cache,
                                use_cache=self.chk_cache.isChecked() and engine.uses_ocr,
                                size_guard=self.chk_guard.isChecked())
        self.runner.log.connect(self.console.append_line)
        self.runner.overall.connect(self.pbar.setValue)
        self.runner.file_started.connect(self.table.mark_running)
        self.runner.file_done.connect(self._on_file_done)
        self.runner.all_done.connect(self.on_all_done)
        self.runner.start()

    def _on_file_done(self, r: int, res: dict):
        self.table.update_result(r, res)
        if res.get("status") == "gagal":
            self.drawer.set_open(True)       # galat: laci log terbuka otomatis

    def _on_progress(self, v: int):
        if self.runner is not None:
            self.lbl_status.set_full_text(f"Memproses… {v}%")

    def cancel_process(self):
        if self.runner:
            self.runner.cancel()
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText("Membatalkan…")
            self.lbl_status.set_full_text("Membatalkan…")

    def on_all_done(self, summary: dict):
        runner, self.runner = self.runner, None
        if runner is not None:
            runner.wait(10000)          # pastikan thread benar-benar selesai sebelum dilepas
            runner.deleteLater()
        self._set_running(False)
        self.btn_cancel.setText("Batal")
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
        self.lbl_status.set_full_text(msg)
        if summary["failed"]:
            self.drawer.set_open(True)
        QMessageBox.information(self, "Selesai", msg)

    def _set_running(self, running: bool):
        self.btn_run.setEnabled(not running)
        self.btn_cancel.setEnabled(running)
        self.files.set_enabled_controls(not running)
        self.combo_engine.setEnabled(not running)
        self.combo_profile.setEnabled(not running)
        self.btn_manage.setEnabled(not running)
        self.stack.setEnabled(not running)
        self.btn_defaults.setEnabled(not running)

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
