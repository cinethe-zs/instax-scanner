# instax-scanner

Extract individual Instax photos from flatbed A4 scanner scans.

## Project layout

```
instax-scanner/
├── build.sh                  ← Linux build script → produces .deb
├── build_windows.bat         ← Windows build script → produces .exe
├── README.md
├── src/
│   ├── instax_extract.py     ← extraction engine (CLI + library, cross-platform)
│   ├── instax_gui.py         ← GTK3 GUI frontend (Linux)
│   └── instax_gui_win.py     ← tkinter GUI frontend (Windows)
├── debian/
│   ├── control               ← package metadata / dependencies
│   ├── postinst              ← post-install hook (icon cache, desktop db)
│   └── launcher              ← /usr/bin/instax-scanner shell wrapper
└── assets/
    ├── instax-scanner.desktop ← freedesktop app menu entry
    └── instax-scanner.png    ← 128×128 app icon
```

---

## Windows

### Build

Requires Python 3.8+ on PATH. Run once from the project root:

```bat
build_windows.bat
```

This creates a virtualenv, installs `opencv-python`, `numpy`, and `pyinstaller`, then produces a single standalone executable:

```
dist\instax-scanner.exe
```

No Python installation required to run the exe.

### Install

Just copy `dist\instax-scanner.exe` anywhere and double-click it.

---

## Linux

### Build the .deb

```bash
chmod +x build.sh
./build.sh            # produces instax-scanner_1.1.0_all.deb
./build.sh 1.0.3      # custom version number
```

Requires only `dpkg-deb` (standard on any Debian/Ubuntu system).

### Install

```bash
# Dependencies
sudo apt install python3-gi python3-opencv gir1.2-gtk-3.0

# Package
sudo dpkg -i instax-scanner_1.1.0_all.deb
```

Then launch **Instax Scanner** from your app menu, or run `instax-scanner`.

---

## Engine: instax_extract.py

### Supported formats

| Format | Image area  | Top border | Bottom border | Side borders |
|--------|-------------|-----------|---------------|--------------|
| Mini   | 62 × 46 mm  | 6 mm      | 15 mm         | 4 mm         |
| Square | 62 × 62 mm  | 7 mm      | 17 mm         | 5 mm         |
| Wide   | 99 × 62 mm  | 6 mm      | 15 mm         | 4.5 mm       |

### CLI usage

```bash
python3 instax_extract.py scan.jpg
python3 instax_extract.py scan.jpg output_folder/
python3 instax_extract.py scan.jpg --padding 2 --dpi 300 --debug
```

| Flag | Default | Description |
|------|---------|-------------|
| `--padding N` | 1 | Tight crop padding in mm |
| `--threshold N` | 200 | Brightness threshold for content detection |
| `--dpi N` | auto | Override DPI (reads JFIF header, falls back to A4 width inference) |
| `--no-tight` | — | Skip tight crop output |
| `--no-card` | — | Skip card-border crop output (Instax only) |
| `--no-large-card` | — | Skip large card crop output (Instax only) |
| `--debug` | — | Save intermediate mask images |

### Output naming

```
scan_01_mini.jpg          ← tight crop (content + padding)
scan_01_mini_card.jpg     ← card crop (full white border, asymmetric)
scan_01_mini_large.jpg    ← large card crop (thick border on all 4 sides)
scan_02_square.jpg
scan_02_square_card.jpg
scan_02_square_large.jpg
scan_03_unknown.jpg       ← non-Instax print (tight crop only)
```

### Algorithm summary

1. **DPI detection** — reads JFIF header; falls back to A4-width inference; snaps to standard values (75–1200).
2. **Foreground mask** — threshold + morphological close with DPI-scaled kernel (≈1 mm at any DPI).
3. **Blob detection** — minimum area = 15 mm², valley-projection split for touching photos.
4. **Format classification** — compares long/short axes (±22% tolerance) against known Instax sizes.
5. **Orientation detection** — brightness probe at 8 mm outside each content edge to locate the thick writing border; handles rotated cards and edge-of-scan placement.
6. **Tight crop** — symmetric 1 mm padding around content bbox.
7. **Card crop** — asymmetric padding matching the physical white border; top/bottom swapped if card is flipped.
8. **Large card crop** — symmetric padding using the thick border dimension (writing area) on all 4 sides; gives a fixed-size output per format regardless of card orientation. Scanner backlight colour is sampled from the four corners of the scan and used to fill any area outside the scan boundary.
9. **Unknown format** — tight crop only (blob bbox = print boundary for standard photographic prints).

---

## GUI

Both GUIs share the same features:
- Multi-file picker (JPEG / PNG / TIFF)
- Output folder browser
- Checkboxes: **Tight crop** / **Card crop** / **Large card** (all on by default; at least one required)
- Options: padding, threshold, DPI override
- Colour-coded log with auto-scroll
- "Open output folder" button appears on completion
- Progress bar during processing

### instax_gui.py — Linux (GTK3)

GTK3 application (`io.github.instax_scanner`).

| Package | Provides |
|---------|---------|
| `python3-gi` | GObject introspection bindings |
| `gir1.2-gtk-3.0` | GTK3 typelib |
| `python3-opencv` | cv2 (extraction engine) |
| `python3-numpy` | numpy (recommended) |

### instax_gui_win.py — Windows (tkinter)

![Instax Scanner — Windows GUI](assets/screenshot-windows-gui.png)

Standalone tkinter application bundled into `instax-scanner.exe` via PyInstaller. No external dependencies required at runtime — everything is included in the exe.
