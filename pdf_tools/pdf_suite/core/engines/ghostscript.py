# -*- coding: utf-8 -*-
import re
from pathlib import Path

from ..schema import OptionSet, bool_opt, choice_opt, float_opt, int_opt, text_opt
from .base import Engine, EngineError, EngineResult, JobContext, page_count, split_args


def qfactor(quality: int) -> float:
    """Peta kualitas JPEG 1-100 ke QFactor Ghostscript (perkiraan)."""
    return round(max(0.05, 2.4 * (1 - quality / 100.0) ** 1.3), 2)


class GhostscriptEngine(Engine):
    id = "ghostscript"
    name = "Ghostscript"
    description = "Cepat dan serbaguna; menurunkan resolusi gambar di dalam PDF. Cocok untuk PDF campuran teks + gambar."
    required_tools = ("gs",)
    options = OptionSet([
        choice_opt("preset", "Preset PDFSETTINGS", "ebook",
                   [("screen", "screen (terkecil)"), ("ebook", "ebook (seimbang)"),
                    ("printer", "printer (tajam)"), ("prepress", "prepress (sangat tajam)"),
                    ("default", "default")],
                   "Dasar pengaturan kompresi Ghostscript. Nilai resolusi di bawah menimpa preset."),
        int_opt("dpi", "Resolusi gambar warna/abu", 150, 36, 600, "Gambar berwarna & grayscale diturunkan ke DPI ini.", suffix=" dpi"),
        bool_opt("grayscale", "Ubah ke hitam-putih (grayscale)", False, "Mengubah semua warna menjadi abu-abu."),
        # Bawaan 70 (bukan 0) = TRADE-OFF, bukan pilihan yang unggul di semua kasus (diukur):
        #   scan berwarna fotografis 300 ppi : 0 -> +74% (Flate lossless, file MEMBESAR)   70 -> -76%
        #   gambar berwarna sedikit (sintetis): 0 -> 61% dari asli                         70 -> 72%, 90 -> 160%
        # Kegagalan 70 ringan (kurang optimal, tetap mengecil); kegagalan 0 berat (membengkak).
        int_opt("jpeg_quality", "Kualitas JPEG (0 = otomatis Ghostscript)", 70, 0, 100,
                "1-100 memaksa kompresi JPEG pada gambar (bawaan 70; aman untuk scan/foto berwarna).\n"
                "0 = Ghostscript memilih sendiri per gambar. Bisa lebih kecil untuk gambar berwarna sedikit "
                "(screenshot, diagram, scan datar), tetapi pada scan/foto berwarna bisa memilih penyandian "
                "tanpa kehilangan sehingga file justru LEBIH BESAR dari aslinya.\n"
                "Kualitas tinggi (90+) dapat membesarkan file bila gambar sumber berwarna sedikit."),
        int_opt("dpi_mono", "Resolusi gambar monokrom", 300, 72, 1200, "Gambar 1-bit (hitam-putih murni).", group="advanced", suffix=" dpi"),
        choice_opt("downsample_type", "Metode downsample", "bicubic",
                   [("bicubic", "Bicubic (halus)"), ("average", "Average"), ("subsample", "Subsample (cepat)")],
                   "Algoritma penurunan resolusi.", group="advanced"),
        float_opt("threshold", "Ambang downsample", 1.5, 1.0, 10.0, 0.1,
                  "Gambar baru diturunkan bila resolusinya > ambang x DPI target.", group="advanced"),
        choice_opt("compat", "Versi kompatibilitas PDF", "1.4",
                   [("1.4", "1.4"), ("1.5", "1.5"), ("1.6", "1.6"), ("1.7", "1.7")], group="advanced"),
        text_opt("extra_args", "Argumen tambahan Ghostscript", "",
                 "Ditempel apa adanya ke perintah gs (mis. -dFastWebView=true).", group="advanced"),
    ])

    def build_cmd(self, gs_cmd, src, out, v):
        dt = {"bicubic": "/Bicubic", "average": "/Average", "subsample": "/Subsample"}[v["downsample_type"]]
        cmd = list(gs_cmd) + [
            "-sDEVICE=pdfwrite", f"-dCompatibilityLevel={v['compat']}", f"-dPDFSETTINGS=/{v['preset']}",
            "-dNOPAUSE", "-dBATCH",
            "-dDownsampleColorImages=true", "-dDownsampleGrayImages=true", "-dDownsampleMonoImages=true",
            f"-dColorImageResolution={v['dpi']}", f"-dGrayImageResolution={v['dpi']}",
            f"-dMonoImageResolution={v['dpi_mono']}",
            f"-dColorImageDownsampleType={dt}", f"-dGrayImageDownsampleType={dt}",
            f"-dColorImageDownsampleThreshold={v['threshold']}", f"-dGrayImageDownsampleThreshold={v['threshold']}",
        ]
        if v["grayscale"]:
            cmd += ["-sColorConversionStrategy=Gray", "-sProcessColorModel=DeviceGray"]
        if v["jpeg_quality"] > 0:
            cmd += ["-dAutoFilterColorImages=false", "-dColorImageFilter=/DCTEncode",
                    "-dAutoFilterGrayImages=false", "-dGrayImageFilter=/DCTEncode"]
        cmd += split_args(v["extra_args"])
        cmd += [f"-sOutputFile={out}"]
        if v["jpeg_quality"] > 0:
            qf = qfactor(v["jpeg_quality"])
            cmd += ["-c",
                    f"<< /ColorImageDict << /QFactor {qf} /Blend 1 /HSamples [2 1 1 2] /VSamples [2 1 1 2] >> "
                    f"/GrayImageDict << /QFactor {qf} /Blend 1 /HSamples [1 1 1 1] /VSamples [1 1 1 1] >> >> setdistillerparams",
                    "-f"]
        cmd += [str(src)]
        return cmd

    def process(self, src: Path, out: Path, values: dict, ctx: JobContext) -> EngineResult:
        v = self.options.normalize(values)
        gs = ctx.tool("gs")
        total = max(1, page_count(src))
        cmd = self.build_cmd(gs.cmd, src, out, v)
        rx = re.compile(r"^Page (\d+)")

        def on_line(line: str):
            m = rx.match(line)
            if m:
                ctx.progress(min(0.98, int(m.group(1)) / total))
            elif re.search(r"error|warning", line, re.I):
                ctx.log("  gs: " + line)

        res = ctx.run(cmd, on_line=on_line)
        if res.returncode != 0 or not Path(out).exists():
            raise EngineError("Ghostscript gagal (kode %s).\n%s" % (res.returncode, "\n".join(res.tail[-8:])))
        ctx.progress(1.0)
        return EngineResult()
