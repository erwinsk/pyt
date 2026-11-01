"""Thread pekerja (QThread): scan, polling/logging, pembacaan tag, dan penulisan."""
import copy
import time
import struct
from datetime import datetime

from PyQt5.QtCore import QThread, pyqtSignal

from .konfigurasi import *  # noqa: F401,F403
from .inti import *  # noqa: F401,F403

# =====================================================================
# THREAD WORKERS
# =====================================================================
class ModbusScannerThread(QThread):
    sinyal_progres = pyqtSignal(int, str)
    sinyal_hasil   = pyqtSignal(list)
    sinyal_selesai = pyqtSignal()
    sinyal_error   = pyqtSignal(str) 

    def __init__(self, client_global, jenis_scan="id", parameter_scan=None):
        super().__init__()
        self.client = client_global
        self.jenis_scan = jenis_scan
        self.parameter_scan = parameter_scan or {}
        self.apakah_berjalan = True

    def run(self):
        # Scan Device ID: ID yang tidak ada perangkatnya pasti timeout. Dengan
        # retry bawaan (mis. 3x) tiap ID kosong memakan timeout x 4 sehingga
        # scan 255 ID bisa lebih dari 15 menit. Selama scan ID, retry
        # diturunkan ke 0 lalu dipulihkan setelah selesai.
        retries_lama = []
        if self.jenis_scan == "id" and self.client:
            retries_lama = atur_retries_client(self.client, 0)
        try:
            self._jalankan_pemindaian()
        finally:
            pulihkan_retries_client(retries_lama)

    def _jalankan_pemindaian(self):
        if not self.client or not client_terhubung(self.client):
            self.sinyal_error.emit("Master Modbus Utama belum terhubung!")
            self.sinyal_selesai.emit()
            return
        hasil = []
        if self.jenis_scan == "id":
            id_awal  = int(self.parameter_scan.get('id_awal', 1))
            id_akhir = int(self.parameter_scan.get('id_akhir', 247))
            tipe_reg = self.parameter_scan.get('tipe_reg', 'Holding')
            reg_uji  = int(self.parameter_scan.get('reg_uji', 0))
            total    = id_akhir - id_awal + 1

            # FIX PERFORMA: sebelumnya sinyal progres dikirim di SETIAP
            # iterasi (untuk scan ID bisa sampai 255x, untuk scan register
            # bisa puluhan ribu kali). Tiap emit sinyal antar-thread masuk
            # ke antrean event loop GUI dan memicu update label/progress bar
            # - pada scan register dengan rentang besar, ini bisa membanjiri
            # event loop dan membuat UI terasa lag walau scan sendiri
            # berjalan di background thread. Sekarang progres hanya dikirim
            # saat NILAI PERSENnya berubah (maksimum ~100 kali per scan,
            # berapa pun jumlah alamat yang dipindai).
            progres_terakhir = -1
            for idx, slave_id in enumerate(range(id_awal, id_akhir + 1)):
                if not self.apakah_berjalan: break
                progres = int(((idx + 1) / total) * 100)
                if progres != progres_terakhir:
                    self.sinyal_progres.emit(progres, f"Memindai Device ID: {slave_id}...")
                    progres_terakhir = progres

                kunci_komunikasi.lock()
                try:
                    res = baca_register_modbus(self.client, tipe_reg, reg_uji, 1, slave_id)
                    if res and not res.isError():
                        hasil.append((slave_id, "MERESPON"))
                        statistik_global.catat_sukses()
                    elif res:
                        statistik_global.catat_gagal()
                except Exception as e:
                    adalah_timeout = "timeout" in str(e).lower() or "time out" in str(e).lower()
                    statistik_global.catat_gagal(adalah_timeout=adalah_timeout)
                    catat_kesalahan(f"Scan ID {slave_id}", e)
                    self.sinyal_error.emit(f"Error saat scan ID {slave_id}: {str(e)}")
                finally:
                    kunci_komunikasi.unlock()
                time.sleep(0.02)

        elif self.jenis_scan == "register":
            target_device_id = int(self.parameter_scan.get('slave_id', 1))
            tipe_reg  = self.parameter_scan.get('tipe_reg', 'Holding')
            reg_awal  = int(self.parameter_scan.get('reg_awal', 0))
            reg_akhir = int(self.parameter_scan.get('reg_akhir', 100))
            encoding  = self.parameter_scan.get('encoding', 'Mentah (16-bit UINT)')
            
            # Step selalu 1 agar tidak ada register yang terlewat
            langkah = 1
            daftar_reg = list(range(reg_awal, reg_akhir + 1, langkah))

            # FIX: jumlah register yang dibaca kini mengikuti kebutuhan
            # jenis encoding yang dipilih (1/2/4 word), bukan selalu 2.
            # Ini juga memperbaiki bug lama: nilai gabungan (float/int32/
            # double) sebelumnya hanya didekode pada baris dengan idx genap
            # (idx % 2 == 0), padahal di mode scan register setiap alamat
            # dibaca independen satu-per-satu sehingga seharusnya SELALU
            # bisa didekode jika register yang terbaca mencukupi.
            jumlah_word = dapatkan_jumlah_word(encoding)

            # FIX PERFORMA: sama seperti scan ID - throttle sinyal progres
            # agar hanya terkirim saat persentasenya berubah, penting untuk
            # scan register yang rentangnya bisa sangat besar.
            progres_terakhir = -1
            for idx, reg in enumerate(daftar_reg):
                if not self.apakah_berjalan: break
                progres = int(((idx + 1) / len(daftar_reg)) * 100)
                if progres != progres_terakhir:
                    self.sinyal_progres.emit(progres, f"Memindai Register: {reg}...")
                    progres_terakhir = progres

                jumlah_baca = jumlah_word if tipe_reg in ['Holding', 'Input'] else 1

                kunci_komunikasi.lock()
                try:
                    res = baca_register_modbus(self.client, tipe_reg, reg, jumlah_baca, target_device_id)
                    if res and not res.isError():
                        statistik_global.catat_sukses()
                        if tipe_reg in ['Holding', 'Input']:
                            val_int = str(struct.unpack('h', struct.pack('H', res.registers[0]))[0]) if encoding == 'Signed 16-bit INT' else str(res.registers[0])
                            val_gabungan = "-"
                            if jumlah_word > 1 and len(res.registers) >= jumlah_word:
                                val_gabungan = dekode_register_multi(res.registers, encoding)
                            hasil.append((reg, val_int, val_gabungan))
                        else:
                            hasil.append((reg, str(res.bits[0]), "-"))
                    elif res:
                        statistik_global.catat_gagal()
                        self.sinyal_error.emit(f"Register {reg}: {terjemahkan_respon_modbus(res)}")
                except Exception as e:
                    adalah_timeout = "timeout" in str(e).lower()
                    statistik_global.catat_gagal(adalah_timeout=adalah_timeout)
                    catat_kesalahan(f"Scan register {reg}", e)
                    self.sinyal_error.emit(f"Error saat scan register {reg}: {str(e)}")
                finally:
                    kunci_komunikasi.unlock()
                time.sleep(0.02)
                
        if self.apakah_berjalan: self.sinyal_progres.emit(100, "Proses Selesai.")
        self.sinyal_hasil.emit(hasil)
        self.sinyal_selesai.emit()


