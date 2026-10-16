# -*- coding: utf-8 -*-
"""Uji modul inti: workspace, cache, proses, deps, skema, analisis PDF."""
import os
import sys
import time

import pytest

from core import deps, pdfinfo
from core.cache import OcrCache
from core.procutil import Cancelled, run_process
from core.schema import OptionSet, int_opt, choice_opt, bool_opt
from core.settings import Settings
from core.workspace import (Scratch, finalize_output, pid_alive, resolve_output, sweep_orphans)


def test_scratch_cleaned_on_success_and_error(workspace):
    from core.paths import scratch_root
    with Scratch() as s:
        (s.path / "x.bin").write_bytes(b"1")
        p = s.path
        assert p.exists()
    assert not p.exists()
    with pytest.raises(RuntimeError):
        with Scratch() as s:
            p2 = s.path
            raise RuntimeError("boom")
    assert not p2.exists()
    assert list(scratch_root().iterdir()) == []


def test_scratch_env_points_temp_to_scratch(workspace):
    with Scratch() as s:
        env = s.env()
        assert env["TMPDIR"] == env["TEMP"] == env["TMP"] == str(s.path)


def test_sweep_orphans_removes_dead_keeps_alive(workspace):
    from core.paths import scratch_root
    root = scratch_root()
    dead = root / "dead"; dead.mkdir(parents=True)
    (dead / "owner.pid").write_text("999999")           # pid tak hidup
    (dead / "f").write_text("x")
    nopid = root / "nopid"; nopid.mkdir()
    alive = root / "alive"; alive.mkdir()
    (alive / "owner.pid").write_text(str(os.getppid()))  # proses induk = hidup
    removed = sweep_orphans()
    assert removed == 2
    assert not dead.exists() and not nopid.exists() and alive.exists()


def test_pid_alive():
    assert pid_alive(os.getpid())
    assert not pid_alive(999999)
    assert not pid_alive(0)


def test_unique_and_resolve_output(tmp_path):
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    p = resolve_output(src, None, "{nama}_{engine}", "mrc")
    assert p == tmp_path / "a_mrc.pdf"
    p.write_bytes(b"y")
    assert resolve_output(src, None, "{nama}_{engine}", "mrc", "unik") == tmp_path / "a_mrc_2.pdf"
    assert resolve_output(src, None, "{nama}_{engine}", "mrc", "timpa") == p
    assert resolve_output(src, None, "{nama}_{engine}", "mrc", "lewati") is None
    # sumber tidak pernah ditimpa
    assert resolve_output(src, None, "{nama}", "mrc", "timpa") != src


def test_finalize_output_atomic_and_no_part_left(tmp_path):
    t = tmp_path / "t.pdf"; t.write_bytes(b"data")
    dest = tmp_path / "out" / "r.pdf"
    finalize_output(t, dest)
    assert dest.read_bytes() == b"data" and not t.exists()
    assert not list((tmp_path / "out").glob("*.part"))
    # gagal -> tidak ada .part
    t2 = tmp_path / "missing.pdf"
    with pytest.raises(OSError):
        finalize_output(t2, tmp_path / "out" / "z.pdf")
    assert not list((tmp_path / "out").glob("*.part"))


def test_run_process_stream_and_cancel(workspace):
    lines = []
    r = run_process([sys.executable, "-c", "print('halo'); print('dunia')"], on_line=lines.append)
    assert r.returncode == 0 and lines == ["halo", "dunia"]
    t0 = time.time()
    with pytest.raises(Cancelled):
        run_process([sys.executable, "-c", "import time; time.sleep(30)"],
                    is_cancelled=lambda: time.time() - t0 > 0.5)
    assert time.time() - t0 < 6


def test_cancel_kills_child_processes(workspace, tmp_path):
    """Pembatalan harus mematikan seluruh pohon proses (anak dari anak)."""
    marker = tmp_path / "alive.txt"
    code = ("import subprocess,sys,time;"
            f"subprocess.Popen([sys.executable,'-c',\"import time,pathlib;"
            f"[ (pathlib.Path(r'{marker}').write_text(str(time.time())), time.sleep(0.3)) for _ in range(100)]\"]);"
            "time.sleep(60)")
    t0 = time.time()
    with pytest.raises(Cancelled):
        run_process([sys.executable, "-c", code], is_cancelled=lambda: time.time() - t0 > 1.0)
    time.sleep(0.8)
    m1 = marker.read_text() if marker.exists() else ""
    time.sleep(0.8)
    m2 = marker.read_text() if marker.exists() else ""
    assert m1 == m2, "proses anak masih menulis setelah dibatalkan"


