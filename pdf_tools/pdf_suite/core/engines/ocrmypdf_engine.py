# -*- coding: utf-8 -*-
"""Engine OCRmyPDF (dipanggil lewat CLI/subprocess).

Dua tahap bila cache OCR aktif:
  1. OCR  -> PDF antara berlapis teks (disimpan di cache; parameter bertanda ↻)
  2. Optimasi/kompresi dari PDF antara itu dengan --mode skip (parameter ⚡)
Mengubah parameter ⚡ tidak mengulang OCR.
"""
from pathlib import Path
from typing import List

from ..cache import OcrCache
from ..deps import tesseract_languages
from ..schema import OptionSet, bool_opt, choice_opt, float_opt, int_opt, langs_opt, text_opt
from .base import CacheStatus, Engine, EngineError, EngineResult, JobContext, page_count, split_args

PSM = [("", "Bawaan")] + [(str(i), str(i)) for i in (1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13)]
OEM = [("", "Bawaan"), ("0", "0 — legacy"), ("1", "1 — LSTM"), ("2", "2 — legacy + LSTM"), ("3", "3 — otomatis")]


class OcrmypdfEngine(Engine):
    id = "ocrmypdf"
    name = "OCRmyPDF"
    description = ("PDF searchable dengan tampilan halaman tetap asli; optimasi gambar (JPEG/PNG). "
                   "Hasil biasanya lebih besar dari MRC tetapi paling aman untuk tampilan.")
    uses_ocr = True
    size_guard = False      # menambah lapisan teks OCR: hasil sedikit lebih besar tetap bernilai
    required_tools = ("ocrmypdf", "tesseract")
    options = OptionSet([
        # ---- OCR (↻) ----
        langs_opt("languages", "Bahasa OCR", "eng", "Gabungkan dengan +, mis. ind+eng. Daftar dari tesseract --list-langs.", affects_ocr=True),
        choice_opt("mode", "Jika halaman sudah punya teks", "default",
                   [("default", "Error (bawaan)"), ("skip", "Lewati halaman bertext"), ("force", "Paksa OCR (rasterisasi)"),
                    ("redo", "Ulangi OCR (ganti lapisan lama)")],
                   "Perilaku untuk PDF yang sebagian/seluruhnya sudah berisi teks.", affects_ocr=True),
        bool_opt("deskew", "Luruskan halaman miring (deskew)", True, "Mengubah gambar halaman di hasil akhir.", affects_ocr=True),
        bool_opt("rotate", "Putar halaman otomatis", False, affects_ocr=True),
        bool_opt("clean", "Bersihkan bintik sebelum OCR (unpaper)", False,
                 "Hanya untuk OCR; gambar bersih tidak masuk hasil akhir.", affects_ocr=True),
        bool_opt("clean_final", "Pakai hasil bersih di PDF akhir", False,
                 "Gambar yang dibersihkan unpaper dipakai di hasil. Bisa menghapus konten yang diinginkan.", affects_ocr=True),
        # ---- Kompresi (⚡) ----
        choice_opt("optimize", "Level optimasi", "3",
                   [("0", "0 — tanpa optimasi"), ("1", "1 — lossless"), ("2", "2 — lossy JPEG"), ("3", "3 — lossy agresif (pngquant)")],
                   "Level 2-3 menurunkan kualitas gambar demi ukuran."),
        int_opt("jpeg_quality", "Kualitas JPEG (0 = bawaan)", 60, 0, 100, "Hanya berpengaruh pada gambar yang sudah JPEG."),
        int_opt("png_quality", "Kualitas PNG/pngquant (0 = bawaan)", 0, 0, 100, "Kuantisasi palet warna pada level 3."),
        choice_opt("output_type", "Tipe output", "auto",
                   [("auto", "auto (PDF/A bila lolos)"), ("pdf", "pdf biasa"), ("pdfa", "pdfa (PDF/A-2b)"),
                    ("pdfa-1", "pdfa-1"), ("pdfa-3", "pdfa-3")],
                   "PDF/A cocok untuk arsip; 'pdf' meminimalkan perubahan."),
        # ---- Lanjutan: OCR ----
        bool_opt("remove_background", "Hapus latar (putihkan)", False, "Untuk halaman berwarna/abu.", group="advanced", affects_ocr=True),
        int_opt("oversample", "Oversample ke DPI (0 = mati)", 0, 0, 1200, group="advanced", affects_ocr=True, suffix=" dpi"),
        float_opt("rotate_threshold", "Ambang rotasi otomatis (0 = bawaan)", 0.0, 0.0, 100.0, 0.5, group="advanced", affects_ocr=True),
        choice_opt("psm", "Tesseract page segmentation (PSM)", "", PSM, group="advanced", affects_ocr=True),
        choice_opt("oem", "Tesseract OCR engine mode (OEM)", "", OEM, group="advanced", affects_ocr=True),
        choice_opt("thresholding", "Tesseract thresholding", "",
                   [("", "Bawaan"), ("otsu", "otsu"), ("adaptive-otsu", "adaptive-otsu"), ("sauvola", "sauvola")],
                   "Membantu halaman berlatar tidak rata. Butuh Tesseract 5+.", group="advanced", affects_ocr=True),
        float_opt("skip_big", "Lewati OCR halaman > MPixel (0 = mati)", 0.0, 0.0, 10000.0, 1.0, group="advanced", affects_ocr=True),
        int_opt("tesseract_timeout", "Timeout OCR per halaman (0 = bawaan)", 0, 0, 7200, group="advanced", suffix=" dtk"),
        text_opt("extra_ocr", "Argumen tambahan (tahap OCR)", "", "Ditempel apa adanya ke perintah ocrmypdf tahap OCR.", group="advanced", affects_ocr=True),
        # ---- Lanjutan: kompresi ----
        choice_opt("pdfa_image_compression", "Kompresi gambar PDF/A", "auto",
                   [("auto", "auto"), ("jpeg", "jpeg"), ("lossless", "lossless")],
                   "Hanya berlaku bila output PDF/A.", group="advanced", enabled_if=lambda v: v.get("output_type") != "pdf"),
        int_opt("gs_jpeg_quality", "Ghostscript JPEG quality (0 = bawaan)", 0, 0, 100, group="advanced",
                enabled_if=lambda v: v.get("output_type") != "pdf"),
        int_opt("gs_jpeg_maxdpi", "Ghostscript max DPI (0 = mati)", 0, 0, 1200, group="advanced", suffix=" dpi",
                enabled_if=lambda v: v.get("output_type") != "pdf"),
        choice_opt("color_conversion", "Konversi warna", "",
                   [("", "Bawaan"), ("Gray", "Gray (hitam-putih)"), ("RGB", "RGB"), ("CMYK", "CMYK"),
                    ("LeaveColorUnchanged", "LeaveColorUnchanged")], group="advanced"),
        text_opt("extra_compress", "Argumen tambahan (tahap kompresi)", "", "Ditempel ke perintah ocrmypdf tahap kompresi.", group="advanced"),
        # ---- Umum ----
        int_opt("jobs", "Jumlah core CPU (0 = semua)", 0, 0, 128, group="advanced"),
        text_opt("title", "Metadata: judul", "", group="advanced"),
        text_opt("author", "Metadata: penulis", "", group="advanced"),
        text_opt("subject", "Metadata: subjek", "", group="advanced"),
        text_opt("keywords", "Metadata: kata kunci", "", group="advanced"),
    ])

    # ---- ketersediaan opsi ---------------------------------------------
    def option_notes(self, tools):
        notes = {}
        if not (tools.get("unpaper") and tools["unpaper"].found):
            notes["clean"] = (False, "unpaper tidak terpasang")
            notes["clean_final"] = (False, "unpaper tidak terpasang")
        if not (tools.get("pngquant") and tools["pngquant"].found):
            notes["png_quality"] = (False, "pngquant tidak terpasang (dibutuhkan optimize 2/3)")
        return notes

    # ---- pembangun argumen -----------------------------------------------
    def _common(self, v) -> List[str]:
        a: List[str] = []
        if v["jobs"] > 0:
            a += ["-j", str(v["jobs"])]
        for key, flag in (("title", "--title"), ("author", "--author"), ("subject", "--subject"), ("keywords", "--keywords")):
            if v[key].strip():
                a += [flag, v[key].strip()]
        return a

    def _ocr_flags(self, v) -> List[str]:
        a = ["-l", v["languages"].strip() or "eng"]
        if v["mode"] != "default":
            a += ["--mode", v["mode"]]
        if v["deskew"]:
            a.append("--deskew")
        if v["rotate"]:
            a.append("--rotate-pages")
            if v["rotate_threshold"] > 0:
                a += ["--rotate-pages-threshold", str(v["rotate_threshold"])]
        if v["clean"]:
            a.append("--clean")
        if v["clean_final"]:
            a.append("--clean-final")
        if v["remove_background"]:
            a.append("--remove-background")
        if v["oversample"] > 0:
            a += ["--oversample", str(v["oversample"])]
        if v["psm"]:
            a += ["--tesseract-pagesegmode", v["psm"]]
        if v["oem"]:
            a += ["--tesseract-oem", v["oem"]]
        if v["thresholding"]:
            a += ["--tesseract-thresholding", v["thresholding"]]
        if v["skip_big"] > 0:
            a += ["--skip-big", str(v["skip_big"])]
        if v["tesseract_timeout"] > 0:
            a += ["--tesseract-timeout", str(v["tesseract_timeout"])]
        return a + split_args(v["extra_ocr"])

    def _compress_flags(self, v) -> List[str]:
        a = ["--output-type", v["output_type"], "-O", v["optimize"]]
        if v["jpeg_quality"] > 0:
            a += ["--jpeg-quality", str(v["jpeg_quality"])]
        if v["png_quality"] > 0:
            a += ["--png-quality", str(v["png_quality"])]
        if v["output_type"] != "pdf":
            if v["pdfa_image_compression"] != "auto":
                a += ["--pdfa-image-compression", v["pdfa_image_compression"]]
            if v["gs_jpeg_quality"] > 0:
                a += ["--ghostscript-jpeg-quality", str(v["gs_jpeg_quality"])]
            if v["gs_jpeg_maxdpi"] > 0:
                a += ["--ghostscript-jpeg-maxdpi", str(v["gs_jpeg_maxdpi"])]
        if v["color_conversion"]:
            a += ["--color-conversion-strategy", v["color_conversion"]]
        return [str(x) for x in a] + split_args(v["extra_compress"])

    def build_cmds(self, base: List[str], src, out, v, two_pass: bool, mid=None):
        """Kembalikan daftar perintah (1 atau 2)."""
        common = self._common(v)
        if not two_pass:
            return [base + common + self._ocr_flags(v) + self._compress_flags(v) + [str(src), str(out)]]
        pass1 = base + common + self._ocr_flags(v) + ["--output-type", "pdf", "-O", "0", str(src), str(mid)]
        pass2 = base + common + ["-l", v["languages"].strip() or "eng", "--mode", "skip"] \
            + self._compress_flags(v) + [str(mid), str(out)]
        return [pass1, pass2]

    # ---- cache ----------------------------------------------------------------
    def _cache_params(self, v) -> dict:
        p = {"engine": "ocrmypdf"}
        p.update(self.options.ocr_params(v))
        return p

    def cache_status(self, src, values, cache: OcrCache):
        v = self.options.normalize(values)
        try:
            key = cache.make_id(cache.file_hash(src), self._cache_params(v))
        except OSError:
            return None
        if cache.exists(key):
            e = cache.lookup(key)
            return CacheStatus(True, e, "OCR cache ada (%s) — dipakai ulang" % _fmt_size(e.size if e else 0))
        return CacheStatus(False, None, "OCR cache belum ada — OCR akan dijalankan")

    # ---- eksekusi ---------------------------------------------------------------
    def _check_languages(self, ctx: JobContext, langs: str):
        have = set(tesseract_languages(ctx.tool("tesseract")))
        if not have:
            return
        missing = [l for l in langs.replace(",", "+").split("+") if l and l not in have]
        if missing:
            from ..deps import install_hint
            raise EngineError("Bahasa OCR belum terpasang: %s. Terpasang: %s.\n%s" %
                              (", ".join(missing), ", ".join(sorted(have)), install_hint("tesseract")))

    def _run(self, ctx: JobContext, cmd: List[str], label: str):
        def on_line(line):
            if line.strip():
                ctx.log("  " + line)
        res = ctx.run(cmd, on_line=on_line)
        if res.returncode != 0:
            hint = ""
            if res.returncode == 6:
                hint = ("\nHalaman sudah berisi teks. Ubah 'Jika halaman sudah punya teks' "
                        "(lewati / paksa / ulangi) lalu coba lagi.")
            raise EngineError("%s gagal (kode %s).%s\n%s" % (label, res.returncode, hint, "\n".join(res.tail[-8:])))

    def process(self, src: Path, out: Path, values: dict, ctx: JobContext) -> EngineResult:
        v = self.options.normalize(values)
        oc = ctx.tool("ocrmypdf")
        self._check_languages(ctx, v["languages"])
        base = list(oc.cmd)
        res = EngineResult()
        if not ctx.use_cache:
            ctx.progress(0.05)
            self._run(ctx, self.build_cmds(base, src, out, v, False)[0], "OCRmyPDF")
            ctx.progress(1.0)
            return res

        cache = ctx.cache
        key = cache.make_id(cache.file_hash(src), self._cache_params(v))
        mid = None
        entry = cache.lookup(key)
        if entry and entry.file("ocr.pdf").exists():
            ctx.log("  OCR cache dipakai (tahap OCR dilewati).")
            mid = entry.file("ocr.pdf")
            res.cache_used = True
            ctx.progress(0.7)
            pass2 = self.build_cmds(base, src, out, v, True, mid)[1]
        else:
            res.cache_used = False
            mid = ctx.scratch.path / "ocr_stage.pdf"
            p1, pass2 = self.build_cmds(base, src, out, v, True, mid)
            ctx.log("  Tahap 1/2: OCR …")
            ctx.progress(0.05)
            self._run(ctx, p1, "OCRmyPDF (tahap OCR)")
            ctx.check_cancel()
            cache.store(key, "ocr_pdf", {"ocr.pdf": mid}, Path(src).name, page_count(src), self._cache_params(v))
            ctx.progress(0.7)
        ctx.log("  Tahap 2/2: optimasi/kompresi …")
        self._run(ctx, pass2, "OCRmyPDF (tahap kompresi)")
        ctx.progress(1.0)
        return res


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return str(n)
