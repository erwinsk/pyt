# PDF Tools Suite

Aplikasi GUI (PyQt5) untuk memperkecil PDF scan dan mengekspor PDF ke gambar.

## Antarmuka

Tata letak horizontal yang hemat ruang (minimum 1000×600, ukuran jendela diingat):
antrean file di kiri (satu tabel: daftar file + hasil + status per file), pengaturan berupa kartu di kanan
(Tujuan, Keluaran, Cache OCR, Metode & parameter yang dilipat), dan log berupa laci satu baris di footer
(terbuka otomatis saat ada galat). Warna mengikuti palet sistem (terang/gelap otomatis).

Pintasan: `Ctrl+O` tambah PDF · `Ctrl+Enter` mulai · `Del` hapus dari antrean · `Ctrl+L` log · `Ctrl+,` dependensi.

Indikator di pojok kanan atas menampilkan "✓ N alat siap" atau "⚠ N alat bermasalah" (klik untuk membuka dialog
Dependensi pada alat yang bermasalah). Bila metode yang dipilih butuh alat yang belum ada, pesannya selalu tampil di
kolom pengaturan, lengkap dengan tautan ke dialog Dependensi.

## Tab

1. **Kompres** — tiga tingkat pilihan (lihat bagian berikutnya). Empat metode, semuanya dengan
   parameter lengkap:
   | Metode | Cocok untuk | Catatan |
   |---|---|---|
   | **Ghostscript** | PDF campuran teks + gambar | cepat; menurunkan resolusi gambar |
   | **Full Image** | kompresi sederhana | halaman dirender jadi JPEG; teks menjadi gambar |
   | **OCRmyPDF** | scan yang harus tetap tampak asli | PDF searchable; optimasi JPEG/PNG |
   | **MRC (recode_pdf)** | scan berwarna, ukuran terkecil | mask teks JBIG2 + latar JPEG2000 + teks OCR |
2. **Atur Halaman** (gaya PDF Arranger) — halaman dari banyak PDF dan gambar tampil sebagai thumbnail yang
   bisa diurutkan dengan seret. Fitur:
   * **Gabung**: tambahkan beberapa PDF/gambar, atur urutan, lalu *Simpan PDF* (semua halaman atau hanya yang terpilih).
   * **Pisah**: per halaman, tiap N halaman, rentang kustom (`1-3, 4, 5-8, 9-`), atau per file sumber. Nama file
     memakai templat `{nama}_{n}` (juga `{awal}`/`{akhir}`) dan **tidak pernah menimpa** file yang sudah ada.
   * **Impor gambar** (PNG, JPG, BMP, GIF, TIFF, WebP) menjadi halaman PDF: ukuran sesuai gambar atau A4/Letter/A5/A3
     dengan margin. JPEG/PNG disisipkan tanpa kompresi ulang; foto diputar sesuai EXIF.
   * **Putar** 90° (lossless), **ubah ukuran halaman** (A3/A4/A5/A6/Letter/Legal/kustom; orientasi otomatis/potret/lanskap;
     proporsi tetap atau diregangkan; margin; atau **relatif dalam %** terhadap ukuran asli tiap halaman), duplikat, sisipkan halaman kosong, hapus, geser, balik urutan.
   * **Seret untuk mengurutkan**: seret thumbnail (atau beberapa yang terpilih) ke posisi baru; garis biru menandai tempat
     sisipnya, daftar menggulir otomatis di tepi, `Esc` membatalkan. Ditangani lewat event mouse biasa (bukan drag & drop
     sistem), jadi perilakunya sama di semua platform.
   * **Zoom thumbnail**: tombol **−** / **+** (juga `Ctrl++`, `Ctrl+-`, atau `Ctrl` + roda mouse).
   * **Undo/redo** (Ctrl+Z / Ctrl+Y), pratinjau besar (klik ganda), PDF berpassword (diminta sandi).
   * Pintasan (saat daftar halaman difokus): `Del` hapus · `Ctrl+R` / `Ctrl+Shift+R` putar · `Ctrl+D` duplikat ·
     `Alt+←/→` geser · `Ctrl+O` tambah · `Ctrl+S` simpan.

   Batasan: *ubah ukuran* menempelkan halaman sebagai objek sehingga tautan/anotasi pada halaman itu tidak terbawa
   (putar tanpa ubah ukuran tidak punya batasan ini); hasil gabung tidak membawa bookmark/daftar isi; TIFF multi-frame
   hanya frame pertama. Menyimpan ke file yang sedang dipakai sebagai sumber ditolak.
