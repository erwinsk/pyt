# -*- coding: utf-8 -*-
"""Uji inti profil kompresi (Tingkat 1: Tujuan) — tanpa Qt, tanpa alat eksternal."""
import json

import pytest

from core import profiles as P
from core.engines import ENGINES, get_engine
from core.settings import Settings


@pytest.fixture()
def store(tmp_path):
    return P.ProfileStore(Settings(tmp_path / "s.json"))


def reload(store):
    return P.ProfileStore(Settings(store.settings.path))


# ------------------------------------------------------------------ profil bawaan
def test_builtin_definitions_are_valid_and_unique():
    ids, names = set(), set()
    for p in P.BUILTIN:
        eng = get_engine(p.engine)
        keys = {o.key for o in eng.options}
        assert set(p.values) <= keys, p.id
        assert not set(p.values) & (P.PREFERENCE_KEYS | P.RAW_ARG_KEYS), p.id
        norm = eng.options.normalize(p.values)
        assert all(norm[k] == v for k, v in p.values.items()), p.id      # tidak ada yang di-clamp
        assert p.category in P.CATEGORY_LABELS and p.builtin
        assert p.id not in ids and p.name.lower() not in names
        ids.add(p.id)
        names.add(p.name.lower())


def test_every_builtin_matches_only_itself(store):
    for p in store.builtin():
        m = store.match(p.engine, store.resolve(p))
        assert m is not None and m.id == p.id, p.id


def test_ghostscript_profiles_never_use_preset_jpeg_quality():
    """Regresi: jpeg_quality=0 menyerahkan ke AutoFilter Ghostscript yang pada uji scan 300 ppi
    menyandikan halaman sebagai Flate lossless (+74% lebih besar dari sumber)."""
    gs = [p for p in P.BUILTIN if p.engine == "ghostscript"]
    assert gs
    for p in gs:
        assert p.values.get("jpeg_quality", 0) > 0, p.id


def test_mrc_rate_direction_is_documented_in_ordering():
    """Regresi: bg_rate/fg_rate adalah RASIO kompresi (N:1), makin tinggi makin KECIL file.
    'Terkecil' pernah salah arah (rasio lebih rendah dari bawaan -> file lebih besar)."""
    d = get_engine("mrc").options.defaults()
    by = {p.id: p for p in P.BUILTIN}
    small, arsip = by["scan_terkecil"].values, by["scan_arsip"].values
    assert small["bg_rate"] > d["bg_rate"] and small["fg_rate"] > d["fg_rate"]
    assert arsip["bg_rate"] < d["bg_rate"] and arsip["fg_rate"] < d["fg_rate"]


def test_engine_defaults_are_recommended_profiles(store):
    assert store.match("mrc", get_engine("mrc").options.defaults()).id == "scan_seimbang"
    # bawaan Ghostscript kini aman (JPEG dipaksa) dan sama dengan profil 'Ringan'
    assert store.match("ghostscript", get_engine("ghostscript").options.defaults()).id == "digital_ringan"


def test_ghostscript_default_forces_jpeg_instead_of_autofilter():
    """Regresi: bawaan jpeg_quality=0 menyerahkan filter ke AutoFilter Ghostscript yang pada uji scan
    300 ppi memilih Flate lossless untuk sebagian halaman (3320 KB -> 5792 KB, +74%)."""
    eng = get_engine("ghostscript")
    d = eng.options.defaults()
    assert d["jpeg_quality"] > 0
    cmd = eng.build_cmd(["gs"], "in.pdf", "out.pdf", d)
    assert "-dAutoFilterColorImages=false" in cmd and "-dColorImageFilter=/DCTEncode" in cmd
    # nilai 0 tetap bisa dipilih sengaja (perilaku otomatis Ghostscript), tanpa memaksa filter
    cmd0 = eng.build_cmd(["gs"], "in.pdf", "out.pdf", dict(d, jpeg_quality=0))
    assert "-dAutoFilterColorImages=false" not in cmd0


# ------------------------------------------------------------ kepemilikan nilai
def test_resolve_resets_owned_and_keeps_preferences(store):
    eng = get_engine("ocrmypdf")
    cur = eng.options.defaults()
    cur.update(languages="ind+eng", title="Judul saya", deskew=True, optimize="3")
    v = store.resolve(store.get("ocr_saja"), cur)
    assert v["languages"] == "ind+eng" and v["title"] == "Judul saya"      # per-dokumen: dipertahankan
    assert v["deskew"] is False and v["optimize"] == "1" and v["mode"] == "skip"   # milik profil


def test_resolve_is_independent_of_previous_owned_values(store):
    eng = get_engine("mrc")
    a = eng.options.defaults()
    b = dict(a, bg_rate=4000, denoise="bregman", bg_downsample=7)
    p = store.get("scan_terkecil")
    assert store.resolve(p, a) == store.resolve(p, b)                      # tidak bergantung riwayat


