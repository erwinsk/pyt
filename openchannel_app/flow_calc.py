# -*- coding: utf-8 -*-
"""
flow_calc.py
Modul perhitungan (engine) untuk aplikasi Open Channel Flowmeter Calculator.

Semua fungsi kalkulasi menerima:
    H   : ketinggian air / head, dalam METER
    p   : dict parameter spesifik metode (nilai mentah sesuai satuan pada UI)
    rho : densitas fluida (kg/m3) - disediakan untuk konsistensi antarmuka,
          konversi ke mass flow dilakukan di layer GUI.

Setiap fungsi mengembalikan tuple:
    (Q, area, notes, warnings)
    Q       : debit volumetrik (m3/s) atau None jika gagal
    area    : estimasi luas penampang basah pada seksi kontrol (m2) atau None
              (dipakai untuk estimasi kecepatan aliran v = Q / area)
    notes   : list[str] catatan informatif (mis. nilai Cd terhitung)
    warnings: list[str] peringatan validitas (mis. di luar rentang berlaku)

CATATAN PENTING:
Formula-formula berikut adalah formula empiris standar yang umum dipakai
dalam hidrometri saluran terbuka (open channel hydrometry). Untuk keperluan
pengukuran resmi / legal metering / custody transfer, selalu verifikasi
koefisien (Cd, C, n, kh, dsb.) terhadap standar yang berlaku di
lokasi/industri Anda (mis. ISO 1438, ISO 9826, SNI, atau hasil kalibrasi
lapangan), karena koefisien "default" di sini adalah nilai tipikal/umum.
"""

import math

G = 9.80665  # percepatan gravitasi, m/s2


# =========================================================================
# 1. V-NOTCH WEIR (WEIR SEGITIGA / TRIANGULAR WEIR)
# =========================================================================

def calc_vnotch_standard(H, p, rho):
    """Q = (8/15) * Cd * sqrt(2g) * tan(theta/2) * H^2.5"""
    theta = math.radians(p["theta"])
    Cd = p["Cd"]

    Q = (8.0 / 15.0) * Cd * math.sqrt(2 * G) * math.tan(theta / 2.0) * (H ** 2.5)
    area = (H ** 2) * math.tan(theta / 2.0)  # estimasi luas segitiga aliran
    notes = []
    warnings = []
    if p["theta"] < 20 or p["theta"] > 120:
        warnings.append("Sudut notch di luar rentang umum (20°-120°); tinjau ulang koefisien Cd.")
    return Q, area, notes, warnings


def calc_vnotch_headcorr(H, p, rho):
    """Q = (8/15) * Cd * sqrt(2g) * tan(theta/2) * (H+kh)^2.5
    kh adalah koreksi head kecil (mm) sesuai praktik ISO 1438 / BS 3680.
    Nilai kh bersifat dapat disesuaikan pengguna - konsultasikan referensi/
    standar yang berlaku untuk nilai kh yang tepat sesuai sudut notch.
    """
    theta = math.radians(p["theta"])
    Cd = p["Cd"]
    kh = p["kh"] / 1000.0  # mm -> m

    He = H + kh
    if He <= 0:
        return None, None, [], ["Head efektif (H+kh) <= 0, periksa nilai kh."]

    Q = (8.0 / 15.0) * Cd * math.sqrt(2 * G) * math.tan(theta / 2.0) * (He ** 2.5)
    area = (He ** 2) * math.tan(theta / 2.0)
    notes = [f"Head efektif He = H + kh = {He * 1000:.2f} mm"]
    warnings = []
    if p["theta"] < 20 or p["theta"] > 120:
        warnings.append("Sudut notch di luar rentang umum (20°-120°); tinjau ulang koefisien Cd.")
    return Q, area, notes, warnings


# =========================================================================
# 2. RECTANGULAR WEIR (WEIR PERSEGI / SUPPRESSED & CONTRACTED)
# =========================================================================

