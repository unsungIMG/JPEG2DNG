# JPEG2DNG

Converts JPEG images to synthetic CFA (Bayer) DNG files that trigger Adobe
Lightroom Classic's full raw processing pipeline — including **AI Denoise**,
**Raw Details**, Adobe Color and Monochrome profiles, raw-gated masking tools,
and the complete Develop module. Two scripts are provided: `jpg_to_dng_bw.py`
for B&W scans and `jpg_to_dng_color.py` for colour scans. Both are designed
for scanned photographic film — B&W negatives, colour slides, and colour prints
— scanned to JPEG. The source images are fully-rendered, display-referred sRGB
files from a film scanner. They are **not** camera sensor data.

---

## The problem it solves

Lightroom Classic withholds a substantial part of its processing capability
from JPEGs and TIFFs. AI Denoise, Raw Details, raw-specific tone mapping, Adobe
Color and Monochrome profiles, and certain masking tools are available **only
to raw files**. JPEG2DNG re-encodes a JPEG as a syntactically valid CFA DNG —
a raw format Lightroom recognises — unlocking these features for scanned film,
archival images, or any pre-rendered source that warrants full raw processing
capability.

The output DNG contains **no invented pixel data**. Source tonal values are
preserved through a linearisation step and written into a 16-bit RGGB Bayer
container. Lightroom's demosaic engine reconstructs the image and applies its
raw pipeline from that point forward.

---

## Requirements

Python 3.8 or later. No C compiler, no DNG SDK, no ExifTool required.

```
pip install Pillow numpy
```

---

## B&W Script: jpg_to_dng_bw.py

### Purpose

`jpg_to_dng_bw.py` is a no-configuration script built specifically for cheaply
scanned B&W JPEGs. Its sole purpose is to produce a valid CFA DNG that
Lightroom Classic will import as a raw file, unlocking **AI Denoise** and
**Raw Details** — features unavailable on JPEG files.

B&W conversion is the more reliable of the two modes. All three source channels
are collapsed to a single Rec.709 luminance value in linear light
(`Y = 0.2126 R + 0.7152 G + 0.0722 B`), normalised to fill the full 0–65535
range, and written identically to all four Bayer positions. Lightroom's demosaic
engine has nothing to push around and reconstructs a perfectly neutral
monochrome image. The full Develop module, Adobe Monochrome profiles, AI
Denoise, Raw Details, and all B&W-specific controls behave correctly.

### Workflow

Workspace folder: **`C:/TEMP/jpg2dngBW_workspace/`** (created automatically on first run)

1. Drop **one JPG copy** into `C:/TEMP/jpg2dngBW_workspace/`
2. Run: `py jpg_to_dng_bw.py`
3. Retrieve your DNG from `C:/TEMP/jpg2dngBW_workspace/DNGcfa_bw.dng`
4. Import into Lightroom Classic. Apply AI Denoise, Raw Details, tone, and crop.

> **Warning: always work with a copy of your image. Never place an original
> file in the workspace.**

> **Warning: clear both the source JPG and `DNGcfa_bw.dng` from
> `C:/TEMP/jpg2dngBW_workspace/` before the next run.** The output filename is
> fixed; a stale DNG left in the workspace will be silently overwritten.

### Variables

These values are hardcoded inside the script. You do not need to change them
for normal use, but they are documented here for reference when working with
unusual or difficult scans.

**`gamma_blend`** — hardcoded to `1.0` (full linearisation, not a named constant)

Controls how much of the sRGB display gamma curve is removed from the pixel
data before it is written into the DNG. Because this value is not exposed as a
named variable, adjusting it requires editing the `convert()` function directly:
replace the `srgb_to_linear(arr)` call with `apply_gamma_blend(arr, value)`,
copying the `apply_gamma_blend()` helper already present in the script.