def test_match_ignores_preference_keys_only(store):
    p = store.get("scan_terkecil")
    v = store.resolve(p)
    assert store.match("mrc", dict(v, languages="xx+yy", title="t", threads=8)).id == p.id
    assert store.match("mrc", dict(v, bg_rate=v["bg_rate"] + 1)) is None


# ---------------------------------------------------------------- profil pengguna
def test_user_profile_lifecycle(store):
    v = store.resolve(store.get("scan_terkecil"))
    v["bg_rate"] = 1000
    p = store.save_user("  Punya   saya\t", "mrc", v)
    assert p.name == "Punya saya" and not p.builtin and p.category == "user"
    assert store.match("mrc", v).id == p.id
    assert [x.id for x in reload(store).user()] == [p.id]                  # persisten
    assert "languages" not in p.values and "title" not in p.values        # bukan milik profil
    v2 = dict(v, bg_rate=1100)
    p2 = store.save_user("punya SAYA", "mrc", v2, overwrite=True)
    assert p2.id == p.id and len(store.user()) == 1
    assert store.get(p.id).values["bg_rate"] == 1100
    assert store.delete_user(p.id) is True and store.delete_user(p.id) is False
    assert store.user() == [] and store.match("mrc", v2) is None


@pytest.mark.parametrize("name, expect", [
    ("", "kosong"), ("   ", "kosong"),
    ("Scan, cepat - tanpa OCR", "bawaan"),
    ("scan, CEPAT - tanpa ocr", "bawaan"),
])
def test_user_profile_rejects_bad_names(store, name, expect):
    v = dict(get_engine("full_image").options.defaults(), quality=33)
    with pytest.raises(P.ProfileError, match=expect):
        store.save_user(name, "full_image", v)


def test_user_profile_rejects_duplicates(store):
    v = dict(get_engine("mrc").options.defaults(), bg_rate=1500)
    store.save_user("A", "mrc", v)
    with pytest.raises(P.ProfileError, match="sudah ada"):
        store.save_user("a", "mrc", dict(v, bg_rate=1600))                  # nama sama, tanpa overwrite
    with pytest.raises(P.ProfileError, match="sudah sama dengan profil 'A'"):
        store.save_user("B", "mrc", v)                                      # isi sama
    with pytest.raises(P.ProfileError, match="Terkecil"):
        store.save_user("C", "mrc", store.resolve(store.get("scan_terkecil")))


def test_name_is_sanitized_and_truncated(store):
    v = dict(get_engine("full_image").options.defaults(), quality=21)
    p = store.save_user("x\x00y\n" + "z" * 200, "full_image", v)
    assert "\x00" not in p.name and "\n" not in p.name and len(p.name) == P.MAX_NAME_LEN


def test_corrupt_stored_entries_are_skipped(store):
    store.settings.set("profiles.user", [
        "bukan dict", {"id": 5}, {"id": "u1", "name": "ok", "engine": "TIDAK ADA", "values": {}},
        {"id": "u2", "name": "   ", "engine": "mrc", "values": {}},
        {"id": "u3", "name": "Sehat", "engine": "full_image", "values": {"quality": "bukan angka", "dpi": 9999}},
    ])
    users = store.user()
    assert [u.id for u in users] == ["u3"]
    assert users[0].values["quality"] == 60 and users[0].values["dpi"] == 600   # dinormalkan
    store.settings.set("profiles.user", "rusak")
    assert store.user() == []


# --------------------------------------------------------------- ekspor / impor
def test_export_import_roundtrip(store, tmp_path):
    v = dict(get_engine("mrc").options.defaults(), bg_rate=1500, denoise="bregman")
    store.save_user("Dokumen kantor", "mrc", v, description="untuk arsip kantor")
    path = tmp_path / "p.json"
    assert store.export_user(path) == 1
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == P.FORMAT_NAME and data["version"] == P.FORMAT_VERSION
    assert "id" not in data["profiles"][0]
    other = P.ProfileStore(Settings(tmp_path / "other.json"))
    rep = other.import_file(path)
    assert rep.added == ["Dokumen kantor"] and not rep.skipped and not rep.sanitized
    got = other.user()[0]
    assert got.description == "untuk arsip kantor"
    assert other.match("mrc", other.resolve(got)).id == got.id
    # impor ulang = duplikat -> dilewati, tidak menggandakan
    rep2 = other.import_file(path)
    assert not rep2.added and len(other.user()) == 1 and "sama dengan profil" in rep2.skipped[0][1]


def test_export_without_user_profiles_explains(store, tmp_path):
    with pytest.raises(P.ProfileError, match="Belum ada profil"):
        store.export_user(tmp_path / "x.json")
    assert not (tmp_path / "x.json").exists()


def _doc(*items):
    return {"format": P.FORMAT_NAME, "version": 1, "profiles": list(items)}


