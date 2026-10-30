# -*- coding: utf-8 -*-
"""Tes logika inti 'Atur Halaman' (core/arranger.py): gabung, pisah, putar, ubah ukuran, impor gambar."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import arranger as A
from core.pdfcompat import fitz


def make_pdf(path, labels, size=(200, 300), rotate=None):
    doc = fitz.open()
    for i, lab in enumerate(labels):
        p = doc.new_page(width=size[0], height=size[1])
        p.insert_text((20, 60), lab, fontsize=24)
        if rotate:
            p.set_rotation(rotate)
    doc.save(str(path))
    doc.close()
    return str(path)


def texts(path):
    with fitz.open(path) as d:
        return [p.get_text().strip() for p in d]


def add(sources, path, password=""):
    kind, sizes = A.inspect_file(path, password)
    s = A.Source(len(sources) + 1, path, kind, password, len(sizes))
    sources[s.id] = s
    return A.refs_for_source(s, sizes)


@pytest.fixture()
def two_pdfs(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", ["A1", "A2", "A3"])
    b = make_pdf(tmp_path / "b.pdf", ["B1", "B2"], size=(300, 200))
    return a, b


# ---------------------------------------------------------------------------------- gabung & urutan
def test_merge_in_custom_order(tmp_path, two_pdfs):
    src = {}
    ra, rb = add(src, two_pdfs[0]), add(src, two_pdfs[1])
    order = [rb[1], ra[0], rb[0], ra[2]]                 # campur & balik urutan; A2 dibuang
    out = str(tmp_path / "gabung.pdf")
    A.build_pdf(order, src, out)
    assert texts(out) == ["B2", "A1", "B1", "A3"]
    assert not [f for f in os.listdir(tmp_path) if f.startswith(".arr_")]      # tidak ada file sementara sisa


def test_duplicate_pages_and_blank_page(tmp_path, two_pdfs):
    src = {}
    ra = add(src, two_pdfs[0])
    blank = A.PageRef(None, 0, (300, 400))
    out = str(tmp_path / "x.pdf")
    A.build_pdf([ra[0], ra[0].copy(), blank], src, out)
    assert texts(out) == ["A1", "A1", ""]
    with fitz.open(out) as d:
        assert (d[2].rect.width, d[2].rect.height) == (300, 400)


# ------------------------------------------------------------------------------------------ putar
def test_rotate_is_lossless_and_stacks_with_source_rotation(tmp_path):
    p = make_pdf(tmp_path / "r.pdf", ["R1", "R2"], rotate=90)
    src = {}
    refs = add(src, p)
    assert refs[0].nat == (300, 200)                      # ukuran tampil sudah memperhitungkan /Rotate sumber
    refs[0].rotate(90)
    refs[1].rotate(-90)
    refs[1].rotate(-90)
    out = str(tmp_path / "o.pdf")
    A.build_pdf(refs, src, out)
    with fitz.open(out) as d:
        assert [pg.rotation for pg in d] == [180, 270]       # /Rotate sumber (90) + putar tambahan (+90 / -180)
        assert texts(out) == ["R1", "R2"]


def test_rotate_rejects_non_multiple_of_90():
    with pytest.raises(ValueError):
        A.PageRef(None).rotate(45)


# --------------------------------------------------------------------------------------- ubah ukuran
def test_resize_to_a4_fit_keeps_text_and_swaps_with_rotation(tmp_path, two_pdfs):
    src = {}
    ra, rb = add(src, two_pdfs[0]), add(src, two_pdfs[1])
    ra[0].set_page_size(A.PAGE_PRESETS["A4"], "auto", "fit", margin=10 * A.MM)
    rb[0].set_page_size(A.PAGE_PRESETS["A4"], "auto")      # sumber lanskap -> A4 lanskap
    assert ra[0].size == A.A4 and rb[0].size == (A.A4[1], A.A4[0])
    ra[1].set_page_size(A.PAGE_PRESETS["Letter"], "auto")
    ra[1].rotate(90)                                       # ukuran ikut tertukar
    assert ra[1].size == (792.0, 612.0)
    out = str(tmp_path / "rs.pdf")
    A.build_pdf([ra[0], rb[0], ra[1]], src, out)
    with fitz.open(out) as d:
        assert [(round(p.rect.width), round(p.rect.height)) for p in d] == [(595, 842), (842, 595), (792, 612)]
    assert texts(out)[:2] == ["A1", "B1"]


def test_resize_fit_vs_stretch_geometry(tmp_path):
    """Halaman lanskap 200x100 berisi blok merah penuh -> halaman persegi 300x300.
    'fit': ada pita putih di atas/bawah (proporsi tetap). 'stretch': merah memenuhi seluruh halaman."""
    doc = fitz.open()
    pg = doc.new_page(width=200, height=100)
    pg.draw_rect(pg.rect, color=(1, 0, 0), fill=(1, 0, 0))
    p = str(tmp_path / "red.pdf")
    doc.save(p)
    doc.close()
    src = {}
    fit, stretch = add(src, p)[0], add(src, p)[0]
    fit.set_page_size((300, 300), "portrait", "fit")
    stretch.set_page_size((300, 300), "portrait", "stretch")

    def px(ref, fx, fy):
        w, h, rgb = A.render_page(ref, src, 150)
        assert w == h
        i = (int(fy * (h - 1)) * w + int(fx * (w - 1))) * 3
        return tuple(rgb[i:i + 3])
    assert px(fit, 0.5, 0.5) == (255, 0, 0)                          # tengah: merah
    assert px(fit, 0.5, 0.05)[1] > 200 and px(fit, 0.5, 0.95)[1] > 200   # atas & bawah: putih (pita kosong)
    assert px(stretch, 0.5, 0.05) == (255, 0, 0) and px(stretch, 0.5, 0.95) == (255, 0, 0)


def test_margin_leaves_white_border(tmp_path):
    doc = fitz.open()
    pg = doc.new_page(width=100, height=100)
    pg.draw_rect(pg.rect, color=(0, 0, 1), fill=(0, 0, 1))
    p = str(tmp_path / "blue.pdf")
    doc.save(p)
    doc.close()
    src = {}
    ref = add(src, p)[0]
    ref.set_page_size((200, 200), "portrait", "fit", margin=50)
    w, h, rgb = A.render_page(ref, src, 200)

    def px(fx, fy):
        i = (int(fy * (h - 1)) * w + int(fx * (w - 1))) * 3
        return tuple(rgb[i:i + 3])
    assert px(0.5, 0.5) == (0, 0, 255) and px(0.05, 0.5) == (255, 255, 255)


def test_rotate_after_resize_keeps_content_upright(tmp_path):
    """Halaman 200x100 merah di sisi kiri -> setelah putar 90° searah jarum jam, sisi merah ada di ATAS."""
    doc = fitz.open()
    pg = doc.new_page(width=200, height=100)
    pg.draw_rect(fitz.Rect(0, 0, 100, 100), color=(1, 0, 0), fill=(1, 0, 0))
    p = str(tmp_path / "half.pdf")
    doc.save(p)
    doc.close()
    src = {}
    ref = add(src, p)[0]
    ref.set_page_size(A.A4, "landscape", "fit")
    ref.rotate(90)
    assert ref.size == A.A4
    w, h, rgb = A.render_page(ref, src, 300)

    def px(fx, fy):
        i = (int(fy * (h - 1)) * w + int(fx * (w - 1))) * 3
        return tuple(rgb[i:i + 3])
    assert px(0.5, 0.3) == (255, 0, 0) and px(0.5, 0.7)[1] > 200


@pytest.mark.parametrize("src_rot", [0, 90])
@pytest.mark.parametrize("extra", [0, 90, 180, 270])
def test_resize_path_has_same_orientation_as_lossless_path(tmp_path, src_rot, extra):
    """Jalur lossless (set_rotation) dan jalur ubah-ukuran (show_pdf_page) harus menghasilkan orientasi yang SAMA,
    termasuk untuk sumber yang sudah ber-/Rotate. Isi: blok merah hanya di kuadran kiri-atas halaman asli."""
    doc = fitz.open()
    pg = doc.new_page(width=200, height=100)
    pg.draw_rect(fitz.Rect(0, 0, 100, 50), color=(1, 0, 0), fill=(1, 0, 0))
    pg.set_rotation(src_rot)
    p = str(tmp_path / "q.pdf")
    doc.save(p)
    doc.close()
    src = {}
    plain = add(src, p)[0]
    plain.rotate(extra)
    resized = plain.copy()
    resized.size = resized.natural_display()                 # ukuran sama persis -> tanpa letterbox
    resized.fit = "fit"

    def quadrants(ref):
        w, h, rgb = A.render_page(ref, src, 200)
        out = []
        for fx, fy in ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)):
            i = (int(fy * (h - 1)) * w + int(fx * (w - 1))) * 3
            out.append(rgb[i:i + 3][1] < 100)                # True = merah
        return out
    assert quadrants(plain) == quadrants(resized)
    assert sum(quadrants(plain)) == 1                        # sanity: tepat satu kuadran merah


def test_set_page_size_none_restores_original():
    r = A.PageRef(1, 0, (200, 300))
    r.set_page_size(A.PAGE_PRESETS["A4"], "portrait", margin=5)
    r.set_page_size(None)
    assert r.size is None and r.margin == 0 and r.display_size() == (200, 300)


def test_relative_scale_is_from_original_size_and_idempotent(tmp_path, two_pdfs):
    src = {}
    ra, rb = add(src, two_pdfs[0]), add(src, two_pdfs[1])           # A: 200x300 potret; B: 300x200 lanskap
    f = ra[0].set_scale(0.5)
    assert f == 0.5 and ra[0].size == (100.0, 150.0) and ra[0].scale == 0.5
    ra[0].set_scale(0.5)                                              # diulang: tetap 50%, bukan 25%
    assert ra[0].size == (100.0, 150.0)
    rb[0].set_scale(1.5)
    assert rb[0].size == (450.0, 300.0)                               # bentuk lanskap dipertahankan per halaman
    out = str(tmp_path / "sc.pdf")
    A.build_pdf([ra[0], rb[0], ra[1]], src, out)
    with fitz.open(out) as d:
        assert [(round(p.rect.width), round(p.rect.height)) for p in d] == [(100, 150), (450, 300), (200, 300)]
    assert texts(out) == ["A1", "B1", "A2"]


def test_relative_scale_with_rotation_resets_and_limits():
    r = A.PageRef(1, 0, (200, 300))
    r.rotate(90)                                                      # tampil 300x200
    r.set_scale(0.5)
    assert r.size == (150.0, 100.0)
    r.rotate(90)                                                      # ukuran ikut tertukar, skala tetap
    assert r.size == (100.0, 150.0) and r.scale == 0.5
    r.set_scale(0.25)
    assert r.size == (50.0, 75.0)
    r.set_page_size(A.A4, "portrait")                                 # mengatur ukuran absolut menghapus tanda skala
    assert r.scale == 0.0
    r.set_scale(1000)                                                 # dibatasi batas PDF (14400 pt)
    assert max(r.size) <= 14400.0 + 1e-6 and r.scale < 1000
    r.set_scale(0.0001)
    assert min(r.size) >= 3.0 - 1e-6
    with pytest.raises(ValueError):
        r.set_scale(0)
    r.reset_changes()
    assert (r.rotation, r.size, r.margin, r.scale) == (0, None, 0.0, 0.0)


def test_relative_scale_content_scales_with_page(tmp_path):
    """Blok merah menutupi separuh kiri halaman: setelah diskalakan 50% proporsinya di halaman harus tetap sama."""
    doc = fitz.open()
    pg = doc.new_page(width=200, height=100)
    pg.draw_rect(fitz.Rect(0, 0, 100, 100), color=(1, 0, 0), fill=(1, 0, 0))
    p = str(tmp_path / "h.pdf")
    doc.save(p)
    doc.close()
    src = {}
    ref = add(src, p)[0]
    ref.set_scale(0.5)
    w, h, rgb = A.render_page(ref, src, 100)
    assert (w, h) == (200, 100)
    px = lambda fx, fy: tuple(rgb[(int(fy * (h - 1)) * w + int(fx * (w - 1))) * 3:][:3])
    assert px(0.25, 0.5) == (255, 0, 0) and px(0.75, 0.5)[1] > 200


def test_describe_size():
    assert A.describe_size(A.PAGE_PRESETS["A4"]) == "A4"
    assert A.describe_size((841.89, 595.28)) == "A4"
    assert A.describe_size((612, 792)) == "Letter"
    assert A.describe_size((300, 300)) == "106 × 106 mm"


# ------------------------------------------------------------------------------------- impor gambar
def make_image(path, size=(800, 400), color=(200, 30, 30), fmt="PNG", exif_orientation=None, dpi=None):
    from PIL import Image
    im = Image.new("RGB", size, color)
    kw = {}
    if dpi:
        kw["dpi"] = (dpi, dpi)
    if exif_orientation:
        ex = Image.Exif()
        ex[0x0112] = exif_orientation
        kw["exif"] = ex
    im.save(str(path), fmt, **kw)
    return str(path)


@pytest.mark.parametrize("fmt,ext", [("PNG", ".png"), ("JPEG", ".jpg"), ("BMP", ".bmp"), ("GIF", ".gif"), ("TIFF", ".tif")])
def test_import_images_become_pages(tmp_path, fmt, ext):
    img = make_image(tmp_path / ("im" + ext), fmt=fmt)
    src = {}
    refs = add(src, img)
    assert src[1].kind == "image" and len(refs) == 1
    refs[0].set_page_size(A.A4, "auto", "fit")
    out = str(tmp_path / "img.pdf")
    A.build_pdf(refs, src, out)
    with fitz.open(out) as d:
        assert d.page_count == 1 and len(d[0].get_images()) == 1
        assert (round(d[0].rect.width), round(d[0].rect.height)) == (842, 595)     # gambar lanskap -> A4 lanskap


def test_image_default_size_uses_dpi_metadata(tmp_path):
    img = make_image(tmp_path / "d.png", size=(720, 360), dpi=72)
    _kind, sizes = A.inspect_file(img)
    assert [round(x) for x in sizes[0]] == [720, 360]
    img2 = make_image(tmp_path / "e.png", size=(1500, 750))                      # tanpa DPI -> 150
    assert [round(x) for x in A.inspect_file(img2)[1][0]] == [720, 360]


def test_jpeg_is_embedded_without_recompression(tmp_path):
    img = make_image(tmp_path / "p.jpg", fmt="JPEG")
    raw = Path(img).read_bytes()
    src = {}
    out = str(tmp_path / "j.pdf")
    A.build_pdf(add(src, img), src, out)
    with fitz.open(out) as d:
        xref = d[0].get_images()[0][0]
        assert d.extract_image(xref)["image"] == raw


def test_exif_orientation_is_applied(tmp_path):
    img = make_image(tmp_path / "ex.jpg", size=(800, 400), fmt="JPEG", exif_orientation=6, dpi=72)
    _k, sizes = A.inspect_file(img)
    assert [round(x) for x in sizes[0]] == [400, 800]                             # foto diputar -> potret


def test_unsupported_and_corrupt_inputs(tmp_path):
    t = tmp_path / "x.txt"
    t.write_text("hi")
    with pytest.raises(A.ArrangerError):
        A.inspect_file(str(t))
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    with pytest.raises(A.ArrangerError):
        A.inspect_file(str(bad))
    badimg = tmp_path / "bad.png"
    badimg.write_bytes(b"nope")
    with pytest.raises(A.ArrangerError):
        A.inspect_file(str(badimg))


# ------------------------------------------------------------------------------------------ sandi
def test_encrypted_pdf_needs_password(tmp_path):
    plain = make_pdf(tmp_path / "p.pdf", ["SECRET"])
    enc = str(tmp_path / "enc.pdf")
    with fitz.open(plain) as d:
        d.save(enc, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with pytest.raises(A.PasswordRequired):
        A.inspect_file(enc)
    with pytest.raises(A.PasswordRequired):
        A.inspect_file(enc, "salah")
    src = {}
    refs = add(src, enc, "pw")
    out = str(tmp_path / "dec.pdf")
    A.build_pdf(refs, src, out)
    assert texts(out) == ["SECRET"]
    with fitz.open(out) as d:
        assert not d.is_encrypted


# ------------------------------------------------------------------------------------------ pisah
def refs_n(n):
    return [A.PageRef(1, i) for i in range(n)]


def test_plan_split_modes():
    p = refs_n(7)
    assert [len(g) for g in A.plan_split(p, "each")] == [1] * 7
    assert [len(g) for g in A.plan_split(p, "every", n=3)] == [3, 3, 1]
    assert [[r.index for r in g] for g in A.plan_split(p, "ranges", ranges="1-3, 5, 6-")] == [[0, 1, 2], [4], [5, 6]]
    mixed = [A.PageRef(1, 0), A.PageRef(1, 1), A.PageRef(2, 0), A.PageRef(None), A.PageRef(1, 2)]
    assert [len(g) for g in A.plan_split(mixed, "source")] == [2, 2, 1]            # halaman kosong ikut kelompok sebelumnya


@pytest.mark.parametrize("text", ["", "abc", "0-2", "3-1", "1-99", "1,,x"])
def test_parse_ranges_rejects_invalid(text):
    with pytest.raises(A.ArrangerError):
        A.parse_ranges(text, 5)


def test_plan_split_rejects_bad_input():
    with pytest.raises(A.ArrangerError):
        A.plan_split([], "each")
    with pytest.raises(A.ArrangerError):
        A.plan_split(refs_n(3), "every", n=0)
    with pytest.raises(A.ArrangerError):
        A.plan_split(refs_n(3), "bogus")


def test_split_output_paths_unique_and_safe(tmp_path):
    (tmp_path / "doc_1.pdf").write_bytes(b"x")                                      # sudah ada -> jangan ditimpa
    groups = A.plan_split(refs_n(12), "every", n=5)
    paths = A.split_output_paths(groups, str(tmp_path), "doc")
    names = [os.path.basename(p) for p in paths]
    assert names == ["doc_2.pdf", "doc_2_2.pdf", "doc_3.pdf"] or len(set(names)) == 3
    assert len(set(paths)) == 3 and all(not os.path.exists(p) for p in paths)
    p2 = A.split_output_paths(groups, str(tmp_path), "x", "{nama}_hal{awal}-{akhir}")
    assert [os.path.basename(p) for p in p2] == ["x_hal1-5.pdf", "x_hal6-10.pdf", "x_hal11-12.pdf"]
    p3 = A.split_output_paths(groups[:1], str(tmp_path), "a/b:c")
    assert os.path.dirname(p3[0]) == str(tmp_path)                                  # tidak bisa keluar dari folder
    with pytest.raises(A.ArrangerError):
        A.split_output_paths(groups, str(tmp_path), "x", "{salah}")


def test_run_jobs_split_end_to_end(tmp_path, two_pdfs):
    src = {}
    ra, rb = add(src, two_pdfs[0]), add(src, two_pdfs[1])
    pages = ra + rb
    groups = A.plan_split(pages, "source")
    outs = A.split_output_paths(groups, str(tmp_path / "out"), "hasil")
    seen = []
    done = A.run_jobs(list(zip(outs, groups)), src, progress=lambda d, t: seen.append((d, t)))
    assert [texts(p) for p in done] == [["A1", "A2", "A3"], ["B1", "B2"]]
    assert seen[-1] == (5, 5) and [d for d, _ in seen] == [1, 2, 3, 4, 5]


def test_cancel_and_failure_leave_nothing(tmp_path, two_pdfs):
    src = {}
    pages = add(src, two_pdfs[0]) + add(src, two_pdfs[1])
    out_dir = tmp_path / "o"
    jobs = [(str(out_dir / "1.pdf"), pages[:3]), (str(out_dir / "2.pdf"), pages[3:])]
    count = {"n": 0}

    def cancel():
        count["n"] += 1
        return count["n"] > 4                               # batal di tengah pekerjaan kedua
    with pytest.raises(A.Cancelled):
        A.run_jobs(jobs, src, is_cancelled=cancel)
    assert not list(out_dir.glob("*"))
    # sumber hilang di tengah jalan -> galat bersih, file yang sudah jadi dihapus
    bad = [A.PageRef(99, 0)]
    with pytest.raises(A.ArrangerError):
        A.run_jobs([(str(out_dir / "1.pdf"), pages[:3]), (str(out_dir / "2.pdf"), bad)], src)
    assert not list(out_dir.glob("*"))


def test_build_rejects_empty_and_bad_index(tmp_path, two_pdfs):
    src = {}
    refs = add(src, two_pdfs[0])
    with pytest.raises(A.ArrangerError):
        A.build_pdf([], src, str(tmp_path / "e.pdf"))
    with pytest.raises(A.ArrangerError):
        A.build_pdf([A.PageRef(1, 50)], src, str(tmp_path / "e.pdf"))
    assert not (tmp_path / "e.pdf").exists()


def test_overwriting_existing_output_is_atomic(tmp_path, two_pdfs):
    src = {}
    refs = add(src, two_pdfs[0])
    out = tmp_path / "t.pdf"
    out.write_bytes(b"OLD")
    A.build_pdf(refs[:1], src, str(out))
    assert texts(str(out)) == ["A1"]