def calc_rect_full(H, p, rho):
    """Full-width / suppressed weir (tanpa kontraksi ujung):
    Q = (2/3) * Cd * sqrt(2g) * L * H^1.5
    """
    L = p["L"]
    Cd = p["Cd"]

    Q = (2.0 / 3.0) * Cd * math.sqrt(2 * G) * L * (H ** 1.5)
    area = L * H
    notes = []
    warnings = []
    if H > 0.6 * (p.get("P", 999) if p.get("P") else 999):
        pass  # tidak ada P pada metode ini, dilewati
    return Q, area, notes, warnings


def calc_rect_contracted(H, p, rho):
    """Formula Francis (kontraksi 2 ujung), satuan metrik:
    Q = 1.84 * (L - 0.2H) * H^1.5
    Koefisien 1.84 sudah menyertakan Cd tipikal (~0.623) - formula empiris klasik.
    """
    L = p["L"]
    Le = L - 0.2 * H
    warnings = []
    if Le <= 0:
        return None, None, [], ["L - 0.2H <= 0: lebar efektif negatif, H terlalu besar relatif terhadap L."]

    Q = 1.84 * Le * (H ** 1.5)
    area = Le * H
    notes = [f"Lebar efektif Le = L - 0.2H = {Le:.4f} m"]
    if H > L:
        warnings.append("H > L: rasio di luar rentang tipikal berlakunya formula Francis.")
    return Q, area, notes, warnings


def calc_rect_rehbock(H, p, rho):
    """Formula Rehbock (memperhitungkan tinggi mercu P):
    Cd = 0.602 + 0.083 * (H/P)
    He = H + 0.0011 m
    Q = (2/3) * Cd * sqrt(2g) * L * He^1.5
    Valid untuk 0.03 m <= H <= P, dan H/P <= ~2 (indikatif).
    """
    L = p["L"]
    P = p["P"]
    if P <= 0:
        return None, None, [], ["Tinggi mercu (P) harus lebih besar dari 0."]

    Cd = 0.602 + 0.083 * (H / P)
    He = H + 0.0011
    Q = (2.0 / 3.0) * Cd * math.sqrt(2 * G) * L * (He ** 1.5)
    area = L * He
    notes = [f"Cd terhitung (Rehbock) = {Cd:.4f}"]
    warnings = []
    if H / P > 2:
        warnings.append("H/P > 2: di luar rentang validasi umum formula Rehbock.")
    if H < 0.03:
        warnings.append("H < 3 cm: akurasi weir menurun pada head yang sangat kecil.")
    return Q, area, notes, warnings


# =========================================================================
# 3. TRAPEZOIDAL WEIR (WEIR TRAPESIUM, TERMASUK CIPOLLETTI)
# =========================================================================

def calc_trap_cipolletti(H, p, rho):
    """Cipolletti weir standar: kemiringan sisi tetap horizontal : vertikal = 1 : 4
    (bukan terkait dengan H = tinggi muka air/head yang dipakai di seluruh
    aplikasi ini - "1:4" di sini murni rasio kemiringan sisi trapesium).
    Q = 1.859 * L * H^1.5  (satuan metrik: L,H dalam meter, Q dalam m3/s)
    """
    L = p["L"]
    z = 0.25  # kemiringan sisi standar Cipolletti (horizontal per vertikal, tetap - tidak bisa diubah pengguna)

    Q = 1.859 * L * (H ** 1.5)
    area = H * (L + z * H)
    notes = []
    warnings = []
    if H > L:
        warnings.append("H > L: rasio di luar rentang tipikal desain Cipolletti.")
    return Q, area, notes, warnings


