# Modbus Tools Kalingin v18.0

Aplikasi master Modbus RTU/TCP berbasis PyQt5 (pymodbus 2.x & 3.x).

## Menjalankan
```
pip install -r requirements.txt     # pymysql hanya dipakai fitur "Simpan ke MySQL"
python modbus_tool.py          # atau: python -m modbus_app
```

## Struktur
| Berkas | Isi |
|---|---|
| `modbus_tool.py` | titik masuk |
| `modbus_app/konfigurasi.py` | konstanta, logging berotasi, penulisan JSON atomik |
| `modbus_app/inti.py` | kompatibilitas pymodbus, encode/decode, validasi, pengelompokan blok tag (tanpa GUI) |
| `modbus_app/worker.py` | thread: scan, polling/logging, baca tag (per blok), tulis |
| `modbus_app/tab_*.py` | satu mixin per tab (scan, reader, write, perintah, logger, tag, konverter) |
| `modbus_app/tab_mysql.py`, `widget_mysql.py` | penulis MySQL (thread + antrean) dan panel isian koneksi MySQL, dipakai tab Data Logger & Daftar Tag |
| `modbus_app/jendela_utama.py` | jendela utama, koneksi, preset, interlock |
| `tests/` | 171 tes: logika murni, GUI offscreen, dan ujung-ke-ujung ke server Modbus TCP mini |

## Tes & build
```
pip install -r requirements-dev.txt
python -m pytest               # semua tes
python build.py                # executable (folder);  --onefile untuk satu berkas
```
Konfigurasi, preset otomatis, dan log (`aplikasi.log`, berotasi) disimpan di folder
`%APPDATA%\ModbusToolsKalingin` (Windows) atau `~/.config/ModbusToolsKalingin`.

## Tab
Pemindai Device ID · Pemindai Peta Register · Pembaca Modbus Live · Write Register / Coil ·
**Daftar Perintah (Write)** · Data Logger CSV (+ MySQL) · Daftar Tag (Multi-Read) (+ logger CSV/MySQL, baca per tag) · **Float Converter**.

## Fitur yang dipindahkan dari `modbus_tool.py` (monolit lama)
Versi monolit di root repo punya empat fitur yang belum ada di v18; kini semuanya tersedia di v18:
- **Daftar Perintah (Write)**: perintah tulis (FC 05/06/15/16/22) disimpan sekali lalu dijalankan dengan satu klik
  (tombol per baris), dengan konfirmasi opsional, verifikasi baca-ulang, simpan/ubah/hapus/urutkan. Logika parsing dibagi
  dengan tab Write (`inti.susun_parameter_tulis`), jadi keduanya selalu berperilaku sama.
- **Simpan ke MySQL** di tab Data Logger: baris yang sama dengan CSV ditulis paralel ke tabel MySQL (tabel/kolom dibuat otomatis).
  Penulisan berjalan di thread terpisah dengan antrean, sehingga GUI tidak membeku bila database lambat/mati;
  bila database mati, hanya galat yang dilaporkan (tidak membanjiri log) dan antrean dibatasi 500 baris.
  Perlu paket `pymysql` (`pip install pymysql`; MySQL 8 dengan autentikasi `caching_sha2_password` juga butuh `cryptography`).
  **Kata sandi database tidak pernah disimpan** ke preset/pengaturan otomatis; isi ulang setiap sesi.
- **Logger Daftar Tag** (CSV dan MySQL): 1 baris = 1 siklus baca, kolom = nama tag. Berbeda dengan Data Logger yang kolomnya alamat register.
  Tombol **Baca** per baris tag membaca satu tag saja (tidak ditulis ke logger).
- **Float Converter**: register 16-bit <-> float32 untuk urutan ABCD/BADC/CDAB/DCBA, input desimal atau `0xHEX`, koma desimal diterima.
- Preset pekerjaan kini ikut menyimpan daftar perintah, pengaturan database (tanpa kata sandi), dan pengaturan logger tag.
  Preset v18.0 lama tetap bisa dimuat.

## Perubahan v18.0
- **Bug**: FC 06 + format 32/64-bit kini ditolak dengan petunjuk memakai FC 16 (sebelumnya hanya separuh data terkirim);
  UI tidak lagi macet saat thread berhenti sendiri; log tidak tumbuh tanpa batas; pengaturan logger
  dikunci & di-snapshot selama merekam; batas tunggu penutupan thread memperhitungkan retry.
