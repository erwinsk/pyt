# -*- coding: utf-8 -*-
"""Panel opsi yang dibangun otomatis dari skema engine."""
from typing import Dict

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                             QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from core import schema as S
from core.deps import tesseract_languages

MARK_OCR = "↻"
MARK_FAST = "⚡"


class LanguageDialog(QDialog):
    def __init__(self, available, current: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pilih bahasa OCR")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Bahasa terpasang di Tesseract:"))
        self.list = QListWidget()
        chosen = [x for x in current.replace(",", "+").split("+") if x]
        for lang in sorted(available):
            it = QListWidgetItem(lang)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if lang in chosen else Qt.Unchecked)
            self.list.addItem(it)
        lay.addWidget(self.list)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._chosen_order = chosen

    def result_text(self) -> str:
        checked = [self.list.item(i).text() for i in range(self.list.count())
                   if self.list.item(i).checkState() == Qt.Checked]
        ordered = [l for l in self._chosen_order if l in checked] + [l for l in checked if l not in self._chosen_order]
        return "+".join(ordered)


class OptionPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, engine, tools: dict, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.tools = tools
        self._widgets: Dict[str, QWidget] = {}
        self._labels: Dict[str, QLabel] = {}
        self._base_tip: Dict[str, str] = {}
        self._langs_cache = None
        self._building = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        basic = QFormLayout()
        basic.setLabelAlignment(Qt.AlignLeft)
        self.adv_form = QFormLayout()
        self.adv_form.setLabelAlignment(Qt.AlignLeft)
        has_adv = False
        for opt in engine.options:
            w = self._make_widget(opt)
            self._widgets[opt.key] = w
            label = QLabel(self._label_text(opt))
            self._labels[opt.key] = label
            tip = opt.tooltip or opt.label
            if engine.uses_ocr:
                tip += "\n\n" + ("↻ Mengubah ini membuat OCR diulang." if opt.affects_ocr
                                 else "⚡ Mengubah ini TIDAK mengulang OCR (memakai cache).")
            self._base_tip[opt.key] = tip
            label.setToolTip(tip)
            w.setToolTip(tip)
            form = self.adv_form if opt.group == "advanced" else basic
            has_adv = has_adv or opt.group == "advanced"
            if opt.kind == S.BOOL:
                form.addRow(w)
                self._labels.pop(opt.key)
            else:
                form.addRow(label, w)
        outer.addLayout(basic)

        self.adv_toggle = QToolButton()
        self.adv_toggle.setText("Lanjutan ▸")
        self.adv_toggle.setCheckable(True)
        self.adv_toggle.setStyleSheet("QToolButton { border: none; font-weight: bold; }")
        self.adv_box = QWidget()
        self.adv_box.setLayout(self.adv_form)
        self.adv_box.setVisible(False)
        self.adv_toggle.toggled.connect(self._toggle_adv)
        if has_adv:
            outer.addWidget(self.adv_toggle)
            outer.addWidget(self.adv_box)
        outer.addStretch(1)
        self._building = False
        self.refresh_availability(tools)

    # ---- pembuat widget ----
    def _label_text(self, opt) -> str:
        if not self.engine.uses_ocr:
            return opt.label + ":"
        return f"{MARK_OCR if opt.affects_ocr else MARK_FAST} {opt.label}:"

    def _make_widget(self, opt) -> QWidget:
        if opt.kind == S.BOOL:
            w = QCheckBox(((MARK_OCR if opt.affects_ocr else MARK_FAST) + " ") * self.engine.uses_ocr + opt.label)
            w.setChecked(bool(opt.default))
            w.toggled.connect(self._on_changed)
        elif opt.kind == S.INT:
            w = QSpinBox()
            w.setRange(int(opt.min if opt.min is not None else -10**9), int(opt.max if opt.max is not None else 10**9))
            w.setValue(int(opt.default))
            if opt.suffix:
                w.setSuffix(opt.suffix)
            w.setKeyboardTracking(False)
            w.valueChanged.connect(self._on_changed)
        elif opt.kind == S.FLOAT:
            w = QDoubleSpinBox()
            w.setDecimals(2 if opt.step < 0.1 else 1)
            w.setRange(float(opt.min if opt.min is not None else -1e9), float(opt.max if opt.max is not None else 1e9))
            w.setSingleStep(float(opt.step))
            w.setValue(float(opt.default))
            w.setKeyboardTracking(False)
            w.valueChanged.connect(self._on_changed)
        elif opt.kind == S.CHOICE:
            w = QComboBox()
            for value, text in opt.choices:
                w.addItem(text, value)
            w.setCurrentIndex(max(0, [c[0] for c in opt.choices].index(opt.default)))
            w.currentIndexChanged.connect(self._on_changed)
        elif opt.kind == S.LANGS:
            box = QWidget()
            h = QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(str(opt.default))
            edit.textChanged.connect(self._on_changed)
            btn = QPushButton("Pilih…")
            btn.clicked.connect(lambda _=False, e=edit: self._pick_langs(e))
            h.addWidget(edit, 1)
            h.addWidget(btn)
            box._edit = edit
            box._btn = btn
            return box
        else:
            w = QLineEdit(str(opt.default))
            w.textChanged.connect(self._on_changed)
        return w

    def _pick_langs(self, edit: QLineEdit):
        if self._langs_cache is None:
            self._langs_cache = tesseract_languages(self.tools["tesseract"]) if self.tools.get("tesseract") else []
        if not self._langs_cache:
            edit.setToolTip("Tesseract tidak ditemukan — ketik kode bahasa manual (mis. ind+eng).")
            return
        dlg = LanguageDialog(self._langs_cache, edit.text(), self)
        if dlg.exec_() == QDialog.Accepted and dlg.result_text():
            edit.setText(dlg.result_text())

    def _toggle_adv(self, on: bool):
        self.adv_box.setVisible(on)
        self.adv_toggle.setText("Lanjutan ▾" if on else "Lanjutan ▸")

    # ---- nilai ----
    def values(self) -> dict:
        out = {}
        for opt in self.engine.options:
            w = self._widgets[opt.key]
            if opt.kind == S.BOOL:
                out[opt.key] = w.isChecked()
            elif opt.kind in (S.INT, S.FLOAT):
                out[opt.key] = w.value()
            elif opt.kind == S.CHOICE:
                out[opt.key] = w.itemData(w.currentIndex())
            elif opt.kind == S.LANGS:
                out[opt.key] = w._edit.text().strip()
            else:
                out[opt.key] = w.text()
        return out

    def set_values(self, values: dict):
        vals = self.engine.options.normalize(values)
        self._building = True
        try:
            for opt in self.engine.options:
                w, v = self._widgets[opt.key], vals[opt.key]
                if opt.kind == S.BOOL:
                    w.setChecked(bool(v))
                elif opt.kind in (S.INT, S.FLOAT):
                    w.setValue(v)
                elif opt.kind == S.CHOICE:
                    idx = w.findData(v)
                    w.setCurrentIndex(idx if idx >= 0 else 0)
                elif opt.kind == S.LANGS:
                    w._edit.setText(str(v))
                else:
                    w.setText(str(v))
        finally:
            self._building = False
        self._apply_enabled()
        self.changed.emit()

    def reset_defaults(self):
        self.set_values(self.engine.options.defaults())

    # ---- ketersediaan ----
    def refresh_availability(self, tools: dict):
        self.tools = tools
        self._notes = self.engine.option_notes(tools)
        self._apply_enabled()

    def _apply_enabled(self):
        vals = self.values()
        for opt in self.engine.options:
            w = self._widgets[opt.key]
            enabled, reason = True, ""
            if opt.enabled_if is not None and not opt.enabled_if(vals):
                enabled, reason = False, "Tidak berlaku untuk pengaturan saat ini"
            note = getattr(self, "_notes", {}).get(opt.key)
            if note:
                if not note[0]:
                    enabled, reason = False, note[1]
                elif note[1] and enabled:
                    reason = note[1]
            w.setEnabled(enabled)
            tip = self._base_tip[opt.key] + (f"\n\n⚠ {reason}" if reason else "")
            w.setToolTip(tip)
            if opt.key in self._labels:
                self._labels[opt.key].setToolTip(tip)

    def _on_changed(self, *_):
        if self._building:
            return
        self._apply_enabled()
        self.changed.emit()
