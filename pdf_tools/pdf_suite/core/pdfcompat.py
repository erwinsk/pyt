# -*- coding: utf-8 -*-
"""Impor PyMuPDF yang kompatibel: `pymupdf` (baru) atau `fitz` (lama)."""
try:
    import pymupdf as fitz  # PyMuPDF >= 1.24.3
except ImportError:  # pragma: no cover
    import fitz  # type: ignore

__all__ = ["fitz"]
