#!/usr/bin/env python3
"""
instax_extract.py - Extract photos from a flatbed A4 scan.

Output per photo:
  ALL photos  -> one tight crop  (content + --padding mm, default 1mm)
  Instax only -> one bordered crop  (content + exact white card border + 1mm)

File naming:
  scan_01_mini.jpg       <- tight crop
  scan_01_mini_card.jpg  <- with Instax white border + 1mm  (Instax only)
  scan_02_unknown.jpg    <- tight crop only

Usage:
    python instax_extract.py scan.jpg
    python instax_extract.py scan.jpg output_folder/
    python instax_extract.py scan.jpg --padding 2 --debug
    python instax_extract.py scan.jpg --dpi 300

Options:
    --padding N    Tight crop padding in mm (default: 1)
    --threshold N  Pixel brightness threshold for content detection (default: 200)
    --dpi N        Override auto-detected scan DPI
    --no-tight     Skip saving the tight crop
    --no-card      Skip saving the card-border crop (Instax only)
    --debug        Save intermediate mask images for troubleshooting

Requires: pip install opencv-python numpy
"""

import sys, cv2, numpy as np, struct
from pathlib import Path

MM           = 25.4
DEFAULT_PAD  = 1       # mm, tight crop
DEFAULT_THR  = 200
BORDER_EXTRA = 1       # mm extra outside card border in the bordered crop
JPEG_Q       = 95
SCAN_BORDER  = 12      # px white strip painted on all 4 edges
MIN_GAP_MM   = 1.0

# Instax image content dimensions (long_mm, short_mm)
INSTAX_IMAGE = {"mini": (62, 46), "square": (62, 62), "wide": (99, 62)}

# Padding from detected content-bbox edge to physical card edge (mm).
# Order: (top, bottom, sides) — "bottom" = thick writing border.
# Measured from 600-DPI scans.
INSTAX_BORDER = {
    "mini":   (6.0, 15.0, 4.0),
    "square": (7.0, 17.0, 5.0),
    "wide":   (6.0, 15.0, 4.5),
}
FORMAT_TOL = 0.22


# ── DPI detection ────────────────────────────────────────────────────────────

def detect_dpi(filepath, img_w):
    try:
        with open(filepath, "rb") as f:
            data = f.read(20)
        if data[6:10] == b"JFIF":
            unit  = data[13]
            x_dpi = struct.unpack(">H", data[14:16])[0]
            if unit == 1 and x_dpi > 50:
                return float(x_dpi)
    except Exception:
        pass
    raw = img_w / (210.0 / MM)   # assume A4 width
    for std in [75, 96, 100, 150, 175, 200, 240, 300, 400, 600, 1200]:
        if abs(raw - std) < std * 0.15:
            return float(std)
    return max(72.0, round(raw / 25) * 25.0)


# ── Unit helpers ─────────────────────────────────────────────────────────────

def mm2px(v, dpi): return v * dpi / MM
def px2mm(v, dpi): return v * MM / dpi


# ── Format classification ─────────────────────────────────────────────────────

def classify(long_px, short_px, dpi):
    lmm, smm = px2mm(long_px, dpi), px2mm(short_px, dpi)
    best, berr = None, float("inf")
    for name, (fl, fs) in INSTAX_IMAGE.items():
        err = max(abs(lmm - fl) / fl, abs(smm - fs) / fs)
        if err < FORMAT_TOL and err < berr:
            berr, best = err, name
    return best, berr


# ── Valley finder ─────────────────────────────────────────────────────────────