def calc_trap_general(H, p, rho):
    """Trapesium umum = kombinasi bagian rectangular (dasar L) + 2 bagian
    segitiga (kemiringan sisi z, horizontal per vertikal).

    Q = (2/3)*Cd_rect*sqrt(2g)*L*H^1.5 + (8/15)*Cd_tri*sqrt(2g)*z*H^2.5
    """
    L = p["L"]
    z = p["z"]
    Cd_rect = p["Cd_rect"]
    Cd_tri = p["Cd_tri"]

    Q_rect = (2.0 / 3.0) * Cd_rect * math.sqrt(2 * G) * L * (H ** 1.5)
    Q_tri = (8.0 / 15.0) * Cd_tri * math.sqrt(2 * G) * z * (H ** 2.5)
    Q = Q_rect + Q_tri
    area = H * (L + z * H)
    notes = [f"Kontribusi bagian persegi = {Q_rect:.5f} m3/s, bagian segitiga = {Q_tri:.5f} m3/s"]
    warnings = []
    if z <= 0:
        warnings.append("Kemiringan sisi (z) harus lebih besar dari 0 untuk weir trapesium.")
    return Q, area, notes, warnings


# =========================================================================
# 4. PARSHALL FLUME
# =========================================================================

# Tabel koefisien C, n untuk formula aliran bebas (free-flow):
#   Q (cfs) = C * Ha(ft)^n
# W_ft = lebar leher (throat width) dalam feet, dipakai untuk estimasi
# luas penampang (area = W * Ha) dan validasi rentang head.
FT_TO_M = 0.3048
CFS_TO_M3S = 0.0283168

PARSHALL_TABLE = {}

# Flume kecil (throat < 1 ft) - formula spesifik per ukuran
PARSHALL_TABLE["3 in (7.6 cm)"] = dict(C=0.992, n=1.547, W_ft=0.25)
PARSHALL_TABLE["6 in (15.2 cm)"] = dict(C=2.06, n=1.58, W_ft=0.5)
PARSHALL_TABLE["9 in (22.9 cm)"] = dict(C=3.07, n=1.53, W_ft=0.75)

# Flume 1-8 ft - formula umum: C = 4*W, n = 1.522 * W^0.026
for w in [1, 1.5, 2, 3, 4, 5, 6, 7, 8]:
    key = f"{w} ft ({w * FT_TO_M * 100:.1f} cm)"
    PARSHALL_TABLE[key] = dict(C=4.0 * w, n=1.522 * (w ** 0.026), W_ft=w)


def calc_parshall_table(H, p, rho):
    """Aliran bebas Parshall Flume menggunakan tabel koefisien standar.
    H (meter) dikonversi ke Ha (ft), Q(cfs) dihitung lalu dikonversi ke m3/s.
    """
    key = p["W_key"]
    coef = PARSHALL_TABLE[key]
    C, n, W_ft = coef["C"], coef["n"], coef["W_ft"]

    Ha_ft = H / FT_TO_M
    Q_cfs = C * (Ha_ft ** n)
    Q = Q_cfs * CFS_TO_M3S
    area = (W_ft * FT_TO_M) * H  # estimasi kasar: lebar leher x head
    notes = [f"C = {C:.4f}, n = {n:.4f} (Ha dalam ft, Q dalam cfs sebelum konversi)"]
    warnings = []
    if Ha_ft < 0.1 or Ha_ft > 2.0 * W_ft:
        warnings.append("Head (Ha) di luar rentang tipikal untuk ukuran flume ini; "
                         "periksa kembali terhadap tabel rentang operasi resmi.")
    return Q, area, notes, warnings


def calc_parshall_custom(H, p, rho):
    """Koefisien kustom (metrik langsung): Q = C * H^n, H dalam meter,
    Q dalam m3/s. Berguna jika Anda memiliki koefisien hasil kalibrasi
    sendiri atau dari flume/referensi non-standar.
    """
    C = p["C"]
    n = p["n"]

    Q = C * (H ** n)
    area = None  # tidak ada informasi lebar leher pada metode ini
    notes = ["Menggunakan koefisien kustom (satuan metrik langsung: H dalam meter, Q dalam m3/s)."]
    warnings = []
    return Q, area, notes, warnings


# =========================================================================
# DEFINISI STRUKTUR TIPE & METODE UNTUK GUI
# (dibaca secara dinamis oleh main.py untuk membangun form parameter)
# =========================================================================

