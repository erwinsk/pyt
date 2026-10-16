# -*- coding: utf-8 -*-
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from make_sample import make_scan_pdf, make_text_pdf  # noqa: E402


@pytest.fixture(scope="session")
def sample_scan(tmp_path_factory):
    d = tmp_path_factory.mktemp("samples")
    return make_scan_pdf(d / "scan.pdf")


@pytest.fixture(scope="session")
def sample_text(tmp_path_factory):
    d = tmp_path_factory.mktemp("samples_t")
    return make_text_pdf(d / "teks.pdf")


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """Folder kerja terisolasi + TMPDIR terpantau (untuk memastikan tidak ada sisa)."""
    ws = tmp_path / "ws dengan spasi"          # sengaja berspasi
    systmp = tmp_path / "systmp"
    systmp.mkdir()
    monkeypatch.setenv("PDFSUITE_WORKSPACE", str(ws))
    monkeypatch.setenv("PDFSUITE_CONFIG", str(tmp_path / "cfg"))
    monkeypatch.setenv("TMPDIR", str(systmp))
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(systmp))
    return {"ws": ws, "systmp": systmp, "tmp": tmp_path}


@pytest.fixture(scope="session")
def tools():
    from core import deps
    return deps.detect_all(None, with_version=False)


def run_engine(engine, src, out_dir, values, tools, use_cache=True, cancel_after=None, logs=None):
    """Jalankan engine seperti JobRunner (scratch -> finalize)."""
    from core.cache import OcrCache
    from core.engines import JobContext
    from core.workspace import Scratch, finalize_output
    cache = OcrCache()
    logs = logs if logs is not None else []
    state = {"n": 0}

    def is_cancelled():
        if cancel_after is None:
            return False
        state["n"] += 1
        return state["n"] > cancel_after

    dest = Path(out_dir) / f"{Path(src).stem}_{engine.id}.pdf"
    with Scratch() as scratch:
        ctx = JobContext(scratch, cache, tools, logs.append, lambda f: None, is_cancelled, use_cache)
        tmp_out = scratch.path / "output.pdf"
        er = engine.process(Path(src), tmp_out, values, ctx)
        finalize_output(tmp_out, dest)
    return dest, er, logs
