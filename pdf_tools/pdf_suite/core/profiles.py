# -*- coding: utf-8 -*-
"""Tingkat 1 — TUJUAN (profil kompresi).

Tiga tingkat pilihan di aplikasi:
  1. Tujuan   : profil siap pakai ("Scan, bisa dicari - Terkecil", "Dokumen digital - Ringan", ...)
  2. Metode   : engine (Ghostscript / Full Image / OCRmyPDF / MRC)
  3. Parameter: panel opsi tiap engine (dibangun dari skema)

Sebuah profil hanyalah pilihan metode + nilai parameter. Ketiga tingkat selalu konsisten:
mengubah metode atau parameter apa pun membuat tampilan Tujuan otomatis berpindah ke
"Kustom" (atau ke profil lain bila nilainya kebetulan sama persis).

Aturan kepemilikan nilai:
  * PREFERENCE_KEYS  : opsi per-dokumen / mesin (bahasa OCR, metadata, jumlah thread, ...).
                       TIDAK dimiliki profil: tidak diubah saat profil diterapkan dan tidak
                       dihitung saat mencocokkan. Mengganti bahasa OCR tidak membuat profil
                       berubah jadi "Kustom".
  * semua opsi lain  : dimiliki profil. Saat diterapkan, yang tidak disebut profil kembali ke
                       nilai bawaan engine, sehingga hasil tidak bergantung pada riwayat klik.
  * RAW_ARG_KEYS     : teks bebas yang ditempel ke baris perintah (mis. argumen tambahan
                       Ghostscript, yang dapat menjalankan PostScript). Tidak pernah diimpor
                       dari berkas profil orang lain.
"""
import json
import math
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import schema as S
from .engines import ENGINES, get_engine

CUSTOM_ID = "__custom__"
FORMAT_NAME = "pdf-tools-suite-profiles"
FORMAT_VERSION = 1
MAX_IMPORT_BYTES = 1_000_000
MAX_IMPORT_PROFILES = 200
MAX_NAME_LEN = 60
MAX_DESC_LEN = 400
MAX_TEXT_VALUE_LEN = 500

PREFERENCE_KEYS = frozenset({
    "languages", "psm", "oem", "dpi_override", "skip_big", "hq_pages",
    "title", "author", "subject", "keywords", "language_meta",
    "jobs", "threads", "tesseract_timeout",
})
RAW_ARG_KEYS = frozenset({
    "extra_args", "extra_ocr", "extra_compress",
    "bg_flags", "fg_flags", "hq_bg_flags", "hq_fg_flags",
})

CATEGORY_LABELS = {
    "scan": "Scan (gambar hasil pindai)",
    "digital": "Dokumen digital (teks asli)",
    "ocr": "Tambah teks OCR",
    "user": "Profil milik saya",
}


class ProfileError(Exception):
    """Kesalahan yang aman ditampilkan apa adanya kepada pengguna."""


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    description: str
    engine: str
    values: Dict[str, Any]
    category: str
    builtin: bool = True