3. **PDF → Gambar** — ekspor tiap halaman ke PNG/JPG, dengan status per file.

Dialog **Dependensi dan cache** (ikon ⚙) — status alat eksternal, path kustom, perintah instal sesuai OS,
dan pengelolaan cache OCR.

## Tiga tingkat pilihan (tab Kompres)

Pengguna memilih **tujuan**, bukan engine. Pilihan lebih rinci tersedia bila dibutuhkan:

| Tingkat | Untuk siapa | Di mana |
|---|---|---|
| **1. Tujuan** | semua orang | combo teratas: profil siap pakai + profil milik sendiri |
| **2. Metode** | pengguna lanjut | bagian "Metode & parameter (lanjutan)" yang bisa dilipat |
| **3. Parameter** | pakar | panel opsi lengkap di bawah Metode |

Ketiganya **selalu konsisten**: mengubah metode atau parameter apa pun membuat Tujuan berpindah ke
"Kustom" (atau ke profil lain bila nilainya kebetulan sama persis); memilih profil mengisi metode dan
parameter. Bagian lanjutan otomatis terbuka bila pengaturan saat ini bukan profil mana pun.

### Profil bawaan

| Profil | Metode | Untuk |
|---|---|---|
| Scan, bisa dicari - Seimbang | MRC | scan; pilihan awal yang disarankan |
| Scan, bisa dicari - Terkecil | MRC | scan; file paling kecil, tampilan lebih lembut |
| Scan, bisa dicari - Kualitas tinggi (arsip) | MRC | scan; paling setia ke asli, file lebih besar |
| Scan, cepat - tanpa OCR | Full Image | scan; sangat cepat, tanpa alat eksternal, tidak bisa dicari |
| Dokumen digital - Ringan (teks tetap vektor) | Ghostscript | PDF buatan aplikasi |
| Dokumen digital - Email / Web (kecil) | Ghostscript | PDF buatan aplikasi, gambar dikecilkan lebih jauh |
| Beri teks OCR - kualitas gambar dijaga | OCRmyPDF | menambah teks bisa dicari tanpa mengubah gambar |

Profil yang butuh alat belum terpasang tetap tampil, dinonaktifkan, dengan cara memasangnya di tooltip.
Profil "Scan" merender ulang halaman; jangan dipakai untuk dokumen digital bila teks vektor harus dijaga.

**Hasil ukur** (scan sintetis 3 halaman, 300 ppi, 3320 KB, Ubuntu; angka Anda akan berbeda):

| Profil | Hasil | Catatan |
|---|---|---|
| Scan - Terkecil | 211 KB (-93,6%) | cap merah dan huruf tampak lebih lembut |
| Scan - Seimbang | 278 KB (-91,6%) | |
| Scan - Kualitas tinggi | 1030 KB (-69,0%) | paling dekat ke asli secara visual |
| Scan - cepat tanpa OCR | 583 KB (-82,4%) | tanpa lapisan teks |
| Beri teks OCR | 3307 KB (-0,4%) | gambar tidak diubah (dimensi sama); +303 kata terbaca per halaman |

Profil digital dicoba pada PDF teks vektor + foto: seluruh kata vektor tetap utuh (354/354 dan 450/450).
Penghematan di sana sangat besar karena foto uji sintetis sangat mulus; foto nyata menghemat jauh lebih sedikit.
Akurasi OCR bukan ukuran ketajaman; perbedaan mutu antarprofil MRC dinilai secara visual pada 300 dpi.

### Aturan nilai profil

* **Per-dokumen/mesin** (bahasa OCR, metadata, jumlah thread, halaman HQ, dsb.) **bukan milik profil**:
  tidak diubah saat profil diterapkan dan tidak dihitung saat mencocokkan. Mengganti bahasa OCR tidak
  membuat profil berubah jadi "Kustom".
* Parameter lain **dimiliki profil**; yang tidak disebut profil kembali ke bawaan metode, sehingga hasil
  tidak bergantung pada riwayat klik.
