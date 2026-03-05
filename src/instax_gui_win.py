#!/usr/bin/env python3
"""
instax-scanner — Windows GUI (tkinter) for instax_extract.py
"""

import sys
import os
import io
import contextlib
import threading
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

# Resolve engine path and make it importable (works as script and PyInstaller bundle)
if getattr(sys, "frozen", False):
    _BASE = sys._MEIPASS
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))

if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

import instax_extract as _eng
import cv2


class InstaxApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Instax Scanner")
        self.geometry("860x620")
        self.minsize(700, 500)

        self._files = []
        self._running = False
        self._out_dir = str(Path.home() / "Pictures" / "instax-extracted")

        self._build_ui()
        self._refresh()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg="#2c3e50", pady=8)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Instax Scanner", bg="#2c3e50", fg="white",
                 font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT, padx=16)
        tk.Label(hdr, text="Extract Instax photos from flatbed scans",
                 bg="#2c3e50", fg="#bdc3c7",
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=4)

        # Main horizontal split
        main = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashwidth=4,
                              sashrelief=tk.FLAT, bg="#dfe6e9")
        main.pack(fill=tk.BOTH, expand=True)

        # ── Left panel ──
        left = tk.Frame(main, padx=14, pady=12)
        main.add(left, minsize=280, width=310)

        self._section(left, "Input scans")

        list_frame = tk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        sb = tk.Scrollbar(list_frame)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED,
                                   yscrollcommand=sb.set, height=8,
                                   activestyle="none", font=("Segoe UI", 9))
        self._listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self._listbox.yview)

        btn_row = tk.Frame(left)
        btn_row.pack(fill=tk.X, pady=(0, 10))
        for lbl, cmd in [("Add files…", self._add),
                         ("Remove", self._remove),
                         ("Clear", self._clear)]:
            tk.Button(btn_row, text=lbl, command=cmd,
                      font=("Segoe UI", 9)).pack(side=tk.LEFT, expand=True,
                                                  fill=tk.X, padx=(0, 2))

        self._section(left, "Output folder")
        out_row = tk.Frame(left)
        out_row.pack(fill=tk.X, pady=(0, 10))
        self._out_var = tk.StringVar(value=self._out_dir)
        tk.Entry(out_row, textvariable=self._out_var,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, fill=tk.X,
                                             expand=True, padx=(0, 4))
        tk.Button(out_row, text="Browse…", command=self._browse,
                  font=("Segoe UI", 9)).pack(side=tk.LEFT)

        self._section(left, "Output types  (Instax formats)")
        self._tight_var      = tk.BooleanVar(value=True)
        self._card_var       = tk.BooleanVar(value=True)
        self._large_card_var = tk.BooleanVar(value=True)
        tk.Checkbutton(left, text="Tight crop  — image content + padding",
                       variable=self._tight_var, command=self._on_chk,
                       font=("Segoe UI", 9)).pack(anchor=tk.W)
        tk.Checkbutton(left, text="Card crop  — full white border included",
                       variable=self._card_var, command=self._on_chk,
                       font=("Segoe UI", 9)).pack(anchor=tk.W)
        tk.Checkbutton(left, text="Large card  — thick border on all 4 sides",
                       variable=self._large_card_var, command=self._on_chk,
                       font=("Segoe UI", 9)).pack(anchor=tk.W, pady=(0, 10))

        self._section(left, "Options")
        grid = tk.Frame(left)
        grid.pack(fill=tk.X, pady=(0, 12))

        self._pad_var = tk.DoubleVar(value=1.0)
        self._thr_var = tk.IntVar(value=200)
        self._dpi_var = tk.IntVar(value=0)

        for row, (lbl, var, lo, hi, step, fmt) in enumerate([
            ("Tight padding (mm)",    self._pad_var, 0.0, 20.0, 0.5, "%.1f"),
            ("Threshold (150–250)",   self._thr_var, 150, 250,  1,   "%d"),
            ("DPI override (0=auto)", self._dpi_var, 0,   1200, 25,  "%d"),
        ]):
            tk.Label(grid, text=lbl, font=("Segoe UI", 9),
                     anchor=tk.W).grid(row=row, column=0, sticky=tk.W,
                                       padx=(0, 8), pady=2)
            ttk.Spinbox(grid, from_=lo, to=hi, increment=step,
                        textvariable=var, format=fmt, width=8,
                        font=("Segoe UI", 9)).grid(row=row, column=1,
                                                    sticky=tk.W)

        self._btn_run = tk.Button(left, text="⚙  Extract photos",
                                  command=self._run, font=("Segoe UI", 10, "bold"),
                                  bg="#2980b9", fg="white",
                                  activebackground="#1a6fa3",
                                  activeforeground="white",
                                  relief=tk.FLAT, pady=6)
        self._btn_run.pack(fill=tk.X, pady=(0, 4))

        self._progress = ttk.Progressbar(left, mode="indeterminate",
                                         length=100)

        self._btn_open = tk.Button(left, text="📂  Open output folder",
                                   command=self._open_folder,
                                   font=("Segoe UI", 9),
                                   bg="#27ae60", fg="white",
                                   activebackground="#1e8449",
                                   activeforeground="white",
                                   relief=tk.FLAT, pady=5)

        # ── Right panel (log) ──
        right = tk.Frame(main, padx=14, pady=12)
        main.add(right, minsize=200)

        self._section(right, "Log")
        self._log = ScrolledText(right, state=tk.DISABLED, wrap=tk.WORD,
                                 font=("Consolas", 9), bg="#1e1e1e",
                                 fg="#d4d4d4", insertbackground="white",
                                 relief=tk.FLAT)
        self._log.pack(fill=tk.BOTH, expand=True)

        self._log.tag_config("ok",   foreground="#27ae60")
        self._log.tag_config("err",  foreground="#e74c3c")
        self._log.tag_config("bold", font=("Consolas", 9, "bold"),
                             foreground="#ecf0f1")
        self._log.tag_config("dim",  foreground="#888888")

        # Status bar
        self._status_var = tk.StringVar(
            value="Ready — add scans and click Extract.")
        status = tk.Label(self, textvariable=self._status_var,
                          font=("Segoe UI", 9), anchor=tk.W,
                          relief=tk.SUNKEN, padx=6, pady=3)
        status.pack(side=tk.BOTTOM, fill=tk.X)

    @staticmethod
    def _section(parent, text):
        tk.Label(parent, text=text, font=("Segoe UI", 9, "bold"),
                 anchor=tk.W).pack(fill=tk.X, pady=(6, 2))

    # ── file list ─────────────────────────────────────────────────────────

    def _add(self):
        paths = filedialog.askopenfilenames(
            title="Select scan files",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.tif *.tiff"
                                   " *.JPG *.JPEG *.PNG *.TIF *.TIFF"),
                       ("All files", "*.*")])
        for p in paths:
            if p not in self._files:
                self._files.append(p)
                self._listbox.insert(tk.END, Path(p).name)
        self._refresh()

    def _remove(self):
        for i in reversed(self._listbox.curselection()):
            self._files.pop(i)
            self._listbox.delete(i)
        self._refresh()

    def _clear(self):
        self._files.clear()
        self._listbox.delete(0, tk.END)
        self._refresh()

    def _browse(self):
        cur = self._out_var.get().strip()
        d = filedialog.askdirectory(title="Select output folder",
                                    initialdir=cur if cur else None)
        if d:
            self._out_var.set(d)

    def _on_chk(self):
        if (not self._tight_var.get() and not self._card_var.get()
                and not self._large_card_var.get()):
            self._tight_var.set(True)
        self._refresh()

    # ── extraction ────────────────────────────────────────────────────────

    def _run(self):
        out = self._out_var.get().strip()
        if not out:
            messagebox.showerror("Error", "Please set an output folder.")
            return
        if not self._files:
            messagebox.showerror("Error", "Please add at least one scan file.")
            return

        self._running = True
        self._btn_run.config(state=tk.DISABLED)
        self._btn_open.pack_forget()
        self._progress.pack(fill=tk.X, pady=(0, 4))
        self._progress.start(50)

        self._log.config(state=tk.NORMAL)
        self._log.delete("1.0", tk.END)
        self._log.config(state=tk.DISABLED)

        params = (list(self._files), out,
                  self._pad_var.get(),
                  int(self._thr_var.get()),
                  int(self._dpi_var.get()) or None,
                  self._tight_var.get(),
                  self._card_var.get(),
                  self._large_card_var.get())
        threading.Thread(target=self._worker, args=params, daemon=True).start()

    def _worker(self, files, out_dir, padding, threshold, dpi,
                save_tight, save_card, save_large):
        for i, fp in enumerate(files):
            name = Path(fp).name
            self.after(0, self._append_log,
                       f"\n── {name}  ({i+1}/{len(files)}) ──\n", "bold")
            self.after(0, self._set_status,
                       f"Processing {i+1}/{len(files)}: {name}")

            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    image = cv2.imread(fp)
                    if image is None:
                        raise RuntimeError("Could not read image.")

                    img_h, img_w = image.shape[:2]
                    dpi_val = float(dpi) if dpi else _eng.detect_dpi(fp, img_w)
                    print(f"  {img_w}x{img_h} px  DPI={dpi_val:.0f}  "
                          f"padding={padding}mm  threshold={threshold}\n")

                    results = _eng.detect_photos(
                        image, fp, dpi_val, padding, threshold, False)

                    if not results:
                        print("  No photos detected.\n"
                              "  Try adjusting threshold or DPI override.")
                    else:
                        out_path = Path(out_dir)
                        out_path.mkdir(parents=True, exist_ok=True)
                        stem = Path(fp).stem
                        saved = 0
                        for idx, r in enumerate(results, 1):
                            fmt  = r["fmt"]
                            base = f"{stem}_{idx:02d}_{fmt}"
                            if save_tight:
                                p = out_path / f"{base}.jpg"
                                cv2.imwrite(str(p), r["tight"],
                                            [cv2.IMWRITE_JPEG_QUALITY, 95])
                                th2, tw2 = r["tight"].shape[:2]
                                print(f"  [{idx:02d}] {fmt:10s}  tight  "
                                      f"{tw2}x{th2}px  -> {p.name}")
                                saved += 1
                            if save_card and r["card"] is not None:
                                p2 = out_path / f"{base}_card.jpg"
                                cv2.imwrite(str(p2), r["card"],
                                            [cv2.IMWRITE_JPEG_QUALITY, 95])
                                ch3, cw3 = r["card"].shape[:2]
                                print(f"  [{idx:02d}] {fmt:10s}  card   "
                                      f"{cw3}x{ch3}px  -> {p2.name}")
                                saved += 1
                            if save_large and r["large_card"] is not None:
                                p3 = out_path / f"{base}_large.jpg"
                                cv2.imwrite(str(p3), r["large_card"],
                                            [cv2.IMWRITE_JPEG_QUALITY, 95])
                                lh, lw = r["large_card"].shape[:2]
                                print(f"  [{idx:02d}] {fmt:10s}  large  "
                                      f"{lw}x{lh}px  -> {p3.name}")
                                saved += 1
                        print(f"\nDone.  {saved} file(s) saved.")

            except Exception as e:
                buf.write(f"Error: {e}\n")

            for line in buf.getvalue().splitlines():
                if not line:
                    continue
                tag = ("err" if "Error" in line or "error" in line
                       else "ok"  if "Done." in line
                       else "dim" if line.startswith("  [")
                       else None)
                self.after(0, self._append_log, line + "\n", tag)

        self.after(0, self._finish, out_dir, len(files))

    def _finish(self, out_dir, n):
        self._running = False
        self._progress.stop()
        self._progress.pack_forget()
        self._btn_run.config(state=tk.NORMAL)
        self._btn_open.pack(fill=tk.X, pady=(0, 4))
        msg = f"Done — {n} file(s) processed.  Output: {out_dir}"
        self._set_status(msg)
        self._append_log(f"\n✓ {msg}\n", "ok")
        self._refresh()

    def _open_folder(self):
        path = self._out_var.get().strip()
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])

    # ── helpers ───────────────────────────────────────────────────────────

    def _refresh(self):
        can_run = (bool(self._files) and not self._running
                   and (self._tight_var.get() or self._card_var.get()
                        or self._large_card_var.get()))
        self._btn_run.config(state=tk.NORMAL if can_run else tk.DISABLED)

    def _append_log(self, text, tag=None):
        self._log.config(state=tk.NORMAL)
        if tag:
            self._log.insert(tk.END, text, tag)
        else:
            self._log.insert(tk.END, text)
        self._log.see(tk.END)
        self._log.config(state=tk.DISABLED)

    def _set_status(self, msg):
        self._status_var.set(msg)


if __name__ == "__main__":
    app = InstaxApp()
    app.mainloop()
