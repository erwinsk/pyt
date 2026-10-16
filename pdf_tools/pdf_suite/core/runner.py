# -*- coding: utf-8 -*-
"""Pelaksana job (QThread) — satu antrian file memakai satu engine."""
import time
from pathlib import Path
from typing import Dict, List, Optional

from PyQt5.QtCore import QThread, pyqtSignal

from .cache import OcrCache
from .deps import ToolStatus
from .engines import Engine, EngineError, JobContext
from .procutil import Cancelled
from .workspace import Scratch, finalize_output, resolve_output


def _kb(n: int) -> str:
    return "%.0f KB" % (n / 1024)


class OutputConfig:
    def __init__(self, out_dir: Optional[str] = None, template: str = "{nama}_{engine}",
                 policy: str = "unik"):
        self.out_dir = out_dir or None
        self.template = template or "{nama}_{engine}"
        self.policy = policy


class JobRunner(QThread):
    log = pyqtSignal(str)
    overall = pyqtSignal(int)
    file_started = pyqtSignal(int, str)
    file_done = pyqtSignal(int, dict)
    all_done = pyqtSignal(dict)

    def __init__(self, engine: Engine, values: dict, files: List[str], out_cfg: OutputConfig,
                 tools: Dict[str, ToolStatus], cache: OcrCache, use_cache: bool = True,
                 size_guard: bool = True, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.values = values
        self.files = list(files)
        self.out_cfg = out_cfg
        self.tools = tools
        self.cache = cache
        self.use_cache = use_cache
        self.size_guard = size_guard
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _is_cancelled(self) -> bool:
        return self._cancel

    def run(self):
        n = len(self.files)
        summary = {"ok": 0, "failed": 0, "skipped": 0, "not_smaller": 0, "cancelled": False}
        for idx, src in enumerate(self.files):
            if self._cancel:
                summary["cancelled"] = True
                break
            src_p = Path(src)
            self.file_started.emit(idx, src)
            self.log.emit(f"[{idx + 1}/{n}] {src_p.name}  —  {self.engine.name}")
            res = {"src": src, "out": "", "orig": 0, "new": 0, "saving": 0.0, "seconds": 0.0,
                   "cache": None, "status": "", "message": ""}
            t0 = time.monotonic()
            try:
                res["orig"] = src_p.stat().st_size
                dest = resolve_output(src_p, self.out_cfg.out_dir, self.out_cfg.template,
                                      self.engine.id, self.out_cfg.policy)
                if dest is None:
                    res["status"] = "dilewati"
                    res["message"] = "File hasil sudah ada"
                    summary["skipped"] += 1
                    self.log.emit("  Dilewati: file hasil sudah ada.")
                else:
                    def prog(frac, i=idx):
                        self.overall.emit(int(((i + max(0.0, min(1.0, frac))) / n) * 100))
                    with Scratch() as scratch:
                        ctx = JobContext(scratch, self.cache, self.tools, self.log.emit, prog,
                                         self._is_cancelled, self.use_cache)
                        tmp_out = scratch.path / "output.pdf"
                        er = self.engine.process(src_p, tmp_out, self.values, ctx)
                        ctx.check_cancel()
                        res["new"] = tmp_out.stat().st_size
                        res["saving"] = (1 - res["new"] / res["orig"]) * 100 if res["orig"] else 0.0
                        res["cache"] = er.cache_used
                        # Pengaman: hasil yang tidak lebih kecil dari sumber TIDAK ditulis. Diputuskan di
                        # dalam blok Scratch karena file sementara hilang begitu blok ini selesai.
                        not_smaller = bool(res["orig"]) and res["new"] >= res["orig"]
                        if not (self.size_guard and self.engine.size_guard and not_smaller):
                            finalize_output(tmp_out, dest)
                    if self.size_guard and self.engine.size_guard and not_smaller:
                        res["status"] = "tidak dikecilkan"
                        res["message"] = ("Hasil (%s) tidak lebih kecil dari aslinya (%s), jadi tidak disimpan. "
                                          "Coba profil/parameter lain, atau matikan 'Lewati bila tidak lebih kecil'."
                                          % (_kb(res["new"]), _kb(res["orig"])))
                        summary["not_smaller"] += 1
                        self.log.emit("  Tidak dikecilkan: hasil %s vs asli %s - tidak disimpan." %
                                      (_kb(res["new"]), _kb(res["orig"])))
                    else:
                        res["out"] = str(dest)
                        res["status"] = "selesai"
                        summary["ok"] += 1
                        self.log.emit("  Selesai: %s  (%.0f KB, %+.1f%%)" % (dest.name, res["new"] / 1024, -res["saving"]))
                        if not_smaller:      # metode tanpa pengaman (mis. OCR) atau pengaman dimatikan
                            res["message"] = "Hasil tidak lebih kecil dari aslinya (%+.1f%%)." % -res["saving"]
                            self.log.emit("  Catatan: hasil tidak lebih kecil dari file asli.")
            except Cancelled:
                res["status"] = "dibatalkan"
                summary["cancelled"] = True
                self.log.emit("  Dibatalkan oleh pengguna.")
            except EngineError as e:
                res["status"] = "gagal"
                res["message"] = str(e)
                summary["failed"] += 1
                self.log.emit("  GAGAL: " + str(e))
            except Exception as e:  # noqa: BLE001
                res["status"] = "gagal"
                res["message"] = f"{type(e).__name__}: {e}"
                summary["failed"] += 1
                self.log.emit("  GAGAL: " + res["message"])
            res["seconds"] = time.monotonic() - t0
            self.file_done.emit(idx, res)
            if summary["cancelled"]:
                break
        self.overall.emit(100 if not summary["cancelled"] else 0)
        self.all_done.emit(summary)