def test_cache_store_lookup_delete(workspace, tmp_path):
    c = OcrCache()
    f = tmp_path / "doc.pdf"; f.write_bytes(b"isi dokumen")
    h = c.file_hash(f)
    key = c.make_id(h, {"lang": "eng"})
    assert key != c.make_id(h, {"lang": "ind"}) and key.startswith(h[:16])
    assert not c.exists(key)
    payload = tmp_path / "ocr.hocr"; payload.write_text("hocr")
    e = c.store(key, "hocr", {"ocr.hocr": payload}, "doc.pdf", 3, {"lang": "eng"})
    assert c.exists(key) and e.size > 0 and e.pages == 3
    assert c.lookup(key).file("ocr.hocr").read_text() == "hocr"
    assert len(c.list()) == 1 and c.total_size() > 0
    # perubahan isi file -> hash berubah -> cache lama tak terpakai
    f.write_bytes(b"isi lain")
    assert c.file_hash(f) != h
    assert c.delete_for_file(h) == 1 and not c.exists(key)
    e = c.store(key, "hocr", {"ocr.hocr": payload}, "doc.pdf", 3, {})
    assert c.delete_all() == 1 and c.list() == []


def test_cache_sweep_partial(workspace):
    c = OcrCache()
    (c.root / ".tmp-abc").mkdir(parents=True)
    assert c.sweep_partial() == 1 and c.list() == []


def test_schema_normalize_and_ocr_params():
    s = OptionSet([int_opt("q", "Q", 60, 1, 100), choice_opt("m", "M", "a", [("a", "A"), ("b", "B")], affects_ocr=True),
                   bool_opt("g", "G", False)])
    n = s.normalize({"q": 500, "m": "zzz", "g": 1, "unknown": 5})
    assert n == {"q": 100, "m": "a", "g": True}
    assert s.ocr_params(n) == {"m": "a"}
    assert s.normalize({"q": "abc"})["q"] == 60


def test_settings_roundtrip(workspace):
    s = Settings()
    s.set("tools.gs", "/opt/gs")
    s.set("a.b.c", 3)
    s2 = Settings()
    assert s2.get("tools.gs") == "/opt/gs" and s2.get("a.b.c") == 3 and s2.get("x.y", "d") == "d"
    s2.set("tools.gs", None)
    assert Settings().get("tools.gs") is None


def test_deps_detect_and_custom_path(workspace, tools, tmp_path):
    assert tools["tesseract"].found and tools["gs"].found
    fake = tmp_path / "gsfake"; fake.write_text("#!/bin/sh\necho GPL Ghostscript 9.99\n"); fake.chmod(0o755)
    s = Settings(); s.set("tools.gs", str(fake))
    st = deps.detect_tool(deps.SPEC_BY_ID["gs"], s)
    assert st.found and st.source == "custom" and "9.99" in st.version
    env = deps.env_for_tools({"gs": st}, {"PATH": "/usr/bin"})
    assert env["PATH"].startswith(str(tmp_path))
    nof = deps.detect_tool(deps.ToolSpec("zzz", "Z", ["tidak-ada-biner-ini"], "x"), None)
    assert not nof.found


def test_install_hints_cover_all_tools_and_families():
    for spec in deps.TOOL_SPECS:
        for fam in ("debian", "fedora", "windows", "linux"):
            assert deps.install_hint(spec.id, fam)
    assert "apt" in deps.install_hint("pngquant", "debian") and "dnf" in deps.install_hint("pngquant", "fedora")


def test_pdfinfo_scan_vs_text(sample_scan, sample_text):
    i = pdfinfo.analyze(sample_scan)
    assert i.n_pages == 3 and i.image_only and not i.has_any_text
    assert all(round(p.ppi) == 96 for p in i.pages)
    assert (i.pages[2].img_w, i.pages[2].img_h) == (2329, 3014)
    plan = pdfinfo.plan_stack(i)
    assert plan.doc_dpi == 96 and all(p.mode == "native" and not p.resampled for p in plan.pages)
    t = pdfinfo.analyze(sample_text)
    assert t.has_any_text and not t.image_only
    tp = pdfinfo.plan_stack(t, render_dpi=150)
    assert tp.doc_dpi == 150 and all(p.mode == "render" for p in tp.pages) and tp.notes


def test_stack_native_pixels_match_source(sample_scan, tmp_path):
    from PIL import Image
    info = pdfinfo.analyze(sample_scan)
    plan = pdfinfo.plan_stack(info)
    paths = pdfinfo.build_stack(sample_scan, plan, tmp_path / "stk")
    sizes = [Image.open(p).size for p in paths]
    assert sizes == [(1700, 2200), (1700, 2200), (2329, 3014)]
    assert Image.open(paths[0]).info.get("dpi")[0] == pytest.approx(96, abs=0.1)
