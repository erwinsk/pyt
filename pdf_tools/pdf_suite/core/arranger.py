# -*- coding: utf-8 -*-
"""Logika inti 'Atur Halaman' (tanpa GUI, sehingga bisa dites): gabung, pisah, putar, ubah ukuran
halaman, dan impor gambar menjadi halaman PDF. Semua memakai PyMuPDF.

Model: daftar `PageRef` berurutan. Tiap PageRef menunjuk satu halaman sumber (PDF atau gambar) beserta
perubahan yang diminta (putar tambahan, ukuran halaman baru). `build_pdf` mengubah daftar itu menjadi file.

Catatan perilaku:
  * Putar tanpa ubah ukuran bersifat lossless (hanya mengubah /Rotate; tautan & anotasi tetap).
  * Ubah ukuran menempelkan halaman sumber ke halaman baru sebagai objek Form XObject: teks/vektor tetap
    tajam, tetapi tautan dan anotasi halaman itu tidak ikut terbawa.
  * Gambar JPEG/PNG disisipkan apa adanya (tanpa kompresi ulang) kecuali perlu diputar sesuai EXIF.
"""
import dataclasses
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from core.pdfcompat import fitz

MM = 72.0 / 25.4
DEFAULT_IMAGE_DPI = 150.0           # bila gambar tidak membawa metadata DPI

# ukuran potret (lebar, tinggi) dalam poin
PAGE_PRESETS: Dict[str, Tuple[float, float]] = {
    "A3": (841.89, 1190.55),
    "A4": (595.28, 841.89),
    "A5": (419.53, 595.28),
    "A6": (297.64, 419.53),
    "Letter": (612.0, 792.0),
    "Legal": (612.0, 1008.0),
}
A4 = PAGE_PRESETS["A4"]

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
FIT_MODES = ("fit", "stretch")      # fit = proporsi tetap & di tengah; stretch = diregangkan memenuhi halaman


class ArrangerError(Exception):
    pass


class PasswordRequired(ArrangerError):
    """PDF terenkripsi dan sandi belum diberikan / salah."""


class Cancelled(Exception):
    pass


# ----------------------------------------------------------------------------------------------- model
@dataclass
class Source:
    id: int
    path: str
    kind: str                       # 'pdf' | 'image'
    password: str = ""
    pages: int = 1

    @property
    def name(self) -> str:
        return os.path.basename(self.path)