| Value | Effect on LRC output |
|---|---|
| `1.0` (default) | Full sRGB linearisation (IEC 61966-2-1 piecewise). Mathematically correct for a raw sensor pipeline. LRC receives linear-light data and applies its own raw tone curve on top. Best dynamic range for most scans. |
| `0.5` | Midpoint blend between gamma-encoded and fully linear. Softer shadow rolloff. Good starting point for scanned material with heavy shadow areas. |
| `0.0` | No linearisation. Gamma-encoded sRGB values written as-is. Closest to the original scan appearance; LRC's raw tone curve still applies, so output will be brighter and lighter than the source. |

Recommended starting points for difficult scans:

| Scene type | Suggested value |
|---|---|
| Outdoor, even tones | 0.75 – 1.0 |
| Mixed interior/exterior | 0.50 – 0.75 |
| Dark-framed (window/door border) | 0.30 – 0.50 |
| Shadow-heavy interior / dark negative | 0.25 – 0.40 |

---

## Color Script: jpg_to_dng_color.py

### Purpose

`jpg_to_dng_color.py` converts a single color JPEG to a CFA DNG, unlocking
**AI Denoise** and **Raw Details** in Lightroom Classic. It computes a
per-image gray-world white balance estimate and embeds the standard IEC
61966-2-1 sRGB-to-XYZ D65 color matrix. There are no command-line arguments.

