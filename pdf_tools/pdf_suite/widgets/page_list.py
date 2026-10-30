# -*- coding: utf-8 -*-
"""Daftar halaman bergambar untuk tab 'Atur Halaman'.

* Thumbnail digambar dari cache gambar sumber + perubahan (putar / ukuran halaman), jadi memutar atau
  mengubah ukuran tidak perlu render ulang.
* Urutan diubah dengan menyeret memakai EVENT MOUSE biasa (tanpa mekanisme drag & drop sistem operasi, yang
  perilakunya berbeda antar platform): garis penanda menunjukkan posisi sisip, daftar menggulir otomatis di tepi,
  Esc membatalkan. Bisa juga lewat `move_selected_to` / `shift_selected`.
* File yang diseret dari pengelola file (drag & drop sistem) memancarkan `files_dropped`.
* Ctrl + roda mouse memancarkan `zoom_requested(+1/-1)`.
"""
from typing import Callable, List, Optional, Tuple

from PyQt5.QtCore import QPoint, QRect, QRectF, QSize, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter, QPalette, QPen
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QListView, QListWidget, QListWidgetItem, QStyle,
                             QStyledItemDelegate)

from core.arranger import PageRef
from theme import is_dark, mix


def paint_page(p: QPainter, area: QRect, thumb: Optional[QImage], ref: PageRef, side: int):
    """Gambar halaman sebagaimana akan tersimpan (putar + ukuran) langsung ke `area` (kotak ikon).
    Kanvas putih berbentuk ukuran hasil, sisi terpanjangnya = `side`; isi diputar/disesuaikan. Tanpa pixmap perantara,
    sehingga hemat memori pada zoom besar."""
    dw, dh = ref.display_size()
    scale = side / max(dw, dh, 1.0)
    cw, ch = max(10, round(dw * scale)), max(10, round(dh * scale))
    canvas = QRect(area.left() + (area.width() - cw) // 2, area.top() + (area.height() - ch) // 2, cw, ch)
    p.fillRect(canvas, Qt.white)
    if ref.src is not None:
        if thumb is None:
            p.setPen(QColor(150, 150, 150))
            p.drawText(canvas, Qt.AlignCenter, "…")
        else:
            m = round(ref.margin * scale) if ref.size else 0
            inner = canvas.adjusted(m, m, -m, -m)
            r = ref.rotation % 360
            rw, rh = (thumb.height(), thumb.width()) if r % 180 else (thumb.width(), thumb.height())
            if ref.size and ref.fit != "stretch":
                sz = QSize(rw, rh).scaled(inner.size(), Qt.KeepAspectRatio)
            else:
                sz = inner.size()
            iw, ih = (sz.height(), sz.width()) if r % 180 else (sz.width(), sz.height())   # ukuran gambar SEBELUM diputar
            p.save()
            p.setClipRect(canvas)
            p.translate(inner.center())
            p.rotate(r)
            p.drawImage(QRect(-iw // 2, -ih // 2, iw, ih), thumb)
            p.restore()
    p.setPen(QPen(QColor(160, 160, 160), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(canvas).adjusted(0.5, 0.5, -0.5, -0.5))      # offset setengah piksel: bingkai 1 px tajam, tidak kabur


class PageDelegate(QStyledItemDelegate):
    """Menggambar tiap sel halaman langsung (hanya yang terlihat): latar pilihan/hover, halaman, dan dua baris teks."""

    def __init__(self, view: "PageList"):
        super().__init__(view)
        self.view = view

    def sizeHint(self, option, index):
        return QSize(self.view.gridSize())

    def paint(self, p, option, index):
        v = self.view
        side, box_w = v.thumb_side(), v.box_width()
        rect, pal = option.rect, option.palette
        win, txt, base, hi = (pal.color(QPalette.Window), pal.color(QPalette.Text),
                              pal.color(QPalette.Base), pal.color(QPalette.Highlight))
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        bg = None
        if option.state & QStyle.State_Selected:
            bg = mix(base, hi, 0.20 if is_dark(pal) else 0.16)
        elif option.state & QStyle.State_MouseOver:
            bg = mix(win, txt, 0.07)
        if bg is not None:
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)
        area = QRect(rect.left() + (rect.width() - box_w) // 2, rect.top() + 6, box_w, side)
        got = v.page_provider(index.data(Qt.UserRole)) if v.page_provider else None
        if got is not None:
            paint_page(p, area, got[1], got[0], side)
        p.setPen(txt)
        fm = p.fontMetrics()
        y = area.bottom() + 6
        for line in (index.data(Qt.DisplayRole) or "").split("\n")[:2]:
            tr = QRect(rect.left() + 4, y, rect.width() - 8, fm.height())
            p.drawText(tr, Qt.AlignHCenter | Qt.AlignVCenter, fm.elidedText(line, Qt.ElideMiddle, tr.width()))
            y += fm.height()
        p.restore()


class PageList(QListWidget):
    files_dropped = pyqtSignal(list)        # path file yang diseret dari luar (pengelola file)
    about_to_reorder = pyqtSignal()         # tepat sebelum urutan berubah karena seret (untuk undo)
    reordered = pyqtSignal()
    zoom_requested = pyqtSignal(int)        # +1 / -1 (Ctrl + roda mouse)
    viewport_resized = pyqtSignal()         # lebar area tampilan berubah (batas zoom ikut berubah)

    EMPTY_TITLE = "Seret PDF atau gambar ke sini"
    EMPTY_HINT = "atau klik “Tambah”. Halaman dari banyak file bisa digabung dan diurutkan."
    AUTOSCROLL_EDGE = 36                    # px dari tepi atas/bawah tempat penggulungan otomatis aktif

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pages")
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setSpacing(6)
        self.setUniformItemSizes(True)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideMiddle)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # Seret-urut ditangani sendiri dengan event mouse; drag & drop bawaan Qt dimatikan. Yang tersisa hanyalah
        # penerimaan file dari luar (drag sistem), jadi acceptDrops diaktifkan SETELAH setDragDropMode.
        self.setDragEnabled(False)
        self.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._side = 140
        self._box_w = 140
        self.page_provider: Optional[Callable[[int], Optional[Tuple[PageRef, Optional[QImage]]]]] = None
        self.setItemDelegate(PageDelegate(self))
        self.set_thumb_geometry(140, 140)
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

    # ---- ukuran ----
    def set_thumb_geometry(self, side: int, box_w: int):
        """side = sisi terpanjang halaman (px); box_w = lebar sel isi (halaman potret lebih sempit dari side)."""
        self._side, self._box_w = int(side), int(box_w)
        fm = self.fontMetrics()
        self.setIconSize(QSize(self._box_w, self._side))
        self.setGridSize(QSize(self._box_w + 24, self._side + 2 * fm.height() + 22))
        self.scheduleDelayedItemsLayout()
        self.viewport().update()

    def set_thumb_side(self, side: int):
        self.set_thumb_geometry(side, side)

    def thumb_side(self) -> int:
        return self._side

    def box_width(self) -> int:
        return self._box_w

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.viewport_resized.emit()

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

    # ---- seret untuk mengurutkan (event mouse) ----
    def _drop_row(self, pos) -> int:
        """Baris tempat item akan disisipkan: sebelum item yang setengah kirinya ditunjuk / baris di bawah kursor."""
        for r in range(self.count()):
            rect = self.visualItemRect(self.item(r))
            if pos.y() < rect.top():
                return r
            if rect.top() <= pos.y() <= rect.bottom() and pos.x() < rect.center().x():
                return r
        return self.count()

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
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            self.files_dropped.emit([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
            e.acceptProposedAction()
        else:
            e.ignore()

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