* Ghostscript: `jpeg_quality` bawaan **70** (bukan 0). Nilai 0 menyerahkan pilihan filter ke `AutoFilter`
  Ghostscript yang pada uji scan 300 ppi menyandikan sebagian halaman sebagai Flate lossless dan memperbesar
  file (3320 KB -> 5792 KB, +74%). Bawaan baru (3320 KB -> 787 KB) sama dengan profil "Dokumen digital -
  Ringan", jadi aplikasi kini dibuka pada profil itu. Pengaturan lama yang tersimpan (0) tidak diubah
  otomatis; pengaman ukuran (di bawah) akan menangkapnya.
  **Ini trade-off, bukan pilihan yang unggul di semua kasus** (diukur): pada gambar berwarna sedikit
  (sampel sintetis tes) otomatis Ghostscript lebih kecil (61% vs 72% dari sumber) dan JPEG 90 malah
  membengkak (160%). Bawaan 70 dipilih karena kegagalannya ringan (kurang optimal, tetap mengecil),
  sedangkan kegagalan 0 berat (membengkak) pada scan berwarna, jenis yang paling umum. Untuk screenshot,
  diagram, atau scan datar, coba 0.
* `bg_rate`/`fg_rate` MRC adalah **rasio kompresi (N:1)**: makin tinggi makin kecil. (Profil "Terkecil"
  pernah salah arah dan terdeteksi saat diukur; kini dijaga tes.)

### Pengaman "hasil tidak lebih kecil"

Hasil yang **tidak lebih kecil dari file asli tidak disimpan** (kotak "Lewati bila tidak lebih kecil",
aktif secara bawaan). Baris di tabel hasil berstatus `tidak dikecilkan` dengan ukuran dan persentase
yang sebenarnya, penjelasan di tooltip, dan ringkasan akhir menghitungnya. Tidak berlaku untuk
**OCRmyPDF**, yang boleh sedikit lebih besar karena lapisan teks OCR (hasilnya tetap disimpan, diberi catatan).
Bila kotak dimatikan, hasil yang lebih besar tetap ditulis dengan catatan. Hasil OCR yang sudah dibuat tetap
tersimpan di cache sehingga mencoba profil lain tidak mengulang OCR.

### Scan yang sudah punya lapisan OCR

Lapisan OCR lama (teks tak terlihat, render mode 3) **tidak lagi** membuat halaman dianggap "bukan scan
murni". Dulu, bila semua halaman sudah ber-OCR, MRC merender ulang semuanya pada 200 dpi (turun dari 300 ppi
asli), sehingga hasilnya tampak lebih hemat padahal sebagian karena piksel berkurang (160 KB pada 200 ppi vs
278 KB pada 300 ppi untuk dokumen uji yang sama). Kini gambar asli dipakai pada resolusi aslinya dan lapisan
lama diganti hasil OCR baru; log mencatat halaman mana yang punya lapisan lama. Teks yang **terlihat**
(atau tak bisa dipastikan jenisnya) tetap membuat halaman dirender, demi keamanan.

### Kelola profil (tombol "Kelola")

Simpan pengaturan saat ini sebagai profil (nama unik; nama profil bawaan dan isi yang sama dengan profil
lain ditolak), hapus profil milik sendiri, ekspor/impor berkas JSON
(`{"format": "pdf-tools-suite-profiles", "version": 1, "profiles": [{name, description, engine, values}]}`).

**Keamanan impor:** berkas profil dari pihak lain **tidak pernah** membawa teks yang ditempel ke baris
perintah (`extra_args`, `extra_ocr`, `extra_compress`, `*_flags`). Ghostscript dapat menjalankan
PostScript, jadi nilai itu dikosongkan otomatis dan pengguna diberi tahu. Tipe nilai diperiksa ketat
(`"false"` sebagai string tidak diterima sebagai boolean), metode tak dikenal dilewati, ukuran berkas dan
jumlah profil dibatasi.

## Instalasi

```bash
# 1. Alat sistem (salin dari dialog Dependensi dan cache (ikon ⚙) sesuai distro Anda), contoh:
# Debian/Ubuntu
sudo apt install ghostscript tesseract-ocr tesseract-ocr-ind tesseract-ocr-eng pngquant unpaper jbig2
# Fedora / Nobara
sudo dnf install ghostscript tesseract tesseract-langpack-ind tesseract-langpack-eng pngquant unpaper
# (jbig2enc: dnf install jbig2enc bila tersedia; jika tidak, bangun dari github.com/agl/jbig2enc)

# 2. Python
python3 -m venv ~/mrc-env && source ~/mrc-env/bin/activate
pip install -r requirements.txt -r requirements-optional.txt

# 3. Jalankan
python main.py
```

### Bagaimana alat dicari

Urutan: **path kustom** (dialog Dependensi) → **`PATH`** → folder Python yang menjalankan aplikasi (mis. venv) →
**folder instalasi pengguna** (`pip install --user` / pipx, mis. `~/.local/bin`) → `python -m modul`
(hanya untuk alat yang punya modul, mis. OCRmyPDF).

