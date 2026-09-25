#!/usr/bin/env python3
"""
QtQR Clone - Aplikasi PyQt5 untuk generate QR Code (+ scan opsional)
Terinspirasi dari aplikasi QtQR.

Fitur Generate:
- Tipe data: Teks/URL, vCard, WiFi, SMS, Email, Lokasi (Geo)
- Kustomisasi warna, ukuran, error correction, logo di tengah
- Export PNG/JPG/BMP dan SVG (vektor)
- Batch generate dari file CSV

Fitur Umum:
- Mode gelap
- Riwayat generate & scan dengan pencarian + export CSV
- Shortcut keyboard
"""

import sys
import os
import csv
import json
import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLabel, QPushButton, QComboBox, QSpinBox,
    QFileDialog, QColorDialog, QMessageBox, QListWidget, QListWidgetItem,
    QGroupBox, QTextEdit, QStatusBar, QAction, QStackedWidget, QLineEdit,
    QCheckBox, QShortcut
)
from PyQt5.QtGui import QPixmap, QImage, QColor, QKeySequence
from PyQt5.QtCore import Qt, QTimer

import qrcode
import qrcode.image.svg
from qrcode.constants import ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, ERROR_CORRECT_H
from PIL import Image

try:
    import cv2
    HAS_CV2 = True
    # opencv-python bundles its own Qt platform plugins (cv2/qt/plugins) and
    # points QT_QPA_PLATFORM_PLUGIN_PATH at them on import, which can silently
    # override PyQt5's plugin path and break "xcb"/"wayland" loading at
    # QApplication() startup. Strip that override so PyQt5 uses its own
    # plugins instead. (Best fix: install opencv-python-headless instead.)
    os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
    os.environ.pop("QT_PLUGIN_PATH", None)
except ImportError:
    HAS_CV2 = False

try:
    from pyzbar.pyzbar import decode as zbar_decode
    HAS_PYZBAR = True
except ImportError:
    HAS_PYZBAR = False


HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".qtqr_clone_history.json")

DARK_STYLESHEET = """
QWidget { background-color: #2b2b2b; color: #e0e0e0; }
QLineEdit, QTextEdit, QComboBox, QSpinBox, QListWidget {
    background-color: #3c3c3c; color: #e0e0e0; border: 1px solid #555;
}
QPushButton {
    background-color: #454545; color: #e0e0e0; border: 1px solid #5a5a5a;
    padding: 5px; border-radius: 3px;
}
QPushButton:hover { background-color: #545454; }
QPushButton:disabled { color: #888; }
QGroupBox { border: 1px solid #555; margin-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }
QMenuBar, QMenu { background-color: #2b2b2b; color: #e0e0e0; }
QMenu::item:selected { background-color: #454545; }
QStatusBar { background-color: #2b2b2b; color: #e0e0e0; }
"""


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def pil2pixmap(im: Image.Image) -> QPixmap:
    im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    qim = QImage(data, im.width, im.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qim)


def escape_field(value: str) -> str:
    """Escape backslash, semicolon, comma, colon for WiFi/vCard-like QR payloads."""
    value = value.replace("\\", "\\\\")
    for ch in [";", ",", ":"]:
        value = value.replace(ch, "\\" + ch)
    return value


ERROR_LEVELS = {
    "L - Low (7%)": ERROR_CORRECT_L,
    "M - Medium (15%)": ERROR_CORRECT_M,
    "Q - Quartile (25%)": ERROR_CORRECT_Q,
    "H - High (30%)": ERROR_CORRECT_H,
}

DATA_TYPES = ["Teks / URL", "vCard (Kontak)", "WiFi", "SMS", "Email", "Lokasi (Geo)"]


class GenerateTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.fill_color = "#000000"
        self.back_color = "#ffffff"
        self.logo_path = None
        self.current_qr_image = None
        self.current_data = None
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        main_layout = QHBoxLayout(self)

        left = QWidget()
        form_layout = QFormLayout(left)

        self.type_combo = QComboBox()
        self.type_combo.addItems(DATA_TYPES)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        form_layout.addRow(QLabel("Tipe Data:"), self.type_combo)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_text_page())
        self.stack.addWidget(self._build_vcard_page())
        self.stack.addWidget(self._build_wifi_page())
        self.stack.addWidget(self._build_sms_page())
        self.stack.addWidget(self._build_email_page())
        self.stack.addWidget(self._build_geo_page())
        form_layout.addRow(self.stack)

        self.error_combo = QComboBox()
        self.error_combo.addItems(list(ERROR_LEVELS.keys()))
        self.error_combo.setCurrentIndex(1)
        form_layout.addRow(QLabel("Koreksi Error:"), self.error_combo)

        self.box_size_spin = QSpinBox()
        self.box_size_spin.setRange(1, 50)
        self.box_size_spin.setValue(10)
        form_layout.addRow(QLabel("Ukuran Kotak:"), self.box_size_spin)

        self.border_spin = QSpinBox()
        self.border_spin.setRange(0, 20)
        self.border_spin.setValue(4)
        form_layout.addRow(QLabel("Border:"), self.border_spin)

        color_layout = QHBoxLayout()
        self.fill_color_btn = QPushButton("Warna Depan")
        self.fill_color_btn.clicked.connect(self.pick_fill_color)
        self.back_color_btn = QPushButton("Warna Latar")
        self.back_color_btn.clicked.connect(self.pick_back_color)
        color_layout.addWidget(self.fill_color_btn)
        color_layout.addWidget(self.back_color_btn)
        form_layout.addRow(QLabel("Warna:"), color_layout)

        logo_layout = QHBoxLayout()
        self.logo_btn = QPushButton("Pilih Logo...")
        self.logo_btn.clicked.connect(self.pick_logo)
        self.logo_clear_btn = QPushButton("Hapus Logo")
        self.logo_clear_btn.clicked.connect(self.clear_logo)
        logo_layout.addWidget(self.logo_btn)
        logo_layout.addWidget(self.logo_clear_btn)
        form_layout.addRow(QLabel("Logo (opsional):"), logo_layout)

        self.generate_btn = QPushButton("Generate QR Code  (Ctrl+G)")
        self.generate_btn.setStyleSheet("font-weight: bold; padding: 8px;")
        self.generate_btn.setShortcut("Ctrl+G")
        self.generate_btn.clicked.connect(self.generate_qr)
        form_layout.addRow(self.generate_btn)

        self.save_btn = QPushButton("Simpan Sebagai...  (Ctrl+S)")
        self.save_btn.setShortcut("Ctrl+S")
        self.save_btn.clicked.connect(self.save_qr)
        self.save_btn.setEnabled(False)
        form_layout.addRow(self.save_btn)

        copy_layout = QHBoxLayout()
        self.copy_image_btn = QPushButton("Salin Gambar  (Ctrl+C)")
        self.copy_image_btn.setShortcut("Ctrl+C")
        self.copy_image_btn.clicked.connect(self.copy_image_to_clipboard)
        self.copy_image_btn.setEnabled(False)
        self.copy_text_btn = QPushButton("Salin Teks Data")
        self.copy_text_btn.clicked.connect(self.copy_text_to_clipboard)
        self.copy_text_btn.setEnabled(False)
        copy_layout.addWidget(self.copy_image_btn)
        copy_layout.addWidget(self.copy_text_btn)
        form_layout.addRow(copy_layout)

        self.batch_btn = QPushButton("Batch Generate dari CSV...")
        self.batch_btn.clicked.connect(self.batch_generate)
        form_layout.addRow(self.batch_btn)

        main_layout.addWidget(left, 1)

        right = QGroupBox("Preview")
        right_layout = QVBoxLayout(right)
        self.preview_label = QLabel("Belum ada QR code")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(320, 320)
        self.preview_label.setStyleSheet("border: 1px solid #999; background: white; color: black;")
        right_layout.addWidget(self.preview_label)
        main_layout.addWidget(right, 1)

    def _build_text_page(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText("Masukkan teks, URL, atau data lain di sini...")
        self.text_input.setFixedHeight(100)
        layout.addWidget(self.text_input)
        return w

    def _build_vcard_page(self):
        w = QWidget()
        layout = QFormLayout(w)
        self.vc_name = QLineEdit()
        self.vc_phone = QLineEdit()
        self.vc_email = QLineEdit()
        self.vc_company = QLineEdit()
        layout.addRow("Nama Lengkap:", self.vc_name)
        layout.addRow("Telepon:", self.vc_phone)
        layout.addRow("Email:", self.vc_email)
        layout.addRow("Perusahaan:", self.vc_company)
        return w

    def _build_wifi_page(self):
        w = QWidget()
        layout = QFormLayout(w)
        self.wifi_ssid = QLineEdit()
        self.wifi_password = QLineEdit()
        self.wifi_enc = QComboBox()
        self.wifi_enc.addItems(["WPA/WPA2", "WEP", "Tanpa Password"])
        self.wifi_hidden = QCheckBox("Jaringan Tersembunyi")
        layout.addRow("SSID:", self.wifi_ssid)
        layout.addRow("Password:", self.wifi_password)
        layout.addRow("Enkripsi:", self.wifi_enc)
        layout.addRow("", self.wifi_hidden)
        return w

    def _build_sms_page(self):
        w = QWidget()
        layout = QFormLayout(w)
        self.sms_number = QLineEdit()
        self.sms_message = QTextEdit()
        self.sms_message.setFixedHeight(70)
        layout.addRow("Nomor Tujuan:", self.sms_number)
        layout.addRow("Pesan:", self.sms_message)
        return w

    def _build_email_page(self):
        w = QWidget()
        layout = QFormLayout(w)
        self.email_address = QLineEdit()
        self.email_subject = QLineEdit()
        self.email_body = QTextEdit()
        self.email_body.setFixedHeight(70)
        layout.addRow("Alamat Email:", self.email_address)
        layout.addRow("Subjek:", self.email_subject)
        layout.addRow("Isi Pesan:", self.email_body)
        return w

    def _build_geo_page(self):
        w = QWidget()
        layout = QFormLayout(w)
        self.geo_lat = QLineEdit()
        self.geo_lat.setPlaceholderText("-6.9932")
        self.geo_lng = QLineEdit()
        self.geo_lng.setPlaceholderText("110.4203")
        layout.addRow("Latitude:", self.geo_lat)
        layout.addRow("Longitude:", self.geo_lng)
        return w

    def _on_type_changed(self, index):
        self.stack.setCurrentIndex(index)

    # ---------- Data composing ----------
    def _compose_data(self):
        idx = self.type_combo.currentIndex()
        if idx == 0:
            return self.text_input.toPlainText().strip()
        elif idx == 1:
            name = self.vc_name.text().strip()
            if not name:
                return ""
            lines = [
                "BEGIN:VCARD", "VERSION:3.0",
                f"N:{escape_field(name)}", f"FN:{escape_field(name)}",
            ]
            if self.vc_phone.text().strip():
                lines.append(f"TEL:{escape_field(self.vc_phone.text().strip())}")
            if self.vc_email.text().strip():
                lines.append(f"EMAIL:{escape_field(self.vc_email.text().strip())}")
            if self.vc_company.text().strip():
                lines.append(f"ORG:{escape_field(self.vc_company.text().strip())}")
            lines.append("END:VCARD")
            return "\n".join(lines)
        elif idx == 2:
            ssid = self.wifi_ssid.text().strip()
            if not ssid:
                return ""
            enc_map = {"WPA/WPA2": "WPA", "WEP": "WEP", "Tanpa Password": "nopass"}
            enc = enc_map[self.wifi_enc.currentText()]
            password = self.wifi_password.text().strip()
            hidden = "true" if self.wifi_hidden.isChecked() else "false"
            pwd_part = f"P:{escape_field(password)};" if enc != "nopass" else ""
            return f"WIFI:T:{enc};S:{escape_field(ssid)};{pwd_part}H:{hidden};;"
        elif idx == 3:
            number = self.sms_number.text().strip()
            if not number:
                return ""
            message = self.sms_message.toPlainText().strip()
            return f"SMSTO:{number}:{message}"
        elif idx == 4:
            address = self.email_address.text().strip()
            if not address:
                return ""
            subject = self.email_subject.text().strip()
            body = self.email_body.toPlainText().strip()
            from urllib.parse import quote
            return f"mailto:{address}?subject={quote(subject)}&body={quote(body)}"
        elif idx == 5:
            lat = self.geo_lat.text().strip()
            lng = self.geo_lng.text().strip()
            if not lat or not lng:
                return ""
            return f"geo:{lat},{lng}"
        return ""

    # ---------- Colors / logo ----------
    def pick_fill_color(self):
        color = QColorDialog.getColor(QColor(self.fill_color), self, "Pilih Warna Depan")
        if color.isValid():
            self.fill_color = color.name()

    def pick_back_color(self):
        color = QColorDialog.getColor(QColor(self.back_color), self, "Pilih Warna Latar")
        if color.isValid():
            self.back_color = color.name()

    def pick_logo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Pilih Gambar Logo", "", "Gambar (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            self.logo_path = path

    def clear_logo(self):
        self.logo_path = None

    # ---------- QR building ----------
    def _current_error_level(self):
        level = ERROR_LEVELS[self.error_combo.currentText()]
        if self.logo_path and level != ERROR_CORRECT_H:
            level = ERROR_CORRECT_H
        return level

    def _build_qr_image(self, data, image_factory=None):
        qr = qrcode.QRCode(
            version=None,
            error_correction=self._current_error_level(),
            box_size=self.box_size_spin.value(),
            border=self.border_spin.value(),
        )
        qr.add_data(data)
        qr.make(fit=True)
        if image_factory is not None:
            return qr.make_image(image_factory=image_factory, fill_color=self.fill_color,
                                  back_color=self.back_color)
        return qr.make_image(fill_color=self.fill_color, back_color=self.back_color).convert("RGB")

    def _apply_logo(self, img):
        if self.logo_path and os.path.exists(self.logo_path):
            try:
                logo = Image.open(self.logo_path)
                qr_w, qr_h = img.size
                logo_size = int(qr_w * 0.22)
                logo.thumbnail((logo_size, logo_size), Image.LANCZOS)
                pos = ((qr_w - logo.width) // 2, (qr_h - logo.height) // 2)
                if logo.mode in ("RGBA", "LA"):
                    img.paste(logo, pos, logo)
                else:
                    img.paste(logo, pos)
            except Exception as e:
                QMessageBox.warning(self, "Peringatan", f"Gagal menambahkan logo: {e}")
        return img

    def generate_qr(self):
        data = self._compose_data()
        if not data:
            QMessageBox.warning(self, "Peringatan", "Data tidak boleh kosong / belum lengkap.")
            return

        img = self._build_qr_image(data)
        img = self._apply_logo(img)

        self.current_qr_image = img
        self.current_data = data
        pixmap = pil2pixmap(img)
        scaled = pixmap.scaled(
            self.preview_label.width(), self.preview_label.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.preview_label.setPixmap(scaled)
        self.save_btn.setEnabled(True)
        self.copy_image_btn.setEnabled(True)
        self.copy_text_btn.setEnabled(True)

        main_window = self.window()
        if hasattr(main_window, "add_generate_history"):
            main_window.add_generate_history(data)

    def copy_image_to_clipboard(self):
        if self.current_qr_image is None:
            return
        QApplication.clipboard().setPixmap(pil2pixmap(self.current_qr_image))
        main_window = self.window()
        if hasattr(main_window, "statusBar"):
            main_window.statusBar().showMessage("Gambar QR disalin ke clipboard", 3000)

    def copy_text_to_clipboard(self):
        if not self.current_data:
            return
        QApplication.clipboard().setText(self.current_data)
        main_window = self.window()
        if hasattr(main_window, "statusBar"):
            main_window.statusBar().showMessage("Teks data disalin ke clipboard", 3000)

    def save_qr(self):
        if self.current_qr_image is None:
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Simpan QR Code", "qrcode.png",
            "PNG (*.png);;JPEG (*.jpg);;Bitmap (*.bmp);;SVG Vektor (*.svg)"
        )
        if not path:
            return
        try:
            if path.lower().endswith(".svg"):
                if self.logo_path:
                    QMessageBox.information(
                        self, "Info", "Logo tidak didukung pada format SVG, akan diexport tanpa logo."
                    )
                svg_img = self._build_qr_image(self.current_data, image_factory=qrcode.image.svg.SvgPathImage)
                svg_img.save(path)
            else:
                self.current_qr_image.save(path)
            QMessageBox.information(self, "Sukses", f"QR code disimpan di:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Gagal menyimpan: {e}")

    # ---------- Batch generate ----------
    def batch_generate(self):
        csv_path, _ = QFileDialog.getOpenFileName(
            self, "Pilih File CSV (kolom 'data', opsional 'filename')", "", "CSV (*.csv)"
        )
        if not csv_path:
            return

        out_dir = QFileDialog.getExistingDirectory(self, "Pilih Folder Output")
        if not out_dir:
            return

        try:
            with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Gagal membaca CSV: {e}")
            return

        if not rows or "data" not in (reader.fieldnames or []):
            QMessageBox.warning(self, "Peringatan", "CSV harus memiliki kolom bernama 'data'.")
            return

        success, failed = 0, 0
        for i, row in enumerate(rows, start=1):
            data = (row.get("data") or "").strip()
            if not data:
                failed += 1
                continue
            filename = (row.get("filename") or "").strip() or f"qr_{i:03d}"
            if not filename.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
                filename += ".png"
            try:
                img = self._build_qr_image(data)
                img = self._apply_logo(img)
                img.save(os.path.join(out_dir, filename))
                success += 1
            except Exception:
                failed += 1

        QMessageBox.information(
            self, "Selesai Batch Generate",
            f"Berhasil: {success}\nGagal: {failed}\nDisimpan di:\n{out_dir}"
        )


class ScanTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.capture = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)

        left = QVBoxLayout()
        self.video_label = QLabel("Kamera tidak aktif")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(400, 320)
        self.video_label.setStyleSheet("border: 1px solid #999; background: #222; color: white;")
        left.addWidget(self.video_label)

        btn_layout = QHBoxLayout()
        self.start_cam_btn = QPushButton("Mulai Kamera")
        self.start_cam_btn.clicked.connect(self.start_camera)
        self.stop_cam_btn = QPushButton("Stop Kamera")
        self.stop_cam_btn.clicked.connect(self.stop_camera)
        self.stop_cam_btn.setEnabled(False)
        self.load_img_btn = QPushButton("Buka Gambar QR...")
        self.load_img_btn.clicked.connect(self.load_image)
        btn_layout.addWidget(self.start_cam_btn)
        btn_layout.addWidget(self.stop_cam_btn)
        btn_layout.addWidget(self.load_img_btn)
        left.addLayout(btn_layout)

        if not HAS_CV2:
            self.start_cam_btn.setEnabled(False)
            self.stop_cam_btn.setEnabled(False)
            self.video_label.setText("OpenCV tidak terinstall.\nInstall dengan: pip install opencv-python-headless")
        if not HAS_PYZBAR:
            self.load_img_btn.setEnabled(False)

        layout.addLayout(left, 2)

        right = QGroupBox("Hasil Scan")
        right_layout = QVBoxLayout(right)
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.copy_btn = QPushButton("Salin Hasil")
        self.copy_btn.clicked.connect(self.copy_result)
        right_layout.addWidget(self.result_text)
        right_layout.addWidget(self.copy_btn)
        layout.addWidget(right, 1)

    def start_camera(self):
        if not HAS_CV2:
            QMessageBox.warning(self, "Peringatan", "OpenCV belum terinstall.")
            return
        self.capture = cv2.VideoCapture(0)
        if not self.capture.isOpened():
            QMessageBox.critical(self, "Error", "Tidak bisa membuka kamera.")
            self.capture = None
            return
        self.timer.start(30)
        self.start_cam_btn.setEnabled(False)
        self.stop_cam_btn.setEnabled(True)

    def stop_camera(self):
        self.timer.stop()
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        self.video_label.setText("Kamera tidak aktif")
        self.start_cam_btn.setEnabled(True)
        self.stop_cam_btn.setEnabled(False)

    def update_frame(self):
        if self.capture is None:
            return
        ret, frame = self.capture.read()
        if not ret:
            return

        if HAS_PYZBAR:
            decoded_objects = zbar_decode(frame)
            for obj in decoded_objects:
                data = obj.data.decode("utf-8", errors="replace")
                self._report_result(data)
                pts = obj.polygon
                if len(pts) > 0:
                    import numpy as np
                    pts_arr = [(p.x, p.y) for p in pts]
                    cv2.polylines(frame, [np.array(pts_arr)], True, (0, 255, 0), 3)

        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        qimg = QImage(rgb_image.data, w, h, ch * w, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg).scaled(
            self.video_label.width(), self.video_label.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.video_label.setPixmap(pixmap)

    def load_image(self):
        if not HAS_PYZBAR:
            QMessageBox.warning(self, "Peringatan", "pyzbar belum terinstall.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Buka Gambar", "", "Gambar (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return
        try:
            img = Image.open(path)
            results = zbar_decode(img)
            if not results:
                QMessageBox.information(self, "Info", "Tidak ada QR code terdeteksi pada gambar ini.")
                return
            for obj in results:
                data = obj.data.decode("utf-8", errors="replace")
                self._report_result(data)
            pixmap = pil2pixmap(img).scaled(
                self.video_label.width(), self.video_label.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.video_label.setPixmap(pixmap)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Gagal membaca gambar: {e}")

    def _report_result(self, data):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {data}"
        if line not in self.result_text.toPlainText():
            self.result_text.append(line)
            main_window = self.window()
            if hasattr(main_window, "add_scan_history"):
                main_window.add_scan_history(data)

    def copy_result(self):
        text = self.result_text.toPlainText()
        if text:
            QApplication.clipboard().setText(text)

    def closeEvent(self, event):
        self.stop_camera()
        event.accept()


class HistoryTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.history = load_history()
        self._build_ui()
        self._reload()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Cari riwayat...  (Ctrl+F)")
        self.search_box.textChanged.connect(self._reload)
        layout.addWidget(self.search_box)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        clear_btn = QPushButton("Hapus Riwayat")
        clear_btn.clicked.connect(self.clear_history)
        export_btn = QPushButton("Export CSV...")
        export_btn.clicked.connect(self.export_csv)
        btn_layout.addWidget(clear_btn)
        btn_layout.addWidget(export_btn)
        layout.addLayout(btn_layout)

    def _reload(self):
        query = self.search_box.text().strip().lower()
        self.list_widget.clear()
        for entry in reversed(self.history):
            text = f"[{entry['time']}] ({entry['type']}) {entry['data']}"
            if query and query not in text.lower():
                continue
            self.list_widget.addItem(QListWidgetItem(text))

    def add_entry(self, entry_type, data):
        entry = {
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type": entry_type,
            "data": data,
        }
        self.history.append(entry)
        save_history(self.history)
        self._reload()

    def clear_history(self):
        reply = QMessageBox.question(
            self, "Konfirmasi", "Hapus semua riwayat?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.history = []
            save_history(self.history)
            self._reload()

    def export_csv(self):
        if not self.history:
            QMessageBox.information(self, "Info", "Riwayat masih kosong.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Riwayat", "riwayat.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["time", "type", "data"])
                writer.writeheader()
                writer.writerows(self.history)
            QMessageBox.information(self, "Sukses", f"Riwayat diexport ke:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Gagal export: {e}")

    def focus_search(self):
        self.search_box.setFocus()
        self.search_box.selectAll()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QtQR Clone - PyQt5 QR Code Generator & Scanner")
        self.resize(950, 580)
        self.dark_mode = False

        self.tabs = QTabWidget()
        self.generate_tab = GenerateTab()
        self.scan_tab = ScanTab()
        self.history_tab = HistoryTab()

        self.tabs.addTab(self.generate_tab, "Generate")
        self.tabs.addTab(self.scan_tab, "Scan")
        self.tabs.addTab(self.history_tab, "Riwayat")

        self.setCentralWidget(self.tabs)
        self.setStatusBar(QStatusBar())
        self._build_menu()
        self._build_shortcuts()

    def _build_menu(self):
        menu = self.menuBar()
        file_menu = menu.addMenu("File")
        exit_action = QAction("Keluar", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = menu.addMenu("Tampilan")
        self.dark_action = QAction("Mode Gelap", self, checkable=True)
        self.dark_action.setShortcut("Ctrl+D")
        self.dark_action.triggered.connect(self.toggle_dark_mode)
        view_menu.addAction(self.dark_action)

        help_menu = menu.addMenu("Bantuan")
        about_action = QAction("Tentang", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def _build_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.history_tab.focus_search)

    def toggle_dark_mode(self, checked):
        self.dark_mode = checked
        QApplication.instance().setStyleSheet(DARK_STYLESHEET if checked else "")

    def show_about(self):
        QMessageBox.information(
            self, "Tentang",
            "QtQR Clone\n\nAplikasi PyQt5 untuk generate dan scan QR code,\n"
            "terinspirasi dari QtQR.\n\nDibuat dengan PyQt5, qrcode, Pillow, OpenCV, pyzbar."
        )

    def add_generate_history(self, text):
        self.history_tab.add_entry("Generate", text)

    def add_scan_history(self, data):
        self.history_tab.add_entry("Scan", data)

    def closeEvent(self, event):
        self.scan_tab.stop_camera()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("QtQR Clone")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
