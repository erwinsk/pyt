# -*- coding: utf-8 -*-
"""Analisis PDF + rencana tumpukan gambar untuk metode MRC.

Prinsip penting (pelajaran dari masalah 'Invalid bounding box'): OCR harus
berjalan pada PIKSEL YANG SAMA dengan yang diproses recode_pdf. Karena itu
gambar halaman diekstrak pada resolusi aslinya (bila halaman scan murni),
bukan dirender ulang pada DPI lain.
"""
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from PIL import Image

from .pdfcompat import fitz


@dataclass
class PageInfo:
    index: int
    width_pt: float
    height_pt: float
    rotation: int = 0
    n_images: int = 0
    has_text: bool = False           # ada teks APA PUN (termasuk lapisan OCR tak terlihat)
    has_visible_text: bool = False   # ada teks yang benar-benar tergambar di halaman
    img_w: int = 0
    img_h: int = 0
    xref: int = 0
    ppi: Optional[float] = None     # resolusi efektif gambar utama (px per inci halaman)
    native_ok: bool = False         # halaman = satu gambar penuh tanpa teks TERLIHAT


@dataclass
class DocInfo:
    path: str
    size_bytes: int
    pages: List[PageInfo] = field(default_factory=list)

    @property
    def n_pages(self) -> int:
        return len(self.pages)

    @property
    def image_only(self) -> bool:
        return bool(self.pages) and all(p.native_ok for p in self.pages)

    @property
    def has_any_text(self) -> bool:
        return any(p.has_text for p in self.pages)


def _has_visible_text(page) -> bool:
    """True bila halaman punya teks yang tergambar. Teks mode render 3 (lapisan OCR tak terlihat
    dari scanner/OCRmyPDF/ABBYY) TIDAK dihitung. Dulu semua teks dihitung, sehingga scan yang sudah
    ber-OCR dianggap 'bukan scan murni' lalu dirender ulang pada 200 dpi (turun dari 300 ppi asli).
    Bila tak bisa dipastikan, anggap terlihat: halaman dirender (aman), bukan diekstrak."""
    try:
        return any(s.get("type") in (0, 1, 2) and s.get("opacity", 1.0) > 0 and s.get("chars")
                   for s in page.get_texttrace())
    except Exception:  # noqa: BLE001
        return True


_ANALYZE_MEMO = {}


def analyze_cached(path) -> "DocInfo":
    """analyze() dengan memo per (path, mtime, ukuran) — untuk pembaruan UI yang sering."""
    p = Path(path)
    st = p.stat()
    key = (str(p.resolve()), st.st_mtime_ns, st.st_size)
    if key not in _ANALYZE_MEMO:
        if len(_ANALYZE_MEMO) > 16:
            _ANALYZE_MEMO.clear()
        _ANALYZE_MEMO[key] = analyze(p)
    return _ANALYZE_MEMO[key]


def analyze(path) -> DocInfo:
    path = str(path)
    info = DocInfo(path=path, size_bytes=os.path.getsize(path))
    with fitz.open(path) as doc:
        for i, page in enumerate(doc):
            rect = page.rect
            pi = PageInfo(index=i, width_pt=rect.width, height_pt=rect.height, rotation=page.rotation)
            pi.has_text = bool(page.get_text("text").strip())
            pi.has_visible_text = _has_visible_text(page) if pi.has_text else False   # jalur cepat bila tanpa teks
            imgs = page.get_image_info(xrefs=True)
            pi.n_images = len(imgs)
            if imgs:
                main = max(imgs, key=lambda d: d["width"] * d["height"])
                bbox = fitz.Rect(main["bbox"])
                pi.img_w, pi.img_h = int(main["width"]), int(main["height"])
                pi.xref = int(main.get("xref", 0) or 0)
                if bbox.width > 0:
                    pi.ppi = pi.img_w / (bbox.width / 72.0)
                inter = bbox & rect
                coverage = (inter.width * inter.height) / (rect.width * rect.height) if rect.width * rect.height else 0
                tr = main.get("transform", (1, 0, 0, 1, 0, 0))
                axis_aligned = abs(tr[1]) < 1e-3 and abs(tr[2]) < 1e-3
                pi.native_ok = (len(imgs) == 1 and coverage >= 0.9 and not pi.has_visible_text
                                and pi.rotation == 0 and axis_aligned and pi.xref > 0)
            info.pages.append(pi)
    return info