# ---------------------------------------------------------------------------
# Profil bawaan
# ---------------------------------------------------------------------------
# Catatan desain: profil berbasis Ghostscript SELALU menetapkan jpeg_quality > 0. Nilai 0
# ("ikut preset") menyerahkan pemilihan ke AutoFilter Ghostscript yang pada uji scan 300 ppi
# menyandikan sebagian halaman sebagai Flate lossless dan membuat hasil JAUH lebih besar.
# bg_rate / fg_rate adalah RASIO kompresi (N:1): nilai LEBIH TINGGI = file LEBIH KECIL, mutu lebih rendah.
# (Terbukti salah arah saat diukur: rasio 300/400 menghasilkan file lebih BESAR dari bawaan 500/750.)
BUILTIN: List[Profile] = [
    Profile(
        "scan_seimbang", "Scan, bisa dicari - Seimbang",
        "Untuk PDF hasil pindai (gambar saja). Halaman dipecah menjadi mask teks, latar, dan "
        "warna (MRC) lalu diberi teks OCR sehingga bisa dicari. Teks tetap tajam, ukuran kecil. "
        "Pilihan awal yang disarankan untuk scan. Butuh waktu proses lebih lama.",
        "mrc", {}, "scan"),
    Profile(
        "scan_terkecil", "Scan, bisa dicari - Terkecil",
        "Seperti 'Seimbang' tetapi latar dan warna dikompresi lebih kuat. Ukuran paling kecil; "
        "foto atau noda di dalam halaman tampak lebih lembut.",
        "mrc", {"bg_downsample": 3, "bg_rate": 900, "fg_rate": 1200}, "scan"),
    Profile(
        "scan_arsip", "Scan, bisa dicari - Kualitas tinggi (arsip)",
        "Seperti 'Seimbang' tetapi latar dan warna dikompresi lebih ringan dan mask tidak "
        "dibersihkan. Lebih besar, tampilan lebih setia ke asli. Cocok untuk arsip.",
        "mrc", {"denoise": "none", "bg_downsample": 1, "bg_rate": 150, "fg_rate": 200}, "scan"),
    Profile(
        "scan_cepat", "Scan, cepat - tanpa OCR",
        "Setiap halaman dijadikan satu gambar JPEG. Sangat cepat dan tanpa alat eksternal, tetapi "
        "teks tidak bisa dicari dan teks tajam tidak sebaik MRC.",
        "full_image", {}, "scan"),
    Profile(
        "digital_ringan", "Dokumen digital - Ringan (teks tetap vektor)",
        "Untuk PDF buatan aplikasi (Word, laporan, dsb.). Hanya gambar di dalamnya yang "
        "dikecilkan; teks tetap vektor sehingga tajam dan bisa disalin.",
        "ghostscript", {"preset": "ebook", "dpi": 150, "jpeg_quality": 70}, "digital"),
    Profile(
        "digital_email", "Dokumen digital - Email / Web (kecil)",
        "Seperti 'Ringan' tetapi gambar dikecilkan lebih jauh untuk dikirim lewat email atau "
        "dibaca di layar.",
        "ghostscript", {"preset": "screen", "dpi": 100, "jpeg_quality": 55}, "digital"),
    Profile(
        "ocr_saja", "Beri teks OCR - kualitas gambar dijaga",
        "Menambahkan lapisan teks yang bisa dicari ke scan tanpa mengubah tampilan gambar "
        "(tanpa kompresi bermasalah). Halaman yang sudah punya teks dilewati.",
        "ocrmypdf", {"mode": "skip", "optimize": "1", "deskew": False, "rotate": False,
                     "output_type": "pdf"}, "ocr"),
]

_OWNED_CACHE: Dict[str, Tuple[str, ...]] = {}


def owned_keys(engine_id: str) -> Tuple[str, ...]:
    """Kunci opsi yang dimiliki profil untuk engine tsb (semua kecuali PREFERENCE_KEYS)."""
    if engine_id not in _OWNED_CACHE:
        eng = get_engine(engine_id)
        _OWNED_CACHE[engine_id] = tuple(o.key for o in eng.options if o.key not in PREFERENCE_KEYS)
    return _OWNED_CACHE[engine_id]


def _validate_builtin():
    """Gagal keras saat import bila definisi bawaan salah (kunci tak dikenal, nilai di luar
    rentang, id/nama ganda). Lebih baik gagal di uji daripada profil diam-diam keliru."""
    ids, names = set(), set()
    for p in BUILTIN:
        eng = get_engine(p.engine)
        keys = {o.key for o in eng.options}
        bad = set(p.values) - keys
        if bad:
            raise ValueError(f"Profil {p.id}: kunci tak dikenal {sorted(bad)}")
        forbidden = set(p.values) & (PREFERENCE_KEYS | RAW_ARG_KEYS)
        if forbidden:
            raise ValueError(f"Profil {p.id}: kunci tak boleh dimiliki profil {sorted(forbidden)}")
        norm = eng.options.normalize(p.values)
        for k, v in p.values.items():
            if norm[k] != v:
                raise ValueError(f"Profil {p.id}: nilai {k}={v!r} tidak valid (jadi {norm[k]!r})")
        if p.id in ids or p.name.lower() in names:
            raise ValueError(f"Profil ganda: {p.id}")
        ids.add(p.id)
        names.add(p.name.lower())


_validate_builtin()


# ---------------------------------------------------------------------------
# Util
# ---------------------------------------------------------------------------
def clean_text(value: Any, limit: int) -> str:
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(value))
    return re.sub(r"\s+", " ", s).strip()[:limit]


def _type_ok(opt, v: Any) -> bool:
    """Pemeriksaan tipe ketat untuk data impor (OptionSet.normalize terlalu longgar:
    bool('false') bernilai True)."""
    if opt.kind == S.BOOL:
        return isinstance(v, bool)
    if opt.kind in (S.INT, S.FLOAT):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    if opt.kind == S.CHOICE:
        return v in [c[0] for c in opt.choices]
    return isinstance(v, str) and len(v) <= MAX_TEXT_VALUE_LEN


