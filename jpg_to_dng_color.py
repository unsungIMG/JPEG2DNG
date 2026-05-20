"""
jpg_to_dng_color.py
===================
Converts a single color JPEG to a synthetic CFA (Bayer) DNG that triggers
Lightroom Classic's full raw processing pipeline, including AI Denoise and
Raw Details -- features unavailable on JPEG files.

Designed for scanned color film negatives, color slides, and color prints.

Pipeline:
  JPG -> decode -> apply_gamma_blend(GAMMA_BLEND) -> gray-world WB in linear
  light -> RGGB remosaic -> 16-bit uint16 -> CFA DNG

Workspace:
# Drop exactly one JPG copy into C:/TEMP/jpg2dngCOLOR_workspace/
# Output: C:/TEMP/jpg2dngCOLOR_workspace/DNGcfa_color.dng
# Log:    C:/TEMP/jpg2dngCOLOR_workspace/DNGcfa_color_log.txt
# Clear all files from the workspace before the next run.

Variables:
# GAMMA_BLEND = 0.75
#   Controls how much sRGB display gamma is removed before writing pixel data
#   into the DNG. 0.75 is the recommended starting point for color scans --
#   partial linearisation avoids shadow crushing when LRC's raw tone curve
#   stacks on top of the remaining gamma. Range: 0.0 (no linearisation, keep
#   gamma as-is) to 1.0 (full IEC 61966-2-1 linearisation).
#
# COLOR_MATRIX = IEC 61966-2-1 sRGB-to-XYZ D65 (9 SRATIONAL pairs)
#   Standard color transform for sRGB-encoded sources. Embedded as
#   ColorMatrix1 (DNG tag 50721). Values are fixed rational numbers with
#   denominator 10000.

Deps:
  Pillow, numpy
"""

import sys
import struct
import math
import datetime
import numpy as np
from pathlib import Path
from PIL import Image

WORKSPACE   = Path(r"C:\TEMP\jpg2dngCOLOR_workspace")
OUTPUT_NAME = "DNGcfa_color.dng"
LOG_DIR     = WORKSPACE

GAMMA_BLEND = 0.75

# IEC 61966-2-1 sRGB-to-XYZ D65 color matrix (ColorMatrix1, DNG tag 50721).
# Numerator/denominator pairs, denominator 10000.
COLOR_MATRIX = [
    ( 32405, 10000), (-15371, 10000), ( -4985, 10000),
    ( -9693, 10000), ( 18760, 10000), (   416, 10000),
    (   556, 10000), ( -2040, 10000), ( 10572, 10000),
]


# ---------------------------------------------------------------------------
# sRGB -> linear light (IEC 61966-2-1 piecewise)
# ---------------------------------------------------------------------------
def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(
        c <= 0.04045,
        c / 12.92,
        ((c + 0.055) / 1.055) ** 2.4
    )


# ---------------------------------------------------------------------------
# Blended linearisation
# ---------------------------------------------------------------------------
def apply_gamma_blend(arr: np.ndarray, gamma_blend: float) -> np.ndarray:
    if gamma_blend >= 1.0:
        return srgb_to_linear(arr)
    if gamma_blend <= 0.0:
        return arr.copy()
    linear = srgb_to_linear(arr)
    return arr * (1.0 - gamma_blend) + linear * gamma_blend


