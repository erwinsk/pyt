# -*- coding: utf-8 -*-
"""Deteksi alat eksternal + petunjuk instal per OS.

Urutan pencarian tiap alat: path kustom (Pengaturan) -> PATH -> folder bin
dari Python yang menjalankan aplikasi (mis. venv) -> folder skrip instalasi pengguna
(`pip install --user` / pipx, mis. ~/.local/bin; sering TIDAK ada di PATH) -> `python -m modul`.
Aplikasi TIDAK pernah menjalankan sudo/instalasi sendiri.
"""
import importlib.util
import os
import platform
import shutil
import site
import subprocess
import sys
import sysconfig
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .settings import Settings


@dataclass
class ToolSpec:
    id: str
    label: str
    binaries: List[str]
    used_by: str
    version_args: List[str] = field(default_factory=lambda: ["--version"])
    python_module: Optional[str] = None
    note: str = ""


TOOL_SPECS: List[ToolSpec] = [
    ToolSpec("gs", "Ghostscript", ["gs", "gswin64c", "gswin32c"], "Ghostscript, OCRmyPDF (PDF/A)", ["-v"]),
    ToolSpec("tesseract", "Tesseract OCR", ["tesseract"], "OCRmyPDF, MRC"),
    ToolSpec("ocrmypdf", "OCRmyPDF", ["ocrmypdf"], "OCRmyPDF", python_module="ocrmypdf"),
    ToolSpec("recode_pdf", "recode_pdf (archive-pdf-tools)", ["recode_pdf"], "MRC"),
    ToolSpec("jbig2", "jbig2enc (biner `jbig2`)", ["jbig2", "jbig2enc"], "MRC (mask JBIG2); tanpa ini dipakai CCITT",
             ["--version"], note="Di beberapa distro biner bernama `jbig2`, bukan `jbig2enc`."),
    ToolSpec("pngquant", "pngquant", ["pngquant"], "OCRmyPDF (optimize 2/3)"),
    ToolSpec("unpaper", "unpaper", ["unpaper"], "OCRmyPDF (opsi Clean)"),
    ToolSpec("jpegoptim", "jpegoptim", ["jpegoptim"], "MRC (hanya format gambar JPEG)"),
]
SPEC_BY_ID = {s.id: s for s in TOOL_SPECS}


@dataclass
class ToolStatus:
    id: str
    label: str
    found: bool = False
    cmd: List[str] = field(default_factory=list)
    path: str = ""
    version: str = ""
    source: str = ""            # custom | path | venv | user | module
    used_by: str = ""
    note: str = ""
    warn: str = ""              # ditemukan, tetapi menjalankannya gagal (mis. ImportError di Python ini)
    searched: List[str] = field(default_factory=list)   # tempat pencarian (diisi bila tidak ditemukan)


def _is_exec(p: Path) -> bool:
    return p.is_file() and os.access(str(p), os.X_OK)


def user_script_dirs() -> List[Path]:
    """Folder skrip hasil `pip install --user` / pipx (mis. ~/.local/bin). Perintah yang dipasang di
    sini sering TIDAK ada di PATH: zsh tidak membaca ~/.bash_profile, atau aplikasi dibuka dari
    peluncur desktop. Tanpa pencarian ini `recode_pdf` terpasang tetapi dilaporkan 'tidak ada'."""
    cands: List[Path] = []
    try:
        cands.append(Path(sysconfig.get_path("scripts", sysconfig.get_preferred_scheme("user"))))
    except Exception:  # noqa: BLE001  (Python < 3.10 atau skema tak dikenal)
        pass
    try:
        cands.append(Path(site.getuserbase()) / ("Scripts" if os.name == "nt" else "bin"))
    except Exception:  # noqa: BLE001
        pass
    cands.append(Path.home() / ".local" / "bin")
    out: List[Path] = []
    for c in cands:
        if c not in out:
            out.append(c)
    return out


def search_places(spec: ToolSpec) -> List[str]:
    """Tempat yang dicari untuk alat ini, dalam bahasa yang bisa dibaca pengguna."""
    n = len([p for p in os.environ.get("PATH", "").split(os.pathsep) if p])
    places = [f"PATH ({n} folder)", f"{Path(sys.executable).parent} (folder Python aplikasi)"]
    places += [f"{d} (instalasi pengguna: pip --user / pipx)" for d in user_script_dirs()]
    if spec.python_module:
        places.append(f"python -m {spec.python_module}")
    return places


