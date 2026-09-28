# Changelog — Pembersihan Duplikat

Tahap ini hanya membersihkan file yang benar-benar duplikat/usang.
Belum ada restrukturisasi besar (gabung jadi 1 app per-tab) — itu tahap berikutnya.

## ❌ Dihapus

| File | Alasan |
|---|---|
| `lutron_logger.py` | Identik secara fungsi dengan `Lutron_DTR.py`, hanya beda binding Qt (PySide2 vs PySide6). PySide2 sudah EOL, jadi `Lutron_DTR.py` (PySide6) dipertahankan sebagai versi resmi. |
| `pdfcompresser.py` (root) | Versi awal/basic dari kompresor PDF. Semua fiturnya sudah ada (dan lebih lengkap) di `pdf_tools/ultimate-pdf-compresor.py` (grayscale, custom Ghostscript path, mode batch, dll). |
| `ultimate-pdf-compresor.py` (root) | 100% identik byte-per-byte dengan `pdf_tools/ultimate-pdf-compresor.py` — copy ganda dari file yang sama. |
| Semua folder `__pycache__/` dan file `*.pyc` | File hasil compile Python, bukan source code, tidak perlu ikut di-track/dikirim. |

## ✅ Dipertahankan apa adanya (belum digabung)

- **`qt-pymodbus-debug/modbus_client*.py`** vs **`qt-pymodbus-logger/modbus_client*.py`**
  Sekilas mirip namanya, tapi setelah dicek isinya **sudah bercabang (diverge)**:
  - Versi di `qt-pymodbus-debug` punya fitur tangkap frame TX/RX mentah (`ModbusFrameHandler`) dan deteksi versi pymodbus yang lebih detail (major.minor → `unit`/`slave`/`device_id`).
  - Versi di `qt-pymodbus-logger` punya penanganan tipe data lebih defensif (`int()`/`float()` cast dari config) dan helper `_call()` yang berbeda strukturnya.
  Menyatukan keduanya butuh keputusan desain (fitur mana yang mau dipakai sebagai standar), jadi ini **disimpan untuk tahap restrukturisasi berikutnya**, bukan dihapus sembarangan supaya tidak menghilangkan fitur.

- **`pdf_tools/convert_pdf_img_1.py`** vs **`pdf_tools/convert_pdf_img_2.py`**
  Bukan duplikat — `_1` adalah script CLI sederhana, `_2` adalah versi GUI (PyQt5) dengan fitur lebih lengkap (rotate, filter, dll). Keduanya punya kegunaan berbeda, jadi tetap dipertahankan dua-duanya untuk saat ini.

- **`modbus_tool.py`** (2635 baris) — file gabungan besar yang sudah ada sebelumnya, dibiarkan utuh dulu. ⚠️ Ini kandidat kuat untuk dipecah saat restrukturisasi Modbus Suite nanti.

## 🆕 Update: PDF Compressor + PDF→Gambar digabung jadi 1 aplikasi

`pdf_tools/pdf_suite/` — aplikasi baru dengan 2 tab:

1. **Compressor** — dari `ultimate-pdf-compresor.py` (dipertahankan penuh: mode Ghostscript/Full Image, grayscale, custom GS path, batch), ditambah opsi **Sharpen** yang dipindah dari `convert_pdf_img_2.py` (hanya aktif di mode Full Image, karena mode Ghostscript diproses lewat binary eksternal, bukan Pillow).
2. **PDF -> Gambar** — GUI baru. Perlu dicatat: `convert_pdf_img_2.py` ternyata **bukan** fitur ekspor ke gambar (isinya rasterize-lalu-repack ke PDF baru, alias compressor varian lain). Fitur ekspor gambar asli justru ada di fungsi `pdf_to_images()` di `convert_pdf_img_1.py` (versi CLI, belum ada GUI) — fungsi itu yang dipindah & dibungkus GUI baru di tab ini.

File asli (`ultimate-pdf-compresor.py`, `convert_pdf_img_1.py`, `convert_pdf_img_2.py`) dipindah ke `pdf_tools/legacy/` sebagai arsip — tidak lagi dipakai aplikasi, aman dihapus setelah suite baru dites dan dipastikan berjalan baik.

File packaging (`Ultimate_PDF_Compressor.spec` → `PDF_Tools_Suite.spec`, `pdf-compressor.desktop` → `pdf-tools-suite.desktop`) sudah diupdate mengarah ke `pdf_suite/main.py`.

Sudah lolos smoke test (syntax check + instansiasi widget headless dengan `QT_QPA_PLATFORM=offscreen`), tapi **belum dites dengan interaksi UI nyata** (drag&drop, klik tombol, dll) — mohon dicoba manual sebelum dipakai produksi.