# ---------------------------------------------------------------------------
# Minimal CFA DNG writer -- color pipeline only.
# Embeds COLOR_MATRIX as ColorMatrix1, D50 illuminant, per-image
# BaselineExposure, and gray-world AsShotNeutral.
# ---------------------------------------------------------------------------
def write_cfa_dng(bayer16: np.ndarray, out_path: str,
                  mode: str = 'color',
                  baseline_exposure: float = 0.0,
                  white_level: int = 65535,
                  asshot_neutral: tuple = (1.0, 1.0, 1.0)) -> str:
    assert bayer16.ndim == 2,          "bayer16 must be 2D (H x W)"
    assert bayer16.dtype == np.uint16, "bayer16 must be uint16"

    h, w       = bayer16.shape
    image_data = bayer16.tobytes()

    BYTE=1; ASCII=2; SHORT=3; LONG=4; RATIONAL=5; SRATIONAL=10

    entries_raw = []
    extra_data  = bytearray()

    def add_shorts(tag, values):
        if len(values) <= 2:
            inline = b''.join(struct.pack('<H', v) for v in values).ljust(4, b'\x00')
            entries_raw.append((tag, SHORT, len(values), inline, None))
        else:
            off = len(extra_data)
            for v in values: extra_data.extend(struct.pack('<H', v))
            entries_raw.append((tag, SHORT, len(values), None, off))

    def add_longs(tag, values):
        if len(values) == 1:
            entries_raw.append((tag, LONG, 1, struct.pack('<L', values[0]), None))
        else:
            off = len(extra_data)
            for v in values: extra_data.extend(struct.pack('<L', v))
            entries_raw.append((tag, LONG, len(values), None, off))

    def add_ascii(tag, s):
        b = s.encode('ascii') + b'\x00'
        off = len(extra_data)
        extra_data.extend(b)
        entries_raw.append((tag, ASCII, len(b), None, off))

    def add_bytes_tag(tag, values):
        if len(values) <= 4:
            inline = bytes(values).ljust(4, b'\x00')
            entries_raw.append((tag, BYTE, len(values), inline, None))
        else:
            off = len(extra_data)
            extra_data.extend(bytes(values))
            entries_raw.append((tag, BYTE, len(values), None, off))

    def add_srational1(tag, value_float):
        denom = 10000
        num   = int(round(value_float * denom))
        off   = len(extra_data)
        extra_data.extend(struct.pack('<lL', num, denom))
        entries_raw.append((tag, SRATIONAL, 1, None, off))

    def add_srationals(tag, pairs):
        off = len(extra_data)
        for n, d in pairs:
            extra_data.extend(struct.pack('<lL', n, d))
        entries_raw.append((tag, SRATIONAL, len(pairs), None, off))

    def add_rationals(tag, pairs):
        off = len(extra_data)
        for n, d in pairs:
            extra_data.extend(struct.pack('<LL', n, d))
        entries_raw.append((tag, RATIONAL, len(pairs), None, off))

    # Core structural tags
    add_longs     (254,   [0])
    add_shorts    (256,   [w])
    add_shorts    (257,   [h])
    add_shorts    (258,   [16])
    add_shorts    (259,   [1])
    add_shorts    (262,   [32803])
    add_longs     (273,   [0])
    add_shorts    (274,   [1])
    add_shorts    (277,   [1])
    add_longs     (278,   [h])
    add_longs     (279,   [len(image_data)])
    add_shorts    (284,   [1])
    add_shorts    (33421, [2, 2])
    add_bytes_tag (33422, [0, 1, 1, 2])
    # Make/Model "Adobe"/"DNG" -> LRC uses Adobe Standard profile (flat, neutral).
    add_ascii     (271,   "Adobe")
    add_ascii     (272,   "DNG")
    add_bytes_tag (50706, [1, 4, 0, 0])
    add_bytes_tag (50707, [1, 1, 0, 0])
    add_ascii     (50708, "Adobe DNG")
    add_shorts    (50717, [white_level])

    # Color: IEC 61966-2-1 sRGB-to-XYZ D65 ColorMatrix1, D50 illuminant,
    # per-image BaselineExposure, gray-world AsShotNeutral (denom 1000000).
    add_srationals(50721, COLOR_MATRIX)
    add_shorts    (50778, [21])
    add_srational1(50730, baseline_exposure)
    denom = 1000000
    add_rationals (50728, [
        (int(round(asshot_neutral[0] * denom)), denom),
        (int(round(asshot_neutral[1] * denom)), denom),
        (int(round(asshot_neutral[2] * denom)), denom),
    ])

    entries_raw.sort(key=lambda e: e[0])

    n_entries   = len(entries_raw)
    ifd_offset  = 8
    ifd_size    = 2 + n_entries * 12 + 4
    extra_start = ifd_offset + ifd_size
    image_start = extra_start + len(extra_data)
    if image_start % 2:
        image_start += 1

    buf = bytearray()
    buf += b'II'
    buf += struct.pack('<H', 42)
    buf += struct.pack('<L', ifd_offset)
    buf += struct.pack('<H', n_entries)
    for (tag, typ, count, inline, extra_off) in entries_raw:
        buf += struct.pack('<HHL', tag, typ, count)
        if inline is not None:
            buf += struct.pack('<L', image_start) if tag == 273 else inline
        else:
            buf += struct.pack('<L', extra_start + extra_off)
    buf += struct.pack('<L', 0)
    buf += bytes(extra_data)
    while len(buf) < image_start:
        buf += b'\x00'
    buf += image_data

    Path(out_path).write_bytes(buf)
    return out_path


