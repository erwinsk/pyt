# -*- coding: utf-8 -*-
"""Folder scratch (sementara) + penyelesaian output yang atomik.

Aturan:
* Scratch SELALU dibersihkan (sukses, gagal, maupun dibatalkan).
* Scratch sisa proses yang crash disapu saat aplikasi dibuka.
* Hasil ditulis dulu di scratch, lalu dipindah ke tujuan hanya bila sukses,
  sehingga tidak pernah ada file setengah jadi di folder pengguna.
"""
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from .paths import scratch_root


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - tidak teruji di container Linux
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def rmtree_retry(path: Path, tries: int = 5, delay: float = 0.2):
    """rmtree yang tahan terhadap file terkunci sesaat (Windows)."""
    for i in range(tries):
        try:
            shutil.rmtree(path)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            time.sleep(delay)
    shutil.rmtree(path, ignore_errors=True)
    return not Path(path).exists()


class Scratch:
    """Context manager folder sementara milik satu proses/job."""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else scratch_root()
        self.path = self.root / uuid.uuid4().hex[:12]

    def __enter__(self) -> "Scratch":
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "owner.pid").write_text(str(os.getpid()))
        return self

    def __exit__(self, exc_type, exc, tb):
        rmtree_retry(self.path)
        return False

    def subdir(self, name: str) -> Path:
        p = self.path / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def env(self, base: Optional[dict] = None) -> dict:
        """Environment subprocess yang mengarahkan temp ke scratch ini."""
        env = dict(base if base is not None else os.environ)
        t = str(self.path)
        env["TMPDIR"] = t
        env["TEMP"] = t
        env["TMP"] = t
        return env


def sweep_orphans(root: Optional[Path] = None) -> int:
    """Hapus folder scratch yatim (pemiliknya sudah tidak hidup)."""
    root = Path(root) if root else scratch_root()
    removed = 0
    if not root.exists():
        return 0
    for d in root.iterdir():
        if not d.is_dir():
            continue
        pid = 0
        try:
            pid = int((d / "owner.pid").read_text().strip())
        except (OSError, ValueError):
            pass
        if pid and pid != os.getpid() and pid_alive(pid):
            continue  # milik instance lain yang masih berjalan
        if pid == os.getpid():
            continue  # milik job kita sendiri
        if rmtree_retry(d):
            removed += 1
    return removed


def unique_path(path: Path) -> Path:
    path = Path(path)
    if not path.exists():
        return path
    n = 2
    while True:
        cand = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not cand.exists():
            return cand
        n += 1


def resolve_output(src: Path, out_dir: Optional[Path], template: str, engine_id: str,
                   policy: str = "unik") -> Optional[Path]:
    """Tentukan path output. policy: unik | timpa | lewati.

    Mengembalikan None bila policy 'lewati' dan file sudah ada.
    File sumber tidak pernah ditimpa.
    """
    src = Path(src)
    folder = Path(out_dir) if out_dir else src.parent
    name = template.replace("{nama}", src.stem).replace("{engine}", engine_id)
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    dest = folder / name
    try:
        same_as_src = dest.resolve() == src.resolve()
    except OSError:
        same_as_src = False
    if same_as_src:
        return unique_path(dest)
    if dest.exists():
        if policy == "lewati":
            return None
        if policy == "unik":
            return unique_path(dest)
    return dest


def finalize_output(tmp_file: Path, dest: Path):
    """Pindahkan hasil ke tujuan secara atomik; bersihkan file .part bila gagal."""
    tmp_file, dest = Path(tmp_file), Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        shutil.copyfile(tmp_file, part)
        os.replace(part, dest)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    finally:
        try:
            tmp_file.unlink()
        except OSError:
            pass