def test_import_strips_command_line_options(store):
    """Berkas profil dari pihak lain tidak boleh membawa teks yang ditempel ke baris perintah
    (mis. argumen tambahan Ghostscript yang dapat menjalankan PostScript)."""
    evil = "-dNOSAFER -c 'x'"
    # satu nilai tak-berbahaya per metode agar profil tidak dianggap duplikat bawaan
    benign = {"ghostscript": {"dpi": 123}, "ocrmypdf": {"jpeg_quality": 77}, "mrc": {"bg_rate": 1234}}
    items = []
    for e in ENGINES:
        raw = [o.key for o in e.options if o.key in P.RAW_ARG_KEYS]
        if raw:
            items.append({"name": f"E-{e.id}", "engine": e.id,
                          "values": dict({k: evil for k in raw}, **benign[e.id])})
    assert {i["engine"] for i in items} == {"ghostscript", "ocrmypdf", "mrc"}
    rep = store.import_data(_doc(*items))
    assert len(rep.added) == 3 and not rep.skipped
    assert sum("demi keamanan" in why for _, why in rep.sanitized) >= 3
    for p in store.user():
        vals = get_engine(p.engine).options.normalize(p.values)
        for k in P.RAW_ARG_KEYS & set(vals):
            assert vals[k] == "", (p.engine, k)
        assert evil not in json.dumps(p.values)
    assert store.user()[0].values["dpi"] == 123          # nilai aman tetap diimpor


def test_import_type_checking_is_strict(store):
    rep = store.import_data(_doc(
        {"name": "T", "engine": "ocrmypdf",
         "values": {"deskew": "false", "optimize": "9", "jpeg_quality": "70", "oversample": True, "rotate": False}}))
    p = store.user()[0]
    d = get_engine("ocrmypdf").options.defaults()
    assert p.values["deskew"] is d["deskew"]            # 'false' (string) TIDAK ditafsir True lalu diterima
    assert p.values["optimize"] == d["optimize"] and p.values["jpeg_quality"] == d["jpeg_quality"]
    assert p.values["oversample"] == d["oversample"]    # bool bukan angka
    assert len(rep.sanitized) == 4


def test_import_skips_and_renames(store):
    v = dict(get_engine("full_image").options.defaults(), quality=44)
    store.save_user("Sama", "full_image", v)
    rep = store.import_data(_doc(
        {"name": "Sama", "engine": "full_image", "values": {"quality": 45}},          # bentrok nama -> (2)
        {"name": "Scan, cepat - tanpa OCR", "engine": "full_image", "values": {"quality": 46}},
        {"name": "Asing", "engine": "rm -rf /", "values": {}},
        {"name": "", "engine": "mrc", "values": {}},
        {"name": "TanpaNilai", "engine": "mrc", "values": "x"},
        "bukan objek",
        {"name": "Bahasa", "engine": "mrc", "values": {"bg_rate": 2000, "languages": "zzz", "title": "T"}},
    ))
    names = [p.name for p in store.user()]
    assert "Sama (2)" in names and "Scan, cepat - tanpa OCR (2)" in names and "Bahasa" in names
    assert len(rep.skipped) == 4 and len(rep.renamed) == 2
    bahasa = next(p for p in store.user() if p.name == "Bahasa")
    assert "languages" not in bahasa.values and "title" not in bahasa.values


@pytest.mark.parametrize("data, msg", [
    ([], "Bukan berkas profil"), ("x", "Bukan berkas profil"), (None, "Bukan berkas profil"),
    ({"format": "lain", "version": 1, "profiles": []}, "Bukan berkas profil"),
    ({"format": P.FORMAT_NAME, "version": 99, "profiles": []}, "tidak didukung"),
    ({"format": P.FORMAT_NAME, "version": True, "profiles": []}, "tidak didukung"),
    ({"format": P.FORMAT_NAME, "version": 1}, "daftar 'profiles'"),
    ({"format": P.FORMAT_NAME, "version": 1, "profiles": {}}, "daftar 'profiles'"),
    ({"format": P.FORMAT_NAME, "version": 1, "profiles": [{}] * (P.MAX_IMPORT_PROFILES + 1)}, "Terlalu banyak"),
])
def test_import_rejects_malformed_documents(store, data, msg):
    with pytest.raises(P.ProfileError, match=msg):
        store.import_data(data)
    assert store.user() == []


def test_import_file_errors(store, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ bukan json", encoding="utf-8")
    with pytest.raises(P.ProfileError, match="JSON"):
        store.import_file(bad)
    big = tmp_path / "big.json"
    big.write_bytes(b" " * (P.MAX_IMPORT_BYTES + 1))
    with pytest.raises(P.ProfileError, match="terlalu besar"):
        store.import_file(big)
    with pytest.raises(P.ProfileError, match="tidak bisa dibaca"):
        store.import_file(tmp_path / "tidak-ada.json")
    assert store.user() == []


def test_failed_import_does_not_touch_existing_profiles(store):
    v = dict(get_engine("full_image").options.defaults(), quality=12)
    store.save_user("Punya", "full_image", v)
    with pytest.raises(P.ProfileError):
        store.import_data({"format": "salah"})
    assert [p.name for p in store.user()] == ["Punya"]
