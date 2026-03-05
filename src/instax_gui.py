#!/usr/bin/env python3
"""
instax-scanner — GTK3 GUI for instax_extract.py
"""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango

import sys, os, threading, subprocess
from pathlib import Path

ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instax_extract.py")


class InstaxWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Instax Scanner")
        self.set_default_size(820, 620)
        self._files   = []
        self._running = False
        self._out_dir = str(Path.home() / "Pictures" / "instax-extracted")
        self._build_ui()
        self.show_all()
        self._progress.hide()
        self._btn_open.hide()

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _h(text):
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup(f"<b>{text}</b>")
        return lbl

    def _spin(self, lo, hi, step, val, digits=0):
        s = Gtk.SpinButton.new_with_range(lo, hi, step)
        s.set_value(val); s.set_digits(digits)
        return s

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        hb = Gtk.HeaderBar(title="Instax Scanner",
                           subtitle="Extract Instax photos from flatbed scans",
                           show_close_button=True)
        self.set_titlebar(hb)

        # top-level vbox (content + statusbar)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(vbox)

        # horizontal split
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        vbox.pack_start(hbox, True, True, 0)

        # ---------- LEFT PANEL ----------
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        left.set_border_width(16)
        left.set_size_request(310, -1)
        hbox.pack_start(left, False, False, 0)
        hbox.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        # Input files
        left.pack_start(self._h("Input scans"), False, False, 0)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_min_content_height(150)
        left.pack_start(sw, True, True, 0)

        self._store = Gtk.ListStore(str, str)
        self._tv = Gtk.TreeView(model=self._store)
        self._tv.set_headers_visible(False)
        self._tv.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self._tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
        sw.add(self._tv)

        btn_row = Gtk.Box(spacing=6)
        left.pack_start(btn_row, False, False, 0)
        for lbl, cb in [("Add files…", self._add), ("Remove", self._remove), ("Clear", self._clear)]:
            b = Gtk.Button(label=lbl)
            b.connect("clicked", cb)
            btn_row.pack_start(b, True, True, 0)

        # Output folder
        left.pack_start(self._h("Output folder"), False, False, 0)
        out_row = Gtk.Box(spacing=6)
        left.pack_start(out_row, False, False, 0)
        self._out_entry = Gtk.Entry(text=self._out_dir, hexpand=True)
        out_row.pack_start(self._out_entry, True, True, 0)
        b = Gtk.Button(label="Browse…")
        b.connect("clicked", self._browse)
        out_row.pack_start(b, False, False, 0)

        # Output types
        left.pack_start(self._h("Output types  (Instax formats)"), False, False, 0)
        self._chk_tight = Gtk.CheckButton(label="Tight crop  — image content + padding")
        self._chk_tight.set_active(True)
        self._chk_tight.connect("toggled", self._on_chk_toggled)
        left.pack_start(self._chk_tight, False, False, 0)

        self._chk_card = Gtk.CheckButton(label="Card crop  — full white border included")
        self._chk_card.set_active(True)
        self._chk_card.connect("toggled", self._on_chk_toggled)
        left.pack_start(self._chk_card, False, False, 0)

        self._chk_large = Gtk.CheckButton(label="Large card  — thick border on all 4 sides")
        self._chk_large.set_active(True)
        self._chk_large.connect("toggled", self._on_chk_toggled)
        left.pack_start(self._chk_large, False, False, 0)

        # Options
        left.pack_start(self._h("Options"), False, False, 0)
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        left.pack_start(grid, False, False, 0)

        grid.attach(Gtk.Label(label="Tight padding (mm)", xalign=0), 0, 0, 1, 1)
        self._pad = self._spin(0, 20, 0.5, 1.0, digits=1)
        grid.attach(self._pad, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="Threshold (150–250)", xalign=0), 0, 1, 1, 1)
        self._thr = self._spin(150, 250, 1, 200)
        grid.attach(self._thr, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="DPI override (0 = auto)", xalign=0), 0, 2, 1, 1)
        self._dpi = self._spin(0, 1200, 25, 0)
        grid.attach(self._dpi, 1, 2, 1, 1)

        # Run button + progress + open folder
        self._btn_run = Gtk.Button(label="⚙  Extract photos")
        self._btn_run.get_style_context().add_class("suggested-action")
        self._btn_run.set_margin_top(4)
        self._btn_run.connect("clicked", self._run)
        left.pack_start(self._btn_run, False, False, 0)

        self._progress = Gtk.ProgressBar(pulse_step=0.07)
        left.pack_start(self._progress, False, False, 0)

        self._btn_open = Gtk.Button(label="📂  Open output folder")
        self._btn_open.connect("clicked", lambda _: subprocess.Popen(
            ["xdg-open", self._out_entry.get_text().strip()]))
        left.pack_start(self._btn_open, False, False, 0)

        # ---------- RIGHT PANEL (log) ----------
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        right.set_border_width(16)
        hbox.pack_start(right, True, True, 0)

        right.pack_start(self._h("Log"), False, False, 0)

        self._log_sw = Gtk.ScrolledWindow()
        self._log_sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        right.pack_start(self._log_sw, True, True, 0)

        self._buf = Gtk.TextBuffer()
        tv2 = Gtk.TextView(buffer=self._buf, editable=False,
                           cursor_visible=False,
                           wrap_mode=Gtk.WrapMode.WORD_CHAR)
        tv2.modify_font(Pango.FontDescription("Monospace 9"))
        self._log_sw.add(tv2)

        for name, fg, bold in [("ok","#27ae60",False),("err","#e74c3c",False),
                                ("bold",None,True),("dim","#888888",False)]:
            t = self._buf.create_tag(name)
            if fg:   t.set_property("foreground", fg)
            if bold: t.set_property("weight", Pango.Weight.BOLD)

        # Status bar
        self._sb  = Gtk.Statusbar()
        self._ctx = self._sb.get_context_id("m")
        vbox.pack_start(self._sb, False, False, 0)
        self._status("Ready — add scans and click Extract.")
        self._refresh()

    # ── file list ─────────────────────────────────────────────────────────

    def _add(self, _):
        dlg = Gtk.FileChooserDialog(title="Select scan files", parent=self,
                                    action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        Gtk.STOCK_OPEN,   Gtk.ResponseType.OK)
        dlg.set_select_multiple(True)
        f = Gtk.FileFilter()
        f.set_name("Images (JPEG / PNG / TIFF)")
        for p in ("*.jpg","*.jpeg","*.png","*.tif","*.tiff",
                  "*.JPG","*.JPEG","*.PNG","*.TIF","*.TIFF"):
            f.add_pattern(p)
        dlg.add_filter(f)
        fa = Gtk.FileFilter(); fa.set_name("All files"); fa.add_pattern("*")
        dlg.add_filter(fa)
        if dlg.run() == Gtk.ResponseType.OK:
            for p in dlg.get_filenames():
                if p not in self._files:
                    self._files.append(p)
                    self._store.append([Path(p).name, p])
        dlg.destroy()
        self._refresh()

    def _remove(self, _):
        _, rows = self._tv.get_selection().get_selected_rows()
        for p in reversed(rows):
            i = p.get_indices()[0]
            self._files.pop(i)
            self._store.remove(self._store.get_iter(p))
        self._refresh()

    def _clear(self, _):
        self._files.clear(); self._store.clear(); self._refresh()

    def _browse(self, _):
        dlg = Gtk.FileChooserDialog(title="Select output folder", parent=self,
                                    action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        Gtk.STOCK_OPEN,   Gtk.ResponseType.OK)
        cur = self._out_entry.get_text().strip()
        if cur: dlg.set_filename(cur)
        if dlg.run() == Gtk.ResponseType.OK:
            self._out_entry.set_text(dlg.get_filename())
        dlg.destroy()

    def _on_chk_toggled(self, _):
        # Prevent all boxes being unchecked at the same time
        if (not self._chk_tight.get_active() and not self._chk_card.get_active()
                and not self._chk_large.get_active()):
            widget = _
            widget.set_active(True)
        self._refresh()

    # ── extraction ────────────────────────────────────────────────────────

    def _run(self, _):
        out = self._out_entry.get_text().strip()
        if not out:        return self._err("Please set an output folder.")
        if not self._files: return self._err("Please add at least one scan file.")
        self._running = True
        self._btn_run.set_sensitive(False)
        self._btn_open.hide()
        self._progress.show()
        self._buf.set_text("")
        params = (list(self._files), out,
                  self._pad.get_value(),
                  int(self._thr.get_value()),
                  int(self._dpi.get_value()) or None,
                  self._chk_tight.get_active(),
                  self._chk_card.get_active(),
                  self._chk_large.get_active())
        threading.Thread(target=self._worker, args=params, daemon=True).start()

    def _worker(self, files, out_dir, padding, threshold, dpi,
                save_tight, save_card, save_large):
        for i, fp in enumerate(files):
            name = Path(fp).name
            GLib.idle_add(self._progress.pulse)
            GLib.idle_add(self._log, f"\n── {name}  ({i+1}/{len(files)}) ──\n", "bold")
            GLib.idle_add(self._status, f"Processing {i+1}/{len(files)}: {name}")

            cmd = [sys.executable, ENGINE, fp, out_dir,
                   "--padding", str(padding), "--threshold", str(threshold)]
            if dpi:             cmd += ["--dpi", str(dpi)]
            if not save_tight:  cmd += ["--no-tight"]
            if not save_card:   cmd += ["--no-card"]
            if not save_large:  cmd += ["--no-large-card"]

            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True)
                for line in proc.stdout:
                    line = line.rstrip()
                    if not line: continue
                    tag = ("err" if "Error" in line or "error" in line
                           else "ok"  if "Done." in line
                           else "dim" if line.startswith("  [")
                           else None)
                    GLib.idle_add(self._log, line + "\n", tag)
                proc.wait()
                if proc.returncode != 0:
                    GLib.idle_add(self._log,
                                  f"Process exited with code {proc.returncode}\n","err")
            except Exception as e:
                GLib.idle_add(self._log, f"Error: {e}\n", "err")

        GLib.idle_add(self._finish, out_dir, len(files))

    def _finish(self, out_dir, n):
        self._running = False
        self._btn_run.set_sensitive(True)
        self._progress.hide()
        self._btn_open.show()
        msg = f"Done — {n} file(s) processed.  Output: {out_dir}"
        self._status(msg)
        self._log(f"\n✓ {msg}\n", "ok")

    # ── small helpers ─────────────────────────────────────────────────────

    def _refresh(self):
        can_run = (bool(self._files) and not self._running
                   and (self._chk_tight.get_active() or self._chk_card.get_active()
                        or self._chk_large.get_active()))
        self._btn_run.set_sensitive(can_run)

    def _log(self, text, tag=None):
        it = self._buf.get_end_iter()
        if tag: self._buf.insert_with_tags_by_name(it, text, tag)
        else:   self._buf.insert(it, text)
        adj = self._log_sw.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())

    def _status(self, msg):
        self._sb.pop(self._ctx); self._sb.push(self._ctx, msg)

    def _err(self, msg):
        dlg = Gtk.MessageDialog(parent=self, flags=Gtk.DialogFlags.MODAL,
                                type=Gtk.MessageType.ERROR,
                                buttons=Gtk.ButtonsType.OK, message_format=msg)
        dlg.run(); dlg.destroy()


class InstaxApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="io.github.instax_scanner")
    def do_activate(self):
        InstaxWindow(self).present()


if __name__ == "__main__":
    import sys
    sys.exit(InstaxApp().run(sys.argv))
