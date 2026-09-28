# Arsip: qt-pymodbus-debug & qt-pymodbus-logger

Kedua aplikasi ini sudah TIDAK diperlukan lagi. Semua fiturnya sudah
terangkum di `modbus_tool.py` (aplikasi "Modbus Tools Kalingin"):

| Fitur di app lama | Sekarang ada di modbus_tool.py |
|---|---|
| qt-pymodbus-debug: baca/tulis register, lihat frame TX/RX | Tab "Pembaca Modbus Live", "Write Register / Coil", "Pemindai Peta Register" |
| qt-pymodbus-logger: polling & simpan ke CSV/MySQL | Tab "Data Logger CSV" (kini dengan opsi simpan ke MySQL) dan tab "Daftar Tag (Multi-Read)" (kini juga dengan logger CSV & MySQL, untuk tag dari alamat yang tidak berurutan) |
| float converter (folder terpisah) | Tab "Float Converter" |

Kedua folder ini disimpan sebagai arsip/referensi (mis. kalau perlu melihat
lagi implementasi `ModbusFrameHandler` untuk capture frame mentah, yang
belum diadopsi ke modbus_tool.py). Aman dihapus kalau sudah yakin
modbus_tool.py mencakup semua yang dibutuhkan.