@dataclass
class PageRef:
    src: Optional[int]              # id Source; None = halaman kosong
    index: int = 0                  # nomor halaman di sumber (0-based)
    nat: Tuple[float, float] = A4   # ukuran tampil asli (lebar, tinggi) dalam poin, sudah memperhitungkan /Rotate sumber
    rotation: int = 0               # putar tambahan searah jarum jam: 0/90/180/270
    size: Optional[Tuple[float, float]] = None   # ukuran halaman hasil (poin); None = pertahankan
    fit: str = "fit"
    margin: float = 0.0             # margin (poin) di dalam halaman hasil, hanya bila size diisi
    scale: float = 0.0              # >0 bila ukuran diatur RELATIF (0.5 = 50% dari ukuran asli); hanya untuk tampilan

    def copy(self) -> "PageRef":
        return dataclasses.replace(self)

    def natural_display(self) -> Tuple[float, float]:
        """Ukuran tampil setelah putar tambahan, tanpa ukuran baru."""
        w, h = self.nat
        return (h, w) if self.rotation % 180 else (w, h)

    def display_size(self) -> Tuple[float, float]:
        return self.size if self.size else self.natural_display()

    def rotate(self, delta: int):
        """Putar searah jarum jam sebesar delta (kelipatan 90). Ukuran baru ikut tertukar agar isi tidak miring."""
        delta = int(delta) % 360
        if delta % 90:
            raise ValueError("rotasi harus kelipatan 90")
        if delta % 180 and self.size:
            self.size = (self.size[1], self.size[0])
        self.rotation = (self.rotation + delta) % 360

    def set_page_size(self, size: Optional[Tuple[float, float]], orientation: str = "auto",
                      fit: str = "fit", margin: float = 0.0):
        """Atur ukuran halaman hasil. size = (lebar, tinggi) potret; None = kembali ke ukuran asli.
        orientation: 'auto' (ikuti bentuk halaman saat ini) | 'portrait' | 'landscape'."""
        self.scale = 0.0
        if size is None:
            self.size, self.margin = None, 0.0
            return
        w, h = sorted((float(size[0]), float(size[1])))
        if orientation == "auto":
            nw, nh = self.natural_display()
            landscape = nw > nh
        else:
            landscape = orientation == "landscape"
        self.size = (h, w) if landscape else (w, h)
        self.fit = fit if fit in FIT_MODES else "fit"
        self.margin = max(0.0, float(margin))

    def set_scale(self, factor: float) -> float:
        """Atur ukuran halaman RELATIF terhadap ukuran asli halaman (setelah putar tambahan): 0.5 = 50%.
        Dihitung dari ukuran asli, bukan ukuran saat ini, sehingga menerapkan 50% dua kali tetap 50%.
        Bentuk halaman tidak berubah. Hasil dibatasi 3–14400 pt per sisi (batas PDF); mengembalikan faktor yang dipakai."""
        factor = float(factor)
        if factor <= 0:
            raise ValueError("skala harus > 0")
        nw, nh = self.natural_display()
        f = min(max(factor, 3.0 / min(nw, nh)), 14400.0 / max(nw, nh))
        self.size = (nw * f, nh * f)
        self.fit, self.margin, self.scale = "fit", 0.0, f
        return f

    def reset_changes(self):
        """Kembalikan putaran dan ukuran ke aslinya."""
        self.rotation, self.size, self.margin, self.scale = 0, None, 0.0, 0.0


def describe_size(size: Tuple[float, float]) -> str:
    """'A4', 'Letter' (bila cocok dengan preset, orientasi apa pun) atau '210 × 297 mm'."""
    w, h = sorted(size)
    for name, (pw, ph) in PAGE_PRESETS.items():
        if abs(w - pw) < 1.5 and abs(h - ph) < 1.5:
            return name
    return "%d × %d mm" % (round(size[0] / MM), round(size[1] / MM))


# ------------------------------------------------------------------------------------------ gambar
def _load_image(path: str) -> Tuple[bytes, Tuple[float, float]]:
    """(byte gambar siap sisip, ukuran halaman alami dalam poin). Menghormati EXIF orientation."""
    from PIL import Image, ImageOps
    import io
    try:
        im = Image.open(path)
        im.load()
    except Exception as e:
        raise ArrangerError("Gambar tidak bisa dibaca: %s (%s)" % (os.path.basename(path), e))
    fmt = (im.format or "").upper()
    orient = 1
    try:
        orient = int(im.getexif().get(0x0112, 1))
    except Exception:
        pass
    dpi = im.info.get("dpi")
    transposed = orient in (2, 3, 4, 5, 6, 7, 8)
    if transposed:
        im = ImageOps.exif_transpose(im)
    wpx, hpx = im.size
    try:
        dx, dy = float(dpi[0]), float(dpi[1])
        if not (36 <= dx <= 1200 and 36 <= dy <= 1200):
            raise ValueError
    except Exception:
        dx = dy = DEFAULT_IMAGE_DPI
    if transposed and orient in (5, 6, 7, 8):
        dx, dy = dy, dx
    size_pt = (wpx * 72.0 / dx, hpx * 72.0 / dy)

    if fmt in ("JPEG", "PNG") and not transposed:
        with open(path, "rb") as f:                       # sisip apa adanya: tanpa kompresi ulang
            return f.read(), size_pt
    buf = io.BytesIO()
    has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
    if fmt == "JPEG" and not has_alpha:
        if im.mode not in ("RGB", "L", "CMYK"):
            im = im.convert("RGB")
        im.save(buf, "JPEG", quality=95)
    else:
        if im.mode not in ("RGB", "RGBA", "L", "LA", "P"):
            im = im.convert("RGBA" if has_alpha else "RGB")
        im.save(buf, "PNG")
    return buf.getvalue(), size_pt