def _p(key, label, unit="-", default=0.0, minv=-1e9, maxv=1e9, decimals=3, step=0.01, ptype="double", options=None, default_index=0, tooltip=None):
    return dict(key=key, label=label, unit=unit, default=default, minv=minv, maxv=maxv,
                decimals=decimals, step=step, type=ptype, options=options, default_index=default_index,
                tooltip=tooltip)


TYPES = {
    "V-Notch Weir (Weir Segitiga)": {
        "methods": {
            "Standar (Cd Konstan)": {
                "func": calc_vnotch_standard,
                "params": [
                    _p("theta", "Sudut Notch (\u03b8)", unit="\u00b0", default=90.0, minv=10.0, maxv=170.0, decimals=1, step=1.0),
                    _p("Cd", "Koefisien Debit (Cd)", unit="-", default=0.580, minv=0.400, maxv=0.900, decimals=3, step=0.001),
                ],
                "desc": "Q = (8/15)\u00b7Cd\u00b7\u221a(2g)\u00b7tan(\u03b8/2)\u00b7H^2.5"
            },
            "Dengan Koreksi Head (H+kh)": {
                "func": calc_vnotch_headcorr,
                "params": [
                    _p("theta", "Sudut Notch (\u03b8)", unit="\u00b0", default=90.0, minv=10.0, maxv=170.0, decimals=1, step=1.0),
                    _p("Cd", "Koefisien Debit (Cd)", unit="-", default=0.580, minv=0.400, maxv=0.900, decimals=3, step=0.001),
                    _p("kh", "Koreksi Head (kh)", unit="mm", default=1.00, minv=-5.00, maxv=5.00, decimals=2, step=0.10),
                ],
                "desc": "Q = (8/15)\u00b7Cd\u00b7\u221a(2g)\u00b7tan(\u03b8/2)\u00b7(H+kh)^2.5 - koreksi head kecil ala ISO 1438/BS 3680"
            },
        }
    },
    "Rectangular Weir (Weir Persegi)": {
        "methods": {
            "Francis - Full Width (Tanpa Kontraksi)": {
                "func": calc_rect_full,
                "params": [
                    _p("L", "Panjang Mercu (L)", unit="m", default=0.500, minv=0.010, maxv=50.0, decimals=3, step=0.01),
                    _p("Cd", "Koefisien Debit (Cd)", unit="-", default=0.620, minv=0.400, maxv=0.900, decimals=3, step=0.001),
                ],
                "desc": "Q = (2/3)\u00b7Cd\u00b7\u221a(2g)\u00b7L\u00b7H^1.5"
            },
            "Francis - Terkontraksi (2 Ujung)": {
                "func": calc_rect_contracted,
                "params": [
                    _p("L", "Panjang Mercu (L)", unit="m", default=0.500, minv=0.010, maxv=50.0, decimals=3, step=0.01),
                ],
                "desc": "Q = 1.84\u00b7(L - 0.2H)\u00b7H^1.5 (formula Francis, kontraksi ujung)"
            },
            "Rehbock (dengan tinggi mercu P)": {
                "func": calc_rect_rehbock,
                "params": [
                    _p("L", "Panjang Mercu (L)", unit="m", default=0.500, minv=0.010, maxv=50.0, decimals=3, step=0.01),
                    _p("P", "Tinggi Mercu di atas Dasar Saluran (P)", unit="m", default=0.300, minv=0.010, maxv=20.0, decimals=3, step=0.01),
                ],
                "desc": "Cd = 0.602 + 0.083(H/P); He = H + 0.0011 m; Q = (2/3)\u00b7Cd\u00b7\u221a(2g)\u00b7L\u00b7He^1.5"
            },
        }
    },
    "Trapezoidal Weir (Weir Trapesium)": {
        "methods": {
            "Cipolletti (Standar, Sisi 1:4)": {
                "func": calc_trap_cipolletti,
                "params": [
                    _p("L", "Lebar Dasar (L)", unit="m", default=0.500, minv=0.010, maxv=50.0, decimals=3, step=0.01,
                       tooltip="Lebar dasar bukaan trapesium (bagian paling bawah, sejajar mercu). "
                               "Kemiringan sisi Cipolletti SUDAH TETAP (horizontal:vertikal = 1:4) dan "
                               "tidak bisa diubah di metode ini - kalau perlu kemiringan lain, pakai "
                               "metode 'Trapesium Umum (Kemiringan Kustom)'."),
                ],
                "desc": "Q = 1.859\u00b7L\u00b7H^1.5. Kemiringan sisi TETAP (horizontal:vertikal = 1:4, "
                        "standar Cipolletti) - hanya lebar dasar L yang bisa diatur. Koefisien 1.859 "
                        "sudah menggabungkan efek kontraksi ujung dari kemiringan sisi tersebut, "
                        "jadi tidak ada parameter Cd terpisah pada metode ini."
            },
            "Trapesium Umum (Kemiringan Kustom)": {
                "func": calc_trap_general,
                "params": [
                    _p("L", "Lebar Dasar (L)", unit="m", default=0.500, minv=0.010, maxv=50.0, decimals=3, step=0.01,
                       tooltip="Lebar dasar bukaan trapesium (bagian paling bawah, sejajar mercu)."),
                    _p("z", "Kemiringan Sisi (z, horizontal:vertikal)", unit="-", default=0.250, minv=0.010, maxv=5.000, decimals=3, step=0.01,
                       tooltip="Rasio horizontal per vertikal tiap sisi miring. Contoh: z=0.25 berarti "
                               "kemiringan 1 (horizontal) : 4 (vertikal), sama seperti standar Cipolletti "
                               "tapi di sini bisa diubah bebas. Lebar di permukaan air = L + 2\u00d7z\u00d7H."),
                    _p("Cd_rect", "Cd Bagian Persegi (rectangular)", unit="-", default=0.620, minv=0.400, maxv=0.900, decimals=3, step=0.001,
                       tooltip="Koefisien debit untuk bagian tengah yang berbentuk persegi (lebar L, "
                               "seolah-olah weir persegi biasa). Terpisah dari Cd Bagian Segitiga karena "
                               "geometrinya beda dan formulanya dihitung sebagai 2 kontribusi yang dijumlah."),
                    _p("Cd_tri", "Cd Bagian Segitiga (kedua sisi miring)", unit="-", default=0.600, minv=0.400, maxv=0.900, decimals=3, step=0.001,
                       tooltip="Koefisien debit untuk kontribusi 2 sisi miring trapesium (digabung "
                               "menjadi satu suku segitiga dalam formula), terpisah dari Cd bagian "
                               "persegi di tengah."),
                ],
                "desc": "Trapesium umum = bagian persegi (lebar dasar L, koefisien Cd_rect) + 2 bagian "
                        "segitiga di kedua sisi miring (kemiringan z, koefisien Cd_tri) yang dijumlahkan: "
                        "Q = (2/3)\u00b7Cd_rect\u00b7\u221a(2g)\u00b7L\u00b7H^1.5 + (8/15)\u00b7Cd_tri\u00b7\u221a(2g)\u00b7z\u00b7H^2.5"
            },
        }
    },
    "Parshall Flume": {
        "methods": {
            "Aliran Bebas - Tabel Standar": {
                "func": calc_parshall_table,
                "params": [
                    _p("W_key", "Lebar Leher (Throat Width)", ptype="combo",
                       options=list(PARSHALL_TABLE.keys()), default_index=3),
                ],
                "desc": "Q(cfs) = C\u00b7Ha(ft)^n, dikonversi ke m3/s. Koefisien C,n dari tabel standar per ukuran leher."
            },
            "Koefisien Kustom (C & n manual)": {
                "func": calc_parshall_custom,
                "params": [
                    _p("C", "Koefisien C (metrik)", unit="-", default=2.200, minv=0.010, maxv=100.0, decimals=4, step=0.01),
                    _p("n", "Eksponen n", unit="-", default=1.550, minv=1.000, maxv=3.000, decimals=3, step=0.001),
                ],
                "desc": "Q = C\u00b7H^n (H dalam meter, Q dalam m3/s) - untuk koefisien hasil kalibrasi sendiri"
            },
        }
    },
}
