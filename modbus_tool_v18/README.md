# Modbus Tools Kalingin v18.0

Aplikasi master Modbus RTU/TCP berbasis PyQt5 (pymodbus 2.x & 3.x).

## Menjalankan
```
pip install -r requirements.txt
python modbus_tool.py          # atau: python -m modbus_app
```

## Struktur
| Berkas | Isi |
|---|---|
| `modbus_tool.py` | titik masuk |
| `modbus_app/konfigurasi.py` | konstanta, logging berotasi, penulisan JSON atomik |
| `modbus_app/inti.py` | kompatibilitas pymodbus, encode/decode, validasi, pengelompokan blok tag (tanpa GUI) |
| `modbus_app/worker.py` | thread: scan, polling/logging, baca tag (per blok), tulis |
| `modbus_app/tab_*.py` | satu mixin per tab (scan, reader, write, logger, tag) |
| `modbus_app/jendela_utama.py` | jendela utama, koneksi, preset, interlock |
| `tests/` | 85 tes: logika murni, GUI offscreen, dan ujung-ke-ujung ke server Modbus TCP mini |

## Tes & build
```
pip install -r requirements-dev.txt
python -m pytest               # semua tes
python build.py                # executable (folder);  --onefile untuk satu berkas
```
Konfigurasi, preset otomatis, dan log (`aplikasi.log`, berotasi) disimpan di folder
`%APPDATA%\ModbusToolsKalingin` (Windows) atau `~/.config/ModbusToolsKalingin`.

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
