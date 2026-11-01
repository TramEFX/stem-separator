"""Stem Separator: a Tk front end for audio-separator (BS-/MelBand-Roformer) on the GPU.

The separation runs in separate_worker.py as a subprocess; this window builds the command line, parses the
worker's '@@' JSON events and kills the process on Cancel. The look (fonts, metal buttons, HUD panels) lives
in scifi_ui.py.
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import ImageTk

import scifi_ui as ui
from scifi_ui import C, px

try:
    from tkinterdnd2 import COPY, DND_FILES, REFUSE_DROP, TkinterDnD
except ImportError:  # installs from before 1.1 lack it; the app then runs without drag and drop
    TkinterDnD = None

APP_VERSION = "1.1"
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(HERE, "models")
SETTINGS = os.path.join(HERE, "settings.json")
WORKER = os.path.join(HERE, "separate_worker.py")
AUDIO_EXTS = (".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".aiff", ".aif", ".wma")
AUDIO_TYPES = [("Audio", " ".join("*" + e for e in AUDIO_EXTS)), ("All files", "*.*")]

# (label, checkpoint filename, short tag used in output folder names, stems)
MODELS = [
    ("BS-Roformer Viperx 1297", "model_bs_roformer_ep_317_sdr_12.9755.ckpt", "BS-Roformer 1297", "Vocals + Instrumental"),
    ("MelBand Roformer Kim (vocals)", "vocals_mel_band_roformer.ckpt", "MelBand Kim", "Vocals + Other"),
    ("MelBand Roformer Big Beta 6X (unwa, vocals)", "melband_roformer_big_beta6x.ckpt", "MelBand Beta6X", "Vocals + Other"),
    ("MelBand Roformer Inst V2 (unwa)", "melband_roformer_inst_v2.ckpt", "MelBand InstV2", "Instrumental + Vocals"),
    ("MelBand Roformer INSTV8 (Gabox)", "mel_band_roformer_instrumental_instv8_gabox.ckpt", "MelBand INSTV8", "Instrumental + Vocals"),
    ("MelBand Roformer Karaoke (becruily)", "mel_band_roformer_karaoke_becruily.ckpt", "Karaoke", "Lead vocals + Backing/instrumental"),
    ("BS-Roformer SW (jarredou, 6 stems)", "BS-Roformer-SW.ckpt", "BS-Roformer SW", "Vocals, Drums, Bass, Guitar, Piano, Other"),
    ("MelBand Roformer De-Reverb (anvuew)", "dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt", "De-Reverb", "No reverb + Reverb"),
    ("MelBand Roformer Denoise (aufr33)", "denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt", "Denoise", "Dry + Noise"),
]
FORMATS = ["WAV", "FLAC", "MP3"]


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def worker_python():
    """python.exe next to pythonw.exe, so the worker's stdout pipe works; the window is hidden via CREATE_NO_WINDOW."""
    exe = sys.executable
    candidate = os.path.join(os.path.dirname(exe), "python.exe")
    return candidate if os.path.isfile(candidate) else exe