class ModbusPoolerLoggerThread(QThread):
    sinyal_data      = pyqtSignal(list, list, str, str)
    sinyal_kesalahan = pyqtSignal(str, str)
    sinyal_info      = pyqtSignal(str, str)

    # Batas mencoba ulang koneksi sebelum jeda tunggu berhenti bertambah
    BACKOFF_MAKS_DETIK = 30.0

    def __init__(self, client_global, parameter, target_tab="reader", single_shot=False, auto_reconnect=True):
        super().__init__()
        self.client     = client_global
        self.parameter  = parameter
        self.target_tab = target_tab
        self.single_shot = single_shot
        self.auto_reconnect = auto_reconnect
        self.apakah_berjalan = True

    def run(self):
        if not self.client:
            self.sinyal_kesalahan.emit("Koneksi master tidak aktif.", self.target_tab)
            return

        target_device_id = int(self.parameter['slave_id'])
        tipe_reg         = self.parameter['tipe_reg']
        reg_awal         = int(self.parameter['reg_awal'])
        jumlah           = int(self.parameter['jumlah'])
        encoding         = self.parameter['encoding']
        interval         = float(self.parameter['interval'])

        percobaan_reconnect = 0

        while self.apakah_berjalan:
            # FIX/Fitur: jika koneksi terputus di tengah polling/logging,
            # coba sambung ulang otomatis dengan backoff (0.5s, 1s, 2s, ...
            # sampai maksimum) alih-alih terus gagal diam-diam sampai
            # dihentikan manual oleh user.
            if not client_terhubung(self.client):
                if not self.auto_reconnect:
                    self.sinyal_kesalahan.emit("Koneksi terputus (auto-reconnect nonaktif).", self.target_tab)
                    break
                percobaan_reconnect += 1
                jeda = min(0.5 * (2 ** (percobaan_reconnect - 1)), self.BACKOFF_MAKS_DETIK)
                self.sinyal_info.emit(
                    f"Koneksi terputus. Mencoba sambung ulang (percobaan ke-{percobaan_reconnect})...",
                    self.target_tab
                )
                kunci_komunikasi.lock()
                try:
                    berhasil = self.client.connect()
                except Exception as e:
                    berhasil = False
                    catat_kesalahan("Auto-reconnect", e)
                finally:
                    kunci_komunikasi.unlock()

                if berhasil:
                    percobaan_reconnect = 0
                    self.sinyal_info.emit("Koneksi berhasil disambung kembali.", self.target_tab)
                else:
                    for _ in range(int(jeda * 10)):
                        if not self.apakah_berjalan: break
                        time.sleep(0.1)
                    continue

            kunci_komunikasi.lock()
            try:
                if client_terhubung(self.client):
                    res = baca_register_modbus(self.client, tipe_reg, reg_awal, jumlah, target_device_id)
                    if res and res.isError():
                        statistik_global.catat_gagal()
                        self.sinyal_kesalahan.emit(f"Modbus Error: {terjemahkan_respon_modbus(res)}", self.target_tab)
                    elif res:
                        statistik_global.catat_sukses()
                        list_alamat = list(range(reg_awal, reg_awal + jumlah))
                        if tipe_reg in ['Holding', 'Input']:
                            nilai_mentah = [str(r) for r in res.registers]
                        else:
                            nilai_mentah = [str(b) for b in res.bits[:jumlah]]
                        self.sinyal_data.emit(list_alamat, nilai_mentah, encoding, self.target_tab)
            except Exception as e:
                adalah_timeout = "timeout" in str(e).lower()
                statistik_global.catat_gagal(adalah_timeout=adalah_timeout)
                catat_kesalahan("Pooler/Logger", e)
                self.sinyal_kesalahan.emit(f"Gangguan Aliran Data: {str(e)}", self.target_tab)
            finally:
                kunci_komunikasi.unlock()

            if self.single_shot:
                break

            for _ in range(int(interval * 10)):
                if not self.apakah_berjalan: break
                time.sleep(0.1)


