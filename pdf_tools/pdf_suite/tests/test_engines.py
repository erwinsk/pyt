# -*- coding: utf-8 -*-
"""Uji engine dengan alat NYATA (gs, tesseract, ocrmypdf, recode_pdf)."""
import pytest

from conftest import run_engine
from core.engines import get_engine
from core.pdfcompat import fitz
from core.procutil import Cancelled


def need(tools, *ids):
    miss = [i for i in ids if not tools[i].found]
    if miss:
        pytest.skip("alat belum terpasang: " + ", ".join(miss))


def assert_clean(workspace):
    """Tidak ada sisa scratch maupun file di temp sistem; hanya hasil akhir."""
    from core.paths import scratch_root
    sr = scratch_root()
    assert (not sr.exists()) or list(sr.iterdir()) == [], "scratch tersisa: %s" % list(sr.iterdir())
    assert list(workspace["systmp"].iterdir()) == [], "sisa di temp sistem: %s" % list(workspace["systmp"].iterdir())


def text_of(pdf):
    with fitz.open(str(pdf)) as d:
        return " ".join(p.get_text() for p in d)


def n_pages(pdf):
    with fitz.open(str(pdf)) as d:
        return len(d)


def test_ghostscript(sample_scan, workspace, tools):
    need(tools, "gs")
    out = workspace["tmp"] / "out"; out.mkdir()
    dest, er, logs = run_engine(get_engine("ghostscript"), sample_scan, out, {"dpi": 100}, tools)
    assert dest.exists() and n_pages(dest) == 3
    # Bawaan = JPEG q70 (aman untuk scan fotografis, lihat ghostscript.py). Pada sampel sintetis berwarna
    # sedikit ini hasilnya 72% dari sumber (otomatis Ghostscript 61%, tetapi +74% pada scan fotografis).
    assert dest.stat().st_size < sample_scan.stat().st_size * 0.8
    assert sorted(p.name for p in out.iterdir()) == [dest.name]
    assert_clean(workspace)


def test_ghostscript_jpeg_quality_and_gray(sample_scan, workspace, tools):
    need(tools, "gs")
    out = workspace["tmp"] / "out"; out.mkdir()
    eng = get_engine("ghostscript")
    d1, _, _ = run_engine(eng, sample_scan, out, {"dpi": 120, "jpeg_quality": 30}, tools)
    out2 = workspace["tmp"] / "out2"; out2.mkdir()
    d2, _, _ = run_engine(eng, sample_scan, out2, {"dpi": 120, "jpeg_quality": 90, "grayscale": True}, tools)
    assert d1.stat().st_size < d2.stat().st_size or d2.stat().st_size < sample_scan.stat().st_size
    assert_clean(workspace)


def test_full_image_native_cap_and_size(sample_scan, workspace, tools):
    out = workspace["tmp"] / "out"; out.mkdir()
    eng = get_engine("full_image")
    dest, _, _ = run_engine(eng, sample_scan, out, {"dpi": 300, "quality": 50, "cap_native": True}, tools)
    with fitz.open(str(dest)) as d:
        info = d[0].get_image_info()[0]
        assert (info["width"], info["height"]) == (1700, 2200), "DPI harus dibatasi ke resolusi asli (96 ppi)"
        assert len(d) == 3
    out2 = workspace["tmp"] / "out2"; out2.mkdir()
    dest2, _, _ = run_engine(eng, sample_scan, out2, {"dpi": 300, "quality": 50, "cap_native": False}, tools)
    with fitz.open(str(dest2)) as d:
        assert d[0].get_image_info()[0]["width"] > 1700
    assert dest.stat().st_size < sample_scan.stat().st_size
    assert_clean(workspace)


def test_full_image_sharpen_modes(sample_scan, workspace, tools):
    for i, mode in enumerate(("off", "light", "unsharp")):
        out = workspace["tmp"] / f"o{i}"; out.mkdir()
        dest, _, _ = run_engine(get_engine("full_image"), sample_scan, out, {"sharpen": mode, "dpi": 72}, tools)
        assert dest.exists()
    assert_clean(workspace)


def test_ocrmypdf_two_pass_reuses_cache(sample_scan, workspace, tools):
    need(tools, "ocrmypdf", "tesseract")
    eng = get_engine("ocrmypdf")
    o1 = workspace["tmp"] / "o1"; o1.mkdir()
    d1, er1, logs1 = run_engine(eng, sample_scan, o1, {"optimize": "1", "deskew": False}, tools)
    assert er1.cache_used is False and "certificate" in text_of(d1).lower()
    # ganti parameter KOMPRESI -> OCR tidak diulang
    o2 = workspace["tmp"] / "o2"; o2.mkdir()
    d2, er2, logs2 = run_engine(eng, sample_scan, o2, {"optimize": "3", "jpeg_quality": 40, "deskew": False}, tools)
    assert er2.cache_used is True
    assert not any("Tahap 1/2" in l for l in logs2)
    assert "certificate" in text_of(d2).lower()
    assert n_pages(d2) == 3
    # ganti parameter OCR -> cache tidak berlaku
    o3 = workspace["tmp"] / "o3"; o3.mkdir()
    d3, er3, _ = run_engine(eng, sample_scan, o3, {"optimize": "1", "deskew": True}, tools)
    assert er3.cache_used is False
    from core.cache import OcrCache
    assert len(OcrCache().list()) == 2
    assert_clean(workspace)