- **Penulisan di thread terpisah** (GUI tidak membeku saat bus sibuk); verifikasi coil kini membandingkan nilai.
- **Pengaturan tersimpan otomatis** saat keluar (termasuk daftar tag & mode gelap).
- **Daftar Tag**: pembacaan per blok (request jauh berkurang), edit, urutkan, impor/ekspor CSV.
- **Scan Device ID** memakai retry 0 sementara (jauh lebih cepat bila banyak ID kosong).
- Validasi input (coil, mask, UINT16, jumlah register vs format), indikator "MENYAMBUNG ULANG…".
- Kode dipecah menjadi modul; ditambah unit test, `requirements*.txt`, dan `build.py`.

## Windows menandai aplikasi "tidak terpercaya" / memblokir
Penyebab berbeda butuh penanganan berbeda. Lihat dulu pesan yang muncul:

| Pesan | Penyebab | Penanganan |
|---|---|---|
| "Windows protected your PC" / *Unknown publisher* (SmartScreen) | exe belum ditandatangani & belum punya reputasi unduhan | tanda tangani kode (di bawah); sementara: *More info → Run anyway* |
| Defender/antivirus menghapus atau karantina, ada nama ancaman (mis. `Trojan:Win32/...!ml`) | **false positive** heuristik; biner PyInstaller sering terkena | bangun dengan `python build.py` (mode folder, tanpa UPX, dengan metadata versi), kirim sampel ke vendor, lihat di bawah |
| "This app can't run on your PC" / diblokir *Smart App Control* (Windows 11) | Smart App Control hanya mengizinkan kode **bertanda tangan terpercaya** (atau yang dikenal baik oleh layanan cloud Microsoft); tanpa tombol "run anyway" | lihat bagian *Smart App Control* di bawah |
| Diblokir AppLocker/WDAC di PC kantor | kebijakan IT | minta IT meng-allow-list berdasarkan publisher (tanda tangan) atau hash SHA-256 |

**Yang sudah dilakukan `build.py`:** mode folder (bukan `--onefile`), `--noupx`, resource versi/penerbit/deskripsi
(`PENERBIT` bisa diatur lewat variabel lingkungan), ikon bila ada `app.ico`, penandatanganan opsional via `signtool` untuk semua exe/dll/pyd,
dan cetak SHA-256. Catatan: bagian khusus Windows ini (resource versi, signtool) belum dijalankan di Windows oleh penulisnya.

**Langkah yang harus Anda lakukan (tidak bisa diselesaikan lewat kode):**
1. **Tanda tangan kode** dengan sertifikat dari CA publik (OV/EV) atau layanan penandatanganan cloud seperti Azure Trusted Signing
   (cek syarat & ketersediaannya). Selalu pakai timestamp (`/tr`) agar tanda tangan tetap sah setelah sertifikat kedaluwarsa.
   Sertifikat *self-signed* TIDAK menghilangkan peringatan SmartScreen; hanya berguna di jaringan internal bila root-nya
   disebar lewat GPO. Reputasi SmartScreen tetap perlu waktu/jumlah unduhan walau sudah bertanda tangan.
2. **Kirim false positive** ke Microsoft (portal *Microsoft Security Intelligence → Submit a file for malware analysis*) dan vendor
   antivirus lain yang menandai berkas Anda, lengkap dengan hash SHA-256 dari `build.py`.
3. **Untuk distribusi internal** (tanpa sertifikat): bagikan lewat folder jaringan/installer, bukan unduhan browser. File dari internet
   membawa tanda *Mark of the Web*; hapus dengan `Unblock-File -Path .\ModbusToolsKalingin_v18.zip` (PowerShell) **sebelum** mengekstrak,
   atau klik kanan → Properties → *Unblock*. Tambahkan folder aplikasi ke pengecualian Defender hanya bila Anda yakin berkasnya aman.
