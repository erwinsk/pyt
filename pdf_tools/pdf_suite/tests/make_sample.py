# -*- coding: utf-8 -*-
"""Pembuat PDF scan sintetis untuk pengujian (meniru PDF image-only berwarna)."""
import io
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

LOREM = [
    "Certificate of Calibration and Flow Measurement Report",
    "The quick brown fox jumps over the lazy dog 0123456789",
    "Electromagnetic flowmeter totalizer reading verified on site",
    "Reference number RCA 2026 / 1234 / 5678 issued by the laboratory",
    "All measurements were performed according to the approved method",
    "Signed and stamped by the authorised technical manager of the lab",
]


def make_page_image(w, h, seed, text_lines=22):
    rnd = random.Random(seed)
    img = Image.new("RGB", (w, h), (250, 244, 225))
    px = img.load()
    # noise halus agar mirip hasil scan
    for _ in range(w * h // 40):
        x, y = rnd.randrange(w), rnd.randrange(h)
        v = rnd.randint(-12, 12)
        r, g, b = px[x, y]
        px[x, y] = (max(0, min(255, r + v)), max(0, min(255, g + v)), max(0, min(255, b + v)))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=int(h / 55))
    except TypeError:  # Pillow lama
        font = ImageFont.load_default()
    y = int(h * 0.06)
    for i in range(text_lines):
        d.text((int(w * 0.08), y), LOREM[(i + seed) % len(LOREM)], fill=(20, 20, 30), font=font)
        y += int(h / 40)
    d.rectangle([int(w * .6), int(h * .8), int(w * .9), int(h * .9)], outline=(200, 30, 30), width=6)
    d.text((int(w * .63), int(h * .83)), "STAMP APPROVED", fill=(200, 30, 30), font=font)
    return img


def make_scan_pdf(path, sizes=((1700, 2200), (1700, 2200), (2329, 3014)), ppi=96):
    """PDF image-only: tiap halaman satu gambar RGB, ditempatkan pada `ppi` tertentu."""
    path = Path(path)
    doc = fitz.open()
    for i, (w, h) in enumerate(sizes):
        img = make_page_image(w, h, seed=i)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page = doc.new_page(width=w * 72 / ppi, height=h * 72 / ppi)
        page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(str(path), garbage=3, deflate=True)
    doc.close()
    return path


def make_text_pdf(path, pages=2):
    """PDF 'born digital' (teks vektor asli)."""
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 100), f"Halaman teks asli nomor {i + 1}", fontsize=14)
    doc.save(str(path))
    doc.close()
    return Path(path)


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "sample_scan.pdf")
    make_scan_pdf(out)
    print(out, out.stat().st_size)
