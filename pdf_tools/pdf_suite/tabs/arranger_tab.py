# -*- coding: utf-8 -*-
"""Tab 'Atur Halaman' (gaya PDF Arranger): gabung / pisah PDF, impor gambar jadi halaman PDF,
putar, ubah ukuran halaman, urutkan (seret), duplikat, sisip halaman kosong, undo/redo.

Model: daftar halaman (QListWidget) yang masing-masing menunjuk satu `core.arranger.PageRef`.
Semua perubahan lewat `_mutate`, sehingga undo/redo selalu konsisten. Penyimpanan dan pembuatan
thumbnail berjalan di thread terpisah agar UI tidak membeku.
"""
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QIcon, QImage, QKeySequence
from PyQt5.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
                             QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidgetItem, QMenu, QMessageBox,
                             QProgressBar, QPushButton, QScrollArea, QShortcut, QSizePolicy, QSpinBox,
                             QToolButton, QVBoxLayout, QWidget)

from core import arranger as A
from widgets.arranger_dialogs import PageSizeDialog, PreviewDialog
from widgets.common import ShrinkCheck, WrapLabel, make_shrinkable, open_folder, side_width
from widgets.log_console import ElidedLabel, LogDrawer
from widgets.page_list import PageList, compose_icon

THUMB_H = 240                       # tinggi render thumbnail (px); ukuran tampil diatur tombol zoom
ZOOM_LEVELS = (80, 100, 120, 140, 170, 200, 240)      # sisi thumbnail (px); 140 = 100%
ZOOM_DEFAULT = 3
UNDO_LIMIT = 60
_IMG = " ".join("*" + e for e in sorted(A.IMAGE_EXTS))
FILE_FILTER = f"PDF dan gambar (*.pdf {_IMG});;PDF (*.pdf);;Gambar ({_IMG})"


class ThumbWorker(QThread):
    """Render thumbnail halaman sumber di latar belakang."""
    ready = pyqtSignal(int, int, QImage)

    def __init__(self, batch: List[Tuple[A.Source, List[int]]]):
        super().__init__()
        self.batch = batch
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        for src, idxs in self.batch:
            if self._stop:
                return
            try:
                doc = A.open_source(src)
            except Exception:
                continue
            try:
                for i in idxs:
                    if self._stop:
                        return
                    try:
                        w, h, rgb = A.render_thumb(doc, i, THUMB_H)
                    except Exception:
                        continue
                    self.ready.emit(src.id, i, QImage(rgb, w, h, w * 3, QImage.Format_RGB888).copy())
            finally:
                doc.close()


class BuildThread(QThread):
    progress = pyqtSignal(int, int)
    file_done = pyqtSignal(str)
    finished_ok = pyqtSignal(list)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, jobs, sources: Dict[int, A.Source], optimize: bool):
        super().__init__()
        self.jobs, self.sources, self.optimize = jobs, sources, optimize
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            outs = A.run_jobs(self.jobs, self.sources, optimize=self.optimize,
                              progress=lambda d, t: self.progress.emit(d, t),
                              is_cancelled=lambda: self._cancel, on_file=self.file_done.emit)
        except A.Cancelled:
            self.cancelled.emit()
            return
        except Exception as e:
            self.failed.emit(str(e))
            return
        self.finished_ok.emit(outs)


