"""Pengelolaan penulis MySQL (tab Data Logger dan Daftar Tag)."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from .konfigurasi import catat_kesalahan
from .inti import MySQLDataLogger, pesan_error_mysql
from .worker import PenulisMySQLThread

# Batas tunggu (ms) saat aplikasi ditutup: sisa antrean dikuras paling lama
# PenulisMySQLThread.BATAS_KURAS_DETIK, ditambah satu operasi yang sedang berjalan
# (dibatasi MySQLDataLogger: connect 5 detik, baca/tulis 10 detik). Jika masih belum
# selesai, thread dihentikan paksa sebagai jalan terakhir.
BATAS_TUNGGU_TUTUP_MS = 9000


class MySQLMixin:
    """Satu penulis MySQL (thread + antrean) per sumber data: 'logger' dan 'tag'."""

    def _siapkan_penulis_mysql(self, kunci, panel, daftar_label, monitor, tabel_bawaan):
        """Sambung ke MySQL, siapkan tabel, lalu jalankan thread penulis untuk
        `kunci`. Mengembalikan True bila siap; False (dengan pesan di `monitor`)
        bila gagal -- pemanggil harus membatalkan pengambilan data. Langkah
        penyiapan berjalan di thread GUI dan paling lama beberapa detik."""
        self._hentikan_penulis_mysql(kunci)
        konf = panel.konfigurasi()
        pencatat = MySQLDataLogger(
            host=konf['host'], port=konf['port'], user=konf['user'],
            password=konf['password'], database=konf['database'],
            table=konf['table'] or tabel_bawaan,
        )
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            pencatat.siapkan_tabel(daftar_label)
        except Exception as e:
            catat_kesalahan(f"Setup MySQL ({kunci})", e)
            self._log_dibatasi(
                monitor, f"<font color='red'>Gagal terhubung ke MySQL: {pesan_error_mysql(e)}</font>")
            return False
        finally:
            QApplication.restoreOverrideCursor()

        th = PenulisMySQLThread(pencatat)
        th.sinyal_log.connect(lambda pesan, m=monitor: self._log_dibatasi(m, pesan))
        self._penulis_mysql[kunci] = (th, list(daftar_label))
        th.start()
        self._log_dibatasi(
            monitor, f"<font color='#3498db'>[Info] Terhubung ke MySQL, tabel `{pencatat.table}` siap.</font>")
        return True

    def _kirim_ke_mysql(self, kunci, stempel, daftar_nilai):
        """Antrekan satu baris untuk ditulis. Tidak melakukan apa-apa bila
        penulis `kunci` tidak aktif (MySQL tidak diaktifkan)."""
        entri = self._penulis_mysql.get(kunci)
        if entri:
            th, daftar_label = entri
            th.kirim(stempel, daftar_label, daftar_nilai)

    def _hentikan_penulis_mysql(self, kunci):
        """Minta penulis `kunci` berhenti setelah sisa antreannya tertulis. Objek
        thread disimpan sampai benar-benar selesai agar tidak terhapus (garbage
        collected) saat masih berjalan."""
        entri = self._penulis_mysql.pop(kunci, None)
        self._penulis_mysql_lama = [t for t in self._penulis_mysql_lama if t.isRunning()]
        if entri:
            th = entri[0]
            th.berhenti()
            self._penulis_mysql_lama.append(th)

    def _matikan_semua_penulis_mysql(self):
        """Dipakai saat aplikasi ditutup: hentikan semua penulis dan tunggu sebentar."""
        for kunci in list(self._penulis_mysql):
            self._hentikan_penulis_mysql(kunci)
        for th in self._penulis_mysql_lama:
            if th.isRunning():
                th.wait(BATAS_TUNGGU_TUTUP_MS)
            if th.isRunning():       # database tidak menjawab: jangan tahan penutupan aplikasi
                th.terminate()
                th.wait(500)
        self._penulis_mysql_lama = []