Folder instalasi pengguna dicari karena sering **tidak ada di `PATH`**: zsh tidak membaca `~/.bash_profile`,
dan aplikasi yang dibuka dari peluncur desktop tidak memuat konfigurasi shell. Akibatnya `recode_pdf`
(archive-pdf-tools) yang sudah terpasang dengan `pip install --user` dulu dilaporkan "tidak ada", sementara
OCRmyPDF terdeteksi lewat cadangan `python -m`. Di dialog Dependensi, pilih sebuah alat untuk melihat dari mana
ia ditemukan, atau **di mana saja** ia dicari bila tidak ditemukan.

Alat yang **ditemukan tetapi gagal dijalankan** (mis. `ModuleNotFoundError` karena versi Python yang
berbeda) kini ditandai **⚠ gagal jalan** dengan pesan galatnya, bukan "ada". Metode yang membutuhkannya
dinonaktifkan dengan alasan itu, alih-alih gagal di tengah proses. Yang dianggap gagal hanya traceback Python
atau penolakan OS untuk menjalankan; kode keluar bukan-nol saja tidak (jbig2 menampilkan bantuan dengan kode itu).
Untuk melihat galat lengkap: `~/.local/bin/recode_pdf --version` di terminal.

Tidak semua alat wajib. Aplikasi mendeteksi apa yang ada dan menonaktifkan metode/opsi yang
alatnya belum terpasang, lengkap dengan alasannya:

- tanpa **jbig2enc** → mask MRC otomatis memakai CCITT (lebih besar, tetap jalan). Di Debian/Ubuntu
  biner-nya bernama `jbig2`; keduanya dikenali.
- tanpa **unpaper** → opsi *Clean* OCRmyPDF nonaktif.
- tanpa **pngquant** → opsi kualitas PNG nonaktif (optimize 2/3 butuh alat ini).
- **jpegoptim** hanya dibutuhkan bila format gambar MRC dipilih JPEG.

Aplikasi **tidak pernah** menjalankan `sudo` atau memasang paket sendiri.

## File sementara dan cache

* Semua yang dibuat aplikasi selain hasil akhir berada di **satu folder kerja** (cache bawaan OS,
  lihat dialog Dependensi dan cache) — bukan di `/tmp` dan bukan di samping PDF Anda.
* **Scratch** (gambar halaman, file antara) **selalu dihapus otomatis**, termasuk saat gagal atau
  dibatalkan. Proses eksternal diarahkan memakai scratch ini (`TMPDIR`/`TEMP`/`TMP`).
  Sisa scratch dari proses yang crash disapu saat aplikasi dibuka.
* **Hasil ditulis atomik**: dibuat di scratch lalu dipindah ke folder tujuan hanya bila sukses,
  sehingga tidak ada file setengah jadi bila dibatalkan.
* **Cache OCR tidak dihapus otomatis.** Hapus lewat "Hapus cache file ini" (tab Kompres) atau
  dialog Dependensi dan cache (per entri / semua).
  * MRC menyimpan **hOCR** (kecil); gambar halaman diekstrak ulang setiap proses.
  * OCRmyPDF bekerja dua tahap: PDF antara berlapis teks (disimpan di cache), lalu kompresi dengan
    `--mode skip`. Pada sampel uji, ukuran hasil identik dengan sekali jalan (834 KB vs 834 KB).
  * Kunci cache = hash isi file + parameter OCR. Mengubah file atau parameter OCR membuat cache
    lama otomatis tidak dipakai.

### Menyetel parameter tanpa OCR ulang

Pada metode OCRmyPDF dan MRC, tiap parameter diberi penanda:

* **↻** — mengubah ini membuat OCR diulang (bahasa, deskew, PSM, …)
* **⚡** — tidak mengulang OCR (downsample, kualitas, rasio kompresi, …)

Jalankan sekali, lalu ubah parameter ⚡ dan jalankan lagi: OCR dilewati dan hasil muncul dalam
hitungan detik. Nama hasil otomatis tidak menimpa hasil sebelumnya (default `{nama}_{engine}`,
akhiran `_2`, `_3`, …; bisa diubah ke "Timpa" atau "Lewati").

## Catatan teknis MRC

* Gambar halaman diekstrak pada **piksel aslinya** bila halaman adalah scan murni (satu gambar penuh,
  tanpa teks); OCR dijalankan pada gambar yang sama persis dengan yang diproses `recode_pdf`.
  Ini mencegah peringatan *Invalid bounding box* (koordinat hOCR tidak cocok dengan gambar).