4. **Installer:** `installer.iss` (Inno Setup, belum diuji) membuat satu berkas setup; tanda tangani installer-nya juga.
5. **Opsional, mengurangi kemiripan dengan malware generik:** bangun PyInstaller dari sumber (`pip install pyinstaller --no-binary pyinstaller`,
   butuh compiler C) agar bootloader-nya tidak identik dengan biner publik yang sering ditandai; bangun di venv bersih dan hanya dengan dependensi yang perlu.

### Smart App Control (Windows 11)
Smart App Control (SAC) memblokir kode tanpa tanda tangan terpercaya dan tidak punya tombol "run anyway".
Pilihan, dari yang paling tepat ke yang paling darurat:

1. **Tanda tangani SEMUA berkas PE**, bukan hanya exe utama. `python build.py` (mode folder) kini menandatangani
   semua `.exe/.dll/.pyd` yang belum bertanda tangan sah, melewati yang sudah ditandatangani penerbit aslinya (mis. `python3xx.dll`).
   Sertifikat harus berantai ke root yang dipercaya Windows (CA publik/Azure Trusted Signing); sertifikat self-signed ditolak SAC.
   Jangan pakai `--onefile`: isinya diekstrak tanpa tanda tangan ke folder sementara saat start dan tidak bisa ditandatangani satu-per-satu.
   Memakai installer (`installer.iss`) tetap disarankan, dengan installer dan exe sama-sama ditandatangani.
2. **PC milik sendiri / yang Anda kelola:** matikan SAC di *Windows Security → App & browser control → Smart App Control settings → Off*.
   Pada versi Windows saat ini SAC umumnya tidak bisa dinyalakan lagi tanpa reset/instal ulang Windows (ini bisa berubah di versi baru,
   cek di PC Anda). Defender dan SmartScreen tetap aktif. Bila SAC masih "Evaluation", Windows dapat mematikannya sendiri jika
   mendeteksi pemakaian yang tidak cocok (mis. perangkat lunak pengembang).
3. **PC kantor terkelola:** minta IT membuat kebijakan WDAC/AppLocker yang mengizinkan publisher (tanda tangan) atau hash SHA-256
   yang dicetak `build.py`.

Catatan: logika penandatanganan sudah diuji dengan `signtool` palsu (tes `tests/test_build.py`), tetapi penandatanganan nyata dan
perilaku SAC belum diuji di Windows oleh penulisnya; setelah menandatangani, uji di PC dengan SAC *On* sebelum membagikan.

## Build otomatis lewat GitHub Actions
`.github/workflows/build-windows.yml` membangun di runner Windows bersih. Cara pakai:
1. Samakan `modbus_app/__init__.py` (`__version__`) dengan tag, mis. `18.0` -> tag `v18.0`, lalu `git tag v18.0 && git push origin v18.0`
   (atau jalankan manual dari tab *Actions*). Workflow menolak tag yang tidak sama dengan `__version__`.
2. Hasil: artifact `ModbusToolsKalingin-win64` (zip + `SHA256SUMS.txt`); untuk tag, otomatis dibuat GitHub Release.
   Bagikan dari halaman *Releases* (bukan artifact, yang terbungkus zip lagi).
3. Opsional: variabel repo `PENERBIT` (nama penerbit di metadata exe); rahasia `SIGN_PFX_B64` (PFX base64) dan `SIGN_PFX_PASSWORD`
   untuk menandatangani. Tanpa rahasia ini build tetap jalan tetapi exe TIDAK bertanda tangan. Sertifikat CA publik yang baru umumnya
   tidak bisa diekspor ke PFX (kunci di perangkat keras/cloud); untuk itu pakai layanan penandatanganan cloud dan sesuaikan langkahnya.
Workflow ini belum pernah dijalankan di GitHub oleh penulisnya; jalankan sekali lewat *workflow_dispatch* dan periksa log-nya.

## Catatan fitur MySQL
- Setiap operasi membuka dan menutup koneksi sendiri. Batas waktu: sambung 5 detik, baca/tulis 10 detik
  (server yang menerima TCP tetapi tidak menjawab kini menghasilkan galat, bukan membuat aplikasi macet).
- Penulisan tidak diulang: baris yang gagal ditulis saat database mati hilang dari database (tetap ada di CSV). Peringatan muncul di monitor.
- Teks galat Modbus pada tag yang gagal dibaca ikut tersimpan di kolom nilai (dipotong 64 karakter di database).