def image_to_doc(path: str) -> "fitz.Document":
    data, (w, h) = _load_image(path)
    doc = fitz.open()
    page = doc.new_page(width=w, height=h)
    page.insert_image(page.rect, stream=data)
    return doc


# ---------------------------------------------------------------------------------------- sumber
def kind_of(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in IMAGE_EXTS:
        return "image"
    raise ArrangerError("Format tidak didukung: %s" % os.path.basename(path))


def open_source(src: Source) -> "fitz.Document":
    if src.kind == "image":
        return image_to_doc(src.path)
    try:
        doc = fitz.open(src.path)
    except Exception as e:
        raise ArrangerError("Tidak bisa membuka %s: %s" % (src.name, e))
    if doc.needs_pass and not doc.authenticate(src.password or ""):
        doc.close()
        raise PasswordRequired(src.name)
    return doc


def inspect_file(path: str, password: str = "") -> Tuple[str, List[Tuple[float, float]]]:
    """(jenis, ukuran tiap halaman). Melempar PasswordRequired / ArrangerError."""
    kind = kind_of(path)
    if kind == "image":
        _data, size = _load_image(path)
        return kind, [size]
    src = Source(0, path, "pdf", password)
    doc = open_source(src)
    try:
        if doc.page_count == 0:
            raise ArrangerError("PDF tanpa halaman: %s" % src.name)
        return kind, [(p.rect.width, p.rect.height) for p in doc]
    finally:
        doc.close()


def refs_for_source(src: Source, sizes: Sequence[Tuple[float, float]]) -> List[PageRef]:
    return [PageRef(src.id, i, (float(w), float(h))) for i, (w, h) in enumerate(sizes)]


# ------------------------------------------------------------------------------------- membangun
def _emit_page(out: "fitz.Document", ref: PageRef, sources: Dict[int, Source], cache: Dict[int, "fitz.Document"]):
    if ref.src is None:                                   # halaman kosong
        w, h = ref.size or ref.natural_display()
        out.new_page(-1, width=w, height=h)
        return
    sdoc = cache.get(ref.src)
    if sdoc is None:
        if ref.src not in sources:
            raise ArrangerError("Sumber halaman tidak ditemukan.")
        sdoc = cache[ref.src] = open_source(sources[ref.src])
    if not (0 <= ref.index < sdoc.page_count):
        raise ArrangerError("Halaman %d tidak ada di %s." % (ref.index + 1, sources[ref.src].name))
    if ref.size is None:
        out.insert_pdf(sdoc, from_page=ref.index, to_page=ref.index)
        if ref.rotation:
            pg = out[-1]
            pg.set_rotation((pg.rotation + ref.rotation) % 360)
        return
    w, h = ref.size
    m = min(ref.margin, min(w, h) / 2.0 - 1.0)
    newp = out.new_page(-1, width=w, height=h)
    # show_pdf_page tidak memperhitungkan /Rotate halaman sumber dengan benar (isi miring/terdistorsi), padahal
    # PDF hasil scan sering ber-/Rotate. Maka tempelkan SALINAN sementara yang rotasinya sudah dinormalkan ke 0
    # (tampilan visual sama; sumber asli tidak disentuh).
    tmp = fitz.open()
    try:
        tmp.insert_pdf(sdoc, from_page=ref.index, to_page=ref.index)
        if tmp[0].rotation:
            tmp[0].remove_rotation()
        newp.show_pdf_page(fitz.Rect(m, m, w - m, h - m), tmp, 0,
                           keep_proportion=(ref.fit != "stretch"),
                           rotate=(-ref.rotation) % 360)    # show_pdf_page memutar BERLAWANAN jarum jam; PageRef searah
    finally:
        tmp.close()


def build_pdf(pages: Sequence[PageRef], sources: Dict[int, Source], out_path: str, *, optimize: bool = True,
              progress: Optional[Callable[[int, int], None]] = None,
              is_cancelled: Optional[Callable[[], bool]] = None, _offset: int = 0, _total: Optional[int] = None):
    """Tulis `pages` menjadi satu PDF di out_path. Penulisan atomik (file sementara lalu ganti)."""
    if not pages:
        raise ArrangerError("Tidak ada halaman untuk disimpan.")
    total = _total if _total is not None else len(pages)
    out = fitz.open()
    cache: Dict[int, "fitz.Document"] = {}
    tmp_name = None
    try:
        for n, ref in enumerate(pages):
            if is_cancelled and is_cancelled():
                raise Cancelled()
            _emit_page(out, ref, sources, cache)
            if progress:
                progress(_offset + n + 1, total)
        d = os.path.dirname(os.path.abspath(out_path))
        os.makedirs(d, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".arr_", suffix=".pdf", dir=d)
        os.close(fd)
        out.save(tmp_name, garbage=3 if optimize else 0, deflate=True)
        out.close()
        for doc in cache.values():
            doc.close()
        cache.clear()
        os.replace(tmp_name, out_path)
        tmp_name = None
    finally:
        try:
            out.close()
        except Exception:
            pass
        for doc in cache.values():
            try:
                doc.close()
            except Exception:
                pass
        if tmp_name and os.path.exists(tmp_name):
            os.remove(tmp_name)


def render_page(ref: PageRef, sources: Dict[int, Source], height_px: int = 800) -> Tuple[int, int, bytes]:
    """Render satu halaman sebagaimana akan tersimpan (putar + ukuran) -> (lebar, tinggi, byte RGB)."""
    out = fitz.open()
    cache: Dict[int, "fitz.Document"] = {}
    try:
        _emit_page(out, ref, sources, cache)
        pg = out[0]
        zoom = max(0.05, height_px / max(1.0, pg.rect.height))
        pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pix.width, pix.height, bytes(pix.samples)
    finally:
        out.close()
        for d in cache.values():
            d.close()


def render_thumb(doc: "fitz.Document", index: int, long_px: int) -> Tuple[int, int, bytes]:
    """Render halaman sumber apa adanya (dengan /Rotate aslinya) sehingga SISI TERPANJANG = long_px piksel.
    (Berdasarkan sisi terpanjang, bukan tinggi, agar halaman lanskap pun tajam pada zoom besar.)"""
    pg = doc[index]
    zoom = max(0.02, long_px / max(1.0, pg.rect.width, pg.rect.height))
    pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return pix.width, pix.height, bytes(pix.samples)


# -------------------------------------------------------------------------------------- memisah
def parse_ranges(text: str, total: int) -> List[Tuple[int, int]]:
    """'1-3, 5, 7-' -> [(0,2), (4,4), (6,total-1)] (indeks 0-based, inklusif). Urutan sesuai ketikan."""
    parts = [p.strip() for p in re.split(r"[,;]", text or "") if p.strip()]
    if not parts:
        raise ArrangerError("Isi rentang halaman, mis. 1-3, 4, 5-8.")
    out = []
    for p in parts:
        m = re.fullmatch(r"(\d+)\s*(?:-\s*(\d*))?", p)
        if not m:
            raise ArrangerError("Rentang tidak valid: '%s'." % p)
        a = int(m.group(1))
        if m.group(2) is None:
            b = a                                   # satu halaman
        elif m.group(2) == "":
            b = total                               # '7-' = sampai akhir
        else:
            b = int(m.group(2))
        if a < 1 or b < a or b > total:
            raise ArrangerError("Rentang '%s' di luar 1–%d atau terbalik." % (p, total))
        out.append((a - 1, b - 1))
    return out


def plan_split(pages: Sequence[PageRef], mode: str, *, n: int = 1, ranges: str = "") -> List[List[PageRef]]:
    """Kelompokkan `pages` menjadi beberapa file.
    mode: 'each' (1 halaman/file) | 'every' (tiap n halaman) | 'ranges' (rentang kustom) | 'source' (per file sumber)."""
    pages = list(pages)
    if not pages:
        raise ArrangerError("Tidak ada halaman untuk dipisah.")
    if mode == "each":
        return [[p] for p in pages]
    if mode == "every":
        n = int(n)
        if n < 1:
            raise ArrangerError("Jumlah halaman per file minimal 1.")
        return [pages[i:i + n] for i in range(0, len(pages), n)]
    if mode == "ranges":
        return [pages[a:b + 1] for a, b in parse_ranges(ranges, len(pages))]
    if mode == "source":
        groups: List[List[PageRef]] = []
        last = object()
        for p in pages:
            if p.src is None and groups:                # halaman kosong ikut kelompok sebelumnya
                groups[-1].append(p)
                continue
            if not groups or p.src != last:
                groups.append([])
                last = p.src
            groups[-1].append(p)
        return groups
    raise ArrangerError("Mode pisah tidak dikenal: %s" % mode)


_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(s: str) -> str:
    s = _ILLEGAL.sub("_", s).strip(" .")
    return s or "hasil"


def unique_path(path: str, taken: Optional[set] = None) -> str:
    """Tambahkan _2, _3 … bila nama sudah ada (di disk atau sudah dipakai dalam rencana ini)."""
    taken = taken if taken is not None else set()
    p = Path(path)
    cand, i = p, 2
    while cand.exists() or str(cand) in taken:
        cand = p.with_name("%s_%d%s" % (p.stem, i, p.suffix))
        i += 1
    taken.add(str(cand))
    return str(cand)


def split_output_paths(groups: Sequence[Sequence[PageRef]], out_dir: str, base: str,
                       template: str = "{nama}_{n}", starts: Optional[Sequence[int]] = None) -> List[str]:
    """Nama file untuk tiap kelompok. Placeholder: {nama} {n} (urut, diberi nol di depan) {awal} {akhir}
    (posisi halaman pertama/terakhir kelompok pada daftar). Tidak pernah menimpa file yang sudah ada."""
    width = len(str(len(groups)))
    taken: set = set()
    paths = []
    pos = 1
    for i, g in enumerate(groups):
        awal = (starts[i] if starts else pos)
        akhir = awal + len(g) - 1
        pos = akhir + 1
        try:
            name = (template or "{nama}_{n}").format(nama=base, n=str(i + 1).zfill(width), awal=awal, akhir=akhir)
        except (KeyError, IndexError, ValueError):
            raise ArrangerError("Template nama tidak valid. Gunakan {nama}, {n}, {awal}, {akhir}.")
        name = safe_name(name)
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        paths.append(unique_path(os.path.join(out_dir, name), taken))
    return paths


def run_jobs(jobs: Sequence[Tuple[str, Sequence[PageRef]]], sources: Dict[int, Source], *, optimize: bool = True,
             progress: Optional[Callable[[int, int], None]] = None,
             is_cancelled: Optional[Callable[[], bool]] = None,
             on_file: Optional[Callable[[str], None]] = None) -> List[str]:
    """Bangun beberapa PDF berurutan. Bila dibatalkan atau gagal, semua file yang dibuat run ini dihapus."""
    total = sum(len(p) for _o, p in jobs)
    done, created = 0, []
    try:
        for out_path, pages in jobs:
            build_pdf(pages, sources, out_path, optimize=optimize, progress=progress,
                      is_cancelled=is_cancelled, _offset=done, _total=total)
            created.append(out_path)
            done += len(pages)
            if on_file:
                on_file(out_path)
    except BaseException:
        for p in created:
            try:
                os.remove(p)
            except OSError:
                pass
        raise
    return created
