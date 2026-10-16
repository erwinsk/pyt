# -*- coding: utf-8 -*-
import io
from pathlib import Path

from PIL import Image, ImageFilter

from ..pdfcompat import fitz
from ..pdfinfo import analyze
from ..schema import OptionSet, bool_opt, choice_opt, float_opt, int_opt
from .base import Engine, EngineResult, JobContext


class FullImageEngine(Engine):
    id = "full_image"
    name = "Full Image"
    description = "Merender tiap halaman jadi gambar JPEG lalu menyusunnya ulang. Sederhana dan cukup kecil, tetapi teks menjadi gambar."
    required_tools = ()
    options = OptionSet([
        int_opt("quality", "Kualitas JPEG", 60, 1, 100, "Semakin rendah semakin kecil dan semakin kasar."),
        int_opt("dpi", "Resolusi render", 150, 10, 600, "DPI render halaman.", suffix=" dpi"),
        bool_opt("cap_native", "Jangan melebihi resolusi asli gambar", True,
                 "Untuk PDF scan, DPI dibatasi ke resolusi asli agar tidak membesarkan gambar tanpa menambah detail."),
        bool_opt("grayscale", "Ubah ke hitam-putih (grayscale)", False),
        choice_opt("sharpen", "Pertajam", "off",
                   [("off", "Mati"), ("light", "Ringan (filter SHARPEN)"), ("unsharp", "Unsharp mask (atur di Lanjutan)")],
                   "Menajamkan teks setelah penurunan resolusi."),
        float_opt("unsharp_radius", "Unsharp: radius", 2.0, 0.1, 10.0, 0.1, group="advanced"),
        int_opt("unsharp_percent", "Unsharp: persen", 150, 1, 500, group="advanced"),
        int_opt("unsharp_threshold", "Unsharp: ambang", 3, 0, 255, group="advanced"),
        choice_opt("subsampling", "Subsampling chroma JPEG", "default",
                   [("default", "Bawaan Pillow"), ("444", "4:4:4 (tajam)"), ("422", "4:2:2"), ("420", "4:2:0 (terkecil)")],
                   group="advanced"),
        bool_opt("progressive", "JPEG progressive", False, group="advanced"),
        bool_opt("optimize", "Optimasi tabel Huffman", True, group="advanced"),
    ])

    def process(self, src: Path, out: Path, values: dict, ctx: JobContext) -> EngineResult:
        v = self.options.normalize(values)
        info = analyze(src) if v["cap_native"] else None
        sub_map = {"444": 0, "422": 1, "420": 2}
        doc = fitz.open(str(src))
        new_doc = fitz.open()
        total = len(doc)
        try:
            for i, page in enumerate(doc):
                ctx.check_cancel()
                dpi = v["dpi"]
                if info is not None and info.pages[i].ppi:
                    dpi = max(10, min(dpi, int(round(info.pages[i].ppi))))
                z = dpi / 72.0
                pix = page.get_pixmap(matrix=fitz.Matrix(z, z), colorspace=fitz.csRGB, alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                if v["grayscale"]:
                    img = img.convert("L")
                if v["sharpen"] == "light":
                    img = img.filter(ImageFilter.SHARPEN)
                elif v["sharpen"] == "unsharp":
                    img = img.filter(ImageFilter.UnsharpMask(v["unsharp_radius"], v["unsharp_percent"], v["unsharp_threshold"]))
                buf = io.BytesIO()
                kw = {"format": "JPEG", "quality": v["quality"], "optimize": v["optimize"], "progressive": v["progressive"]}
                if v["subsampling"] in sub_map and img.mode == "RGB":
                    kw["subsampling"] = sub_map[v["subsampling"]]
                img.save(buf, **kw)
                new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
                new_page.insert_image(new_page.rect, stream=buf.getvalue())
                ctx.progress((i + 1) / total)
            new_doc.save(str(out), garbage=4, deflate=True)
        finally:
            new_doc.close()
            doc.close()
        return EngineResult()
