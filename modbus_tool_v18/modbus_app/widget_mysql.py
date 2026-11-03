"""Panel isian koneksi MySQL, dipakai tab Data Logger CSV dan tab Daftar Tag."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QCheckBox, QFrame, QGridLayout, QGroupBox, QLabel, QLineEdit, QScrollArea, QSpinBox


def bungkus_scroll(widget, lebar_maks=350):
    """Bungkus panel pengaturan (kolom kiri tab) dengan area gulir, supaya tetap
    terjangkau di layar pendek walau isiannya banyak."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(widget)
    area.setMaximumWidth(lebar_maks)
    return area


class PanelMySQL(QGroupBox):
    """Kelompok isian: aktif/tidak, host, port, user, kata sandi, database, tabel.

    Kata sandi sengaja TIDAK ikut disimpan ke preset (lihat `pengaturan`),
    karena preset adalah berkas JSON teks biasa."""

    def __init__(self, judul, label_aktif, tabel_bawaan, parent=None):
        super().__init__(judul, parent)
        grid = QGridLayout(self)

        self.chk = QCheckBox(label_aktif)
        self.chk.setToolTip(
            "Menulis baris data yang sama dengan CSV ke tabel MySQL.\n"
            "Butuh paket 'pymysql' ter-install (lihat requirements.txt).\n"
            "Kata sandi tidak disimpan ke preset/pengaturan otomatis."
        )
        grid.addWidget(self.chk, 0, 0, 1, 2)

        grid.addWidget(QLabel("Host:"), 1, 0)
        self.txt_host = QLineEdit("localhost")
        grid.addWidget(self.txt_host, 1, 1)

        grid.addWidget(QLabel("Port:"), 2, 0)
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(3306)
        grid.addWidget(self.spin_port, 2, 1)

        grid.addWidget(QLabel("User:"), 3, 0)
        self.txt_user = QLineEdit("root")
        grid.addWidget(self.txt_user, 3, 1)

        grid.addWidget(QLabel("Password:"), 4, 0)
        self.txt_pass = QLineEdit()
        self.txt_pass.setEchoMode(QLineEdit.Password)
        grid.addWidget(self.txt_pass, 4, 1)

        grid.addWidget(QLabel("Database:"), 5, 0)
        self.txt_db = QLineEdit("modbus")
        grid.addWidget(self.txt_db, 5, 1)

        grid.addWidget(QLabel("Tabel:"), 6, 0)
        self.txt_tabel = QLineEdit(tabel_bawaan)
        grid.addWidget(self.txt_tabel, 6, 1)

        self._widget_isian = [self.chk, self.txt_host, self.spin_port, self.txt_user,
                              self.txt_pass, self.txt_db, self.txt_tabel]

    def aktif(self):
        return self.chk.isChecked()

    def konfigurasi(self):
        """Parameter koneksi untuk MySQLDataLogger (termasuk kata sandi)."""
        return {
            'host': self.txt_host.text().strip(),
            'port': self.spin_port.value(),
            'user': self.txt_user.text().strip(),
            'password': self.txt_pass.text(),
            'database': self.txt_db.text().strip(),
            'table': self.txt_tabel.text().strip(),
        }

    def pengaturan(self):
        """Isian untuk preset: TANPA kata sandi."""
        data = self.konfigurasi()
        data.pop('password')
        data['aktif'] = self.chk.isChecked()
        return data

    def terapkan(self, data):
        """Terapkan isian dari preset; kunci yang tidak ada dibiarkan apa adanya."""
        if not isinstance(data, dict):
            return
        if 'host' in data:
            self.txt_host.setText(str(data['host']))
        if 'port' in data:
            try:
                self.spin_port.setValue(int(data['port']))
            except (TypeError, ValueError):
                pass
        if 'user' in data:
            self.txt_user.setText(str(data['user']))
        if 'database' in data:
            self.txt_db.setText(str(data['database']))
        if 'table' in data:
            self.txt_tabel.setText(str(data['table']))
        if 'aktif' in data:
            self.chk.setChecked(bool(data['aktif']))

    def widget_isian(self):
        return list(self._widget_isian)

    def kunci(self, kunci):
        """Kunci/lepas semua isian (dipakai selama logging berjalan)."""
        for w in self._widget_isian:
            w.setEnabled(not kunci)
