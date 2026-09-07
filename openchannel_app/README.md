# Kalkulator Open Channel Flowmeter (PyQt5)

Aplikasi desktop untuk menghitung debit (flow rate), laju alir massa (mass
flow), dan estimasi kecepatan aliran pada berbagai jenis alat ukur aliran
saluran terbuka (open channel flowmeter), berdasarkan input ketinggian air
(head).

## Tipe Alat Ukur & Metode yang Didukung

| Tipe | Metode Perhitungan |
|---|---|
| **V-Notch Weir** (Weir Segitiga) | Standar (Cd konstan); Dengan Koreksi Head (H+kh) |
| **Rectangular Weir** (Weir Persegi) | Francis - Full Width; Francis - Terkontraksi (2 ujung); Rehbock |
| **Trapezoidal Weir** (Weir Trapesium) | Cipolletti (standar, sisi 1:4); Trapesium Umum (kemiringan kustom) |
| **Parshall Flume** | Aliran Bebas - Tabel Standar (throat 3 in - 8 ft); Koefisien Kustom (C & n manual) |

Setiap tipe/metode memiliki parameter yang dapat disesuaikan sendiri
(mis. sudut notch, panjang mercu, kemiringan sisi, tinggi mercu, lebar
leher flume, koefisien debit Cd, dsb).

## Instalasi

```bash
pip install -r requirements.txt
```

## Menjalankan Aplikasi

```bash
python main.py
```

## Cara Pakai

1. Pilih **Tipe Alat Ukur** dari dropdown.
2. Pilih **Metode Perhitungan** (jika tersedia lebih dari satu metode).
3. Isi **parameter spesifik** yang muncul (berbeda-beda tiap tipe/metode).
4. Masukkan **Ketinggian Air (H)** beserta satuannya (mm/cm/m).
5. (Opsional) Sesuaikan **Densitas Fluida** jika bukan air murni (default 1000 kg/m3).
6. Klik **Hitung**.

Hasil yang ditampilkan:
- **Debit Volumetrik (Q)** dalam m3/s, m3/jam, L/s, L/menit
- **Laju Alir Massa (ṁ)** dalam kg/s, kg/jam, ton/jam
- **Kecepatan Aliran (v)** - estimasi pada seksi kontrol (v = Q/A)
- **Luas Penampang Basah (A)** - estimasi

Sketsa visual di panel kiri otomatis menyesuaikan tipe & metode yang
dipilih, dan menampilkan label dimensi secara langsung mengikuti nilai
parameter yang Anda masukkan:
- **V-Notch Weir**: posisi *vertex* notch (referensi H=0), garis muka air
  berlabel **H**, sudut **θ**, dan bila memakai metode koreksi head, garis
  putus-putus **kh** (origin efektif He = H + kh).
- **Rectangular Weir**: **L** (panjang mercu), **H** (head di atas mercu),
  dan **P** (tinggi mercu, khusus metode Rehbock).
- **Trapezoidal Weir**: **L** (lebar dasar), **H**, dan kemiringan sisi
  (tetap 1:4 untuk Cipolletti, atau **z** untuk metode kustom).
- **Parshall Flume**: bagian konvergen/leher (**W**)/divergen, serta titik
  pengukuran head **Ha**.

## Export Riwayat Perhitungan

Setiap kali tombol **Hitung** berhasil dijalankan, hasilnya otomatis
tersimpan ke riwayat sesi (di memori aplikasi, selama aplikasi masih
terbuka). Gunakan tombol **Export ke Excel/CSV** (atau menu
`File > Export Riwayat ke Excel/CSV...`) untuk menyimpan seluruh riwayat
ke file:
- **Excel (.xlsx)** - rapi dengan header berwarna, lebar kolom otomatis.
  Memerlukan modul `openpyxl` (lihat `requirements.txt`).
- **CSV (.csv)** - selalu tersedia tanpa dependensi tambahan, dapat
  dibuka di Excel/Google Sheets.

Kolom yang diexport mencakup: waktu, tipe alat ukur, metode, seluruh
parameter yang dipakai, H (input & dalam meter), densitas, debit (4
satuan), laju alir massa (3 satuan), kecepatan, luas basah, catatan, dan
peringatan validasi.

Gunakan tombol **Hapus Riwayat** (atau menu `File > Hapus Riwayat`) untuk
mengosongkan riwayat sesi jika ingin memulai pencatatan baru.

## Tab Modbus RTU - Pembacaan Sensor Otomatis

Aplikasi memiliki tab kedua, **"Modbus RTU - Pembacaan Sensor"**, untuk
membaca ketinggian air langsung dari sensor level transmitter (ultrasonic,
radar, pressure) melalui RS-485/Modbus RTU, tanpa perlu input manual.

### 1. Koneksi Serial
Atur port (dropdown otomatis mendeteksi port yang tersedia + tombol
**Refresh**), baudrate, parity, data bits, stop bits, Slave ID (Unit ID),
dan timeout. Klik **Sambungkan**. Indikator bulat berwarna menunjukkan
status (hijau = terhubung, merah = terputus).