# ---------------------------------------------------------------------------
# Conversion -- color pipeline, full resolution.
# ---------------------------------------------------------------------------
def convert(src: Path) -> Path:
    out_path = WORKSPACE / OUTPUT_NAME
    run_ts   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"  Processing 1/1: {src.name}")
    print(f"  GammaBlend  : {GAMMA_BLEND}  (1.0=full linear, 0.0=keep gamma)")
    print(f"  Source      : {src}")

    # Load as float32 RGB in [0, 1]
    img     = Image.open(src).convert("RGB")
    arr_raw = np.array(img)
    norm    = 255.0
    arr     = arr_raw.astype(np.float32) / norm
    print(f"  Loaded      {arr.shape[1]}x{arr.shape[0]} px  (norm={norm:.0f})")

    # Blended linearisation
    linear = apply_gamma_blend(arr, GAMMA_BLEND)
    print(f"  Linearised  range {linear.min():.4f}-{linear.max():.4f}")

    # Gray-world WB in linear light
    r_mean = float(linear[:, :, 0].mean())
    g_mean = float(linear[:, :, 1].mean())
    b_mean = float(linear[:, :, 2].mean())
    g_mean = max(g_mean, 1e-6)
    asshot_neutral = (
        min(r_mean / g_mean, 1.0),
        1.0,
        min(b_mean / g_mean, 1.0),
    )
    print(f"  WB (gray-world)  R/G={asshot_neutral[0]:.4f}  B/G={asshot_neutral[2]:.4f}")

    # BaselineExposure from ratio of gamma mean to linear mean
    mean_gamma  = float(arr.mean())
    mean_linear = float(linear.mean())
    be = -math.log2(mean_gamma / mean_linear) if mean_linear > 0 else -0.579
    print(f"  BaselineExp : {be:.4f} EV")

    # Trim to even dimensions for Bayer grid
    h, w     = linear.shape[:2]
    h_e, w_e = h - (h % 2), w - (w % 2)
    linear   = linear[:h_e, :w_e, :]

    # RGGB remosaic
    bayer = np.empty((h_e, w_e), dtype=np.float32)
    bayer[0::2, 0::2] = linear[0::2, 0::2, 0]  # R
    bayer[0::2, 1::2] = linear[0::2, 1::2, 1]  # G
    bayer[1::2, 0::2] = linear[1::2, 0::2, 1]  # G
    bayer[1::2, 1::2] = linear[1::2, 1::2, 2]  # B
    print(f"  Remosaiced  RGGB Bayer {w_e}x{h_e}")

    # Scale to 16-bit
    bayer16     = (bayer * 65535).clip(0, 65535).astype(np.uint16)
    bayer16_max = int(bayer16.max())
    bayer16_min = int(bayer16.min())
    white_level = bayer16_max
    if white_level == 0:
        print("  WARNING     : image appears entirely black; white_level forced to 1")
        white_level = 1
    print(f"  16-bit      range {bayer16.min()}-{bayer16.max()}  (BitsPerSample=16, uint16)")

    write_cfa_dng(bayer16, str(out_path),
                  mode='color',
                  baseline_exposure=be,
                  white_level=white_level,
                  asshot_neutral=asshot_neutral)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print()
    print(f"  Output      : {out_path}")
    print(f"  Size        : {size_mb:.1f} MB")

    # Clipping status for log
    if bayer16_max == 65535 and bayer16_min > 0:
        clipping = (f"WARNING Highlight clipping (bayer16.max() == 65535)\n"
                    f"               WARNING Shadow floor (bayer16.min() == {bayer16_min}, no pure black pixels)")
    elif bayer16_max == 65535:
        clipping = "WARNING Highlight clipping: bayer16.max() == 65535"
    elif bayer16_min > 0:
        clipping = f"WARNING Shadow floor: bayer16.min() == {bayer16_min} (no pure black pixels)"
    else:
        clipping = "OK No clipping detected."

    # Write structured log to workspace, overwriting any previous run.
    # Non-fatal if write fails.
    log_path = LOG_DIR / "DNGcfa_color_log.txt"
    log_text = (
        f"HEADER\n"
        f"------\n"
        f"Script       : jpg_to_dng_color.py\n"
        f"Run          : {run_ts}\n"
        f"Source file  : {src.name}\n"
        f"Source path  : {src}\n"
        f"\n"
        f"INPUT\n"
        f"-----\n"
        f"Dimensions   : {arr.shape[1]} x {arr.shape[0]} px\n"
        f"Bit depth    : 8 (JPEG)\n"
        f"Source size  : {src.stat().st_size / 1024:.1f} KB\n"
        f"\n"
        f"PROCESSING\n"
        f"----------\n"
        f"gamma_blend  : {GAMMA_BLEND}  (controls how much sRGB gamma is removed before writing to DNG)\n"
        f"WB R/G       : {asshot_neutral[0]:.4f}\n"
        f"WB B/G       : {asshot_neutral[2]:.4f}\n"
        f"BaselineExp  : {be:.4f} EV\n"
        f"Clipping     : {clipping}\n"
        f"\n"
        f"OUTPUT\n"
        f"------\n"
        f"DNG filename : {out_path.name}\n"
        f"DNG path     : {out_path}\n"
        f"DNG size     : {size_mb:.1f} MB\n"
        f"Output dims  : {w_e} x {h_e} px\n"
        f"\n"
        f"IF RESULTS ARE NOT SATISFACTORY\n"
        f"================================\n"
        f"\n"
        f"(a) Shadows crushed or too dark\n"
        f"    Lower GAMMA_BLEND toward 0.5 or 0.3.\n"
        f"    Current value      : {GAMMA_BLEND}\n"
        f"    Location in script : GAMMA_BLEND = {GAMMA_BLEND}  (near the top of the file)\n"
        f"\n"
        f"(b) Color cast present\n"
        f"    Use the White Balance picker in Lightroom Classic on a neutral area,\n"
        f"    then sync to remaining images.\n"
        f"\n"
        f"(c) Overall too bright\n"
        f"    BaselineExposure is computed automatically from image statistics.\n"
        f"    If consistently wrong, consider adjusting GAMMA_BLEND first -- a lower\n"
        f"    value raises the blended-linear mean and reduces the BaselineExposure\n"
        f"    correction applied by Lightroom.\n"
    )
    try:
        log_path.write_text(log_text, encoding="utf-8")
        print(f"  Log         : {log_path}")
    except Exception:
        pass

    return out_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    print("WARNING: This script should only be run on COPIES of your images.")
    print("         Never place original files in the workspace.\n")

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    print(f"Workspace   : {WORKSPACE}")
    print(f"Drop your JPG file into  : {WORKSPACE}")
    print(f"Your DNG will be here    : {WORKSPACE / OUTPUT_NAME}\n")

    jpg_files = [
        f for f in WORKSPACE.iterdir()
        if f.is_file() and f.suffix.lower() in {'.jpg', '.jpeg'}
    ]

    if len(jpg_files) == 0:
        print(f"No JPG or JPEG files found in {WORKSPACE}")
        print("Drop exactly one JPG copy into the workspace folder and run again.")
        sys.exit(1)

    if len(jpg_files) > 1:
        print(f"More than one JPG/JPEG file found in {WORKSPACE}.")
        print("This script expects exactly one file. Files found:")
        for f in sorted(jpg_files):
            print(f"  {f.name}")
        print("Remove all but one file and run again.")
        sys.exit(1)

    src = jpg_files[0]
    print(f"Found: {src.name}\n")

    convert(src)

    print("\nDone.")
    print("WARNING: Before the next run, remove both the source JPG and")
    print(f"         DNGcfa_color.dng from {WORKSPACE}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)