class TagListReaderThread(QThread):
    """Membaca sekumpulan tag yang alamatnya bisa TIDAK berurutan/kontinu
    (mis. suhu di Holding 100, tekanan di Input 40, status di Coil 5),
    masing-masing dengan tipe register, encoding, skala, dan offset sendiri.

    Tag yang alamatnya bersambung dan berada di slave+tipe yang sama otomatis
    digabung menjadi satu request blok (lihat susun_blok_tag), sehingga lalu
    lintas bus RS-485 jauh berkurang. Jika sebuah blok ditolak perangkat
    (mis. Illegal Data Address), tag di dalamnya dibaca satu-per-satu."""
    sinyal_hasil     = pyqtSignal(list)
    sinyal_kesalahan = pyqtSignal(str, str)
    sinyal_info      = pyqtSignal(str, str)

    def __init__(self, client_global, daftar_tag, single_shot=True, interval=2.0, auto_reconnect=True):
        super().__init__()
        self.client = client_global
        # Snapshot: daftar milik GUI tidak boleh dimodifikasi/dibaca silang
        # thread saat polling berjalan.
        self.daftar_tag = copy.deepcopy(list(daftar_tag))
        self.single_shot = single_shot
        self.interval = interval
        self.auto_reconnect = auto_reconnect
        self.apakah_berjalan = True

    @staticmethod
    def _hasil_error(tag, pesan):
        return {'nama': tag.get('nama', '-'), 'nilai_mentah': '-', 'nilai_akhir': pesan, 'status': 'ERROR'}

    def _baca_satu(self, hasil, indeks, mulai_tag, jumlah_tag, slave_id, tipe_reg):
        tag = self.daftar_tag[indeks]
        kunci_komunikasi.lock()
        try:
            res = baca_register_modbus(self.client, tipe_reg, mulai_tag, jumlah_tag, slave_id)
            if res and not res.isError():
                statistik_global.catat_sukses()
                data = list(res.registers[:jumlah_tag]) if tipe_reg in ('Holding', 'Input') else list(res.bits[:jumlah_tag])
                hasil[indeks] = olah_nilai_tag(tag, data)
            else:
                statistik_global.catat_gagal()
                hasil[indeks] = self._hasil_error(tag, terjemahkan_respon_modbus(res) if res else "Tidak ada respons")
        except Exception as e:
            statistik_global.catat_gagal(adalah_timeout="timeout" in str(e).lower())
            catat_kesalahan(f"Baca tag {tag.get('nama', '-')}", e)
            hasil[indeks] = self._hasil_error(tag, f"Error: {e}")
        finally:
            kunci_komunikasi.unlock()

    def _baca_blok(self, blok, hasil):
        slave_id, tipe_reg = blok['slave_id'], blok['tipe_reg']
        jumlah_total = blok['akhir'] - blok['mulai']
        perlu_fallback = False

        kunci_komunikasi.lock()
        try:
            res = baca_register_modbus(self.client, tipe_reg, blok['mulai'], jumlah_total, slave_id)
            if res and not res.isError():
                statistik_global.catat_sukses()
                if tipe_reg in ('Holding', 'Input'):
                    semua = list(res.registers[:jumlah_total])
                else:
                    semua = list(res.bits[:jumlah_total])
                for indeks, mulai_tag, jumlah_tag in blok['anggota']:
                    offset = mulai_tag - blok['mulai']
                    hasil[indeks] = olah_nilai_tag(self.daftar_tag[indeks], semua[offset:offset + jumlah_tag])
            else:
                statistik_global.catat_gagal()
                perlu_fallback = True
                pesan_blok = terjemahkan_respon_modbus(res) if res else "Tidak ada respons"
        except Exception as e:
            # Exception (umumnya timeout/koneksi) => perangkat kemungkinan tidak
            # menjawab; membaca ulang satu-per-satu hanya melipatgandakan timeout.
            statistik_global.catat_gagal(adalah_timeout="timeout" in str(e).lower())
            catat_kesalahan(f"Baca blok tag slave {slave_id} {tipe_reg} {blok['mulai']}", e)
            for indeks, _m, _j in blok['anggota']:
                hasil[indeks] = self._hasil_error(self.daftar_tag[indeks], f"Error: {e}")
        finally:
            kunci_komunikasi.unlock()

        if perlu_fallback:
            if len(blok['anggota']) == 1:
                indeks, _m, _j = blok['anggota'][0]
                hasil[indeks] = self._hasil_error(self.daftar_tag[indeks], pesan_blok)
            else:
                for indeks, mulai_tag, jumlah_tag in blok['anggota']:
                    if not self.apakah_berjalan:
                        break
                    self._baca_satu(hasil, indeks, mulai_tag, jumlah_tag, slave_id, tipe_reg)

    def run(self):
        if not self.client:
            self.sinyal_kesalahan.emit("Koneksi master tidak aktif.", "tag")
            return

        daftar_blok = susun_blok_tag(self.daftar_tag)
        percobaan_reconnect = 0
        while self.apakah_berjalan:
            if not client_terhubung(self.client):
                if not self.auto_reconnect:
                    self.sinyal_kesalahan.emit("Koneksi terputus (auto-reconnect nonaktif).", "tag")
                    break
                percobaan_reconnect += 1
                jeda = min(0.5 * (2 ** (percobaan_reconnect - 1)), 30.0)
                self.sinyal_info.emit(f"{AWALAN_PESAN_TERPUTUS}, mencoba sambung ulang (ke-{percobaan_reconnect})...", "tag")
                kunci_komunikasi.lock()
                try:
                    berhasil = self.client.connect()
                except Exception as e:
                    berhasil = False
                    catat_kesalahan("Auto-reconnect (tag)", e)
                finally:
                    kunci_komunikasi.unlock()
                if berhasil:
                    percobaan_reconnect = 0
                    self.sinyal_info.emit(f"{AWALAN_PESAN_TERSAMBUNG}.", "tag")
                else:
                    for _ in range(int(jeda * 10)):
                        if not self.apakah_berjalan: break
                        time.sleep(0.1)
                    continue

            hasil = [None] * len(self.daftar_tag)
            for blok in daftar_blok:
                if not self.apakah_berjalan:
                    break
                self._baca_blok(blok, hasil)
                time.sleep(0.01)

            # Hanya kirim bila satu putaran penuh selesai, supaya baris hasil
            # selalu sejajar dengan baris tabel tag.
            if self.apakah_berjalan and all(h is not None for h in hasil):
                self.sinyal_hasil.emit(hasil)

            if self.single_shot:
                break
            for _ in range(int(self.interval * 10)):
                if not self.apakah_berjalan: break
                time.sleep(0.1)