## 🆕 Update: `modbus_tool.py` dikembangkan (bukan digabung ke app baru)

Sesuai arahan, `modbus_tool.py` (app "Modbus Tools Kalingin") tetap 1 file,
ditambah 2 kemampuan baru sebagai tab menu:

1. **Tab "Float Converter"** (baru) — dipindah dari `float converter/converter.py`
   (class `ModbusFloatConverter`), sekarang jadi tab ke-7 di `modbus_tool.py`,
   memakai widget yang sudah diimpor di file yang sama (tidak nambah dependency).
   Fitur & hasil konversinya identik dengan versi standalone (sudah dites round-trip
   float → register → float untuk semua 4 urutan byte: ABCD/BADC/CDAB/DCBA).
   Folder `float converter/` dipindah ke `pdf_tools/legacy/`-setara, yaitu
   `legacy_float_converter/` di root, sebagai arsip.

2. **Logger ke Database (MySQL)** — ditambahkan di tab "Data Logger CSV" yang sudah
   ada, bukan bikin tab baru, karena datanya memang sama (baris yang sama ditulis
   ke CSV *dan* opsional ke MySQL secara paralel). Detail implementasi:
   - Class baru `MySQLDataLogger` (di dalam `modbus_tool.py`), diadaptasi dari pola
     `qt-pymodbus-logger/storage/mysql_logger.py`: tabel & kolom dibuat/ditambah
     otomatis saat logging dimulai.
   - Beda dari referensi: nama kolom di sini mengikuti nama header CSV yang sudah
     ada (mis. `Reg_40001-40002` → `reg_40001_40002`), supaya baris di CSV dan di
     DB gampang dicocokkan satu sama lain. Tipe kolom data dibuat `VARCHAR(64)`
     (bukan `DOUBLE`) karena nilai yang dicatat logger ini macam-macam bentuknya
     (float, signed int, atau 0/1 untuk Coil).
   - UI baru: groupbox "Simpan ke Database (MySQL)" di tab Data Logger — checkbox
     aktifkan + field host/port/user/password/database/tabel.
   - `pymysql` ditambahkan ke `requirements.txt` sebagai dependency opsional
     (hanya perlu di-install kalau fitur ini dipakai; kalau tidak ter-install,
     aplikasi tetap jalan normal, cuma opsi "Simpan ke MySQL" akan menampilkan
     pesan error yang jelas saat dicentang & logging dimulai).

Sudah lolos smoke test: syntax check, instansiasi `ModbusApp` headless
(7 tab tampil termasuk "Float Converter"), dan test fungsional konversi
float/register. **Belum dites** koneksi MySQL sungguhan (perlu server MySQL
aktif) — mohon dicoba manual dengan kredensial database asli sebelum dipakai
produksi.

## 🆕 Update: Logger di tab "Daftar Tag" + qt-pymodbus-* diarsipkan

- **Tab "Daftar Tag (Multi-Read)"** kini punya groupbox **"Logger Daftar Tag"**:
  checkbox "Simpan ke CSV" + path file, dan checkbox "Simpan ke MySQL" + kredensial
  (host/port/user/password/database/tabel — pakai class `MySQLDataLogger` yang sama
  dengan tab Data Logger CSV). Bedanya dari tab Data Logger CSV: di sini **kolom =
  nama tag** (bukan alamat register), karena Daftar Tag memang dirancang untuk tag
  dari alamat yang tidak berurutan/campuran tipe register. Berlaku baik untuk mode
  "Baca Semua Tag (Sekali)" maupun polling terus-menerus.
  Sudah dites: simulasi 2 tag → 2 baris CSV tertulis benar dengan header nama tag.

- **`qt-pymodbus-debug/` dan `qt-pymodbus-logger/` dipindah ke `legacy_qt_pymodbus/`**
  (diarsipkan, bukan dihapus). Semua fitur keduanya sudah terangkum di
  `modbus_tool.py`. Satu-satunya fitur di app lama yang **belum** diadopsi:
  `ModbusFrameHandler` di `qt-pymodbus-debug` (capture frame TX/RX mentah) — kalau
  suatu saat dibutuhkan, tinggal lihat lagi arsipnya. Lihat
  `legacy_qt_pymodbus/README.md` untuk tabel pemetaan fitur lama → baru.

## 📌 Belum disentuh (di luar scope "bersihkan duplikat")
Semua aplikasi/tool lain (openchannel_app, qtqr_clone, port_scanner, loster_grid_creator, logger_rata, serial_logger, USB_VIS_Spectro, decode_wh24cp) tidak ada duplikat internal yang ditemukan, jadi dibiarkan seperti semula.
