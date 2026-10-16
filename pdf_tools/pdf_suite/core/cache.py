# -*- coding: utf-8 -*-
"""Cache hasil OCR — dipertahankan sampai pengguna menghapusnya sendiri.

Kunci cache = hash isi file sumber + parameter yang memengaruhi OCR.
Mengubah parameter kompresi TIDAK mengubah kunci, sehingga OCR dipakai ulang.
Penyimpanan atomik: dibangun di folder sementara lalu di-rename.
"""
import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .paths import cache_root
from .workspace import rmtree_retry

META = "meta.json"


@dataclass
class CacheEntry:
    id: str
    path: Path
    kind: str = ""
    source_name: str = ""
    pages: int = 0
    params: Dict = field(default_factory=dict)
    size: int = 0
    created: float = 0.0
    last_used: float = 0.0

    def file(self, name: str) -> Path:
        return self.path / name


def _dir_size(p: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


class OcrCache:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else cache_root()
        self._hash_memo: Dict[tuple, str] = {}

    # ---- kunci -------------------------------------------------------
    def file_hash(self, path) -> str:
        p = Path(path)
        st = p.stat()
        memo_key = (str(p.resolve()), st.st_mtime_ns, st.st_size)
        if memo_key in self._hash_memo:
            return self._hash_memo[memo_key]
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        digest = h.hexdigest()
        self._hash_memo[memo_key] = digest
        return digest

    @staticmethod
    def make_id(file_hash: str, params: dict) -> str:
        blob = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
        ph = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        return f"{file_hash[:16]}-{ph[:12]}"

    # ---- operasi -----------------------------------------------------
    def _read_entry(self, d: Path) -> Optional[CacheEntry]:
        try:
            meta = json.loads((d / META).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return CacheEntry(
            id=d.name, path=d, kind=meta.get("kind", ""), source_name=meta.get("source_name", ""),
            pages=int(meta.get("pages", 0)), params=meta.get("params", {}),
            size=_dir_size(d), created=float(meta.get("created", 0)),
            last_used=float(meta.get("last_used", meta.get("created", 0))))

    def lookup(self, entry_id: str) -> Optional[CacheEntry]:
        d = self.root / entry_id
        if not d.is_dir():
            return None
        entry = self._read_entry(d)
        if entry:
            self.touch(entry_id)
        return entry

    def exists(self, entry_id: str) -> bool:
        return (self.root / entry_id / META).is_file()

    def touch(self, entry_id: str):
        mp = self.root / entry_id / META
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
            meta["last_used"] = time.time()
            mp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        except (OSError, ValueError):
            pass

    def store(self, entry_id: str, kind: str, files: Dict[str, Path], source_name: str,
              pages: int, params: dict) -> CacheEntry:
        """Simpan file-file (nama_tujuan -> path sumber) secara atomik."""
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f".tmp-{uuid.uuid4().hex[:8]}"
        tmp.mkdir()
        try:
            for name, src in files.items():
                shutil.copyfile(src, tmp / name)
            now = time.time()
            (tmp / META).write_text(json.dumps({
                "kind": kind, "source_name": source_name, "pages": pages,
                "params": params, "created": now, "last_used": now}, ensure_ascii=False),
                encoding="utf-8")
            final = self.root / entry_id
            if final.exists():
                rmtree_retry(final)
            os.replace(tmp, final)
        except BaseException:
            rmtree_retry(tmp)
            raise
        return self._read_entry(self.root / entry_id)  # type: ignore[return-value]

    def list(self) -> List[CacheEntry]:
        out: List[CacheEntry] = []
        if not self.root.exists():
            return out
        for d in sorted(self.root.iterdir()):
            if d.is_dir() and not d.name.startswith(".tmp-"):
                e = self._read_entry(d)
                if e:
                    out.append(e)
        return out

    def total_size(self) -> int:
        return sum(e.size for e in self.list())

    def delete(self, entry_id: str) -> bool:
        d = self.root / entry_id
        return rmtree_retry(d) if d.exists() else False

    def delete_for_file(self, file_hash: str) -> int:
        n = 0
        if not self.root.exists():
            return 0
        for d in list(self.root.iterdir()):
            if d.is_dir() and d.name.startswith(file_hash[:16]):
                if rmtree_retry(d):
                    n += 1
        return n

    def delete_all(self) -> int:
        n = 0
        if not self.root.exists():
            return 0
        for d in list(self.root.iterdir()):
            if d.is_dir() and rmtree_retry(d):
                n += 1
        return n

    def sweep_partial(self) -> int:
        """Hapus sisa folder .tmp-* (penulisan cache yang terputus)."""
        n = 0
        if self.root.exists():
            for d in list(self.root.iterdir()):
                if d.is_dir() and d.name.startswith(".tmp-") and rmtree_retry(d):
                    n += 1
        return n