def find_valleys(proj, min_gap_px):
    mx    = float(proj.max()) if proj.max() > 0 else 1.0
    empty = proj < max(3, mx * 0.004)
    vals, inv, vs = [], False, 0
    for i, e in enumerate(empty):
        if e and not inv:   inv, vs = True, i
        elif not e and inv:
            inv = False
            if i - vs >= min_gap_px: vals.append((vs, i, (vs + i) // 2))
    if inv and len(proj) - vs >= min_gap_px:
        vals.append((vs, len(proj), (vs + len(proj)) // 2))
    return vals


# ── Orientation detection ─────────────────────────────────────────────────────

def _is_rotated(fmt, cw, ch):
    """
    Return True when the card is 90° off its natural scan orientation.

    Natural orientation (thick/thin borders are VERTICAL = y-axis):
      mini   → portrait  (ch > cw)
      square → portrait  (ch > cw)
      wide   → landscape (cw > ch)

    When rotated (thick/thin borders are HORIZONTAL = x-axis):
      mini / square in landscape  (cw > ch)
      wide in portrait            (ch > cw)
    """
    if fmt in ("mini", "square"):
        return cw > ch
    if fmt == "wide":
        return ch > cw
    return False


def detect_flip(gray, cx, cy, cw, ch, angle, dpi, rotated=False):
    """
    Probe at 8mm out from the content edge on BOTH sides of the border axis.

    The 8mm probe distance is chosen so that:
      - It clears the thin border (6–7 mm) → reading scanner background (brighter).
      - It is still inside the thick border (15–17 mm) → reading card white (slightly darker).

    For natural orientation (rotated=False): probe ABOVE/BELOW (y-axis).
      below brighter  → scanner bg below → thick border at top  → IS flipped.

    For rotated orientation (rotated=True):  probe LEFT/RIGHT (x-axis).
      right brighter  → scanner bg right → thick border at left → IS flipped.

    Returns True if the card needs its top/bottom padding swapped.

    Edge cases: if a photo is too close to the scan boundary for the probe on
    one side to fit, we use an absolute brightness threshold on the valid side
    to decide.  Scanner glass ≈ 240–255; Instax card white ≈ 215–230.
    """
    SCAN_BG_THR = 235   # safely above card white, below scanner max

    H, W   = gray.shape
    M      = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    rot    = cv2.warpAffine(gray, M, (W, H), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REPLICATE)
    gap_px = int(mm2px(8.0, dpi))
    prb_px = max(4, int(mm2px(3.0, dpi)))

    if not rotated:
        half_h = int(ch / 2)
        x1 = max(0, int(cx - cw * 0.3));  x2 = min(W, int(cx + cw * 0.3))

        ya1 = max(0,   int(cy) - half_h - gap_px - prb_px)
        ya2 = max(0,   int(cy) - half_h - gap_px)
        yb1 = min(H-1, int(cy) + half_h + gap_px)
        yb2 = min(H,   int(cy) + half_h + gap_px + prb_px)

        side_a = rot[ya1:ya2, x1:x2]   # above
        side_b = rot[yb1:yb2, x1:x2]   # below

        a_ok = side_a.size > 0
        b_ok = side_b.size > 0

        if not a_ok and not b_ok:
            return False
        if not a_ok:
            # Photo is near scan top → scanner bg is above (thin border at top) → normal.
            # If below is also scanner bg it's ambiguous; default to normal.
            return False
        if not b_ok:
            # Photo near scan bottom; can't probe below.
            # If above reads scanner bg → thin border at top → normal; else → flipped.
            return float(side_a.mean()) < SCAN_BG_THR   # a dim → thick border above → flipped

        # Both valid — brighter side has scanner bg = thin border there
        return float(side_b.mean()) > float(side_a.mean())

    else:
        half_w = int(cw / 2)
        y1 = max(0, int(cy - ch * 0.3));  y2 = min(H, int(cy + ch * 0.3))

        xl1 = max(0,   int(cx) - half_w - gap_px - prb_px)
        xl2 = max(0,   int(cx) - half_w - gap_px)
        xr1 = min(W-1, int(cx) + half_w + gap_px)
        xr2 = min(W,   int(cx) + half_w + gap_px + prb_px)

        side_a = rot[y1:y2, xl1:xl2]   # left
        side_b = rot[y1:y2, xr1:xr2]   # right

        a_ok = side_a.size > 0
        b_ok = side_b.size > 0

        if not a_ok and not b_ok:
            return False
        if not a_ok:
            return False          # near left edge → thin border at left → normal
        if not b_ok:
            return float(side_a.mean()) < SCAN_BG_THR   # dim left → thick border left → flipped

        return float(side_b.mean()) > float(side_a.mean())


# ── Crop helpers ──────────────────────────────────────────────────────────────

def find_print_edge(image, gray, cx, cy, cw, ch, angle, dpi, pad_px):
    """
    For non-Instax (lab) prints: crop to the detected content bbox + padding.

    The blob tight content bbox already spans the full print (photographic
    prints have image content edge-to-edge, so the foreground mask equals the
    print boundary).  Walking outward further fails when neighbouring prints
    are close together because the gap brightness (~230) never reaches the
    scanner glass threshold (~240+), causing the probe to cross through other
    photos and produce full-scan-width crops.

    We therefore use the same symmetric crop as tight_crop, which gives a
    clean, correctly-bounded result for all placement configurations.
    """
    return tight_crop(image, cx, cy, cw, ch, angle, pad_px)


def tight_crop(image, cx, cy, cw, ch, angle, pad_px):
    """Symmetric padding on all sides — v3 algorithm."""
    H, W = image.shape[:2]
    M    = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    rot  = cv2.warpAffine(image, M, (W, H), flags=cv2.INTER_CUBIC,
                           borderMode=cv2.BORDER_REPLICATE)
    x1 = max(0, int(cx - cw / 2 - pad_px))
    x2 = min(W, int(cx + cw / 2 + pad_px))
    y1 = max(0, int(cy - ch / 2 - pad_px))
    y2 = min(H, int(cy + ch / 2 + pad_px))
    return rot[y1:y2, x1:x2]


def large_card_crop(image, cx, cy, cw, ch, angle, pad_px):
    """
    Fixed-size crop: content + pad_px on all 4 sides.
    The output dimensions are always exactly (cw + 2*pad_px) x (ch + 2*pad_px).
    Areas that fall outside the scan boundary are filled with white (255),
    matching the scanner backlight colour.
    """
    H, W = image.shape[:2]
    ch_n = image.shape[2] if image.ndim == 3 else 1
    out_w = int(round(cw + 2 * pad_px))
    out_h = int(round(ch + 2 * pad_px))

    # Rotate full image around the card centre; out-of-image areas → white
    M   = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    rot = cv2.warpAffine(image, M, (W, H), flags=cv2.INTER_CUBIC,
                         borderMode=cv2.BORDER_CONSTANT,
                         borderValue=(255,) * ch_n)

    # Desired crop window (may extend outside scan bounds)
    x1 = int(round(cx - cw / 2 - pad_px))
    y1 = int(round(cy - ch / 2 - pad_px))
    x2 = x1 + out_w
    y2 = y1 + out_h

    # White canvas of exact target size
    canvas = np.full((out_h, out_w, ch_n) if ch_n > 1 else (out_h, out_w),
                     255, dtype=image.dtype)

    # Copy only the in-bounds pixels
    sx1, sy1 = max(0, x1), max(0, y1)
    sx2, sy2 = min(W, x2), min(H, y2)
    if sx2 > sx1 and sy2 > sy1:
        dx1, dy1 = sx1 - x1, sy1 - y1
        canvas[dy1:dy1 + (sy2 - sy1), dx1:dx1 + (sx2 - sx1)] = rot[sy1:sy2, sx1:sx2]

    return canvas


def card_crop(image, cx, cy, cw, ch, angle,
              pad_top, pad_bot, pad_sides, rotated=False):
    """
    Asymmetric padding — card border crop.

    rotated=False (natural orientation):
      x ← pad_sides,  y ← pad_top / pad_bot

    rotated=True (card 90° off natural):
      x ← pad_top (left) / pad_bot (right),  y ← pad_sides
    """
    H, W = image.shape[:2]
    M    = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    rot  = cv2.warpAffine(image, M, (W, H), flags=cv2.INTER_CUBIC,
                           borderMode=cv2.BORDER_REPLICATE)
    if not rotated:
        x1 = max(0, int(cx - cw / 2 - pad_sides))
        x2 = min(W, int(cx + cw / 2 + pad_sides))
        y1 = max(0, int(cy - ch / 2 - pad_top))
        y2 = min(H, int(cy + ch / 2 + pad_bot))
    else:
        # "top" padding goes LEFT, "bot" padding goes RIGHT
        x1 = max(0, int(cx - cw / 2 - pad_top))
        x2 = min(W, int(cx + cw / 2 + pad_bot))
        y1 = max(0, int(cy - ch / 2 - pad_sides))
        y2 = min(H, int(cy + ch / 2 + pad_sides))
    return rot[y1:y2, x1:x2]


# ── Main detection — v3 pipeline ──────────────────────────────────────────────

def detect_photos(image, filepath, dpi, padding_mm, threshold, debug):
    img_h, img_w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # 1. Kill scanner-edge dark artifacts
    g = gray.copy()
    b = SCAN_BORDER
    g[:b, :] = g[-b:, :] = g[:, :b] = g[:, -b:] = 255

    # 2. Foreground mask (v3: fixed 24x24px kernel at 600 DPI ≈ 1mm, scaled here)
    _, fg = cv2.threshold(g, threshold, 255, cv2.THRESH_BINARY_INV)
    k_px  = max(3, int(round(24 * dpi / 600)))   # scale 24px@600dpi to actual dpi
    k     = cv2.getStructuringElement(cv2.MORPH_RECT, (k_px, k_px))
    fg    = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, k)

    if debug:
        cv2.imwrite("debug_01_fg.jpg", fg)
        print("[debug] debug_01_fg.jpg saved")

    # 3. Find blobs (v3: MIN_CONTENT scaled to dpi)
    min_area = int(mm2px(15.0, dpi) ** 2)
    cnts, _  = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    blobs    = [c for c in cnts if cv2.contourArea(c) > min_area]
    print(f"  Found {len(blobs)} content blob(s)")

    if debug:
        dbg = cv2.cvtColor(fg, cv2.COLOR_GRAY2BGR)
        cv2.drawContours(dbg, blobs, -1, (0, 200, 0), 8)
        cv2.imwrite("debug_02_blobs.jpg", dbg)
        print("[debug] debug_02_blobs.jpg saved")

    pad_px   = int(mm2px(padding_mm, dpi))
    extra_px = int(mm2px(BORDER_EXTRA, dpi))
    gap_px   = max(3, int(mm2px(MIN_GAP_MM, dpi)))
    results  = []

    for blob in blobs:
        bx, by, bw, bh = cv2.boundingRect(blob)
        bmask = np.zeros((img_h, img_w), np.uint8)
        cv2.drawContours(bmask, [blob], -1, 255, cv2.FILLED)
        cm = bmask[by:by+bh, bx:bx+bw]

        # v3 interior projection for split detection
        rm  = max(4, int(bh * 0.02))
        cm_ = max(4, int(bw * 0.02))
        intr = cm[rm:bh-rm, cm_:bw-cm_]
        if intr.size == 0: intr = cm

        csplits = [bx + cm_ + v[2] for v in find_valleys(intr.sum(axis=0), gap_px)]
        rsplits = [by + rm  + v[2] for v in find_valleys(intr.sum(axis=1), gap_px)]
        if debug and (csplits or rsplits):
            print(f"  Split at x={csplits}, y={rsplits}")

        xb = sorted([bx] + csplits + [bx + bw])
        yb = sorted([by] + rsplits + [by + bh])

        for yi in range(len(yb) - 1):
            for xi in range(len(xb) - 1):
                rx1, rx2 = xb[xi], xb[xi+1]
                ry1, ry2 = yb[yi], yb[yi+1]

                sub = bmask[ry1:ry2, rx1:rx2]
                if sub.sum() // 255 < min_area:
                    continue

                # Tight content bbox (v3 approach)
                nnz = np.argwhere(sub > 0)
                r0, c0 = nnz.min(axis=0)
                r1, c1 = nnz.max(axis=0)
                cw2 = c1 - c0
                ch2 = r1 - r0
                cx  = float(rx1 + c0 + cw2 / 2)
                cy  = float(ry1 + r0 + ch2 / 2)

                # Rotation angle (v3 approach)
                sc, _ = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if sc:
                    lc  = max(sc, key=cv2.contourArea)
                    lco = lc + np.array([[[rx1, ry1]]])
                    _, (rw, rh), ang = cv2.minAreaRect(lco)
                    if rw < rh: ang += 90
                    while ang >  45: ang -= 90
                    while ang < -45: ang += 90
                else:
                    ang = 0.0

                lpx = max(cw2, ch2)
                spx = min(cw2, ch2)
                fmt, err = classify(lpx, spx, dpi)

                print(f"    -> {px2mm(lpx,dpi):.0f}x{px2mm(spx,dpi):.0f}mm  "
                      f"angle={ang:.1f}  format={fmt or 'unknown'}"
                      + (f" ({err:.0%})" if fmt else ""))

                # ── Tight crop: symmetric padding (v3 algorithm) ─────────────
                if fmt is None:
                    # Unknown (lab print): expand to physical print edges
                    t = find_print_edge(image, gray, cx, cy, cw2, ch2, ang, dpi, pad_px)
                else:
                    t = tight_crop(image, cx, cy, cw2, ch2, ang, pad_px)

                # ── Card crop: asymmetric border + orientation (new algorithm) ─
                c = None
                lc = None
                if fmt in INSTAX_BORDER:
                    orig_top, orig_bot, orig_side = INSTAX_BORDER[fmt]
                    top_mm, bot_mm, side_mm = orig_top, orig_bot, orig_side
                    rot_card = _is_rotated(fmt, cw2, ch2)
                    if detect_flip(gray, cx, cy, cw2, ch2, ang, dpi,
                                   rotated=rot_card):
                        top_mm, bot_mm = bot_mm, top_mm
                    top_px  = int(mm2px(top_mm,  dpi)) + extra_px
                    bot_px  = int(mm2px(bot_mm,  dpi)) + extra_px
                    side_px = int(mm2px(side_mm, dpi)) + extra_px
                    c = card_crop(image, cx, cy, cw2, ch2, ang,
                                  top_px, bot_px, side_px,
                                  rotated=rot_card)

                    # ── Large card: thick border on all 4 sides, fixed size ───
                    # Always use orig_bot (the physical writing-area border)
                    # so output dimensions are constant for a given format.
                    # Out-of-scan areas are filled with white.
                    large_px = int(mm2px(orig_bot, dpi)) + extra_px
                    lc = large_card_crop(image, cx, cy, cw2, ch2, ang, large_px)

                results.append({"fmt": fmt or "unknown",
                                 "tight": t, "card": c, "large_card": lc,
                                 "cx": cx, "cy": cy})

    row_bucket = int(mm2px(60, dpi))
    results.sort(key=lambda r: (round(r["cy"] / row_bucket), r["cx"]))
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__); sys.exit(0)

    ipath          = Path(args[0])
    odir           = None
    padding_mm     = DEFAULT_PAD
    threshold      = DEFAULT_THR
    dpi_override   = None
    save_tight     = True
    save_card      = True
    save_large_card = True
    debug          = False

    i = 1
    while i < len(args):
        a = args[i]
        if   a == "--debug":                           debug = True
        elif a == "--no-tight":                        save_tight      = False
        elif a == "--no-card":                         save_card       = False
        elif a == "--no-large-card":                   save_large_card = False
        elif a == "--padding"   and i+1 < len(args):  padding_mm   = float(args[i+1]); i += 1
        elif a == "--threshold" and i+1 < len(args):  threshold    = int(args[i+1]);   i += 1
        elif a == "--dpi"       and i+1 < len(args):  dpi_override = float(args[i+1]); i += 1
        elif not a.startswith("--") and odir is None: odir = Path(a)
        i += 1

    if odir is None:
        odir = ipath.parent / (ipath.stem + "_extracted")
    if not ipath.exists():
        print(f"Error: {ipath} not found"); sys.exit(1)

    print(f"\nLoading {ipath} ...")
    image = cv2.imread(str(ipath))
    if image is None:
        print("Error: could not read image."); sys.exit(1)

    img_h, img_w = image.shape[:2]
    dpi = dpi_override if dpi_override else detect_dpi(str(ipath), img_w)
    print(f"  {img_w}x{img_h} px  ({px2mm(img_w,dpi):.0f}x{px2mm(img_h,dpi):.0f} mm)  DPI={dpi:.0f}")
    print(f"  Tight padding: {padding_mm}mm    Border extra: {BORDER_EXTRA}mm    Threshold: {threshold}\n")

    results = detect_photos(image, str(ipath), dpi, padding_mm, threshold, debug)

    if not results:
        print("  No photos detected.\n"
              "  Try --debug, --threshold 190, --threshold 210, or --dpi 300")
        sys.exit(1)

    odir.mkdir(parents=True, exist_ok=True)
    nb = sum(1 for r in results if r["card"] is not None)
    print(f"\n  {len(results)} photo(s) detected ({nb} Instax -> also saved with card border)")
    print(f"  Output: {odir}/\n")

    stem = ipath.stem
    saved = 0
    for idx, r in enumerate(results, 1):
        fmt  = r["fmt"]
        base = f"{stem}_{idx:02d}_{fmt}"

        if save_tight:
            p = odir / f"{base}.jpg"
            cv2.imwrite(str(p), r["tight"], [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
            th2, tw2 = r["tight"].shape[:2]
            print(f"  [{idx:02d}] {fmt:10s}  tight  "
                  f"{tw2}x{th2}px ({px2mm(tw2,dpi):.0f}x{px2mm(th2,dpi):.0f}mm)  -> {p.name}")
            saved += 1

        if save_card and r["card"] is not None:
            p2 = odir / f"{base}_card.jpg"
            cv2.imwrite(str(p2), r["card"], [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
            ch3, cw3 = r["card"].shape[:2]
            print(f"  [{idx:02d}] {fmt:10s}  card   "
                  f"{cw3}x{ch3}px ({px2mm(cw3,dpi):.0f}x{px2mm(ch3,dpi):.0f}mm)  -> {p2.name}")
            saved += 1

        if save_large_card and r["large_card"] is not None:
            p3 = odir / f"{base}_large.jpg"
            cv2.imwrite(str(p3), r["large_card"], [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
            lh, lw = r["large_card"].shape[:2]
            print(f"  [{idx:02d}] {fmt:10s}  large  "
                  f"{lw}x{lh}px ({px2mm(lw,dpi):.0f}x{px2mm(lh,dpi):.0f}mm)  -> {p3.name}")
            saved += 1

    print(f"\nDone.  {saved} file(s) saved.")


if __name__ == "__main__":
    main()
