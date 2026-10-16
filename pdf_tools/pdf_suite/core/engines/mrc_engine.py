# -*- coding: utf-8 -*-
"""Engine MRC (archive-pdf-tools / recode_pdf).

Alur:
  1. Analisis PDF + ekstrak gambar halaman pada piksel ASLI  (PyMuPDF)
  2. OCR tesseract -> hOCR pada gambar yang SAMA              (di-cache; ↻)
  3. recode_pdf --from-imagestack ... -T hocr                 (kompresi; ⚡)
Karena hOCR dan gambar selalu selaras, peringatan 'Invalid bounding box' tidak muncul.
"""
import re
from pathlib import Path
from typing import List, Optional

from ..cache import OcrCache
from ..deps import install_hint, tesseract_languages
from ..pdfinfo import analyze, analyze_cached, build_stack, plan_stack
from ..schema import OptionSet, choice_opt, int_opt, langs_opt, text_opt
from .base import CacheStatus, Engine, EngineError, EngineResult, JobContext, page_count, split_args
from .ocrmypdf_engine import OEM, PSM, _fmt_size

NOISE = re.compile(r"^\s+[A-Z0-9_]+$|`fitz` API is deprecated")


class MrcEngine(Engine):
    id = "mrc"
    name = "MRC (recode_pdf)"
    description = ("Memisahkan teks (mask 1-bit JBIG2) dari latar berwarna (JPEG2000 resolusi rendah). "
                   "Ukuran terkecil untuk scan berwarna, teks tetap dapat dicari.")
    uses_ocr = True
    required_tools = ("recode_pdf", "tesseract")
    options = OptionSet([
        # ---- OCR / sumber gambar (↻) ----
        langs_opt("languages", "Bahasa OCR", "eng", "Gabungkan dengan +, mis. ind+eng.", affects_ocr=True),
        choice_opt("psm", "Tesseract page segmentation (PSM)", "", PSM, group="advanced", affects_ocr=True),
        choice_opt("oem", "Tesseract OCR engine mode (OEM)", "", OEM, group="advanced", affects_ocr=True),
        int_opt("dpi_override", "DPI dokumen (0 = otomatis dari file)", 0, 0, 1200,
                "Hanya label DPI; ukuran halaman = piksel / DPI. Isi hanya bila tahu DPI sebenarnya.",
                group="advanced", affects_ocr=True, suffix=" dpi"),
        int_opt("render_dpi", "DPI render halaman non-scan", 200, 72, 600,
                "Halaman bukan scan murni (teks/vektor) dirender pada DPI ini.", group="advanced",
                affects_ocr=True, suffix=" dpi"),
        # ---- Kompresi (⚡) ----
        int_opt("bg_downsample", "Downsample latar (faktor)", 2, 0, 8,
                "Semakin besar semakin kecil. Tidak memengaruhi ketajaman huruf. 0 = tanpa downsample."),
        choice_opt("color_mode", "Warna", "keep", [("keep", "Pertahankan warna"), ("gray", "Grayscale"), ("bw", "Hitam-putih 1-bit")]),
        choice_opt("mask_compression", "Kompresi mask teks", "jbig2",
                   [("jbig2", "JBIG2 (terkecil)"), ("ccitt", "CCITT G4")],
                   "Jika jbig2enc tidak terpasang, otomatis memakai CCITT."),
        choice_opt("denoise", "Denoise mask", "fast",
                   [("none", "Tidak ada (huruf paling utuh)"), ("fast", "Cepat"), ("bregman", "Bregman (halus, lambat)")],
                   "Membersihkan bintik pada mask teks agar lebih kecil."),
        int_opt("fg_downsample", "Downsample foreground (faktor)", 0, 0, 8, group="advanced"),
        int_opt("downsample", "Downsample seluruh gambar (faktor)", 0, 0, 8,
                "Menurunkan resolusi SEMUA lapisan termasuk mask — huruf jadi lebih kasar.", group="advanced"),
        choice_opt("mrc_format", "Format gambar MRC", "jpeg2000",
                   [("jpeg2000", "JPEG2000 (lebih kecil)"), ("jpeg", "JPEG (butuh jpegoptim)")], group="advanced"),
        choice_opt("jp2_impl", "Encoder JPEG2000", "pillow",
                   [("pillow", "Pillow (bawaan)"), ("openjpeg", "OpenJPEG (opj_compress)"),
                    ("grok", "Grok"), ("kakadu", "Kakadu")], group="advanced"),
        int_opt("bg_rate", "Rasio kompresi latar (:1)", 500, 1, 5000,
                "Lebih besar = lebih kecil & lebih buram. Berlaku untuk Pillow/OpenJPEG/Grok.", group="advanced"),
        int_opt("fg_rate", "Rasio kompresi foreground (:1)", 750, 1, 5000, group="advanced"),
        text_opt("hq_pages", "Halaman kualitas tinggi", "",
                 "Daftar dipisah koma, boleh negatif: 1,2,-1 (tanpa downsample, kompresi lebih ringan).", group="advanced"),
        int_opt("hq_bg_rate", "Rasio latar halaman HQ (:1)", 100, 1, 5000, group="advanced"),
        int_opt("hq_fg_rate", "Rasio foreground halaman HQ (:1)", 300, 1, 5000, group="advanced"),
        text_opt("bg_flags", "Flag manual latar (menimpa rasio)", "", "Mis. -slope 44250 untuk Kakadu.", group="advanced"),
        text_opt("fg_flags", "Flag manual foreground (menimpa rasio)", "", group="advanced"),
        text_opt("hq_bg_flags", "Flag manual latar HQ", "", group="advanced"),
        text_opt("hq_fg_flags", "Flag manual foreground HQ", "", group="advanced"),
        int_opt("threads", "Jumlah thread recode_pdf (0 = 1)", 0, 0, 64, group="advanced"),
        text_opt("title", "Metadata: judul", "", group="advanced"),
        text_opt("author", "Metadata: penulis", "", group="advanced"),
        text_opt("subject", "Metadata: subjek", "", group="advanced"),
        text_opt("language_meta", "Metadata: bahasa (RFC 3066)", "", "Mis. id en", group="advanced"),
        text_opt("extra_args", "Argumen tambahan recode_pdf", "", "Ditempel apa adanya.", group="advanced"),
    ])

    def option_notes(self, tools):
        notes = {}
        if not (tools.get("jbig2") and tools["jbig2"].found):
            notes["mask_compression"] = (True, "jbig2enc tidak terpasang — akan memakai CCITT")
        return notes

    # ---- rencana & cache ---------------------------------------------------------
    def _plan(self, src, v, fresh: bool = False):
        info = analyze(src) if fresh else analyze_cached(src)
        return info, plan_stack(info, v["render_dpi"], v["dpi_override"])

    def _cache_params(self, v, plan) -> dict:
        p = {"engine": "mrc-hocr"}
        p.update({k: val for k, val in self.options.ocr_params(v).items() if k not in ("dpi_override", "render_dpi")})
        p["stack"] = plan.signature()
        return p

    def cache_status(self, src, values, cache: OcrCache):
        v = self.options.normalize(values)
        try:
            _info, plan = self._plan(src, v)
            key = cache.make_id(cache.file_hash(src), self._cache_params(v, plan))
        except Exception:
            return None
        if cache.exists(key):
            e = cache.lookup(key)
            return CacheStatus(True, e, "OCR cache ada (%s) — dipakai ulang" % _fmt_size(e.size if e else 0))
        return CacheStatus(False, None, "OCR cache belum ada — OCR akan dijalankan")

    # ---- recode_pdf ----------------------------------------------------------------
    @staticmethod
    def _rate_flag(impl: str, rate: int) -> Optional[str]:
        if impl == "pillow":
            return 'quality_mode:"rates";quality_layers:[%d]' % rate
        if impl in ("openjpeg", "grok"):
            return "-r %d" % rate
        return None  # kakadu: gunakan flag manual

    def build_recode_cmd(self, rc_cmd, stack_glob, hocr, out, dpi, tmp_dir, v, mask_compression) -> List[str]:
        cmd = list(rc_cmd) + ["--from-imagestack", stack_glob, "-T", str(hocr), "-o", str(out),
                              "-D", str(dpi), "--tmp-dir", str(tmp_dir), "--verbose",
                              "--mask-compression", mask_compression,
                              "--denoise-mask", v["denoise"], "-J", v["jp2_impl"],
                              "--mrc-image-format", v["mrc_format"]]
        if v["threads"] > 1:
            cmd += ["--threads", str(v["threads"])]
        for flag, key in (("--bg-downsample", "bg_downsample"), ("--fg-downsample", "fg_downsample"),
                          ("--downsample", "downsample")):
            if v[key] > 0:
                cmd += [flag, str(v[key])]
        if v["color_mode"] == "gray":
            cmd.append("--grayscale-pdf")
        elif v["color_mode"] == "bw":
            cmd.append("--bw-pdf")
        if v["hq_pages"].strip():
            cmd += ["--hq-pages", v["hq_pages"].strip()]
        if v["mrc_format"] == "jpeg2000":
            for flag, manual, rate in (("--bg-compression-flags", "bg_flags", "bg_rate"),
                                       ("--fg-compression-flags", "fg_flags", "fg_rate"),
                                       ("--hq-bg-compression-flags", "hq_bg_flags", "hq_bg_rate"),
                                       ("--hq-fg-compression-flags", "hq_fg_flags", "hq_fg_rate")):
                val = v[manual].strip() or self._rate_flag(v["jp2_impl"], v[rate])
                if val:
                    cmd.append(f"{flag}={val}")   # bentuk '=' wajib agar nilai berawalan '-' diterima
        else:
            for flag, manual in (("--bg-compression-flags", "bg_flags"), ("--fg-compression-flags", "fg_flags"),
                                 ("--hq-bg-compression-flags", "hq_bg_flags"), ("--hq-fg-compression-flags", "hq_fg_flags")):
                if v[manual].strip():
                    cmd.append(f"{flag}={v[manual].strip()}")
        for flag, key in (("--metadata-title", "title"), ("--metadata-author", "author"),
                          ("--metadata-subject", "subject")):
            if v[key].strip():
                cmd += [flag, v[key].strip()]
        if v["language_meta"].strip():
            cmd += ["--metadata-language"] + v["language_meta"].split()
        return cmd + split_args(v["extra_args"])

    # ---- eksekusi ---------------------------------------------------------------------
    def process(self, src: Path, out: Path, values: dict, ctx: JobContext) -> EngineResult:
        import os
        v = self.options.normalize(values)
        rc = ctx.tool("recode_pdf")
        tess = ctx.tool("tesseract")
        res = EngineResult()

        have = set(tesseract_languages(tess))
        missing = [l for l in v["languages"].replace(",", "+").split("+") if l and have and l not in have]
        if missing:
            raise EngineError("Bahasa OCR belum terpasang: %s. Terpasang: %s.\n%s" %
                              (", ".join(missing), ", ".join(sorted(have)), install_hint("tesseract")))

        mask = v["mask_compression"]
        if mask == "jbig2" and not ctx.have("jbig2"):
            ctx.log("  jbig2enc tidak ditemukan — mask memakai CCITT (hasil lebih besar).")
            mask = "ccitt"
        if v["mrc_format"] == "jpeg" and not ctx.have("jpegoptim"):
            raise EngineError("Format MRC 'JPEG' membutuhkan jpegoptim. " + install_hint("jpegoptim"))
        if v["jp2_impl"] in ("openjpeg", "grok", "kakadu"):
            import shutil
            need = {"openjpeg": "opj_compress", "grok": "grk_compress", "kakadu": "kdu_compress"}[v["jp2_impl"]]
            if not shutil.which(need, path=ctx.env().get("PATH")):
                raise EngineError(f"Encoder JPEG2000 '{v['jp2_impl']}' butuh '{need}' di PATH. Gunakan 'Pillow' (bawaan).")

        # 1. analisis + tumpukan gambar pada piksel asli
        ctx.log("  Menganalisis dan menyiapkan gambar halaman …")
        info, plan = self._plan(src, v, fresh=True)
        for n in plan.notes:
            ctx.log("  • " + n)
        stack = ctx.scratch.subdir("stack")
        build_stack(src, plan, stack, ctx.is_cancelled,
                    lambda i, t: ctx.progress(0.15 * i / t))
        ctx.check_cancel()
        n_pages = len(plan.pages)

        # 2. OCR (cache)
        cache = ctx.cache
        params = self._cache_params(v, plan)
        key = cache.make_id(cache.file_hash(src), params)
        hocr: Optional[Path] = None
        entry = cache.lookup(key) if ctx.use_cache else None
        if entry and entry.file("ocr.hocr").exists():
            hocr = entry.file("ocr.hocr")
            res.cache_used = True
            ctx.log("  OCR cache dipakai (tahap OCR dilewati).")
            ctx.progress(0.55)
        else:
            res.cache_used = False
            ctx.log("  Menjalankan OCR (tesseract) …")
            (stack / "list.txt").write_text("\n".join(f"p{i + 1:04d}.png" for i in range(n_pages)) + "\n", encoding="utf-8")
            cmd = list(tess.cmd) + ["list.txt", "ocr", "-l", v["languages"].strip() or "eng"]
            if v["psm"]:
                cmd += ["--psm", v["psm"]]
            if v["oem"]:
                cmd += ["--oem", v["oem"]]
            cmd.append("hocr")
            rx = re.compile(r"^Page (\d+)")

            def on_ocr(line):
                m = rx.match(line)
                if m:
                    ctx.progress(0.15 + 0.4 * (int(m.group(1)) + 1) / n_pages)

            r = ctx.run(cmd, on_line=on_ocr, cwd=str(stack))
            produced = stack / "ocr.hocr"
            if r.returncode != 0 or not produced.exists():
                raise EngineError("Tesseract gagal (kode %s).\n%s" % (r.returncode, "\n".join(r.tail[-6:])))
            n_ocr = len(re.findall(r"class=['\"]ocr_page['\"]", produced.read_text(encoding="utf-8", errors="replace")))
            if n_ocr != n_pages:
                raise EngineError(f"Jumlah halaman hOCR ({n_ocr}) tidak sama dengan PDF ({n_pages}).")
            hocr = ctx.scratch.path / "ocr.hocr"
            os.replace(produced, hocr)
            if ctx.use_cache:
                cache.store(key, "hocr", {"ocr.hocr": hocr}, Path(src).name, n_pages, params)
            ctx.progress(0.55)
        ctx.check_cancel()

        # 3. recode_pdf
        ctx.log("  Kompresi MRC (recode_pdf) …")
        import glob as _glob
        pattern = os.path.join(_glob.escape(str(stack)), "p*.png")
        rtmp = ctx.scratch.subdir("recode_tmp")
        cmd = self.build_recode_cmd(rc.cmd, pattern, hocr, out, plan.doc_dpi, rtmp, v, mask)
        stages = (("Creating text only PDF", 0.6), ("Inserting (and compressing) images", 0.65),
                  ("Saving PDF now", 0.95))

        def on_rc(line):
            if NOISE.search(line) or not line.strip():
                return
            for text, frac in stages:
                if text in line:
                    ctx.progress(frac)
            if line.startswith("Encountered runtime error") or "Error" in line or "Warning" in line:
                ctx.log("  ! " + line)
            elif line.startswith("Compression ratio") or line.startswith("Processed"):
                ctx.log("  " + line)

        r = ctx.run(cmd, on_line=on_rc)
        if r.returncode != 0 or not Path(out).exists():
            tail = [l for l in r.tail if not NOISE.search(l)][-8:]
            raise EngineError("recode_pdf gagal (kode %s).\n%s" % (r.returncode, "\n".join(tail)))
        if page_count(out) != n_pages:
            raise EngineError("Jumlah halaman hasil (%d) berbeda dari sumber (%d)." % (page_count(out), n_pages))
        ctx.progress(1.0)
        return res