class ArrangerTab(QWidget):
    def __init__(self, ctx=None):
        super().__init__()
        self.ctx = ctx
        self.setAcceptDrops(True)
        self.sources: Dict[int, A.Source] = {}
        self.refs: Dict[int, A.PageRef] = {}
        self.thumbs: Dict[Tuple[int, int], QImage] = {}
        self._next_src = 1
        self._next_uid = 1
        self._undo: List[List[A.PageRef]] = []
        self._redo: List[List[A.PageRef]] = []
        self._pending_snap: Optional[List[A.PageRef]] = None
        self._workers: List[ThumbWorker] = []
        self._pending_thumbs = set()
        self._job: Optional[BuildThread] = None
        self._busy = False
        self._last_dir = ""
        # Timer milik widget (ikut terhapus bersama widget; aman saat jendela ditutup)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(80)
        self._thumb_timer.timeout.connect(self._flush_thumbs)
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.setInterval(120)
        self._zoom_timer.timeout.connect(self._apply_zoom)
        self._build()
        self._update_state()

    # ============================================================================== UI
    @staticmethod
    def _card(title: str):
        f = QFrame()
        f.setObjectName("card")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)
        t = QLabel(title.upper())
        t.setObjectName("cardTitle")
        lay.addWidget(t)
        return f, lay

    def _tbtn(self, text, tip, slot, width=None):
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setObjectName("tool")
        b.setFocusPolicy(Qt.NoFocus)             # fokus tetap di daftar halaman -> pintasan papan ketik tetap berlaku
        b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)     # teks tombol tidak pernah terpotong
        b.clicked.connect(lambda _c=False: slot())
        return b

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(10)
        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body, 1)

        # ===================== KIRI: bilah alat + daftar halaman =====================
        left = QVBoxLayout()
        left.setSpacing(8)
        self.toolbar = QWidget()
        tb = QHBoxLayout(self.toolbar)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(6)
        self.btn_add = self._tbtn("＋ Tambah", "Tambah PDF atau gambar (Ctrl+O). Bisa juga diseret ke jendela ini.", self.add_dialog)
        self.btn_rot_l = self._tbtn("⟲", "Putar 90° berlawanan jarum jam (Ctrl+Shift+R)", lambda: self.rotate(-90))
        self.btn_rot_r = self._tbtn("⟳", "Putar 90° searah jarum jam (Ctrl+R)", lambda: self.rotate(90))
        self.btn_del = self._tbtn("Hapus", "Hapus halaman terpilih (Del)", self.delete_selected)
        self.btn_size = self._tbtn("Ukuran…", "Ubah ukuran halaman (A4, Letter, kustom, …)", self.resize_dialog)
        self.btn_more = QToolButton()
        self.btn_more.setObjectName("tool")
        self.btn_more.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_more.setText("Lainnya ▾")
        self.btn_more.setPopupMode(QToolButton.InstantPopup)
        self.btn_more.setFocusPolicy(Qt.NoFocus)
        menu = QMenu(self.btn_more)
        self.act_dup = menu.addAction("Duplikat halaman terpilih\tCtrl+D", self.duplicate)
        self.act_blank = menu.addAction("Sisipkan halaman kosong", self.insert_blank)
        menu.addSeparator()
        self.act_left = menu.addAction("Geser terpilih ke kiri\tAlt+←", lambda: self.shift(-1))
        self.act_right = menu.addAction("Geser terpilih ke kanan\tAlt+→", lambda: self.shift(1))
        self.act_all = menu.addAction("Pilih semua\tCtrl+A", lambda: self.list.selectAll())
        self.act_first = menu.addAction("Pindahkan terpilih ke awal", lambda: self.move_edge(True))
        self.act_last = menu.addAction("Pindahkan terpilih ke akhir", lambda: self.move_edge(False))
        self.act_reverse = menu.addAction("Balik urutan semua halaman", self.reverse_all)
        menu.addSeparator()
        self.act_reset = menu.addAction("Kembalikan putaran dan ukuran asli (terpilih)", self.reset_selected)
        self.act_clear = menu.addAction("Hapus semua halaman", self.clear_all)
        self.btn_more.setMenu(menu)
        self.btn_undo = self._tbtn("↶", "Urungkan (Ctrl+Z)", self.undo)
        self.btn_redo = self._tbtn("↷", "Ulangi (Ctrl+Y)", self.redo)
        for w in (self.btn_add, self.btn_rot_l, self.btn_rot_r, self.btn_del,
                  self.btn_size, self.btn_more):
            tb.addWidget(w)
        tb.addStretch(1)
        tb.addWidget(self.btn_undo)
        tb.addWidget(self.btn_redo)
        left.addWidget(self.toolbar)

        self.list = PageList()
        self.list.files_dropped.connect(self.add_paths)
        self.list.about_to_reorder.connect(lambda: setattr(self, "_pending_snap", self._snapshot()))
        self.list.reordered.connect(self._on_reordered)
        self.list.itemSelectionChanged.connect(self._update_state)
        self.list.itemDoubleClicked.connect(self._open_preview)
        left.addWidget(self.list, 1)

        info = QHBoxLayout()
        self.lbl_count = QLabel()
        self.lbl_count.setObjectName("statusText")
        self.btn_zoom_out = self._tbtn("−", "Perkecil thumbnail (Ctrl+−, atau Ctrl + roda mouse)", lambda: self.zoom_step(-1))
        self.btn_zoom_in = self._tbtn("+", "Perbesar thumbnail (Ctrl++, atau Ctrl + roda mouse)", lambda: self.zoom_step(1))
        self.lbl_zoom = QLabel()
        self.lbl_zoom.setObjectName("statusText")
        self.lbl_zoom.setAlignment(Qt.AlignCenter)
        self.lbl_zoom.setMinimumWidth(48)
        info.addWidget(self.lbl_count, 1)
        info.addWidget(self.btn_zoom_out)
        info.addWidget(self.lbl_zoom)
        info.addWidget(self.btn_zoom_in)
        self._zoom_idx = ZOOM_DEFAULT
        self._sync_zoom_ui()
        self.list.zoom_requested.connect(self.zoom_step)
        left.addLayout(info)
        body.addLayout(left, 1)

        # ===================== KANAN: kartu keluaran =====================
        self.right_scroll = QScrollArea()
        self.right_scroll.setObjectName("rightScroll")
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setFrameShape(QFrame.NoFrame)
        self.right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.right_scroll.setFixedWidth(side_width(1100))
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 6, 0)
        rl.setSpacing(10)
        self.right_scroll.setWidget(right)
        body.addWidget(self.right_scroll)

        # ---- gabung: simpan sebagai satu PDF ----
        c_save, sl = self._card("Simpan sebagai satu PDF")
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(8)
        g.setColumnStretch(1, 1)
        g.addWidget(QLabel("File"), 0, 0)
        self.edit_out = QLineEdit()
        self.edit_out.setPlaceholderText("Kosong = tanya saat menyimpan")
        btn_b = QPushButton("…")
        btn_b.setFixedWidth(38)
        btn_b.setToolTip("Pilih nama dan lokasi file hasil")
        btn_b.clicked.connect(self.browse_out)
        g.addWidget(self.edit_out, 0, 1)
        g.addWidget(btn_b, 0, 2)
        sl.addLayout(g)
        self.chk_sel = ShrinkCheck("Hanya halaman terpilih")
        self.chk_opt = ShrinkCheck("Optimalkan ukuran file")
        self.chk_opt.setChecked(True)
        self.chk_opt.setToolTip("Membuang objek yang tak terpakai dan memadatkan struktur PDF hasil. Tidak mengubah tampilan halaman.")
        sl.addWidget(self.chk_sel)
        sl.addWidget(self.chk_opt)
        self.btn_save = QPushButton("Simpan PDF")
        self.btn_save.setObjectName("primary")
        self.btn_save.setToolTip("Gabungkan semua halaman sesuai urutan jadi satu PDF (Ctrl+S)")
        self.btn_save.clicked.connect(self.save_pdf)
        sl.addWidget(self.btn_save)
        rl.addWidget(c_save)

        # ---- pisah ----
        c_split, pl = self._card("Pisahkan jadi beberapa PDF")
        self.combo_mode = QComboBox()
        for v, t in (("each", "Setiap halaman jadi 1 file"), ("every", "Setiap N halaman"),
                     ("ranges", "Rentang halaman kustom"), ("source", "Per file sumber")):
            self.combo_mode.addItem(t, v)
        make_shrinkable(self.combo_mode, 8)
        self.combo_mode.currentIndexChanged.connect(self._sync_split)
        pl.addWidget(self.combo_mode)
        self.row_every = QWidget()
        re_ = QHBoxLayout(self.row_every)
        re_.setContentsMargins(0, 0, 0, 0)
        re_.addWidget(QLabel("Tiap"))
        self.spin_n = QSpinBox()
        self.spin_n.setRange(1, 100000)
        self.spin_n.setValue(2)
        re_.addWidget(self.spin_n, 1)
        re_.addWidget(QLabel("halaman"))
        pl.addWidget(self.row_every)
        self.edit_ranges = QLineEdit()
        self.edit_ranges.setPlaceholderText("mis. 1-3, 4, 5-8, 9-")
        self.edit_ranges.setToolTip("Nomor halaman mengikuti urutan saat ini di daftar. Tiap rentang jadi satu file.")
        pl.addWidget(self.edit_ranges)
        g2 = QGridLayout()
        g2.setHorizontalSpacing(8)
        g2.setVerticalSpacing(8)
        g2.setColumnStretch(1, 1)
        g2.addWidget(QLabel("Folder"), 0, 0)
        self.edit_dir = QLineEdit()
        self.edit_dir.setPlaceholderText("Kosong = folder file sumber")
        btn_d = QPushButton("…")
        btn_d.setFixedWidth(38)
        btn_d.setToolTip("Pilih folder hasil")
        btn_d.clicked.connect(self.browse_dir)
        g2.addWidget(self.edit_dir, 0, 1)
        g2.addWidget(btn_d, 0, 2)
        g2.addWidget(QLabel("Nama"), 1, 0)
        self.edit_tpl = QLineEdit("{nama}_{n}")
        self.edit_tpl.setToolTip("{nama} = nama file sumber pertama, {n} = nomor urut, {awal}/{akhir} = posisi halaman. "
                                 "Nama yang sudah ada tidak pernah ditimpa (diberi _2, _3 …).")
        g2.addWidget(self.edit_tpl, 1, 1, 1, 2)
        pl.addLayout(g2)
        self.chk_split_sel = ShrinkCheck("Hanya halaman terpilih")
        pl.addWidget(self.chk_split_sel)
        self.btn_split = QPushButton("Pisahkan")
        self.btn_split.setToolTip("Pembagian mengikuti urutan, putaran, dan ukuran halaman saat ini")
        self.btn_split.clicked.connect(self.split_pages)
        pl.addWidget(self.btn_split)
        rl.addWidget(c_split)

        # ---- impor gambar ----
        c_img, il = self._card("Impor gambar")
        g3 = QGridLayout()
        g3.setHorizontalSpacing(8)
        g3.setVerticalSpacing(8)
        g3.setColumnStretch(1, 1)
        g3.addWidget(QLabel("Halaman"), 0, 0)
        self.combo_img = QComboBox()
        self.combo_img.addItem("Sesuai ukuran gambar", None)
        for n in ("A4", "Letter", "A5", "A3"):
            self.combo_img.addItem(n, n)
        self.combo_img.setCurrentIndex(self.combo_img.findData("A4"))
        make_shrinkable(self.combo_img, 8)
        g3.addWidget(self.combo_img, 0, 1)
        g3.addWidget(QLabel("Margin"), 1, 0)
        self.spin_img_margin = QDoubleSpinBox()
        self.spin_img_margin.setRange(0, 100)
        self.spin_img_margin.setDecimals(1)
        self.spin_img_margin.setSuffix(" mm")
        g3.addWidget(self.spin_img_margin, 1, 1)
        il.addLayout(g3)
        h = WrapLabel("Berlaku untuk gambar yang ditambahkan berikutnya. Orientasi mengikuti gambar; foto "
                      "diputar sesuai EXIF. JPEG/PNG disisipkan tanpa kompresi ulang.")
        h.setObjectName("hint")
        il.addWidget(h)
        rl.addWidget(c_img)
        rl.addStretch(1)
        self._sync_split()

        # ===================== FOOTER =====================
        foot = QHBoxLayout()
        foot.setSpacing(10)
        self.btn_open = QPushButton("Buka folder hasil")
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self.open_results)
        self.pbar = QProgressBar()
        self.pbar.setTextVisible(False)
        self.pbar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.lbl_status = ElidedLabel("Siap")
        self.lbl_status.setObjectName("statusText")
        self.btn_cancel = QPushButton("Batal")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_job)
        for b in (self.btn_open, self.btn_cancel):
            b.setMinimumHeight(34)
        mid = QVBoxLayout()
        mid.setSpacing(5)
        mid.addWidget(self.lbl_status)
        mid.addWidget(self.pbar)
        foot.addWidget(self.btn_open)
        foot.addSpacing(4)
        foot.addLayout(mid, 1)
        foot.addWidget(self.btn_cancel)
        root.addLayout(foot)

        self.drawer = LogDrawer()
        self.console = self.drawer.console
        root.addWidget(self.drawer)

        # pintasan: yang memengaruhi halaman hanya aktif saat daftar halaman difokus (tidak bentrok dengan kolom teks)
        for key, slot in (("Delete", self.delete_selected), ("Ctrl+D", self.duplicate),
                          ("Ctrl+R", lambda: self.rotate(90)), ("Ctrl+Shift+R", lambda: self.rotate(-90)),
                          ("Alt+Left", lambda: self.shift(-1)), ("Alt+Right", lambda: self.shift(1)),
                          ("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo),
                          ("Ctrl++", lambda: self.zoom_step(1)), ("Ctrl+=", lambda: self.zoom_step(1)),
                          ("Ctrl+-", lambda: self.zoom_step(-1))):
            sc = QShortcut(QKeySequence(key), self.list)
            sc.setContext(Qt.WidgetShortcut)
            sc.activated.connect(slot)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.add_dialog)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_pdf)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.drawer.toggle)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.right_scroll.setFixedWidth(side_width(self.width()))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_paths([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    def _sync_split(self):
        mode = self.combo_mode.currentData()
        self.row_every.setVisible(mode == "every")
        self.edit_ranges.setVisible(mode == "ranges")

    # ============================================================================== model
    def _log(self, msg: str):
        self.console.append_line(msg)

    def _hint(self, msg: str):
        self.lbl_status.set_full_text(msg)

    def _ref(self, item) -> A.PageRef:
        return self.refs[item.data(Qt.UserRole)]

    def _ordered(self) -> List[A.PageRef]:
        return [self._ref(self.list.item(r)) for r in range(self.list.count())]

    def _selected_items(self) -> List[QListWidgetItem]:
        return [self.list.item(r) for r in self.list.selected_rows()]

    def _snapshot(self) -> List[A.PageRef]:
        return [r.copy() for r in self._ordered()]

    def _src_name(self, ref: A.PageRef) -> str:
        return self.sources[ref.src].name if ref.src is not None else "Halaman kosong"

    def _item_text(self, pos: int, ref: A.PageRef) -> str:
        bits = []
        if ref.src is not None and self.sources[ref.src].kind == "pdf":
            bits.append("hal %d" % (ref.index + 1))
        if ref.rotation:
            bits.append("%d°" % ref.rotation)
        if ref.scale:
            bits.append("%d%%" % round(ref.scale * 100))
        elif ref.size:
            bits.append(A.describe_size(ref.size))
        return "%d · %s\n%s" % (pos, self._src_name(ref), " · ".join(bits))

    def _tooltip(self, ref: A.PageRef) -> str:
        lines = [self._src_name(ref)]
        if ref.src is not None:
            lines.append(self.sources[ref.src].path)
            if self.sources[ref.src].kind == "pdf":
                lines.append("Halaman %d" % (ref.index + 1))
        w, h = ref.display_size()
        lines.append("Ukuran hasil: %s" % A.describe_size((w, h)) + (" (diubah)" if ref.size else ""))
        if ref.scale:
            lines.append("Skala: %d%% dari ukuran asli" % round(ref.scale * 100))
        if ref.rotation:
            lines.append("Putar tambahan: %d°" % ref.rotation)
        return "\n".join(lines)

    def _decorate(self, item: QListWidgetItem, ref: A.PageRef):
        pm = compose_icon(self.thumbs.get((ref.src, ref.index)), ref, self.list.thumb_side())
        icon = QIcon()
        icon.addPixmap(pm, QIcon.Normal)
        icon.addPixmap(pm, QIcon.Selected)          # tanpa tint biru saat dipilih: pratinjau tetap akurat
        item.setIcon(icon)
        item.setToolTip(self._tooltip(ref))

    def _add_item(self, ref: A.PageRef, row: Optional[int] = None) -> QListWidgetItem:
        uid = self._next_uid
        self._next_uid += 1
        self.refs[uid] = ref
        it = QListWidgetItem()
        it.setData(Qt.UserRole, uid)
        it.setTextAlignment(Qt.AlignHCenter)
        self._decorate(it, ref)
        if row is None:
            self.list.addItem(it)
        else:
            self.list.insertItem(row, it)
        return it

    def _renumber(self):
        for r in range(self.list.count()):
            it = self.list.item(r)
            it.setText(self._item_text(r + 1, self._ref(it)))

    def _forget(self, item: QListWidgetItem):
        self.refs.pop(item.data(Qt.UserRole), None)

    def _mutate(self, fn) -> bool:
        """Jalankan perubahan; bila ada yang berubah, simpan keadaan sebelumnya untuk undo."""
        if self._busy:
            return False
        snap = self._snapshot()
        changed = bool(fn())
        if changed:
            self._push_undo(snap)
            self._renumber()
            self._update_state()
        return changed

    def _push_undo(self, snap):
        self._undo.append(snap)
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()

    def _on_reordered(self):
        if self._pending_snap is not None:
            self._push_undo(self._pending_snap)
            self._pending_snap = None
        self._renumber()
        self._update_state()

    def _restore(self, snap: List[A.PageRef]):
        self.list.clearSelection()
        self.list.clear()
        self.refs.clear()
        for r in snap:
            self._add_item(r.copy())
        self._renumber()
        self._update_state()

    def undo(self):
        if self._busy or not self._undo:
            return
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())

    def redo(self):
        if self._busy or not self._redo:
            return
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())

    def _update_state(self):
        n, k = self.list.count(), len(self.list.selected_rows())
        self.lbl_count.setText(("%d halaman" % n) + (" · %d dipilih" % k if k else "") if n else "Belum ada halaman")
        for w in (self.btn_rot_l, self.btn_rot_r, self.btn_del, self.act_dup, self.act_left, self.act_right,
                  self.act_first, self.act_last, self.act_reset):
            w.setEnabled(k > 0)
        for w in (self.btn_size, self.btn_save, self.btn_split, self.act_all, self.act_reverse, self.act_clear):
            w.setEnabled(n > 0)
        self.btn_undo.setEnabled(bool(self._undo))
        self.btn_redo.setEnabled(bool(self._redo))

    # ============================================================================== tambah file
    def _start_dir(self) -> str:
        if self._last_dir and os.path.isdir(self._last_dir):
            return self._last_dir
        for s in self.sources.values():
            return os.path.dirname(s.path)
        return str(Path.home())

    def _image_page_size(self):
        name = self.combo_img.currentData()
        return (A.PAGE_PRESETS[name] if name else None), self.spin_img_margin.value() * A.MM

    def add_dialog(self):
        if self._busy:
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Tambah PDF atau gambar", self._start_dir(), FILE_FILTER)
        if files:
            self._last_dir = os.path.dirname(files[0])
            self.add_paths(files)

    def add_paths(self, paths: List[str]) -> int:
        """Tambahkan file (PDF/gambar) ke akhir daftar. Mengembalikan jumlah file yang berhasil ditambahkan."""
        if self._busy:
            return 0
        batch: List[Tuple[A.Source, List[A.PageRef]]] = []
        size, margin = self._image_page_size()
        for path in paths:
            name = os.path.basename(path)
            try:
                A.kind_of(path)
            except A.ArrangerError as e:
                self._log("Dilewati: %s" % e)
                continue
            pw, sizes, kind, prompt = "", None, None, "Masukkan sandi untuk %s:" % name
            while True:
                try:
                    kind, sizes = A.inspect_file(path, pw)
                    break
                except A.PasswordRequired:
                    pw, ok = QInputDialog.getText(self, "PDF terkunci", prompt, QLineEdit.Password)
                    prompt = "Sandi salah. Coba lagi untuk %s:" % name
                    if not ok:
                        self._log("Dilewati (sandi tidak diberikan): %s" % name)
                        break
                except A.ArrangerError as e:
                    self._log("Gagal: %s" % e)
                    break
            if not sizes:
                continue
            src = A.Source(self._next_src, path, kind, pw, len(sizes))
            self._next_src += 1
            refs = A.refs_for_source(src, sizes)
            if kind == "image" and size:
                for r in refs:
                    r.set_page_size(size, "auto", "fit", margin)
            self.sources[src.id] = src
            batch.append((src, refs))
        if not batch:
            return 0
        snap = self._snapshot()
        for src, refs in batch:
            for r in refs:
                self._add_item(r)
            self._log("Ditambahkan: %s (%d halaman)" % (src.name, len(refs)))
        self._push_undo(snap)
        self._renumber()
        self._update_state()
        self._hint("%d file ditambahkan" % len(batch))
        self._start_thumbs([(s, [r.index for r in refs]) for s, refs in batch])
        return len(batch)

    # ============================================================================== thumbnail
    def _start_thumbs(self, batch):
        self._workers = [w for w in self._workers if w.isRunning()]
        w = ThumbWorker(batch)
        w.ready.connect(self._on_thumb)
        self._workers.append(w)
        w.start()

    def _on_thumb(self, sid: int, idx: int, img: QImage):
        self.thumbs[(sid, idx)] = img
        self._pending_thumbs.add((sid, idx))
        self._thumb_timer.start()

    def _flush_thumbs(self):
        pend, self._pending_thumbs = self._pending_thumbs, set()
        for r in range(self.list.count()):
            it = self.list.item(r)
            ref = self._ref(it)
            if (ref.src, ref.index) in pend:
                self._decorate(it, ref)

    def _sync_zoom_ui(self):
        self.lbl_zoom.setText("%d%%" % round(ZOOM_LEVELS[self._zoom_idx] * 100 / ZOOM_LEVELS[ZOOM_DEFAULT]))
        self.btn_zoom_out.setEnabled(self._zoom_idx > 0)
        self.btn_zoom_in.setEnabled(self._zoom_idx < len(ZOOM_LEVELS) - 1)

    def zoom_step(self, delta: int):
        """Perbesar (+1) / perkecil (-1) thumbnail satu tingkat."""
        idx = max(0, min(len(ZOOM_LEVELS) - 1, self._zoom_idx + (1 if delta > 0 else -1)))
        if idx == self._zoom_idx:
            return
        self._zoom_idx = idx
        self._sync_zoom_ui()
        self._zoom_timer.start()                     # gambar ulang ikon ditunda sebentar agar klik beruntun tidak berat

    def _apply_zoom(self):
        self._zoom_timer.stop()
        self.list.set_thumb_side(ZOOM_LEVELS[self._zoom_idx])
        for r in range(self.list.count()):
            it = self.list.item(r)
            self._decorate(it, self._ref(it))

    def wait_thumbs(self, timeout_ms: int = 20000):
        """Tunggu semua thumbnail selesai (untuk tes)."""
        for w in list(self._workers):
            w.wait(timeout_ms)
        QApplication.processEvents()                # teruskan sinyal thumbnail yang masih antre
        self._thumb_timer.stop()
        self._flush_thumbs()

    # ============================================================================== operasi halaman
    def _need_selection(self) -> bool:
        if self.list.selected_rows():
            return True
        self._hint("Pilih halaman dulu.")
        return False

    def rotate(self, delta: int):
        if not self._need_selection():
            return

        def op():
            for it in self._selected_items():
                ref = self._ref(it)
                ref.rotate(delta)
                self._decorate(it, ref)
            return True
        self._mutate(op)

    def delete_selected(self):
        if not self._need_selection():
            return

        def op():
            for r in reversed(self.list.selected_rows()):
                it = self.list.takeItem(r)
                self._forget(it)
            return True
        self._mutate(op)

    def duplicate(self):
        if not self._need_selection():
            return
        new_items = []

        def op():
            for r in reversed(self.list.selected_rows()):
                new_items.append(self._add_item(self._ref(self.list.item(r)).copy(), r + 1))
            return True
        if self._mutate(op):
            self.list.clearSelection()
            for it in new_items:
                it.setSelected(True)

    def shift(self, delta: int):
        if not self._need_selection():
            return
        self._mutate(lambda: self.list.shift_selected(delta))

    def move_edge(self, to_start: bool):
        if not self._need_selection():
            return
        self._mutate(lambda: self.list.move_selected_to(0 if to_start else self.list.count()))

    def reverse_all(self):
        def op():
            n = self.list.count()
            if n < 2:
                return False
            sel = set(self.list.selected_rows())
            items = [self.list.takeItem(0) for _ in range(n)]
            for i, it in enumerate(reversed(items)):
                self.list.addItem(it)
            for old in sel:
                self.list.item(n - 1 - old).setSelected(True)
            return True
        self._mutate(op)

    def insert_blank(self):
        rows = self.list.selected_rows()
        row = rows[-1] + 1 if rows else self.list.count()
        size = self._ref(self.list.item(rows[-1])).display_size() if rows else A.A4
        new = []

        def op():
            new.append(self._add_item(A.PageRef(None, 0, size), row))
            return True
        if self._mutate(op):
            self.list.clearSelection()
            new[0].setSelected(True)

    def reset_selected(self):
        if not self._need_selection():
            return

        def op():
            changed = False
            for it in self._selected_items():
                ref = self._ref(it)
                if ref.rotation or ref.size:
                    ref.reset_changes()
                    self._decorate(it, ref)
                    changed = True
            return changed
        self._mutate(op)

    def clear_all(self):
        if not self.list.count():
            return
        if QMessageBox.question(self, "Hapus semua halaman", "Hapus semua %d halaman dari daftar? "
                                "(Bisa diurungkan dengan Ctrl+Z.)" % self.list.count()) != QMessageBox.Yes:
            return

        def op():
            self.list.clear()
            self.refs.clear()
            return True
        self._mutate(op)

    def resize_dialog(self):
        if not self.list.count():
            return
        dlg = PageSizeDialog(self, len(self.list.selected_rows()), self.list.count())
        if dlg.exec_() != dlg.Accepted:
            return
        v = dlg.values()
        items = self._selected_items() if v["scope"] == "selected" else [self.list.item(r) for r in range(self.list.count())]

        def op():
            changed = False
            for it in items:
                ref = self._ref(it)
                before = (ref.size, ref.fit, ref.margin, ref.scale)
                if v.get("scale"):
                    ref.set_scale(v["scale"])
                else:
                    ref.set_page_size(v["size"], v["orientation"], v["fit"], v["margin"])
                if (ref.size, ref.fit, ref.margin, ref.scale) != before:
                    changed = True
                    self._decorate(it, ref)
            return changed                              # menerapkan ukuran yang sama tidak mencatat undo
        self._mutate(op)

    def _open_preview(self, item):
        refs = self._snapshot()
        PreviewDialog(self, refs, dict(self.sources), self.list.row(item)).exec_()

    # ============================================================================== simpan / pisah
    def _pages_for(self, selected_only: bool) -> List[A.PageRef]:
        if selected_only:
            sel = self._selected_items()
            if not sel:
                self._hint("Tidak ada halaman terpilih.")
                return []
            return [self._ref(it).copy() for it in sel]
        return self._snapshot()

    def _is_source(self, path: str) -> bool:
        p = os.path.normcase(os.path.abspath(path))
        return any(os.path.normcase(os.path.abspath(s.path)) == p for s in self.sources.values())

    def browse_out(self):
        start = self.edit_out.text().strip() or os.path.join(self._start_dir(), "gabungan.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Simpan PDF", start, "PDF (*.pdf)")
        if path:
            self.edit_out.setText(path)

    def browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Pilih folder hasil", self.edit_dir.text().strip() or self._start_dir())
        if d:
            self.edit_dir.setText(d)

    def save_pdf(self):
        if self._busy or not self.list.count():
            return
        pages = self._pages_for(self.chk_sel.isChecked())
        if not pages:
            return
        path = self.edit_out.text().strip()
        picked = False
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Simpan PDF", os.path.join(self._start_dir(), "gabungan.pdf"),
                                                  "PDF (*.pdf)")
            if not path:
                return
            picked = True
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self.edit_out.setText(path)
        if self._is_source(path):
            QMessageBox.warning(self, "Nama file dipakai", "File ini sedang dipakai sebagai sumber halaman. "
                                "Pilih nama file hasil yang lain.")
            return
        if os.path.exists(path) and not picked:
            if QMessageBox.question(self, "Timpa file?", "%s sudah ada. Timpa?" % os.path.basename(path)) != QMessageBox.Yes:
                return
        self._start_job([(path, pages)])

    def split_pages(self):
        if self._busy or not self.list.count():
            return
        pages = self._pages_for(self.chk_split_sel.isChecked())
        if not pages:
            return
        try:
            groups = A.plan_split(pages, self.combo_mode.currentData(), n=self.spin_n.value(),
                                  ranges=self.edit_ranges.text())
        except A.ArrangerError as e:
            QMessageBox.warning(self, "Pisahkan", str(e))
            return
        first = next((self.sources[p.src] for p in pages if p.src is not None), None)
        out_dir = self.edit_dir.text().strip() or (os.path.dirname(first.path) if first else "")
        if not out_dir:
            QMessageBox.warning(self, "Pisahkan", "Pilih folder hasil terlebih dahulu.")
            return
        base = Path(first.path).stem if first else "hasil"
        pos = {id(p): i + 1 for i, p in enumerate(pages)}
        try:
            paths = A.split_output_paths(groups, out_dir, base, self.edit_tpl.text().strip() or "{nama}_{n}",
                                         starts=[pos[id(g[0])] for g in groups])
        except A.ArrangerError as e:
            QMessageBox.warning(self, "Pisahkan", str(e))
            return
        if len(paths) > 25 and QMessageBox.question(self, "Pisahkan", "Ini akan membuat %d file di:\n%s\n\nLanjutkan?"
                                                    % (len(paths), out_dir)) != QMessageBox.Yes:
            return
        self._start_job(list(zip(paths, groups)))

    # ---------------------------------------------------------------- pekerjaan di thread
    def is_busy(self) -> bool:
        return self._job is not None

    def _set_busy(self, busy: bool):
        self._busy = busy
        for w in (self.toolbar, self.right_scroll, self.list):
            w.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)

    def _start_job(self, jobs):
        self._job = BuildThread(jobs, dict(self.sources), self.chk_opt.isChecked())
        self._job.progress.connect(self._on_progress)
        self._job.file_done.connect(lambda p: self._log("Tersimpan: %s" % p))
        self._job.finished_ok.connect(self._on_job_ok)
        self._job.failed.connect(self._on_job_failed)
        self._job.cancelled.connect(self._on_job_cancelled)
        self.pbar.setValue(0)
        self._hint("Memproses… 0%")
        self._set_busy(True)
        self._job.start()

    def _end_job(self):
        job, self._job = self._job, None
        if job is not None:
            job.wait()
        self._set_busy(False)
        self._update_state()

    def _on_progress(self, done: int, total: int):
        pct = int(done * 100 / max(1, total))
        self.pbar.setValue(pct)
        self._hint("Memproses… %d%% (%d/%d halaman)" % (pct, done, total))

    def _on_job_ok(self, outs: list):
        self._end_job()
        self.pbar.setValue(100)
        self._last_dir_out = os.path.dirname(outs[0])
        self.btn_open.setEnabled(True)
        msg = ("Selesai: %s" % os.path.basename(outs[0])) if len(outs) == 1 else "Selesai: %d file dibuat." % len(outs)
        self._hint(msg)
        self._log(msg)
        QMessageBox.information(self, "Selesai", msg)

    def _on_job_failed(self, err: str):
        self._end_job()
        self._hint("Gagal: %s" % err)
        self._log("GAGAL: %s" % err)
        self.drawer.set_open(True)
        QMessageBox.warning(self, "Gagal", err)

    def _on_job_cancelled(self):
        self._end_job()
        self.pbar.setValue(0)
        self._hint("Dibatalkan. Tidak ada file yang tersisa.")
        self._log("Dibatalkan.")

    def cancel_job(self):
        if self._job is not None:
            self._job.cancel()
            self._hint("Membatalkan…")

    def open_results(self):
        d = getattr(self, "_last_dir_out", "")
        if d and os.path.isdir(d):
            open_folder(d)

    def abort_and_wait(self):
        if self._job is not None:
            self._job.cancel()
            self._job.wait()

    def shutdown(self):
        """Hentikan semua thread latar belakang (dipanggil saat jendela ditutup)."""
        self.abort_and_wait()
        for w in self._workers:
            w.stop()
        for w in self._workers:
            w.wait()
        self._thumb_timer.stop()
        self._zoom_timer.stop()
        # Lepas semua QPixmap/QIcon/QImage SEKARANG: bila baru dihancurkan setelah QApplication selesai, Qt crash saat keluar.
        self.list.clear()
        self.thumbs.clear()
        self.refs.clear()
        self._undo.clear()
        self._redo.clear()
