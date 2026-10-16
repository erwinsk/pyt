# -*- coding: utf-8 -*-
"""Uji: (1) pengaman 'hasil tidak lebih kecil dari asli -> tidak disimpan',
(2) klasifikasi halaman yang mengabaikan lapisan OCR tak terlihat."""
import io
from pathlib import Path

from core import pdfinfo
from core.cache import OcrCache
from core.engines import get_engine
from core.pdfcompat import fitz
from core.runner import JobRunner, OutputConfig

# Rasterisasi teks vektor kecil pada kualitas/DPI tinggi SELALU lebih besar dari aslinya:
BLOAT = {"quality": 95, "dpi": 300}


def run_jobs(engine_id, values, files, out_dir, tools, size_guard=True):
    """Jalankan JobRunner secara sinkron (tanpa memulai thread) dan kumpulkan hasilnya."""
    r = JobRunner(get_engine(engine_id), values, [str(f) for f in files], OutputConfig(str(out_dir)),
                  tools, OcrCache(), use_cache=False, size_guard=size_guard)
    results, logs = [], []
    r.file_done.connect(lambda i, res: results.append(res))
    r.log.connect(logs.append)
    summary = {}
    r.all_done.connect(summary.update)
    r.run()
    return results, summary, logs


# ============================================================ pengaman ukuran
def test_engine_size_guard_flags():
    assert get_engine("ocrmypdf").size_guard is False          # menambah lapisan teks: boleh lebih besar
    for eid in ("ghostscript", "full_image", "mrc"):
        assert get_engine(eid).size_guard is True


def test_larger_result_is_not_written(workspace, tools, sample_text, tmp_path):
    out = tmp_path / "hasil"
    results, summary, logs = run_jobs("full_image", BLOAT, [sample_text], out, tools)
    r = results[0]
    assert r["status"] == "tidak dikecilkan" and r["out"] == ""
    assert r["new"] >= r["orig"] > 0 and r["saving"] < 0              # angka asli tetap dilaporkan
    assert "tidak lebih kecil" in r["message"] and "Lewati bila tidak lebih kecil" in r["message"]
    assert summary["not_smaller"] == 1 and summary["ok"] == 0 and summary["failed"] == 0
    assert not out.exists() or not list(out.glob("*"))               # tidak ada file hasil
    assert any("Tidak dikecilkan" in l for l in logs)


def test_guard_off_writes_larger_result_with_note(workspace, tools, sample_text, tmp_path):
    out = tmp_path / "hasil"
    results, summary, logs = run_jobs("full_image", BLOAT, [sample_text], out, tools, size_guard=False)
    r = results[0]
    assert r["status"] == "selesai" and Path(r["out"]).exists()
    assert Path(r["out"]).stat().st_size == r["new"] >= r["orig"]
    assert "tidak lebih kecil" in r["message"]                        # tetap diberi catatan
    assert summary["ok"] == 1 and summary["not_smaller"] == 0


def test_smaller_result_is_written_normally(workspace, tools, sample_scan, tmp_path):
    out = tmp_path / "hasil"
    results, summary, _ = run_jobs("full_image", {}, [sample_scan], out, tools)
    r = results[0]
    assert r["status"] == "selesai" and Path(r["out"]).exists() and r["new"] < r["orig"] and not r["message"]
    assert summary["ok"] == 1 and summary["not_smaller"] == 0


def test_queue_mixes_written_and_skipped(workspace, tools, sample_scan, sample_text, tmp_path):
    """Satu file yang tak bisa dikecilkan (teks vektor kecil -> rasterisasi lebih besar) dan satu yang
    bisa (scan): hanya yang kedua ditulis, dan antrian tetap berjalan sampai habis."""
    out = tmp_path / "hasil"
    results, summary, _ = run_jobs("full_image", {}, [sample_text, sample_scan], out, tools)
    assert [r["status"] for r in results] == ["tidak dikecilkan", "selesai"]
    assert summary["ok"] == 1 and summary["not_smaller"] == 1 and summary["failed"] == 0
    assert [p.name for p in out.glob("*.pdf")] == [Path(results[1]["out"]).name]


