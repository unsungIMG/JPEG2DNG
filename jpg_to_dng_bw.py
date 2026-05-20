"""
jpg_to_dng_bw.py
================
Converts a single B&W JPEG to a synthetic CFA (Bayer) DNG that triggers
Lightroom Classic's full raw processing pipeline, including AI Denoise and
Raw Details -- features unavailable on JPEG files.

Designed for cheaply scanned B&W film negatives and B&W prints.

Pipeline:
  JPG -> decode -> sRGB linearise -> Rec.709 luma -> normalise -> RGGB Bayer DNG

Workspace:
# Drop exactly one JPG copy into C:/TEMP/jpg2dngBW_workspace/
# Output: C:/TEMP/jpg2dngBW_workspace/DNGcfa_bw.dng
# Clear both files from the workspace before the next run.

Deps:
  Pillow, numpy
"""

import sys
import struct
import datetime
import numpy as np
from pathlib import Path
from PIL import Image

WORKSPACE   = Path(r"C:\TEMP\jpg2dngBW_workspace")
OUTPUT_NAME = "DNGcfa_bw.dng"
LOG_DIR     = Path(r"C:\Users\Public\Documents\PYProjects\Logs")


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
# Minimal CFA DNG writer -- mono pipeline only.
# Unconditionally writes: identity ColorMatrix, D50 illuminant, zero
# BaselineExposure, and neutral AsShotNeutral (1,1,1).
# ---------------------------------------------------------------------------
def write_cfa_dng(bayer16: np.ndarray, out_path: str, white_level: int) -> str:
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

    # Mono-specific: identity ColorMatrix, D50 illuminant, zero BaselineExposure,
    # neutral AsShotNeutral. All four Bayer positions carry the same luma value
    # so no color transform is needed or wanted.
    add_srationals(50721, [
        (1,1),(0,1),(0,1),
        (0,1),(1,1),(0,1),
        (0,1),(0,1),(1,1),
    ])
    add_shorts    (50778, [21])
    add_srational1(50730, 0.0)
    add_rationals (50728, [(1,1),(1,1),(1,1)])

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
# Conversion -- mono pipeline only, full resolution, full linearisation.
# ---------------------------------------------------------------------------
def convert(src: Path) -> Path:
    out_path  = WORKSPACE / OUTPUT_NAME
    log_lines = []

    def log(msg: str) -> None:
        print(msg)
        log_lines.append(msg)

    log(f"  Processing 1/1: {src.name}")
    log(f"  Source      : {src}")

    # Load as float32 RGB in [0, 1]
    img     = Image.open(src).convert("RGB")
    arr_raw = np.array(img)
    norm    = 255.0
    arr     = arr_raw.astype(np.float32) / norm
    log(f"  Loaded      {arr.shape[1]}x{arr.shape[0]} px  (norm={norm:.0f})")

    # Full sRGB linearisation (gamma_blend = 1.0)
    linear = srgb_to_linear(arr)
    log(f"  Linearised  range {linear.min():.4f}-{linear.max():.4f}")

    # Rec.709 luma
    luma = (0.2126 * linear[:, :, 0]
          + 0.7152 * linear[:, :, 1]
          + 0.0722 * linear[:, :, 2])
    log(f"  Luma        Rec.709  range {luma.min():.4f}-{luma.max():.4f}")

    # Normalise to fill the full 0-65535 range -- maximises dynamic range
    # without inventing data.
    luma_max = float(luma.max())
    if luma_max > 0:
        luma = luma / luma_max
    log(f"  Normalised  range {luma.min():.4f}-{luma.max():.4f}  (peak was {luma_max:.4f})")

    # Trim to even dimensions for Bayer grid
    h, w     = luma.shape
    h_e, w_e = h - (h % 2), w - (w % 2)
    luma     = luma[:h_e, :w_e]

    # Remosaic: all 4 Bayer positions = luma. Eliminates false colour in
    # demosaic because there is no inter-channel variation to reconstruct.
    bayer = np.empty((h_e, w_e), dtype=np.float32)
    bayer[0::2, 0::2] = luma[0::2, 0::2]
    bayer[0::2, 1::2] = luma[0::2, 1::2]
    bayer[1::2, 0::2] = luma[1::2, 0::2]
    bayer[1::2, 1::2] = luma[1::2, 1::2]
    log(f"  Remosaiced  RGGB Bayer {w_e}x{h_e} (all positions = luma)")

    # Scale to 16-bit
    bayer16     = (bayer * 65535).clip(0, 65535).astype(np.uint16)
    white_level = int(bayer16.max())
    if white_level == 0:
        log("  WARNING     : image appears entirely black; white_level forced to 1")
        white_level = 1
    log(f"  16-bit      range {bayer16.min()}-{bayer16.max()}  (BitsPerSample=16, uint16)")

    write_cfa_dng(bayer16, str(out_path), white_level=white_level)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print()
    log(f"  Output      : {out_path}")
    log(f"  Size        : {size_mb:.1f} MB")

    # Write log file -- non-fatal if the log directory is unavailable
    datestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path  = LOG_DIR / f"jpg_to_dng_bw_{datestamp}.log"
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
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
    print(f"         DNGcfa_bw.dng from {WORKSPACE}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)