def test_ocrmypdf_single_pass_when_cache_disabled(sample_scan, workspace, tools):
    need(tools, "ocrmypdf", "tesseract")
    from core.cache import OcrCache
    o = workspace["tmp"] / "o"; o.mkdir()
    d, er, _ = run_engine(get_engine("ocrmypdf"), sample_scan, o, {"optimize": "1", "deskew": False}, tools, use_cache=False)
    assert er.cache_used is None and d.exists()
    assert OcrCache().list() == []
    assert_clean(workspace)


def test_ocrmypdf_text_pdf_gives_clear_hint(sample_text, workspace, tools):
    need(tools, "ocrmypdf", "tesseract")
    from core.engines import EngineError
    o = workspace["tmp"] / "o"; o.mkdir()
    with pytest.raises(EngineError) as ei:
        run_engine(get_engine("ocrmypdf"), sample_text, o, {}, tools)
    assert "sudah berisi teks" in str(ei.value)
    assert list(o.iterdir()) == []
    assert_clean(workspace)


def test_ocrmypdf_unknown_language_message(sample_scan, workspace, tools):
    need(tools, "ocrmypdf", "tesseract")
    from core.engines import EngineError
    o = workspace["tmp"] / "o"; o.mkdir()
    with pytest.raises(EngineError) as ei:
        run_engine(get_engine("ocrmypdf"), sample_scan, o, {"languages": "xyz"}, tools)
    assert "xyz" in str(ei.value)
    assert_clean(workspace)


def test_mrc_end_to_end_and_cache(sample_scan, workspace, tools):
    need(tools, "recode_pdf", "tesseract")
    eng = get_engine("mrc")
    o1 = workspace["tmp"] / "o1"; o1.mkdir()
    d1, er1, logs1 = run_engine(eng, sample_scan, o1, {"bg_downsample": 2}, tools)
    joined = "\n".join(logs1)
    assert "Invalid bounding box" not in joined
    assert er1.cache_used is False
    assert n_pages(d1) == 3 and "certificate" in text_of(d1).lower()
    assert d1.stat().st_size < sample_scan.stat().st_size * 0.2
    # halaman asli tetap proporsional (halaman 3 lebih besar, seperti sumber)
    with fitz.open(str(d1)) as a, fitz.open(str(sample_scan)) as b:
        for i in range(3):
            assert a[i].rect.width == pytest.approx(b[i].rect.width, rel=0.01)
            assert a[i].rect.height == pytest.approx(b[i].rect.height, rel=0.01)
    # ganti parameter kompresi -> OCR dipakai ulang
    o2 = workspace["tmp"] / "o2"; o2.mkdir()
    d2, er2, logs2 = run_engine(eng, sample_scan, o2, {"bg_downsample": 4, "denoise": "none", "bg_rate": 800}, tools)
    assert er2.cache_used is True and not any("Menjalankan OCR" in l for l in logs2)
    assert n_pages(d2) == 3 and "certificate" in text_of(d2).lower()
    assert d2.stat().st_size != d1.stat().st_size
    assert_clean(workspace)


def test_mrc_gray_ccitt_and_no_jbig2_fallback(sample_scan, workspace, tools, monkeypatch):
    need(tools, "recode_pdf", "tesseract")
    t2 = dict(tools)
    from core.deps import ToolStatus
    t2["jbig2"] = ToolStatus("jbig2", "jbig2")           # seolah tidak terpasang
    o = workspace["tmp"] / "o"; o.mkdir()
    d, er, logs = run_engine(get_engine("mrc"), sample_scan, o, {"color_mode": "gray", "bg_downsample": 3}, t2)
    assert any("CCITT" in l for l in logs)
    assert d.exists() and n_pages(d) == 3
    assert_clean(workspace)


def test_mrc_text_pdf_renders_pages(sample_text, workspace, tools):
    need(tools, "recode_pdf", "tesseract")
    o = workspace["tmp"] / "o"; o.mkdir()
    d, er, logs = run_engine(get_engine("mrc"), sample_text, o, {"render_dpi": 100}, tools)
    assert any("bukan scan murni" in l for l in logs)
    assert n_pages(d) == 2
    assert_clean(workspace)


def test_cancel_leaves_no_leftovers(sample_scan, workspace, tools):
    need(tools, "recode_pdf", "tesseract")
    o = workspace["tmp"] / "o"; o.mkdir()
    raised = 0
    for after in (3, 40, 120):
        try:
            run_engine(get_engine("mrc"), sample_scan, o, {}, tools, cancel_after=after)
        except Cancelled:
            raised += 1
    assert raised >= 2, "uji pembatalan harus benar-benar memicu Cancelled (terpicu %d kali)" % raised
    assert list(o.iterdir()) == [], "tidak boleh ada file hasil/.part setelah dibatalkan"
    from core.cache import OcrCache
    assert not any(p.name.startswith(".tmp-") for p in OcrCache().root.glob("*")) if OcrCache().root.exists() else True
    assert_clean(workspace)