def resolve(spec: ToolSpec, custom_path: Optional[str] = None):
    """Kembalikan (cmd, source) atau None."""
    if custom_path and Path(custom_path).exists():
        return [str(custom_path)], "custom"
    for name in spec.binaries:
        p = shutil.which(name)
        if p:
            return [p], "path"
    bindir = Path(sys.executable).parent
    for name in spec.binaries:
        for ext in ("", ".exe"):
            c = bindir / (name + ext)
            if _is_exec(c):
                return [str(c)], "venv"
    for d in user_script_dirs():
        for name in spec.binaries:
            for ext in ("", ".exe"):
                c = d / (name + ext)
                if _is_exec(c):
                    return [str(c)], "user"
    if spec.python_module and importlib.util.find_spec(spec.python_module):
        return [sys.executable, "-m", spec.python_module], "module"
    return None


def _first_line(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s and "fitz" not in s.lower() and not s.startswith("warning"):
            return s[:80]
    return ""


def _probe(cmd: List[str], args: List[str]) -> Tuple[str, str]:
    """Jalankan `cmd args`; kembalikan (versi, peringatan). Peringatan hanya diisi bila alat JELAS
    gagal dijalankan (traceback Python, atau OS menolak menjalankan): bukan sekadar kode keluar
    bukan-nol, karena sebagian alat (mis. jbig2) menampilkan bantuan dengan kode itu."""
    try:
        r = subprocess.run(cmd + args, capture_output=True, text=True, timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        return "", ""
    except OSError as e:          # mis. 'bad interpreter', 'Exec format error'
        return "", str(e)[:200]
    except Exception:  # noqa: BLE001
        return "", ""
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    if "Traceback (most recent call last)" in out:
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        return "", (lines[-1] if lines else "Traceback")[:200]
    return _first_line(r.stdout) or _first_line(r.stderr), ""


def _version(cmd: List[str], args: List[str]) -> str:
    return _probe(cmd, args)[0]


SOURCE_LABELS = {
    "custom": "path kustom (Pengaturan)",
    "path": "PATH",
    "venv": "folder Python aplikasi",
    "user": "folder instalasi pengguna (pip --user / pipx) yang tidak ada di PATH",
    "module": "modul Python (python -m)",
}


def describe_status(st: "ToolStatus") -> str:
    """Penjelasan satu alat untuk tab Dependensi: dari mana ditemukan, atau di mana dicari."""
    if not st.found:
        where = "; ".join(st.searched) if st.searched else "PATH dan folder instalasi pengguna"
        return (f"Tidak ditemukan. Dicari di: {where}. Bila sudah terpasang di tempat lain, isi "
                f"'Path kustom' di bawah.")
    src = SOURCE_LABELS.get(st.source, st.source)
    if st.warn:
        return (f"Ditemukan di {st.path} ({src}), tetapi gagal dijalankan: {st.warn}\n"
                f"Jalankan `{st.path} --version` di terminal untuk melihat galat lengkapnya.")
    return f"Ditemukan lewat {src}."


def detect_tool(spec: ToolSpec, settings: Optional[Settings] = None, with_version: bool = True) -> ToolStatus:
    custom = settings.get(f"tools.{spec.id}") if settings else None
    st = ToolStatus(spec.id, spec.label, used_by=spec.used_by, note=spec.note)
    found = resolve(spec, custom)
    if not found:
        st.searched = search_places(spec)
        return st
    st.cmd, st.source = found
    st.found = True
    st.path = st.cmd[0] if st.source != "module" else " ".join(st.cmd)
    if with_version:
        ver, st.warn = _probe(st.cmd, spec.version_args)
        st.version = ver or ("" if st.warn else "(terdeteksi)")
    return st


def detect_all(settings: Optional[Settings] = None, with_version: bool = True) -> Dict[str, ToolStatus]:
    return {s.id: detect_tool(s, settings, with_version) for s in TOOL_SPECS}


def tesseract_languages(st: ToolStatus) -> List[str]:
    if not st.found:
        return []
    try:
        r = subprocess.run(st.cmd + ["--list-langs"], capture_output=True, text=True, timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except Exception:
        return []
    langs = [l.strip() for l in (r.stdout or r.stderr).splitlines()[1:] if l.strip()]
    return [l for l in langs if l != "osd"]


def env_for_tools(tools: Dict[str, ToolStatus], base: Optional[dict] = None) -> dict:
    """PATH untuk subprocess: sertakan folder alat yang ditemukan lewat path kustom/venv."""
    env = dict(base if base is not None else os.environ)
    extra: List[str] = []
    for st in tools.values():
        if st.found and st.source in ("custom", "venv", "user"):
            d = str(Path(st.cmd[0]).parent)
            if d not in extra:
                extra.append(d)
    if extra:
        env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    return env


# --------------------------------------------------------------------------
def os_family() -> str:
    system = platform.system()
    if system == "Windows":
        return "windows"
    if system == "Darwin":
        return "macos"
    ids = ""
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith(("ID=", "ID_LIKE=")):
                ids += " " + line.split("=", 1)[1].strip().strip('"').lower()
    except OSError:
        pass
    if any(x in ids for x in ("debian", "ubuntu")):
        return "debian"
    if any(x in ids for x in ("fedora", "rhel", "centos", "nobara")):
        return "fedora"
    if "arch" in ids:
        return "arch"
    return "linux"


PIP_HINT = "pipx install {pkg}   (atau: pip install --user {pkg}; folder ~/.local/bin dicari otomatis)"

HINTS: Dict[str, Dict[str, str]] = {
    "gs": {
        "debian": "sudo apt install ghostscript",
        "fedora": "sudo dnf install ghostscript",
        "arch": "sudo pacman -S ghostscript",
        "macos": "brew install ghostscript",
        "windows": "winget install ArtifexSoftware.GhostScript   [belum diuji]  — atau isi path gswin64c.exe manual",
    },
    "tesseract": {
        "debian": "sudo apt install tesseract-ocr tesseract-ocr-ind tesseract-ocr-eng",
        "fedora": "sudo dnf install tesseract tesseract-langpack-ind tesseract-langpack-eng",
        "arch": "sudo pacman -S tesseract tesseract-data-ind tesseract-data-eng",
        "macos": "brew install tesseract tesseract-lang",
        "windows": "winget install UB-Mannheim.TesseractOCR   [belum diuji]  — pilih data bahasa saat instal",
    },
    "ocrmypdf": {k: PIP_HINT.format(pkg="ocrmypdf") for k in ("debian", "fedora", "arch", "macos", "windows", "linux")},
    "recode_pdf": {k: PIP_HINT.format(pkg="archive-pdf-tools") for k in ("debian", "fedora", "arch", "macos", "windows", "linux")},
    "jbig2": {
        "debian": "sudo apt install jbig2   (biner bernama `jbig2`)",
        "fedora": "sudo dnf install jbig2enc   (jika tidak ada di repo: bangun dari github.com/agl/jbig2enc)",
        "arch": "paket jbig2enc dari AUR",
        "macos": "brew install jbig2enc",
        "windows": "Tidak ada biner resmi (setahu kami). Tanpa ini mask memakai CCITT — hasil lebih besar tapi tetap jalan.",
    },
    "pngquant": {
        "debian": "sudo apt install pngquant",
        "fedora": "sudo dnf install pngquant",
        "arch": "sudo pacman -S pngquant",
        "macos": "brew install pngquant",
        "windows": "Unduh dari pngquant.org lalu taruh di PATH (atau isi path manual)   [belum diuji]",
    },
    "unpaper": {
        "debian": "sudo apt install unpaper",
        "fedora": "sudo dnf install unpaper",
        "arch": "sudo pacman -S unpaper",
        "macos": "brew install unpaper",
        "windows": "Sulit didapat di Windows; opsi Clean akan dinonaktifkan.",
    },
    "jpegoptim": {
        "debian": "sudo apt install jpegoptim",
        "fedora": "sudo dnf install jpegoptim",
        "arch": "sudo pacman -S jpegoptim",
        "macos": "brew install jpegoptim",
        "windows": "Hanya perlu bila memilih format gambar MRC = JPEG; unduh manual lalu isi path.",
    },
}


def install_hint(tool_id: str, family: Optional[str] = None) -> str:
    family = family or os_family()
    table = HINTS.get(tool_id, {})
    return table.get(family) or table.get("linux") or "Gunakan package manager distro Anda."
