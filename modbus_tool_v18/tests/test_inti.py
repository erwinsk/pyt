"""Uji logika murni (tanpa GUI & tanpa perangkat): encode/decode, validasi, pengelompokan tag."""
import pytest

from modbus_app.inti import (
    DAFTAR_ENCODING, JENIS_REGISTER, atur_retries_client, dapatkan_jumlah_word, dekode_register_multi,
    enkode_nilai_ke_register, normalisasi_tag, olah_nilai_tag, parse_nilai_bool,
    peringatan_jumlah_register, pulihkan_retries_client, susun_blok_tag, terjemahkan_respon_modbus,
)

NILAI_UJI = {
    "Mentah (16-bit UINT)": ("1234", 1234.0),
    "Signed 16-bit INT": ("-1234", -1234.0),
    "32-bit FLOAT (ABCD - Big Endian)": ("3.5", 3.5),
    "32-bit FLOAT (CDAB - Word Swap)": ("-12.25", -12.25),
    "32-bit FLOAT (BADC - Byte Swap)": ("100.125", 100.125),
    "32-bit FLOAT (DCBA - Little Endian)": ("0.5", 0.5),
    "32-bit INT Signed (ABCD - Big Endian)": ("-123456", -123456.0),
    "32-bit INT Signed (CDAB - Word Swap)": ("2000000", 2000000.0),
    "64-bit DOUBLE (ABCDEFGH - Big Endian)": ("3.141592", 3.141592),
    "64-bit DOUBLE (HGFEDCBA - Little Endian)": ("-2.718281", -2.718281),
}


def test_semua_encoding_tercakup_oleh_uji():
    assert set(NILAI_UJI) == set(DAFTAR_ENCODING)


@pytest.mark.parametrize("encoding", DAFTAR_ENCODING)
def test_encode_decode_bolak_balik(encoding):
    teks, diharapkan = NILAI_UJI[encoding]
    reg = enkode_nilai_ke_register(teks, encoding)
    assert len(reg) == dapatkan_jumlah_word(encoding)
    assert all(0 <= r <= 0xFFFF for r in reg)
    assert float(dekode_register_multi(reg, encoding)) == pytest.approx(diharapkan, abs=1e-4)


def test_decode_float_pi_abcd():
    assert dekode_register_multi([0x4048, 0xF5C3], "32-bit FLOAT (ABCD - Big Endian)") == "3.1400"


def test_urutan_byte_berbeda_menghasilkan_register_berbeda():
    hasil = {tuple(enkode_nilai_ke_register("3.14", e)) for e in DAFTAR_ENCODING if "FLOAT" in e}
    assert len(hasil) == 4


def test_decode_register_kurang_dari_kebutuhan():
    assert dekode_register_multi([1], "32-bit FLOAT (ABCD - Big Endian)") == "-"


@pytest.mark.parametrize("nilai", ["70000", "-1"])
def test_uint16_menolak_di_luar_rentang(nilai):
    with pytest.raises(ValueError):
        enkode_nilai_ke_register(nilai, "Mentah (16-bit UINT)")


def test_int16_dan_int32_menolak_di_luar_rentang():
    with pytest.raises(ValueError):
        enkode_nilai_ke_register("40000", "Signed 16-bit INT")
    with pytest.raises(ValueError):
        enkode_nilai_ke_register("3000000000", "32-bit INT Signed (ABCD - Big Endian)")


def test_encode_bukan_angka():
    with pytest.raises(ValueError):
        enkode_nilai_ke_register("abc", "Mentah (16-bit UINT)")


@pytest.mark.parametrize("teks,hasil", [("1", True), ("TRUE", True), (" on ", True), ("ya", True),
                                        ("0", False), ("False", False), ("off", False), ("no", False)])
def test_parse_bool_valid(teks, hasil):
    assert parse_nilai_bool(teks) is hasil


@pytest.mark.parametrize("teks", ["2", "", "maybe", "yess"])
def test_parse_bool_ditolak(teks):
    with pytest.raises(ValueError):
        parse_nilai_bool(teks)


def test_peringatan_jumlah_register():
    f32 = "32-bit FLOAT (ABCD - Big Endian)"
    assert peringatan_jumlah_register("Holding", 4, f32) is None
    assert "kelipatan 2" in peringatan_jumlah_register("Input", 5, f32)
    assert "kelipatan 4" in peringatan_jumlah_register("Holding", 6, "64-bit DOUBLE (ABCDEFGH - Big Endian)")
    assert peringatan_jumlah_register("Coil", 5, f32) is None
    assert peringatan_jumlah_register("Holding", 5, "Mentah (16-bit UINT)") is None