# --------------------------------------------------------------------------
@dataclass
class PagePlan:
    index: int
    mode: str                 # 'native' | 'render'
    xref: int
    size: tuple               # (w, h) piksel akhir di tumpukan
    src_size: tuple           # ukuran asli sebelum resample
    resampled: bool = False


@dataclass
class StackPlan:
    doc_dpi: int
    pages: List[PagePlan]
    notes: List[str] = field(default_factory=list)

    def signature(self) -> list:
        """Tanda tangan deterministik untuk kunci cache OCR."""
        return [self.doc_dpi] + [[p.mode, p.size[0], p.size[1]] for p in self.pages]


def plan_stack(info: DocInfo, render_dpi: int = 200, dpi_override: int = 0) -> StackPlan:
    native_ppis = [round(p.ppi) for p in info.pages if p.native_ok and p.ppi]
    notes: List[str] = []
    if dpi_override:
        doc_dpi = int(dpi_override)
        auto_dpi = None
    elif native_ppis:
        auto_dpi = Counter(native_ppis).most_common(1)[0][0]
        doc_dpi = auto_dpi
    else:
        auto_dpi = None
        doc_dpi = int(render_dpi)
        notes.append("Tidak ada halaman scan murni; semua halaman dirender pada %d dpi." % doc_dpi)
    pages: List[PagePlan] = []
    for p in info.pages:
        if p.native_ok:
            size = (p.img_w, p.img_h)
            resampled = False
            if auto_dpi and p.ppi and abs(p.ppi - auto_dpi) / auto_dpi > 0.03:
                f = auto_dpi / p.ppi
                size = (max(1, round(p.img_w * f)), max(1, round(p.img_h * f)))
                resampled = True
                notes.append("Halaman %d: resolusi %.0f ppi disamakan ke %d ppi agar ukuran halaman tetap." %
                             (p.index + 1, p.ppi, auto_dpi))
            pages.append(PagePlan(p.index, "native", p.xref, size, (p.img_w, p.img_h), resampled))
        else:
            size = (max(1, round(p.width_pt * doc_dpi / 72.0)), max(1, round(p.height_pt * doc_dpi / 72.0)))
            notes.append("Halaman %d bukan scan murni (teks/vektor/banyak gambar); dirender pada %d dpi." %
                         (p.index + 1, doc_dpi))
            pages.append(PagePlan(p.index, "render", 0, size, size))
    hidden = [p.index + 1 for p in info.pages if p.native_ok and p.has_text]
    if hidden:
        notes.append("Halaman %s memiliki lapisan OCR lama (tak terlihat): gambar asli dipakai pada resolusi "
                     "aslinya dan lapisan lama diganti hasil OCR baru." % ", ".join(map(str, hidden)))
    return StackPlan(doc_dpi=doc_dpi, pages=pages, notes=notes)


def build_stack(src, plan: StackPlan, out_dir: Path, is_cancelled: Optional[Callable[[], bool]] = None,
                on_page: Optional[Callable[[int, int], None]] = None) -> List[Path]:
    """Tulis gambar tiap halaman sebagai PNG (dengan metadata DPI) ke out_dir."""
    from .procutil import Cancelled
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    with fitz.open(str(src)) as doc:
        total = len(plan.pages)
        for pp in plan.pages:
            if is_cancelled and is_cancelled():
                raise Cancelled()
            if pp.mode == "native":
                pix = fitz.Pixmap(doc, pp.xref)
                if pix.colorspace is None or pix.colorspace.n not in (1, 3):
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                if pix.alpha:
                    pix = fitz.Pixmap(pix, 0)
                mode = "L" if pix.n == 1 else "RGB"
                img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
            else:
                pix = doc[pp.index].get_pixmap(dpi=plan.doc_dpi, alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            if img.size != tuple(pp.size):
                img = img.resize(tuple(pp.size), Image.LANCZOS)
            p = out_dir / ("p%04d.png" % (pp.index + 1))
            img.save(p, format="PNG", dpi=(plan.doc_dpi, plan.doc_dpi), compress_level=1)
            paths.append(p)
            if on_page:
                on_page(pp.index + 1, total)
    return paths
