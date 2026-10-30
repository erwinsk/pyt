# -*- coding: utf-8 -*-
"""Daftar halaman bergambar untuk tab 'Atur Halaman'.

* Thumbnail digambar dari cache gambar sumber + perubahan (putar / ukuran halaman), jadi memutar atau
  mengubah ukuran tidak perlu render ulang.
<<<<<<< HEAD
* Urutan diubah dengan drag & drop (logika penempatan ditulis sendiri agar pasti dan bisa dites) atau lewat
  `move_selected_to` / `shift_selected`.
* File yang diseret dari pengelola file memancarkan `files_dropped`.
"""
from typing import List, Optional

from PyQt5.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPalette, QPen, QPixmap, QTransform
from PyQt5.QtWidgets import QAbstractItemView, QListView, QListWidget, QListWidgetItem
=======
* Urutan diubah dengan menyeret memakai EVENT MOUSE biasa (tanpa mekanisme drag & drop sistem operasi, yang
  perilakunya berbeda antar platform): garis penanda menunjukkan posisi sisip, daftar menggulir otomatis di tepi,
  Esc membatalkan. Bisa juga lewat `move_selected_to` / `shift_selected`.
* File yang diseret dari pengelola file (drag & drop sistem) memancarkan `files_dropped`.
* Ctrl + roda mouse memancarkan `zoom_requested(+1/-1)`.
"""
from typing import List, Optional

from PyQt5.QtCore import QPoint, QRect, QSize, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter, QPalette, QPen, QPixmap, QTransform
from PyQt5.QtWidgets import QAbstractItemView, QApplication, QListView, QListWidget, QListWidgetItem
>>>>>>> 36ee49d (update pdf tools, arrange pdf)

from core.arranger import PageRef
from theme import mix


def compose_icon(thumb: Optional[QImage], ref: PageRef, side: int) -> QPixmap:
    """Gambar halaman sebagaimana akan tersimpan: kanvas putih berbentuk ukuran hasil, isi diputar/disesuaikan."""
    dw, dh = ref.display_size()
    scale = side / max(dw, dh, 1.0)
    cw, ch = max(10, round(dw * scale)), max(10, round(dh * scale))
    pm = QPixmap(side, side)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    canvas = QRect((side - cw) // 2, (side - ch) // 2, cw, ch)
    p.fillRect(canvas, Qt.white)
    if ref.src is not None:
        if thumb is None:
            p.setPen(QColor(150, 150, 150))
            p.drawText(canvas, Qt.AlignCenter, "…")
        else:
            m = round(ref.margin * scale) if ref.size else 0
            inner = canvas.adjusted(m, m, -m, -m)
            img = thumb
            if ref.rotation:
                img = img.transformed(QTransform().rotate(ref.rotation), Qt.SmoothTransformation)
            if ref.size and ref.fit != "stretch":
                sz = img.size().scaled(inner.size(), Qt.KeepAspectRatio)
                target = QRect(0, 0, sz.width(), sz.height())
                target.moveCenter(inner.center())
            else:
                target = inner
            p.drawImage(target, img)
    p.setPen(QPen(QColor(160, 160, 160), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRect(canvas.adjusted(0, 0, -1, -1))
    p.end()
    return pm


class PageList(QListWidget):
<<<<<<< HEAD
    files_dropped = pyqtSignal(list)        # path file yang diseret dari luar
    about_to_reorder = pyqtSignal()         # tepat sebelum urutan berubah karena drag (untuk undo)
    reordered = pyqtSignal()

    EMPTY_TITLE = "Seret PDF atau gambar ke sini"
    EMPTY_HINT = "atau klik “Tambah”. Halaman dari banyak file bisa digabung dan diurutkan."
=======
    files_dropped = pyqtSignal(list)        # path file yang diseret dari luar (pengelola file)
    about_to_reorder = pyqtSignal()         # tepat sebelum urutan berubah karena seret (untuk undo)
    reordered = pyqtSignal()
    zoom_requested = pyqtSignal(int)        # +1 / -1 (Ctrl + roda mouse)

    EMPTY_TITLE = "Seret PDF atau gambar ke sini"
    EMPTY_HINT = "atau klik “Tambah”. Halaman dari banyak file bisa digabung dan diurutkan."
    AUTOSCROLL_EDGE = 36                    # px dari tepi atas/bawah tempat penggulungan otomatis aktif
>>>>>>> 36ee49d (update pdf tools, arrange pdf)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pages")
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
<<<<<<< HEAD
        self.setMovement(QListView.Static)                  # penempatan ditangani sendiri (lihat dropEvent)
=======
        self.setMovement(QListView.Static)
>>>>>>> 36ee49d (update pdf tools, arrange pdf)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setSpacing(6)
        self.setUniformItemSizes(True)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideMiddle)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
<<<<<<< HEAD
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)            # CopyAction: Qt tidak menghapus item sumber setelah drop
=======
        # Seret-urut ditangani sendiri dengan event mouse; drag & drop bawaan Qt dimatikan. Yang tersisa hanyalah
        # penerimaan file dari luar (drag sistem), jadi acceptDrops diaktifkan SETELAH setDragDropMode.
        self.setDragEnabled(False)
        self.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.setAcceptDrops(True)
>>>>>>> 36ee49d (update pdf tools, arrange pdf)
        self.setDropIndicatorShown(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._side = 140
        self.set_thumb_side(140)
<<<<<<< HEAD
=======
        # status seret
        self._press_item: Optional[QListWidgetItem] = None
        self._press_pos = QPoint()
        self._press_ev: Optional[QMouseEvent] = None
        self._deferred = False              # tekan pada item yang sudah terpilih: perubahan pilihan ditunda
        self._drag_active = False
        self._drop_target: Optional[int] = None
        self._last_pos = QPoint()
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(30)
        self._auto_timer.timeout.connect(self._autoscroll_tick)
>>>>>>> 36ee49d (update pdf tools, arrange pdf)

    # ---- ukuran ----
    def set_thumb_side(self, side: int):
        self._side = int(side)
        fm = self.fontMetrics()
        self.setIconSize(QSize(self._side, self._side))
        self.setGridSize(QSize(self._side + 24, self._side + 2 * fm.height() + 22))

    def thumb_side(self) -> int:
        return self._side

    # ---- pilihan & urutan ----
    def selected_rows(self) -> List[int]:
        return sorted(self.row(i) for i in self.selectedItems())

    @staticmethod
    def _after_move_rows(rows: List[int], target: int) -> List[int]:
        t = target - sum(1 for r in rows if r < target)
        return list(range(t, t + len(rows)))

    def would_change(self, rows: List[int], target: int) -> bool:
        return bool(rows) and self._after_move_rows(rows, target) != rows

    def move_selected_to(self, target: int) -> bool:
        """Pindahkan semua item terpilih ke sebelum baris `target` (0..count), urutan relatifnya tetap."""
        rows = self.selected_rows()
        target = max(0, min(self.count(), target))
        if not self.would_change(rows, target):
            return False
        t = target - sum(1 for r in rows if r < target)
        items = [self.takeItem(r) for r in reversed(rows)]
        items.reverse()
        for k, it in enumerate(items):
            self.insertItem(t + k, it)
        for it in items:
            it.setSelected(True)
        self.scrollToItem(items[0])
        return True

    def shift_selected(self, delta: int) -> bool:
        """Geser terpilih satu langkah (delta -1 = ke awal, +1 = ke akhir); blok bertemu tepi/blok lain berhenti."""
        rows = self.selected_rows()
        if not rows or delta not in (-1, 1):
            return False
        sel = set(rows)
        moved = False
        for r in (rows if delta < 0 else reversed(rows)):
            n = r + delta
            if 0 <= n < self.count() and n not in sel:
                it = self.takeItem(r)
                self.insertItem(n, it)
                sel.discard(r)
                sel.add(n)
                moved = True
        if moved:
            for r in sel:
                self.item(r).setSelected(True)
            self.scrollToItem(self.item(min(sel) if delta < 0 else max(sel)))
        return moved

<<<<<<< HEAD
    # ---- drag & drop ----
=======
    # ---- seret untuk mengurutkan (event mouse) ----
>>>>>>> 36ee49d (update pdf tools, arrange pdf)
    def _drop_row(self, pos) -> int:
        """Baris tempat item akan disisipkan: sebelum item yang setengah kirinya ditunjuk / baris di bawah kursor."""
        for r in range(self.count()):
            rect = self.visualItemRect(self.item(r))
            if pos.y() < rect.top():
                return r
            if rect.top() <= pos.y() <= rect.bottom() and pos.x() < rect.center().x():
                return r
        return self.count()

<<<<<<< HEAD
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.source() is self:
=======
    def is_dragging(self) -> bool:
        return self._drag_active

    def _reset_drag(self):
        self._press_item, self._press_ev, self._deferred = None, None, False
        was = self._drag_active
        self._drag_active, self._drop_target = False, None
        self._auto_timer.stop()
        if was:
            self.viewport().unsetCursor()
        self.viewport().update()

    def cancel_drag(self):
        self._reset_drag()

    def mousePressEvent(self, e):
        self._reset_drag()
        plain = not (e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))
        if e.button() == Qt.LeftButton and plain:
            it = self.itemAt(e.pos())
            if it is not None:
                self._press_item, self._press_pos = it, e.pos()
                if it.isSelected():
                    # Tekan pada item yang sudah terpilih (mungkin salah satu dari banyak): jangan ubah pilihan dulu,
                    # sebab bisa jadi ini awal seretan seluruh pilihan. Bila ternyata hanya klik, diputar ulang saat dilepas.
                    self._deferred = True
                    self._press_ev = QMouseEvent(e)
                    e.accept()
                    return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press_item is not None and (e.buttons() & Qt.LeftButton):
            self._last_pos = e.pos()
            if not self._drag_active:
                if (e.pos() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
                    return
                if not self._press_item.isSelected():
                    return
                self._drag_active = True
                self.viewport().setCursor(Qt.ClosedHandCursor)
                self._auto_timer.start()
            self._drop_target = self._drop_row(e.pos())
            self.viewport().update()
            e.accept()
            return
        if self._deferred:
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._press_item is not None and e.button() == Qt.LeftButton:
            active, target = self._drag_active, self._drop_target
            deferred, press_ev = self._deferred, self._press_ev
            self._reset_drag()
            if active:
                rows = self.selected_rows()
                if target is not None and self.would_change(rows, target):
                    self.about_to_reorder.emit()
                    self.move_selected_to(target)
                    self.reordered.emit()
                e.accept()
                return
            if deferred and press_ev is not None:
                super().mousePressEvent(press_ev)          # klik biasa: sekarang terapkan pilihan
                super().mouseReleaseEvent(e)
                return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if self._drag_active and e.key() == Qt.Key_Escape:
            self._reset_drag()
            e.accept()
            return
        super().keyPressEvent(e)

    def changeEvent(self, e):
        if e.type() == e.EnabledChange and not self.isEnabled():
            self._reset_drag()
        super().changeEvent(e)

    def _autoscroll_tick(self):
        """Gulir otomatis saat kursor (dalam seretan) berada di dekat tepi atas/bawah daftar."""
        if not self._drag_active:
            return
        bar, h, y = self.verticalScrollBar(), self.viewport().height(), self._last_pos.y()
        step = 0
        if y < self.AUTOSCROLL_EDGE:
            step = -max(4, (self.AUTOSCROLL_EDGE - y) // 2)
        elif y > h - self.AUTOSCROLL_EDGE:
            step = max(4, (y - (h - self.AUTOSCROLL_EDGE)) // 2)
        if step and bar.value() + step != bar.value():
            bar.setValue(bar.value() + step)
            self._drop_target = self._drop_row(self._last_pos)
            self.viewport().update()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            d = e.angleDelta().y()
            if d:
                self.zoom_requested.emit(1 if d > 0 else -1)
            e.accept()
            return
        super().wheelEvent(e)

    # ---- file dari luar (drag & drop sistem) ----
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
>>>>>>> 36ee49d (update pdf tools, arrange pdf)
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
<<<<<<< HEAD
        if e.mimeData().hasUrls() or e.source() is self:
=======
        if e.mimeData().hasUrls():
>>>>>>> 36ee49d (update pdf tools, arrange pdf)
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
<<<<<<< HEAD
        if e.source() is self:
            rows = self.selected_rows()
            target = self._drop_row(e.pos())
            if self.would_change(rows, target):
                self.about_to_reorder.emit()
                self.move_selected_to(target)
                self.reordered.emit()
            e.setDropAction(Qt.CopyAction)
            e.accept()
        elif e.mimeData().hasUrls():
=======
        if e.mimeData().hasUrls():
>>>>>>> 36ee49d (update pdf tools, arrange pdf)
            self.files_dropped.emit([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
            e.acceptProposedAction()
        else:
            e.ignore()

<<<<<<< HEAD
    # ---- tampilan kosong ----
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count():
            return
=======
    # ---- tampilan ----
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count() == 0:
            self._paint_empty()
        elif self._drag_active and self._drop_target is not None:
            self._paint_drop_line()

    def _paint_drop_line(self):
        t, n = self._drop_target, self.count()
        if t < n:
            r = self.visualItemRect(self.item(t))
            x = r.left() - 4
        else:
            r = self.visualItemRect(self.item(n - 1))
            x = r.right() + 4
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self.palette().color(QPalette.Highlight))
        p.drawRoundedRect(QRect(x - 1, r.top() + 2, 3, max(10, r.height() - 4)), 1.5, 1.5)
        p.end()

    def _paint_empty(self):
>>>>>>> 36ee49d (update pdf tools, arrange pdf)
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        win, txt = pal.color(QPalette.Window), pal.color(QPalette.Text)
        r = self.viewport().rect().adjusted(14, 14, -14, -14)
        p.setPen(QPen(mix(win, txt, 0.28), 1.4, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 10, 10)
        tf = QFont(self.font())
        tf.setPointSizeF(tf.pointSizeF() + 1.5)
        tf.setBold(True)
        p.setFont(tf)
        ht = p.fontMetrics().height()
        p.setFont(self.font())
        hh = p.fontMetrics().height()
        top = r.center().y() - (ht + 6 + hh) // 2
        p.setFont(tf)
        p.setPen(mix(txt, win, 0.20))
        p.drawText(QRect(r.left(), top, r.width(), ht), Qt.AlignCenter, self.EMPTY_TITLE)
        p.setFont(self.font())
        p.setPen(mix(txt, win, 0.45))
        p.drawText(QRect(r.left() + 10, top + ht + 6, r.width() - 20, hh), Qt.AlignCenter,
                   p.fontMetrics().elidedText(self.EMPTY_HINT, Qt.ElideRight, r.width() - 20))
        p.end()