def test_normalisasi_tag_valid_dan_default():
    tag = normalisasi_tag({"nama": " Suhu ", "slave_id": "3", "tipe_reg": "Input", "alamat": "40",
                           "encoding": DAFTAR_ENCODING[2], "skala": "0.1", "offset": "-2"})
    assert tag == {"nama": "Suhu", "slave_id": 3, "tipe_reg": "Input", "alamat": 40,
                   "encoding": DAFTAR_ENCODING[2], "skala": 0.1, "offset": -2.0}
    minimal = normalisasi_tag({"nama": "X"})
    assert minimal["slave_id"] == 1 and minimal["tipe_reg"] == "Holding" and minimal["skala"] == 1.0


@pytest.mark.parametrize("baris", [
    {"nama": ""}, {"nama": "a", "tipe_reg": "Aneh"}, {"nama": "a", "encoding": "xyz"},
    {"nama": "a", "slave_id": "300"}, {"nama": "a", "alamat": "70000"}, {"nama": "a", "alamat": "abc"},
])
def test_normalisasi_tag_ditolak(baris):
    with pytest.raises(ValueError):
        normalisasi_tag(baris)


def _tag(nama, alamat, enc="Mentah (16-bit UINT)", slave=1, tipe="Holding"):
    return {"nama": nama, "slave_id": slave, "tipe_reg": tipe, "alamat": alamat, "encoding": enc}


def test_blok_tag_menggabungkan_yang_bersambung():
    f32 = "32-bit FLOAT (ABCD - Big Endian)"
    blok = susun_blok_tag([_tag("A", 100, f32), _tag("B", 102), _tag("C", 200)])
    assert [(b["mulai"], b["akhir"]) for b in blok] == [(100, 103), (200, 201)]
    assert [m[0] for m in blok[0]["anggota"]] == [0, 1]


def test_blok_tag_tidak_menggabung_jika_ada_celah_atau_beda_slave_atau_tipe():
    blok = susun_blok_tag([_tag("A", 10), _tag("B", 12), _tag("C", 11, slave=2), _tag("D", 11, tipe="Input")])
    assert len(blok) == 4


def test_blok_tag_duplikat_dan_bertumpuk_digabung():
    blok = susun_blok_tag([_tag("A", 10), _tag("B", 10), _tag("C", 11, "32-bit FLOAT (ABCD - Big Endian)")])
    assert len(blok) == 1 and (blok[0]["mulai"], blok[0]["akhir"]) == (10, 13)


def test_blok_tag_dibatasi_maks_register():
    tags = [_tag(f"T{i}", i) for i in range(300)]
    blok = susun_blok_tag(tags, maks_register=125)
    assert all(b["akhir"] - b["mulai"] <= 125 for b in blok)
    assert sum(len(b["anggota"]) for b in blok) == 300


def test_blok_tag_urutan_indeks_asli_terjaga():
    tags = [_tag("Z", 50), _tag("A", 10), _tag("M", 11)]
    blok = susun_blok_tag(tags)
    semua = sorted(m[0] for b in blok for m in b["anggota"])
    assert semua == [0, 1, 2]


def test_olah_nilai_tag_skala_offset():
    tag = {**_tag("T", 0), "skala": 0.1, "offset": 1.0}
    assert olah_nilai_tag(tag, [50])["nilai_akhir"] == "6.0000"
    float_tag = {**_tag("F", 0, "32-bit FLOAT (ABCD - Big Endian)"), "skala": 2.0, "offset": 0.0}
    assert olah_nilai_tag(float_tag, [0x4048, 0xF5C3])["nilai_akhir"] == "6.2800"


def test_olah_nilai_tag_coil():
    hasil = olah_nilai_tag(_tag("C", 1, tipe="Coil"), [True])
    assert hasil["nilai_akhir"] == "True" and hasil["status"] == "OK"


def test_terjemahkan_respon_modbus():
    class Res:
        exception_code = 2
    assert "Illegal Data Address" in terjemahkan_respon_modbus(Res())

    class Lain:
        exception_code = 99
        def __str__(self):
            return "mentah"
    assert terjemahkan_respon_modbus(Lain()) == "mentah"


def test_atur_dan_pulihkan_retries():
    class Transaksi:
        retries = 3

    class FakeClient:
        retries = 3
        transaction = Transaksi()

    c = FakeClient()
    simpanan = atur_retries_client(c, 0)
    assert c.retries == 0 and c.transaction.retries == 0
    pulihkan_retries_client(simpanan)
    assert c.retries == 3 and c.transaction.retries == 3
    assert atur_retries_client(None, 0) == []


def test_jenis_register_konsisten():
    assert JENIS_REGISTER == ["Holding", "Input", "Coil", "Discrete Input"]