### 2. Pemetaan Register (Register Mapping)
Karena setiap sensor punya mapping register berbeda, seluruh parameter
berikut dapat dikonfigurasi dari UI:
- **Fungsi Baca**: Read Holding Registers (FC03) atau Read Input Registers (FC04)
- **Alamat Register** (0-based)
- **Tipe Data**: uint16, int16, uint32, int32, atau Float 32-bit (IEEE754)
- **Urutan Word** (khusus tipe 32-bit): register tinggi dulu atau rendah dulu
- **Faktor Skala** (multiplier) dan **Offset** (penambah) - nilai akhir
  dihitung sebagai `H = (register_terbaca × Skala) + Offset`
- **Satuan Hasil** (mm/cm/m) setelah skala

### 3. Kontrol Pembacaan
Fungsi pembacaan Modbus di sini murni untuk **mengisi ketinggian air (H)
di tab Kalkulasi secara otomatis** - bukan fitur pemantauan ketinggian
air yang berdiri sendiri. Karena itu setiap pembacaan yang berhasil
(baik sekali maupun polling) **selalu** langsung mengisi H dan
menghitung ulang debit/mass flow/kecepatan di tab Kalkulasi memakai
Tipe & Metode yang sedang aktif di sana - tidak ada opsi untuk hanya
mengisi H tanpa menghitung.
- **Baca Sensor Sekali** - pembacaan on-demand: mengisi field H di tab
  Kalkulasi lalu langsung menjalankan perhitungan (setara menekan
  tombol Hitung), termasuk menambah baris ke riwayat export manual.
- **Mulai Polling / Hentikan Polling** - pembacaan berkala otomatis sesuai
  **Interval Polling** yang diatur (mis. tiap 2 detik). Setiap polling
  mengisi H dan memperbarui hasil debit/mass flow/kecepatan di tab
  Kalkulasi secara live (tanpa membanjiri riwayat export manual).
- **Simpan Log ke CSV Setiap Polling** (checkbox) - mencatat setiap hasil
  polling (waktu, register mentah, nilai decode, H, dan hasil debit)
  sebagai baris baru pada file CSV yang dipilih. Log ini terpisah dari
  riwayat kalkulasi manual di tab Kalkulasi, agar tidak
  tercampur/membanjiri riwayat export manual.
- Polling otomatis berhenti sendiri setelah 5 kali gagal membaca
  berturut-turut (mis. kabel lepas), disertai notifikasi.

### 4. Simpan Sampel Polling ke Riwayat Kalkulasi (untuk Export)
Terpisah dari log CSV mentah di atas: bila dicentang, sebagian hasil
polling ikut ditambahkan ke Riwayat tab Kalkulasi, sehingga ikut
terekspor bersama hasil perhitungan manual saat menekan tombol
**Export Riwayat**. Karena polling bisa berjalan sangat cepat (interval
serendah 0,2 detik), hanya satu sampel yang disimpan per **Interval
Simpan ke Riwayat** yang diatur (default 10 detik) - bukan setiap
siklus polling. Setiap baris pada hasil export punya kolom **Sumber
Data** (`Manual (Kalkulasi)`, `Sensor Modbus (Baca Sekali)`, atau
`Polling Otomatis`) sehingga asal datanya tetap bisa dibedakan.

### Instalasi Dependensi Modbus
```bash
pip install pymodbus pyserial
```
Jika belum terpasang, aplikasi tetap berjalan normal (tab Kalkulasi tidak
terpengaruh); tab Modbus akan menampilkan peringatan dan pesan error yang
jelas saat mencoba menyambung/membaca.

## Struktur File

```
openchannel_app/
├── main.py           # Aplikasi GUI utama (PyQt5) - tab Kalkulasi & tab Modbus RTU
├── flow_calc.py       # Modul rumus/engine perhitungan seluruh tipe & metode
├── modbus_reader.py    # Wrapper komunikasi Modbus RTU (koneksi, baca & decode register)
├── requirements.txt      # Dependensi (PyQt5 wajib; openpyxl, pymodbus, pyserial opsional)
└── README.md
```

## Catatan Penting / Disclaimer

Formula yang digunakan adalah formula empiris standar yang umum dipakai
dalam hidrometri saluran terbuka (Francis, Rehbock, Cipolletti, Kindsvater,
tabel koefisien Parshall Flume, dsb). Koefisien default (Cd, C, n, kh) yang
disediakan bersifat **nilai tipikal/umum**.

Untuk keperluan:
- Pengukuran resmi / legal metering / custody transfer,
- Instalasi dengan toleransi akurasi ketat,
- Rentang head/geometri di luar kondisi tipikal,

selalu **verifikasi koefisien terhadap standar yang berlaku** di industri/
lokasi Anda (mis. ISO 1438, ISO 9826, SNI, atau hasil kalibrasi lapangan),
atau konsultasikan dengan insinyur hidrologi/instrumentasi yang berwenang.

Estimasi **kecepatan aliran** dan **luas penampang basah** dihitung dari
geometri sederhana pada H yang diukur (bukan pengukuran langsung), sehingga
sifatnya indikatif.

## Menambahkan Tipe/Metode Baru

Struktur `TYPES` di `flow_calc.py` dirancang modular. Untuk menambah tipe
atau metode baru:
1. Tulis fungsi perhitungan baru dengan signature `func(H_m, params, rho) -> (Q, area, notes, warnings)`.
2. Tambahkan entri baru pada dict `TYPES` dengan daftar parameter (`_p(...)`) sesuai kebutuhan.
3. Aplikasi GUI akan otomatis membangun form input berdasarkan struktur ini — tidak perlu mengubah `main.py`.