* DPI dokumen diambil dari resolusi efektif gambar di PDF. Halaman dengan resolusi berbeda >3%
  disamakan agar ukuran halaman tetap proporsional. Halaman non-scan dirender pada "DPI render".
* Rasio kompresi (`bg_rate`, dll.) berlaku untuk encoder Pillow/OpenJPEG/Grok; untuk Kakadu pakai
  kolom "Flag manual".

## Struktur kode

```
pdf_suite/
  main.py, app_context.py
  core/                 # tanpa Qt, mudah diuji (termasuk arranger.py: gabung/pisah/putar/ubah ukuran)
    engines/            # base.py, ghostscript.py, full_image.py, ocrmypdf_engine.py, mrc_engine.py
    schema.py           # opsi didefinisikan SATU kali -> UI, validasi, kunci cache
    profiles.py         # Tingkat 1: profil bawaan/milik pengguna, pencocokan, ekspor/impor
    workspace.py        # scratch, sapu sisa, output atomik
    cache.py            # cache OCR (hash file + parameter OCR)
    deps.py             # deteksi alat + petunjuk instal per OS
    pdfinfo.py          # analisis PDF + tumpukan gambar MRC
    procutil.py         # subprocess + pembatalan pohon proses
    runner.py           # QThread antrian job
  widgets/              # queue (antrean terpadu), page_list + arranger_dialogs (Atur Halaman), option_panel, log_console
  theme.py              # stylesheet berbasis palet sistem
  tabs/                 # compressor_tab, arranger_tab, image_export_tab, deps_cache_tab (dialog)
  tests/
```

**Menambah parameter**: tambahkan satu `Option` di skema engine terkait — panel UI, normalisasi nilai,
penanda ↻/⚡, dan kunci cache ikut otomatis. **Menambah metode**: buat subclass `Engine`, daftarkan di
`core/engines/__init__.py`.

## Pengujian

```bash
pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python -m pytest tests -q
```

Pengujian memakai alat nyata (gs, tesseract, ocrmypdf, recode_pdf). Sebagian besar tes yang butuh alat
otomatis dilewati bila alat belum terpasang, **kecuali** `test_deps_detect_and_custom_path` yang menegaskan
`gs` dan `tesseract` terpasang. Total 124 tes. Yang diuji: pembersihan scratch (sukses/gagal/batal), tidak ada sisa di temp sistem,
pembatalan mematikan seluruh pohon proses, cache dipakai ulang hanya bila parameter OCR tidak berubah,
dan alur lengkap lewat GUI (mode offscreen). Untuk profil: validitas definisi bawaan, kepemilikan nilai,
sinkronisasi tiga tingkat, simpan/hapus/ekspor/impor, seluruh jalur keamanan impor, persistensi, tata
letak (tanpa widget saling menimpa), dan regresi dua kesalahan yang ditemukan saat pengukuran. Kekuatan
tes diperiksa dengan uji mutasi (merusak kode sengaja, memastikan tes gagal).

**Lingkungan pengujian:** Ubuntu 24.04, Python 3.12, PyQt5 5.15, PyMuPDF 1.28, ocrmypdf 17.13,
archive-pdf-tools 1.5.7, Tesseract 5.3 (hanya bahasa `eng`). **Belum diuji:** Nobara/Fedora, Windows,
dan bahasa `ind`.

## Windows

Kode ditulis lintas-OS (pathlib, platformdirs, subprocess tanpa shell, pembatalan via `taskkill`,
jendela konsol disembunyikan), tetapi **belum diuji di Windows**. Petunjuk instal Windows di tab
Dependensi bertanda `[belum diuji]`. Keterbatasan yang diperkirakan: `unpaper` dan `jbig2enc` sulit
didapat (aplikasi turun ke mode terbatas otomatis).

## Rencana berikutnya

* Fase 2 (sebagian selesai: profil, simpan/muat/ekspor/impor, pengaman ukuran, klasifikasi lapisan OCR):
  panel analisis file (image-only vs bertext, ppi, saran metode) dan pratinjau perintah + salin.
  Yang masih perlu dikerjakan: pemilihan metode otomatis per file, analisis di thread pekerja (kini
  membekukan UI ±30 dtk untuk scan 150 halaman saat label cache MRC dihitung), dan anggaran ukuran cache.
* Fase 3: tab Bandingkan (satu file lewat beberapa metode) dan uji cepat pada halaman tertentu.