class ModbusWriteThread(QThread):
    """Eksekusi penulisan (dan verifikasi baca-ulang) di thread terpisah, agar
    GUI tidak membeku ketika bus sedang dipakai polling lain atau perangkat
    lambat/timeout (sebelumnya lock bus diambil langsung di thread GUI)."""
    sinyal_log = pyqtSignal(str)

    def __init__(self, client_global, parameter):
        super().__init__()
        self.client = client_global
        self.p = parameter

    def _log(self, html):
        self.sinyal_log.emit(f"[{datetime.now().strftime('%H:%M:%S')}] {html}")

    def run(self):
        p = self.p
        if not self.client or not client_terhubung(self.client):
            self._log("<font color='red'>Master Modbus belum terhubung!</font>")
            return

        kunci_komunikasi.lock()
        try:
            kwargs = {'address': p['alamat']}
            kwargs.update(get_modbus_device_kwargs(p['device_id']))
            jenis = p['jenis']

            if jenis == 'single_coil':
                kwargs['value'] = p['nilai_bool']
                res = self.client.write_coil(**kwargs)
                data_kirim = str(p['nilai_bool'])
            elif jenis == 'single_reg':
                kwargs['value'] = p['register_final'][0]
                res = self.client.write_register(**kwargs)
                data_kirim = str(p['register_final'][0])
            elif jenis == 'multi_coil':
                kwargs['values'] = p['daftar_bool']
                res = self.client.write_coils(**kwargs)
                data_kirim = str(p['daftar_bool'])
            elif jenis == 'multi_reg':
                kwargs['values'] = p['register_final']
                res = self.client.write_registers(**kwargs)
                data_kirim = str(p['register_final'])
            elif jenis == 'mask':
                kwargs['and_mask'] = p['and_mask']
                kwargs['or_mask'] = p['or_mask']
                if not hasattr(self.client, 'mask_write_register'):
                    raise AttributeError("Versi pymodbus ini tidak mendukung mask_write_register().")
                res = self.client.mask_write_register(**kwargs)
                data_kirim = f"AND=0x{p['and_mask']:04X}, OR=0x{p['or_mask']:04X}"
            else:
                res = None
                data_kirim = ""

            if res is None:
                self._log("<font color='red'>Jenis penulisan tidak dikenali.</font>")
            elif res.isError():
                statistik_global.catat_gagal()
                self._log(f"<font color='red'>Gagal! {terjemahkan_respon_modbus(res)}</font>")
            else:
                statistik_global.catat_sukses()
                self._log(f"<font color='green'>Transmisi Sukses → Addr: {p['alamat']} | ID: {p['device_id']} | Data: {data_kirim}</font>")
                if p.get('verifikasi') and jenis != 'mask':
                    self._verifikasi()
        except Exception as e:
            statistik_global.catat_gagal(adalah_timeout="timeout" in str(e).lower())
            catat_kesalahan("Eksekusi tulis Modbus", e)
            self._log(f"<font color='red'>Kesalahan Hardware: {e}</font>")
        finally:
            kunci_komunikasi.unlock()

    def _verifikasi(self):
        """Baca kembali alamat yang baru ditulis (lock bus sudah dipegang run())
        dan bandingkan dengan nilai yang dikirim."""
        p = self.p
        try:
            if p['jenis'] in ('single_coil', 'multi_coil'):
                diharapkan = [p['nilai_bool']] if p['jenis'] == 'single_coil' else list(p['daftar_bool'])
                res = baca_register_modbus(self.client, "Coil", p['alamat'], len(diharapkan), p['device_id'])
                if res and not res.isError():
                    terbaca = [bool(b) for b in res.bits[:len(diharapkan)]]
                    if terbaca == diharapkan:
                        self._log(f"<font color='green'>Verifikasi OK: coil di perangkat cocok {terbaca}.</font>")
                    else:
                        self._log(f"<font color='orange'>Verifikasi TIDAK cocok! Diharapkan {diharapkan}, terbaca {terbaca}.</font>")
                else:
                    self._log(f"<font color='orange'>Verifikasi gagal: {terjemahkan_respon_modbus(res) if res else 'tidak ada respons'}</font>")
            else:
                diharapkan = list(p['register_final'])
                res = baca_register_modbus(self.client, "Holding", p['alamat'], len(diharapkan), p['device_id'])
                if res and not res.isError():
                    terbaca = list(res.registers[:len(diharapkan)])
                    if terbaca == diharapkan:
                        self._log(f"<font color='green'>Verifikasi OK: nilai di perangkat cocok ({terbaca}).</font>")
                    else:
                        self._log(f"<font color='orange'>Verifikasi TIDAK cocok! Diharapkan {diharapkan}, terbaca {terbaca}.</font>")
                else:
                    self._log(f"<font color='orange'>Verifikasi gagal: {terjemahkan_respon_modbus(res) if res else 'tidak ada respons'}</font>")
        except Exception as e:
            catat_kesalahan("Verifikasi baca ulang write", e)
            self._log(f"<font color='orange'>Verifikasi gagal: {e}</font>")
