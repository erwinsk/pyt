# PDF Tools Suite

Gabungan dari 2 aplikasi PDF yang sebelumnya terpisah, sekarang jadi 1
aplikasi dengan tab:

1. **Compressor** — kompresi PDF via mode Ghostscript atau Full Image
   (PyMuPDF + Pillow), grayscale, dan opsi **Sharpen** (baru, hanya
   aktif di mode Full Image).
2. **PDF -> Gambar** — ekspor tiap halaman PDF menjadi file gambar
   (PNG/JPG) terpisah, satu subfolder per PDF.

## Menjalankan

```bash
pip install -r requirements.txt
python main.py
```

Mode **Ghostscript** di tab Compressor butuh Ghostscript terpasang di
sistem (`gs` di Linux/Mac, `gswin64c.exe`/`gswin32c.exe` di Windows),
atau isi path custom lewat opsi "Gunakan Custom GS Path".

## Asal-usul kode

| Tab | Berasal dari |
|---|---|
| Compressor | `legacy/ultimate-pdf-compresor.py` (dipertahankan hampir seluruhnya, + opsi Sharpen dari `legacy/convert_pdf_img_2.py`) |
| PDF -> Gambar | Fungsi `pdf_to_images()` di `legacy/convert_pdf_img_1.py`, dibungkus GUI baru yang konsisten dengan tab Compressor |

File di folder `legacy/` disimpan sebagai arsip/referensi, **tidak lagi
dipakai** oleh aplikasi ini — aman dihapus kalau sudah yakin suite ini
berjalan baik. Lihat `../../CHANGELOG.md` di root proyek untuk detail
keputusan penggabungan.