See [Color limitations](#color-limitations) for an honest account of what to
expect from color conversion.

### Workflow

Workspace folder: **`C:/TEMP/jpg2dngCOLOR_workspace/`** (created automatically on first run)

1. Drop **one JPG copy** into `C:/TEMP/jpg2dngCOLOR_workspace/`
2. Run: `py jpg_to_dng_color.py`
3. Retrieve your DNG from `C:/TEMP/jpg2dngCOLOR_workspace/DNGcfa_color.dng`
4. Import into Lightroom Classic. Apply AI Denoise, Raw Details, tone, and crop.

> **Warning: always work with a copy of your image. Never place an original
> file in the workspace.**

> **Warning: clear both the source JPG and `DNGcfa_color.dng` from
> `C:/TEMP/jpg2dngCOLOR_workspace/` before the next run.** The output filename
> is fixed; a stale DNG left in the workspace will be silently overwritten.

### Variables

These named constants are defined near the top of the script. They can be
edited directly for difficult scans without changing the script logic.

**`GAMMA_BLEND`** — set to `0.75`

Controls how much of the sRGB display gamma curve is removed before writing
pixel data into the DNG. `0.75` is the recommended starting point for color
scans — three-quarter linearisation gives LRC useful linear-light data while
softening the shadow crushing that full linearisation can produce when LRC's
raw tone curve stacks on top.

| Value | Effect on LRC output |
|---|---|
| `1.0` | Full sRGB linearisation (IEC 61966-2-1 piecewise). Mathematically correct for raw. Can crush shadows when LRC's raw tone curve stacks on top. |
| `0.75` (default) | Three-quarter blend. LRC receives mostly linear data with softer shadow rolloff. Good balance for most color scans. |
| `0.5` | Midpoint blend. Softer shadows. Good for scanned slides with heavy shadow areas or dark borders. |
| `0.0` | No linearisation. Gamma-encoded values written as-is. Softest shadows; closest to original scan appearance. LRC's raw tone curve still applies. |

Recommended starting points by scene type:

| Scene type | Suggested value |
|---|---|
| Outdoor, even tones | 0.75 – 1.0 |
| Mixed interior/exterior | 0.50 – 0.75 |
| Dark-framed (window/door border) | 0.30 – 0.50 |
| Shadow-heavy interior / dark negative | 0.25 – 0.40 |

**`COLOR_MATRIX`** — IEC 61966-2-1 sRGB-to-XYZ D65 (fixed, not intended to be changed)

The standard color transform for sRGB-encoded sources. Embedded as
`ColorMatrix1` (DNG tag 50721) as nine signed rational values with denominator
10000:

```
 3.2405  -1.5371  -0.4985
-0.9693   1.8760   0.0416
 0.0556  -0.2040   1.0572
```

An alternative "match mode" matrix derived from Olympus OM-1 calibration data
was evaluated and found to produce a consistent blue cast on scanner-sourced
color JPEGs. It was excluded. The IEC 61966-2-1 matrix is the correct
transform for images that originated as sRGB data.

---

## Color limitations

Color conversion is substantially more complex than B&W and the results are
an editing starting point, not a pixel-accurate reconstruction.

**Residual cool/cyan cast.** A slight cool or cyan shift relative to the source
JPEG is typical and expected. Lightroom's raw pipeline was designed for
spectrally-separated camera sensor data, not for pre-rendered sRGB images. The
color science applied does not match the original film's color characteristics.
This is correctable with the WB picker in LRC — fix one image, sync to the
rest of the roll.

**Gray-world WB fails on dominant-hue scenes.** The gray-world white balance
estimate assumes the average scene is neutral grey. It will produce a cast on
images dominated by a single hue — heavy blue sky filling the frame, dense
green foliage, black rock. Use the WB picker in LRC to correct these
individually.

**Not pixel-accurate.** The RGGB Bayer pattern gives the green channel twice
the spatial representation of red or blue. Lightroom's demosaic interpolates
red and blue from fewer source pixels, which introduces subtle hue shifts even
with a correct white balance and color matrix. The source JPEG remains the
definitive color reference for archival purposes.

**AI Denoise and Raw Details are the primary value.** The DNG gives Lightroom
access to its full raw processing toolset. For scanned color film that needs
grain reduction, sharpening at the raw level, or raw-only masking tools, the
color accuracy tradeoffs are acceptable.

---

## Shared technical notes

**DNG structure.** Built from scratch using Python's `struct` module with no
external DNG library. The TIFF/IFD binary structure is constructed directly,
keeping the dependency footprint to Pillow and NumPy only.

**Make/Model.** DNGs are tagged `Make="Adobe"` `Model="DNG"`. This causes
Lightroom to use its Adobe Standard profile (flat, neutral) rather than a
camera-specific colour profile. An earlier version of this project used
`Make="Olympus"` `Model="OM-1"` to associate files with a known profile set,
but Lightroom applied sensor-calibrated colour science to scanner data,
producing a systematic colour tint. The Adobe DNG tags avoid this.

**Bayer pattern.** RGGB. Lightroom's demosaic engine handles this natively for
all DNG files.

**BaselineExposure.** Computed from `−log2(mean_gamma / mean_linear)`, which
calibrates Lightroom's initial exposure rendering to the source image's average
brightness. With `GAMMA_BLEND < 1.0`, the blended-linear mean is higher than
full-linear, so BaselineExposure is automatically less negative — Lightroom
compensates less aggressively, which is the correct behaviour.

**ColorMatrix domain.** The IEC 61966-2-1 XYZ D65 to sRGB matrix is the
standard inverse transform for sRGB-encoded sources. It is embedded as
`ColorMatrix1` (tag 50721) as signed rational values (SRATIONAL, denominator
10000).

**Gray-world WB domain.** Computed in linear light (after gamma blend removal),
which is the physically correct radiometric domain for computing channel means.
The result is clipped to ≤ 1.0 per channel to stay within the valid DNG
`AsShotNeutral` range. Embedded as unsigned rationals (RATIONAL, denominator
1,000,000).

---

## Note on archived script

`jpg_to_cfa_dng.py` was the earlier combined script that this repository has
superseded. It provided all four modes (`neutral`, `match`, `mono`, `color`)
in a single file with full CLI argument support. It has been archived to the
private repository `unsungIMG/unsungIMGpriv` for reference.

---

## License

MIT License. Copyright (c) 2025 Drew Adkins | Unsung Images. See LICENSE for details.
