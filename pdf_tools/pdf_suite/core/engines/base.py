# -*- coding: utf-8 -*-
"""Kerangka engine kompresi + konteks job."""
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ..cache import CacheEntry, OcrCache
from ..deps import ToolStatus, env_for_tools, install_hint
from ..procutil import Cancelled, ProcResult, run_process
from ..schema import OptionSet
from ..workspace import Scratch


class EngineError(Exception):
    """Kegagalan engine dengan pesan yang layak ditampilkan ke pengguna."""


@dataclass
class EngineResult:
    cache_used: Optional[bool] = None     # None = engine tidak memakai cache OCR
    notes: List[str] = field(default_factory=list)


@dataclass
class CacheStatus:
    exists: bool
    entry: Optional[CacheEntry] = None
    text: str = ""


class JobContext:
    def __init__(self, scratch: Scratch, cache: OcrCache, tools: Dict[str, ToolStatus],
                 log: Callable[[str], None], progress: Callable[[float], None],
                 is_cancelled: Callable[[], bool], use_cache: bool = True):
        self.scratch = scratch
        self.cache = cache
        self.tools = tools
        self.log = log
        self.progress = progress
        self.is_cancelled = is_cancelled
        self.use_cache = use_cache

    def check_cancel(self):
        if self.is_cancelled():
            raise Cancelled()

    def tool(self, tool_id: str) -> ToolStatus:
        st = self.tools.get(tool_id)
        if not st or not st.found:
            raise EngineError(f"Alat '{tool_id}' tidak ditemukan. Cara memasang: {install_hint(tool_id)}")
        return st

    def have(self, tool_id: str) -> bool:
        st = self.tools.get(tool_id)
        return bool(st and st.found)

    def env(self) -> dict:
        return env_for_tools(self.tools, self.scratch.env())

    def run(self, cmd: List[str], on_line: Optional[Callable[[str], None]] = None,
            cwd: Optional[str] = None, timeout: Optional[float] = None) -> ProcResult:
        return run_process(cmd, env=self.env(), cwd=cwd, on_line=on_line,
                           is_cancelled=self.is_cancelled, timeout=timeout)


class Engine:
    id = ""
    name = ""
    description = ""
    uses_ocr = False
    # Pengaman 'hasil tidak lebih kecil dari asli -> jangan disimpan' berlaku untuk metode ini?
    # False bila hasil yang lebih besar tetap bernilai (mis. menambah lapisan teks OCR).
    size_guard = True
    required_tools: Tuple[str, ...] = ()
    options: OptionSet = OptionSet([])

    # ---- ketersediaan ------------------------------------------------
    def availability(self, tools: Dict[str, ToolStatus]) -> Tuple[bool, List[str]]:
        missing = []
        for t in self.required_tools:
            st = tools.get(t)
            if not st or not st.found:
                missing.append(f"{t}: {install_hint(t)}")
            elif st.warn:       # ada, tetapi tak bisa dijalankan: jangan dibiarkan gagal di tengah proses
                missing.append(f"{t}: ditemukan di {st.path} tetapi gagal dijalankan ({st.warn})")
        return (not missing), missing

    def option_notes(self, tools: Dict[str, ToolStatus]) -> Dict[str, Tuple[bool, str]]:
        """key -> (aktif?, alasan bila nonaktif). Default: semua aktif."""
        return {}

    def cache_status(self, src: Path, values: dict, cache: OcrCache) -> Optional[CacheStatus]:
        return None

    def process(self, src: Path, out: Path, values: dict, ctx: JobContext) -> EngineResult:
        raise NotImplementedError


def split_args(text: str) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text, posix=True)
    except ValueError as e:
        raise EngineError(f"Argumen tambahan tidak valid: {e}")


def page_count(path) -> int:
    from ..pdfcompat import fitz
    with fitz.open(str(path)) as d:
        return len(d)