def clock(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def audio_files(paths):
    """Expand dropped paths: audio files as they are, folders to every audio file inside them. Returns (files, skipped)."""
    found, skipped = [], 0
    for p in paths:
        if os.path.isdir(p):
            for folder, dirs, names in os.walk(p):
                dirs.sort()
                found += [os.path.join(folder, n) for n in sorted(names) if n.lower().endswith(AUDIO_EXTS)]
        elif p.lower().endswith(AUDIO_EXTS):
            found.append(p)
        else:
            skipped += 1
    return found, skipped


class App:
    def __init__(self, root):
        self.root = root
        self.proc = None
        self.events = queue.Queue()
        self.cancelled = False
        self.paths = []
        self.file_count = 0
        self.file_index = 0
        self.started = 0.0
        self.current = ""
        self.done_failed = 0
        self.last_folder = None
        self._clock_job = None
        s = load_settings()

        self.fonts = f = ui.init_theme(root)
        root.title("Stem Separator")
        root.geometry(f"{px(880)}x{px(830)}")
        root.minsize(px(780), px(760))
        self.icons = [ImageTk.PhotoImage(ui.render_icon(n), master=root) for n in (16, 32, 48, 256)]
        root.iconphoto(True, *self.icons)

        shell = tk.Frame(root, bg=C["bg"])  # drop target covering the whole window, margins included
        shell.pack(fill="both", expand=True)
        main = tk.Frame(shell, bg=C["bg"])
        main.pack(fill="both", expand=True, padx=px(18), pady=(px(8), px(14)))
        main.columnconfigure(0, weight=1, uniform="half")
        main.columnconfigure(1, weight=1, uniform="half")
        main.rowconfigure(3, weight=1)

        self.header = ui.Header(main, f, "STEM SEPARATOR", f"ROFORMER NEURAL SOURCE SEPARATION  //  V{APP_VERSION}")
        self.header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, px(6)))

        # 01 source audio
        p = ui.HudPanel(main, 1, "Source audio", f)
        p.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=px(4))
        b = p.body
        b.columnconfigure(0, weight=1)
        self.files = tk.Listbox(b, height=5, selectmode="extended", activestyle="none", relief="flat", bd=0,
                                bg=C["field"], fg=C["text"], selectbackground=C["accent_dim"],
                                selectforeground="#ffffff", highlightthickness=1, highlightbackground=C["line_hi"],
                                highlightcolor=C["accent_dim"], font=f.mono(10))
        self.files.grid(row=0, column=0, sticky="nsew")
        self.files.bind("<Delete>", lambda e: self.remove_files())
        sb = ttk.Scrollbar(b, orient="vertical", style="Hud.Vertical.TScrollbar", command=self.files.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.files.configure(yscrollcommand=sb.set)
        self.empty_hint = tk.Label(self.files, text="NO SOURCE LOADED  //  PRESS ADD TO QUEUE AUDIO FILES",
                                   bg=C["field"], fg=C["faint"], font=f.mono(9))
        self.drop_hint = tk.Label(self.files, text="RELEASE TO QUEUE  //  AUDIO FILES AND FOLDERS",
                                  bg=C["accent_deep"], fg=C["accent"], font=f.mono(10))
        self._drop_shown = False
        side = tk.Frame(b, bg=C["panel"])
        side.grid(row=0, column=2, sticky="n", padx=(px(10), 0))
        self.add_btn = ui.MetalButton(side, "Add", self.add_files, width=116, height=30, icon="plus")
        self.remove_btn = ui.MetalButton(side, "Remove", self.remove_files, width=116, height=30, icon="minus")
        self.clear_btn = ui.MetalButton(side, "Clear", self.clear_files, width=116, height=30, icon="x")
        for w in (self.add_btn, self.remove_btn, self.clear_btn):
            w.pack()

        # 02 model
        p = ui.HudPanel(main, 2, "Model", f)
        p.grid(row=2, column=0, sticky="nsew", pady=px(4), padx=(0, px(6)))
        b = p.body
        b.columnconfigure(1, weight=1)
        labels = [m[0] for m in MODELS]
        self.model = tk.StringVar(value=s.get("model") if s.get("model") in labels else labels[0])
        self.model_box = ttk.Combobox(b, textvariable=self.model, values=labels, state="readonly",
                                      style="Hud.TCombobox", font=f.ui(12))
        self.model_box.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, px(10)))
        self.model_box.bind("<<ComboboxSelected>>", lambda e: (self.model_box.selection_clear(), self.update_model_info()))
        self.stems_label = self._readout(b, 1, "STEMS")
        self.cache_label = self._readout(b, 2, "CACHE")
        self._key(b, 3, "FP16")
        self.fp16 = tk.BooleanVar(value=s.get("fp16", True))
        row = tk.Frame(b, bg=C["panel"])
        row.grid(row=3, column=1, sticky="w", pady=(px(6), 0))
        self.fp16_switch = ui.ToggleSwitch(row, self.fp16)
        self.fp16_switch.pack(side="left")
        tk.Label(row, text="HALF PRECISION  ·  FASTER ON GPU", bg=C["panel"], fg=C["dim"],
                 font=f.mono(8)).pack(side="left", padx=(px(10), 0))

        # 03 output
        p = ui.HudPanel(main, 3, "Output", f)
        p.grid(row=2, column=1, sticky="nsew", pady=px(4), padx=(px(6), 0))
        b = p.body
        b.columnconfigure(0, weight=1)
        default_out = os.path.join(os.path.expanduser("~"), "Music", "Stems")
        self.out = tk.StringVar(value=s.get("output", default_out))
        box = tk.Frame(b, bg=C["field"], highlightthickness=1, highlightbackground=C["line_hi"])
        box.grid(row=0, column=0, sticky="ew")
        self.out_entry = tk.Entry(box, textvariable=self.out, relief="flat", bd=0, bg=C["field"], fg=C["text"],
                                  insertbackground=C["accent"], highlightthickness=0, disabledbackground=C["field"],
                                  disabledforeground=C["dim"], font=f.mono(10))
        self.out_entry.pack(fill="x", padx=px(8), ipady=px(6))
        self.out_entry.bind("<FocusIn>", lambda e: box.configure(highlightbackground=C["accent_dim"]))
        self.out_entry.bind("<FocusOut>", lambda e: box.configure(highlightbackground=C["line_hi"]))
        self.browse_btn = ui.MetalButton(b, "", self.browse_out, width=44, height=30, icon="folder")
        self.browse_btn.grid(row=0, column=1, padx=(px(6), 0))
        row = tk.Frame(b, bg=C["panel"])
        row.grid(row=1, column=0, columnspan=2, sticky="w", pady=(px(8), 0))
        tk.Label(row, text="FORMAT", bg=C["panel"], fg=C["dim"], font=f.mono(9), width=7, anchor="w").pack(side="left")
        self.fmt = tk.StringVar(value=s.get("format") if s.get("format") in FORMATS else "WAV")
        self.fmt_choice = ui.SegmentedChoice(row, [(x, x) for x in FORMATS], self.fmt)
        self.fmt_choice.pack(side="left")
        tk.Label(b, text="NEW FOLDER EACH RUN  //  <SONG> [MODEL] (2), (3) ...", bg=C["panel"],
                 fg=C["faint"], font=f.mono(8), anchor="w").grid(row=2, column=0, columnspan=2, sticky="w",
                                                                 pady=(px(10), 0))

        # 04 process
        p = ui.HudPanel(main, 4, "Process", f)
        p.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=px(4))
        b = p.body
        b.columnconfigure(0, weight=1)
        b.rowconfigure(4, weight=1)
        self.status = tk.Label(b, text="STANDBY  //  LOAD SOURCE AUDIO, THEN PRESS SEPARATE", bg=C["panel"],
                               fg=C["text"], font=f.mono(10), anchor="w")
        self.status.grid(row=0, column=0, sticky="ew")
        self.pct = tk.Label(b, text="0%", bg=C["panel"], fg=C["accent"], font=f.display(13), anchor="e")
        self.pct.grid(row=0, column=1, sticky="e")
        self.file_bar = ui.SegmentBar(b)
        self.file_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(px(4), px(10)))
        self.song_label = tk.Label(b, text="QUEUE  0 / 0", bg=C["panel"], fg=C["dim"], font=f.mono(9), anchor="w")
        self.song_label.grid(row=2, column=0, sticky="w")
        self.elapsed = tk.Label(b, text="T+ 00:00", bg=C["panel"], fg=C["dim"], font=f.mono(9), anchor="e")
        self.elapsed.grid(row=2, column=1, sticky="e")
        self.total_bar = ui.SegmentBar(b, height=10)
        self.total_bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(px(4), px(10)))
        log_frame = tk.Frame(b, bg=C["panel"])
        log_frame.grid(row=4, column=0, columnspan=2, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(log_frame, height=5, wrap="word", state="disabled", relief="flat", bd=0, bg=C["field"],
                           fg=C["dim"], insertbackground=C["accent"], selectbackground=C["accent_dim"],
                           highlightthickness=1, highlightbackground=C["line_hi"], highlightcolor=C["line_hi"],
                           padx=px(8), pady=px(6), font=f.mono(9))
        self.log.grid(row=0, column=0, sticky="nsew")
        for tag, color in (("ok", C["ok"]), ("err", C["err"]), ("info", C["accent"]), ("warn", C["warn"])):
            self.log.tag_configure(tag, foreground=color)
        lsb = ttk.Scrollbar(log_frame, orient="vertical", style="Hud.Vertical.TScrollbar", command=self.log.yview)
        lsb.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=lsb.set)

        # footer
        foot = tk.Frame(main, bg=C["bg"])
        foot.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(px(8), 0))
        self.open_btn = ui.MetalButton(foot, "Open output", self.open_output, width=170, height=36, icon="folder")
        self.open_btn.pack(side="left")
        self.run_btn = ui.MetalButton(foot, "Separate", self.start, width=190, height=40, icon="play",
                                      primary=True, font_px=13)
        self.run_btn.pack(side="right")
        self.cancel_btn = ui.MetalButton(foot, "Cancel", self.cancel, width=140, height=36, icon="stop")
        self.cancel_btn.pack(side="right", padx=(0, px(6)))
        self.cancel_btn.set_enabled(False)

        if self.enable_drop(shell):
            self.empty_hint.configure(text="NO SOURCE LOADED  //  DROP AUDIO HERE OR PRESS ADD")
        self.refresh_files()
        self.update_model_info()
        self.write_log(f">> STEM SEPARATOR V{APP_VERSION}  //  SYSTEM READY", "info")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.poll)
        ui.style_titlebar(root)

    # ---- small builders
    def _key(self, parent, row, text):
        tk.Label(parent, text=text, bg=C["panel"], fg=C["dim"], font=self.fonts.mono(9), width=7,
                 anchor="w").grid(row=row, column=0, sticky="w", pady=(px(6) if row == 3 else 0, 0))

    def _readout(self, parent, row, key):
        self._key(parent, row, key)
        value = tk.Label(parent, bg=C["panel"], fg=C["text"], font=self.fonts.ui(12), anchor="w")
        value.grid(row=row, column=1, columnspan=2, sticky="w")
        return value

    # ---- helpers
    def selected_model(self):
        return next(m for m in MODELS if m[0] == self.model.get())

    def update_model_info(self):
        _, filename, _, stems = self.selected_model()
        self.stems_label.configure(text=stems)
        if os.path.isfile(os.path.join(MODEL_DIR, filename)):
            self.cache_label.configure(text="Ready on disk", fg=C["ok"])
        else:
            self.cache_label.configure(text="Downloads on first use (~0.6-0.9 GB)", fg=C["warn"])

    def refresh_files(self):
        self.files.delete(0, "end")
        for i, path in enumerate(self.paths, 1):
            self.files.insert("end", f" {i:02d}   {os.path.basename(path)}")
        if self.paths:
            self.empty_hint.place_forget()
        else:
            self.empty_hint.place(relx=0.5, rely=0.5, anchor="center")
        self.song_label.configure(text=f"QUEUE  0 / {len(self.paths)}")

    def write_log(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_status(self, text, color=None):
        self.status.configure(text=text.replace("…", "...").upper(), fg=color or C["text"])

    def set_running(self, running):
        for w in (self.add_btn, self.remove_btn, self.clear_btn, self.browse_btn, self.fp16_switch,
                  self.fmt_choice):
            w.set_enabled(not running)
        self.run_btn.set_enabled(not running)
        self.cancel_btn.set_enabled(running)
        self.model_box.configure(state="disabled" if running else "readonly")
        self.out_entry.configure(state="disabled" if running else "normal")

    def save_settings(self):
        data = {"model": self.model.get(), "output": self.out.get(), "format": self.fmt.get(), "fp16": self.fp16.get()}
        try:
            with open(SETTINGS, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def tick_clock(self):
        self.elapsed.configure(text="T+ " + clock(time.monotonic() - self.started))
        self._clock_job = self.root.after(500, self.tick_clock)

    # ---- drag and drop
    def enable_drop(self, widget):
        """Accept files and folders dropped anywhere on `widget`. Returns False when tkinterdnd2 is unavailable."""
        if TkinterDnD is None:
            return False
        try:
            TkinterDnD.require(self.root)
        except RuntimeError:
            return False
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<DropEnter>>", self.on_drag)
        widget.dnd_bind("<<DropPosition>>", self.on_drag)
        widget.dnd_bind("<<DropLeave>>", lambda e: self.show_drop_zone(False))
        widget.dnd_bind("<<Drop>>", self.on_drop)
        return True

    def show_drop_zone(self, on):
        if on == self._drop_shown:
            return
        self._drop_shown = on
        if on:
            self.drop_hint.place(relx=0, rely=0, relwidth=1, relheight=1)
        else:
            self.drop_hint.place_forget()
        self.files.configure(highlightbackground=C["accent"] if on else C["line_hi"])

    def on_drag(self, event):
        if self.proc:  # the queue is fixed while a separation runs
            return REFUSE_DROP
        self.show_drop_zone(True)
        return COPY  # never MOVE: Explorer would then delete the originals

    def on_drop(self, event):
        self.show_drop_zone(False)
        if self.proc:
            return REFUSE_DROP
        found, skipped = audio_files(self.root.tk.splitlist(event.data))
        self.add_paths(found)
        if not found:
            self.write_log("   drop ignored: no audio files in it", "warn")
        elif skipped:
            self.write_log(f"   skipped {skipped} non-audio item{'s' * (skipped > 1)}", "warn")
        return COPY

    # ---- actions
    def add_paths(self, paths):
        for p in paths:
            p = os.path.normpath(p)
            if p not in self.paths:
                self.paths.append(p)
        self.refresh_files()

    def add_files(self):
        self.add_paths(filedialog.askopenfilenames(title="Choose songs", filetypes=AUDIO_TYPES))

    def remove_files(self):
        for i in reversed(self.files.curselection()):
            del self.paths[i]
        self.refresh_files()

    def clear_files(self):
        self.paths.clear()
        self.refresh_files()

    def browse_out(self):
        d = filedialog.askdirectory(title="Output folder", initialdir=self.out.get() or HERE)
        if d:
            self.out.set(os.path.normpath(d))

    def open_output(self):
        target = self.last_folder if self.last_folder and os.path.isdir(self.last_folder) else self.out.get()
        if os.path.isdir(target):
            os.startfile(target)
        else:
            messagebox.showinfo("Stem Separator", "The output folder doesn't exist yet.")

    def start(self):
        if not self.paths:
            messagebox.showinfo("Stem Separator", "Add at least one song first.")
            return
        out = self.out.get().strip()
        if not out:
            messagebox.showinfo("Stem Separator", "Choose an output folder.")
            return
        _, filename, tag, _ = self.selected_model()
        cmd = [worker_python(), WORKER, "--model", filename, "--out", out, "--tag", tag, "--format", self.fmt.get()]
        if self.fp16.get():
            cmd.append("--fp16")
        cmd += self.paths
        self.save_settings()

        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        try:
            self.proc = subprocess.Popen(cmd, cwd=HERE, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                         creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError as e:
            messagebox.showerror("Stem Separator", f"Could not start the worker:\n{e}")
            return
        self.cancelled = False
        self.file_count, self.file_index = len(self.paths), 0
        self.started = time.monotonic()
        self.total_bar.set(0)
        self.file_bar.set(0)
        self.file_bar.busy(True)
        self.pct.configure(text="0%")
        self.song_label.configure(text=f"QUEUE  0 / {self.file_count}")
        self.set_status("Initialising engine...")
        self.header.set_engine("Initialising", "busy")
        self.write_log(f">> {time.strftime('%H:%M:%S')}  {self.model.get()}  ->  {out}", "info")
        self.set_running(True)
        self.tick_clock()
        threading.Thread(target=self.read_output, args=(self.proc,), daemon=True).start()

    def read_output(self, proc):
        for line in proc.stdout:
            self.events.put(line)
        proc.wait()
        self.events.put(None)

    def cancel(self):
        if self.proc and self.proc.poll() is None:
            self.cancelled = True
            self.set_status("Aborting...", C["warn"])
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                           capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)

    def on_close(self):
        if self.proc and self.proc.poll() is None:
            if not messagebox.askyesno("Stem Separator", "A separation is running. Stop it and quit?"):
                return
            self.cancel()
        self.save_settings()
        self.root.destroy()

    # ---- event handling
    def poll(self):
        try:
            while True:
                line = self.events.get_nowait()
                if line is None:
                    self.finished()
                elif line.startswith("@@"):
                    try:
                        self.handle(json.loads(line[2:]))
                    except ValueError:
                        self.write_log(line)
                elif line.strip() and "ONNXruntime" not in line:
                    self.write_log(line)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def handle(self, ev):
        kind = ev.get("event")
        if kind == "status":
            self.set_status(ev["msg"])
        elif kind == "ready":
            self.header.set_engine(ev["device"], "busy")
            self.write_log(f"   engine online: {ev['device']}")
            if ev["device"] == "CPU":
                self.write_log("   warning: no GPU found, running on CPU. This will be very slow.", "warn")
            self.update_model_info()
        elif kind == "file":
            self.file_index = ev["index"]
            self.current = ev["name"]
            self.set_status(f"Separating {self.current}")
            self.song_label.configure(text=f"QUEUE  {ev['index'] + 1} / {ev['count']}")
            self.total_bar.set(ev["index"] / max(ev["count"], 1))
        elif kind == "progress":
            frac = ev["n"] / ev["total"] if ev["total"] else 0
            self.file_bar.set(frac)
            self.pct.configure(text=f"{frac:.0%}")
            if ev["kind"] == "download":
                self.set_status("Downloading model weights")
            else:
                self.set_status(f"Separating {self.current}  ·  chunk {ev['n']:02d}/{ev['total']:02d}")
                self.total_bar.set((self.file_index + frac) / max(self.file_count, 1))
        elif kind == "file_done":
            self.last_folder = ev["folder"]
            self.write_log(f"   [OK]  {os.path.basename(ev['folder'])}  ({ev['seconds']} s)", "ok")
        elif kind == "file_error":
            self.write_log(f"   [ERR] song {ev['index'] + 1}: {ev['msg']}", "err")
        elif kind == "fatal":
            self.write_log(f"   [ERR] {ev['msg']}", "err")
        elif kind == "done":
            self.done_failed = ev.get("failed", 0)

    def finished(self):
        code = self.proc.returncode if self.proc else None
        if self._clock_job:
            self.root.after_cancel(self._clock_job)
            self._clock_job = None
        elapsed = clock(time.monotonic() - self.started)
        self.file_bar.busy(False)
        if self.cancelled:
            self.set_status("Aborted  //  files of the song in progress may be incomplete", C["warn"])
            self.header.set_engine("Aborted", "idle")
        elif code == 0:
            failed = self.done_failed
            self.file_bar.set(1.0)
            self.total_bar.set(1.0)
            self.pct.configure(text="100%")
            if failed:
                self.set_status(f"Complete in {elapsed}  //  {failed} failed, see log", C["warn"])
                self.header.set_engine("Completed with errors", "err")
            else:
                self.set_status(f"Complete in {elapsed}", C["ok"])
                self.header.set_engine("Complete", "ok")
        else:
            self.set_status(f"Fault  //  worker exited with code {code}, see log", C["err"])
            self.header.set_engine("Fault", "err")
        self.done_failed = 0
        self.proc = None
        self.set_running(False)


def main():
    ui.prepare_process()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