# ================================================= lapisan OCR tak terlihat
def make_scan_300ppi(path, pages=2, invisible=(), visible=(), mixed=()):
    """Halaman 144x192 pt berisi satu gambar 600x800 px (= 300 ppi). `invisible` = halaman dengan
    lapisan OCR tak terlihat (render mode 3), `visible` = dengan teks biasa, `mixed` = keduanya."""
    from PIL import Image, ImageDraw
    doc = fitz.open()
    for i in range(pages):
        img = Image.new("RGB", (600, 800), (235, 230, 215))
        d = ImageDraw.Draw(img)
        for k in range(30):
            d.text((20, 20 + k * 25), "Peraturan ini menetapkan ketentuan umum %d" % k, fill=(30, 30, 30))
        b = io.BytesIO()
        img.save(b, "JPEG", quality=85)
        p = doc.new_page(width=144, height=192)
        p.insert_image(p.rect, stream=b.getvalue())
        if i in invisible or i in mixed:
            p.insert_text((10, 20), "lapisan ocr lama", fontsize=8, render_mode=3)
        if i in visible or i in mixed:
            p.insert_text((10, 60), "teks terlihat", fontsize=8)
    doc.save(str(path))
    return path


def test_pure_scan_is_native(tmp_path):
    info = pdfinfo.analyze(make_scan_300ppi(tmp_path / "a.pdf"))
    for p in info.pages:
        assert p.native_ok and not p.has_text and not p.has_visible_text
        assert round(p.ppi) == 300


def test_invisible_ocr_layer_does_not_prevent_native_extraction(tmp_path):
    """Regresi: scan yang sudah ber-OCR dianggap 'bukan scan murni' lalu dirender ulang pada 200 dpi
    (turun dari 300 ppi asli) hanya karena adanya lapisan OCR tak terlihat."""
    info = pdfinfo.analyze(make_scan_300ppi(tmp_path / "a.pdf", pages=1, invisible=(0,)))
    p = info.pages[0]
    assert p.has_text and not p.has_visible_text and p.native_ok
    assert info.image_only and info.has_any_text


def test_visible_text_still_means_not_a_pure_scan(tmp_path):
    info = pdfinfo.analyze(make_scan_300ppi(tmp_path / "a.pdf", pages=3, visible=(0,), mixed=(1,)))
    assert [p.native_ok for p in info.pages] == [False, False, True]
    assert [p.has_visible_text for p in info.pages] == [True, True, False]


def test_all_pages_with_ocr_layer_keep_native_resolution(tmp_path):
    """Kasus yang paling sering: SEMUA halaman sudah ber-OCR. Dulu: 'Tidak ada halaman scan murni;
    semua halaman dirender pada 200 dpi'."""
    info = pdfinfo.analyze(make_scan_300ppi(tmp_path / "a.pdf", pages=3, invisible=(0, 1, 2)))
    plan = pdfinfo.plan_stack(info, render_dpi=200)
    assert plan.doc_dpi == 300 and all(p.mode == "native" for p in plan.pages)
    assert not any("dirender" in n for n in plan.notes)
    assert any("lapisan OCR lama" in n and "1, 2, 3" in n for n in plan.notes)   # pengguna diberi tahu
    files = pdfinfo.build_stack(tmp_path / "a.pdf", plan, tmp_path / "stack")
    assert [image_size(f) for f in files] == [(600, 800)] * 3                     # piksel asli, bukan 400x533


def image_size(path):
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def test_no_notes_about_hidden_layer_when_there_is_none(tmp_path):
    info = pdfinfo.analyze(make_scan_300ppi(tmp_path / "a.pdf", pages=2))
    plan = pdfinfo.plan_stack(info)
    assert plan.doc_dpi == 300 and plan.notes == []


def test_unverifiable_text_is_treated_as_visible(tmp_path, monkeypatch):
    """Bila jenis teks tak bisa dipastikan, jangan ambil risiko: halaman dirender (aman)."""
    path = make_scan_300ppi(tmp_path / "a.pdf", pages=1, invisible=(0,))

    def boom(self, *a, **k):
        raise RuntimeError("tidak didukung")
    monkeypatch.setattr(fitz.Page, "get_texttrace", boom)
    p = pdfinfo.analyze(path).pages[0]
    assert p.has_visible_text and not p.native_ok


def test_texttrace_is_only_consulted_when_text_exists(tmp_path, monkeypatch):
    calls = []
    orig = fitz.Page.get_texttrace
    monkeypatch.setattr(fitz.Page, "get_texttrace", lambda self, *a, **k: calls.append(1) or orig(self, *a, **k))
    pdfinfo.analyze(make_scan_300ppi(tmp_path / "plain.pdf", pages=3))
    assert calls == []                                              # jalur cepat: tanpa teks -> tanpa texttrace
    pdfinfo.analyze(make_scan_300ppi(tmp_path / "ocr.pdf", pages=3, invisible=(0, 2)))
    assert len(calls) == 2