@dataclass
class ImportReport:
    added: List[str] = field(default_factory=list)
    renamed: List[Tuple[str, str]] = field(default_factory=list)
    skipped: List[Tuple[str, str]] = field(default_factory=list)
    sanitized: List[Tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"{len(self.added)} profil ditambahkan."]
        if self.renamed:
            lines.append("Diganti nama karena bentrok: " +
                         "; ".join(f"'{a}' -> '{b}'" for a, b in self.renamed))
        if self.sanitized:
            lines.append("Disesuaikan:")
            lines += [f"  - {n}: {why}" for n, why in self.sanitized]
        if self.skipped:
            lines.append("Dilewati:")
            lines += [f"  - {n}: {why}" for n, why in self.skipped]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Penyimpanan
# ---------------------------------------------------------------------------
class ProfileStore:
    """Profil bawaan + profil milik pengguna (disimpan di Settings, kunci 'profiles.user')."""

    def __init__(self, settings):
        self.settings = settings

    # ---- baca ----
    def builtin(self) -> List[Profile]:
        return list(BUILTIN)

    def user(self) -> List[Profile]:
        raw = self.settings.get("profiles.user", [])
        out: List[Profile] = []
        for e in raw if isinstance(raw, list) else []:
            try:
                if not isinstance(e, dict) or not isinstance(e.get("id"), str):
                    continue
                eng = get_engine(str(e["engine"]))
                vals = eng.options.normalize(e.get("values") if isinstance(e.get("values"), dict) else {})
                owned = {k: vals[k] for k in owned_keys(eng.id)}
                name = clean_text(e.get("name", ""), MAX_NAME_LEN)
                if not name:
                    continue
                out.append(Profile(e["id"], name, clean_text(e.get("description", ""), MAX_DESC_LEN),
                                   eng.id, owned, "user", builtin=False))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def all(self) -> List[Profile]:
        return self.builtin() + self.user()

    def get(self, pid: str) -> Optional[Profile]:
        return next((p for p in self.all() if p.id == pid), None)

    def find_by_name(self, name: str) -> Optional[Profile]:
        n = clean_text(name, MAX_NAME_LEN).lower()
        return next((p for p in self.all() if p.name.lower() == n), None)

    # ---- nilai ----
    def resolve(self, profile: Profile, current: Optional[dict] = None) -> dict:
        """Nilai penuh untuk panel opsi saat profil diterapkan. Nilai per-dokumen
        (PREFERENCE_KEYS) dipertahankan dari `current`."""
        eng = get_engine(profile.engine)
        vals = eng.options.defaults()
        vals.update(profile.values)
        for k in PREFERENCE_KEYS:
            if current and k in vals and k in current:
                vals[k] = current[k]
        return eng.options.normalize(vals)

    def signature(self, engine_id: str, values: dict) -> Dict[str, Any]:
        norm = get_engine(engine_id).options.normalize(values)
        return {k: norm[k] for k in owned_keys(engine_id)}

    def profile_signature(self, p: Profile) -> Dict[str, Any]:
        return self.signature(p.engine, self.resolve(p))

    def match(self, engine_id: str, values: dict) -> Optional[Profile]:
        """Profil yang nilainya sama persis dengan `values` (bawaan lebih dulu), atau None."""
        sig = self.signature(engine_id, values)
        for p in self.all():
            if p.engine == engine_id and self.profile_signature(p) == sig:
                return p
        return None

    # ---- tulis ----
    def _write_user(self, profiles: List[Profile]):
        self.settings.set("profiles.user", [
            {"id": p.id, "name": p.name, "description": p.description,
             "engine": p.engine, "values": p.values} for p in profiles])

    def save_user(self, name: str, engine_id: str, values: dict, description: str = "",
                  overwrite: bool = False) -> Profile:
        name = clean_text(name, MAX_NAME_LEN)
        if not name:
            raise ProfileError("Nama profil tidak boleh kosong.")
        eng = get_engine(engine_id)
        sig = self.signature(engine_id, values)
        users = self.user()
        same_name = next((p for p in self.all() if p.name.lower() == name.lower()), None)
        if same_name is not None:
            if same_name.builtin:
                raise ProfileError(f"Nama '{name}' dipakai profil bawaan. Pilih nama lain.")
            if not overwrite:
                raise ProfileError(f"Profil '{name}' sudah ada.")
        dup = self.match(engine_id, values)
        if dup is not None and (same_name is None or dup.id != same_name.id):
            raise ProfileError(f"Pengaturan ini sudah sama dengan profil '{dup.name}'.")
        prof = Profile(same_name.id if same_name else "user:" + uuid.uuid4().hex[:10],
                       name, clean_text(description, MAX_DESC_LEN), eng.id, sig, "user", builtin=False)
        users = [prof if p.id == prof.id else p for p in users]
        if same_name is None:
            users.append(prof)
        self._write_user(users)
        return prof

    def delete_user(self, pid: str) -> bool:
        users = self.user()
        keep = [p for p in users if p.id != pid]
        if len(keep) == len(users):
            return False
        self._write_user(keep)
        return True

    # ---- ekspor / impor ----
    def export_user(self, path) -> int:
        users = self.user()
        if not users:
            raise ProfileError("Belum ada profil milik Anda. Simpan dulu lewat 'Simpan sebagai...'.")
        data = {"format": FORMAT_NAME, "version": FORMAT_VERSION, "profiles": [
            {"name": p.name, "description": p.description, "engine": p.engine, "values": p.values}
            for p in users]}
        tmp = str(path) + ".part"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise ProfileError(f"Gagal menulis berkas: {e}") from e
        return len(users)

    def import_file(self, path) -> ImportReport:
        try:
            if os.path.getsize(path) > MAX_IMPORT_BYTES:
                raise ProfileError("Berkas terlalu besar untuk berkas profil.")
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except ProfileError:
            raise
        except (OSError, ValueError) as e:
            raise ProfileError(f"Berkas tidak bisa dibaca sebagai JSON: {e}") from e
        return self.import_data(data)

    def import_data(self, data: Any) -> ImportReport:
        if not isinstance(data, dict) or data.get("format") != FORMAT_NAME:
            raise ProfileError("Bukan berkas profil PDF Tools Suite.")
        ver = data.get("version")
        if not isinstance(ver, int) or isinstance(ver, bool) or ver < 1 or ver > FORMAT_VERSION:
            raise ProfileError(f"Versi berkas profil ({ver!r}) tidak didukung aplikasi ini.")
        items = data.get("profiles")
        if not isinstance(items, list):
            raise ProfileError("Berkas profil tidak berisi daftar 'profiles'.")
        if len(items) > MAX_IMPORT_PROFILES:
            raise ProfileError(f"Terlalu banyak profil (maksimal {MAX_IMPORT_PROFILES}).")

        rep = ImportReport()
        users = self.user()
        taken = {p.name.lower() for p in self.all()}
        known_sigs = [(p.engine, self.profile_signature(p), p.name) for p in self.all()]
        for item in items:
            label = clean_text(item.get("name", "?"), MAX_NAME_LEN) if isinstance(item, dict) else "?"
            if not isinstance(item, dict):
                rep.skipped.append((label, "entri bukan objek"))
                continue
            name = clean_text(item.get("name", ""), MAX_NAME_LEN)
            if not name:
                rep.skipped.append((label, "nama kosong"))
                continue
            try:
                eng = get_engine(str(item.get("engine", "")))
            except KeyError:
                rep.skipped.append((name, f"metode tidak dikenal: {item.get('engine')!r}"))
                continue
            raw = item.get("values")
            if not isinstance(raw, dict):
                rep.skipped.append((name, "nilai parameter tidak valid"))
                continue
            clean, notes = self._clean_values(eng, raw)
            for n in notes:
                rep.sanitized.append((name, n))
            sig = self.signature(eng.id, clean)
            dup = next((n for (e, s, n) in known_sigs if e == eng.id and s == sig), None)
            if dup is not None:
                rep.skipped.append((name, f"pengaturan sama dengan profil '{dup}'"))
                continue
            final = name
            if final.lower() in taken:
                i = 2
                while f"{name} ({i})".lower() in taken:
                    i += 1
                final = f"{name} ({i})"
                rep.renamed.append((name, final))
            prof = Profile("user:" + uuid.uuid4().hex[:10], final,
                           clean_text(item.get("description", ""), MAX_DESC_LEN),
                           eng.id, sig, "user", builtin=False)
            users.append(prof)
            taken.add(final.lower())
            known_sigs.append((eng.id, sig, final))
            rep.added.append(final)
        if rep.added:
            self._write_user(users)
        return rep

    @staticmethod
    def _clean_values(eng, raw: dict) -> Tuple[dict, List[str]]:
        by_key = {o.key: o for o in eng.options}
        out: Dict[str, Any] = {}
        notes: List[str] = []
        for k, v in raw.items():
            if k not in by_key:
                notes.append(f"opsi tak dikenal '{k}' diabaikan")
            elif k in PREFERENCE_KEYS:
                continue
            elif k in RAW_ARG_KEYS:
                if str(v).strip():
                    notes.append(f"'{k}' dikosongkan: argumen baris perintah tidak diimpor demi keamanan")
            elif not _type_ok(by_key[k], v):
                notes.append(f"nilai '{k}' tidak valid, memakai bawaan")
            else:
                out[k] = v
        return out, notes


def engine_name(engine_id: str) -> str:
    return next((e.name for e in ENGINES if e.id == engine_id), engine_id)
