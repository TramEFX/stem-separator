"""Sci-fi look for the Tk GUI: bundled fonts, brushed-metal buttons, HUD panels, segmented bars and toggles.

Metal faces and the title are drawn with Pillow at 3x, scaled down and cached per state. The fonts in
assets/fonts (SIL Open Font License) are registered privately for this process on Windows; other systems
fall back to installed fonts.
"""
import ctypes
import os
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageTk

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "assets", "fonts")
ORBITRON = "Orbitron[wght].ttf"
SS = 3  # supersampling factor for Pillow drawing

C = {
    "bg": "#06080c",
    "panel": "#0b1017",
    "field": "#0e151e",
    "line": "#1c2836",
    "line_hi": "#2b3d50",
    "text": "#d4e1ee",
    "dim": "#6a7d91",
    "faint": "#34445a",
    "accent": "#2ad4ff",
    "accent_dim": "#0f5d73",
    "accent_deep": "#082630",
    "ok": "#3ef2a5",
    "warn": "#ffb547",
    "err": "#ff5470",
}

_scale = [1.0]


def px(n):
    """Logical pixels (96 dpi) to screen pixels."""
    return max(1, round(n * _scale[0]))


def rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def chamfer(x0, y0, x1, y1, c):
    """Rectangle with the top-left and bottom-right corners cut off, as a flat point list."""
    return [x0 + c, y0, x1, y0, x1, y1 - c, x1 - c, y1, x0, y1, x0, y0 + c]


# ---------------------------------------------------------------- process / window setup

def prepare_process():
    """Call before creating the Tk root: crisp text on high-DPI screens, own taskbar identity, bundled fonts."""
    if sys.platform != "win32":
        return
    for call in (lambda: ctypes.windll.shcore.SetProcessDpiAwareness(1),
                 lambda: ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("StemSeparator.GUI")):
        try:
            call()
        except (AttributeError, OSError):
            pass
    if os.path.isdir(FONT_DIR):
        for name in os.listdir(FONT_DIR):
            if name.lower().endswith((".ttf", ".otf")):
                ctypes.windll.gdi32.AddFontResourceExW(os.path.join(FONT_DIR, name), 0x10, 0)  # FR_PRIVATE


def style_titlebar(root):
    """Dark Windows 11 title bar in the window's own colours (ignored on older systems)."""
    if sys.platform != "win32":
        return
    root.update_idletasks()
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())

    def colorref(hex_color):
        r, g, b = rgb(hex_color)
        return r | g << 8 | b << 16

    for attr, value in ((20, 1), (35, colorref(C["bg"])), (34, colorref(C["line_hi"]))):
        v = ctypes.c_int(value)
        try:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
        except (AttributeError, OSError):
            pass


class Fonts:
    """Tk font tuples, using the bundled families when Tk can see them."""

    def __init__(self, root):
        fams = set(tkfont.families(root))
        self._ui = "Rajdhani SemiBold" if "Rajdhani SemiBold" in fams else "Segoe UI Semibold"
        self._ui_bold = "Rajdhani" if "Rajdhani" in fams else "Segoe UI"
        self._mono = "Share Tech Mono" if "Share Tech Mono" in fams else "Consolas"
        self._display = "Orbitron SemiBold" if "Orbitron SemiBold" in fams else "Segoe UI"

    def ui(self, size=12):
        return (self._ui, size)

    def ui_bold(self, size=12):
        return (self._ui_bold, size, "bold")

    def mono(self, size=10):
        return (self._mono, size)

    def display(self, size=10):
        return (self._display, size)


def init_theme(root):
    """Set the scale, root colours and ttk styles. Returns the Fonts to use."""
    _scale[0] = root.winfo_fpixels("1i") / 96.0
    fonts = Fonts(root)
    root.configure(bg=C["bg"])
    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure("Hud.TCombobox", fieldbackground=C["field"], background=C["field"], foreground=C["text"],
                 arrowcolor=C["accent"], bordercolor=C["line_hi"], lightcolor=C["field"], darkcolor=C["field"],
                 insertcolor=C["accent"], padding=(px(8), px(5)), arrowsize=px(14))
    st.map("Hud.TCombobox",
           fieldbackground=[("disabled", C["panel"]), ("readonly", C["field"])],
           foreground=[("disabled", C["dim"]), ("readonly", C["text"])],
           selectbackground=[("readonly", C["field"])], selectforeground=[("readonly", C["text"])],
           bordercolor=[("focus", C["accent_dim"]), ("hover", C["accent_dim"])],
           background=[("active", C["field"]), ("pressed", C["field"])],
           arrowcolor=[("disabled", C["faint"])])
    for key, value in (("background", C["field"]), ("foreground", C["text"]), ("selectBackground", C["accent_dim"]),
                       ("selectForeground", "#ffffff"), ("font", fonts.ui(12)), ("borderWidth", 0)):
        root.option_add(f"*TCombobox*Listbox.{key}", value)
    st.configure("Hud.Vertical.TScrollbar", background=C["line"], troughcolor=C["field"], bordercolor=C["field"],
                 lightcolor=C["line"], darkcolor=C["line"], arrowcolor=C["dim"], gripcount=0, arrowsize=px(11))
    st.map("Hud.Vertical.TScrollbar", background=[("pressed", C["accent_dim"]), ("active", C["line_hi"])])
    return fonts


# ---------------------------------------------------------------- Pillow rendering

_pil_fonts = {}


def pil_font(name, size, weight=None):
    key = (name, size, weight)
    if key not in _pil_fonts:
        try:
            f = ImageFont.truetype(os.path.join(FONT_DIR, name), size)
            if weight:
                f.set_variation_by_axes([weight])
        except OSError:
            f = ImageFont.load_default(size)
        _pil_fonts[key] = f
    return _pil_fonts[key]


METAL = {  # vertical gradient stops (position, RGB) for the brushed-metal faces
    "raised": [(0.0, (168, 179, 192)), (0.08, (124, 135, 148)), (0.49, (84, 94, 106)),
               (0.51, (56, 63, 73)), (0.85, (64, 72, 83)), (1.0, (98, 108, 120))],
    "sunken": [(0.0, (34, 39, 46)), (0.49, (50, 57, 66)), (0.51, (58, 66, 76)), (1.0, (86, 96, 108))],
}


def _gradient(height, stops):
    pos = np.array([p for p, _ in stops])
    cols = np.array([c for _, c in stops], dtype=np.float32)
    y = np.linspace(0.0, 1.0, height)
    return np.stack([np.interp(y, pos, cols[:, i]) for i in range(3)], axis=1)


def _brushed(w, h, stops, gain=1.0):
    """Brushed metal: vertical gradient plus horizontal streaks. Seeded so every state has the same grain."""
    body = np.repeat(_gradient(h, stops)[:, None, :] * gain, w, axis=1)
    rng = np.random.default_rng(7)
    streaks = rng.normal(0.0, 1.0, (h, max(2, w // (16 * SS)))).astype(np.float32)
    streaks = np.asarray(Image.fromarray(streaks).resize((w, h), Image.BILINEAR))
    body += (streaks * 5.0 + rng.normal(0.0, 1.8, (h, 1)))[:, :, None]
    return body


def _icon(d, kind, x, cy, s, fill, lw):
    h = s / 2
    if kind == "play":
        d.polygon([(x, cy - h * 0.95), (x + s * 0.85, cy), (x, cy + h * 0.95)], fill=fill)
    elif kind == "stop":
        d.rectangle([x + s * 0.1, cy - h * 0.72, x + s * 0.82, cy + h * 0.72], fill=fill)
    elif kind == "plus":
        d.line([(x, cy), (x + s, cy)], fill=fill, width=lw)
        d.line([(x + s / 2, cy - h), (x + s / 2, cy + h)], fill=fill, width=lw)
    elif kind == "minus":
        d.line([(x, cy), (x + s, cy)], fill=fill, width=lw)
    elif kind == "x":
        d.line([(x + s * 0.12, cy - h * 0.82), (x + s * 0.88, cy + h * 0.82)], fill=fill, width=lw)
        d.line([(x + s * 0.12, cy + h * 0.82), (x + s * 0.88, cy - h * 0.82)], fill=fill, width=lw)
    elif kind == "folder":
        d.polygon([(x, cy - h * 0.8), (x + s * 0.4, cy - h * 0.8), (x + s * 0.52, cy - h * 0.5),
                   (x + s, cy - h * 0.5), (x + s, cy + h * 0.8), (x, cy + h * 0.8)], outline=fill, width=lw)


def _tracked(text, font, track):
    widths = [font.getlength(ch) for ch in text]
    return widths, sum(widths) + track * max(len(text) - 1, 0)


def _draw_tracked(d, text, widths, font, track, x, y, fill):
    for ch, w in zip(text, widths):
        d.text((x, y), ch, font=font, fill=fill)
        x += w + track


def render_metal(w, h, label="", icon=None, face="normal", primary=False, lit=False, margin=0, font_px=12, cut=None):
    """Brushed-metal face of w x h screen pixels (glow margin included) as an RGBA image.

    face: normal | hover | pressed | disabled. primary: cyan rim, glow and lettering. lit: selected toggle (cyan LED).
    """
    W, H, M = w * SS, h * SS, margin * SS
    bw, bh = W - 2 * M, H - 2 * M
    c = round((cut if cut is not None else (h - 2 * margin) * 0.28) * SS)
    t = SS  # one screen pixel
    sunken = face == "pressed"
    gain = {"hover": 1.15, "disabled": 0.5}.get(face, 1.0)
    body = _brushed(bw, bh, METAL["sunken" if sunken else "raised"], gain)
    if face == "disabled":
        body = body * 0.35 + body.mean(axis=2, keepdims=True) * 0.65
    body_img = Image.fromarray(np.clip(body, 0, 255).astype(np.uint8)).convert("RGBA")
    mask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(mask).polygon(chamfer(0, 0, bw - 1, bh - 1, c), fill=255)
    body_img.putalpha(mask)

    # bevel: light top/left, dark bottom/right (swapped when pressed), then a dark outer edge
    d = ImageDraw.Draw(body_img)
    hi, lo = ((0, 0, 0, 120), (255, 255, 255, 45)) if sunken else ((255, 255, 255, 115), (0, 0, 0, 150))
    i = round(1.5 * t)
    pts = chamfer(i, i, bw - 1 - i, bh - 1 - i, max(c - i, 1))
    p = list(zip(pts[::2], pts[1::2]))
    d.line([p[5], p[0], p[1]], fill=hi, width=t)
    d.line([p[1], p[2], p[3], p[4]], fill=lo, width=t)
    d.line([p[4], p[5]], fill=hi[:3] + (hi[3] // 2,), width=t)
    d.polygon(chamfer(0, 0, bw - 1, bh - 1, c), outline=(5, 7, 10, 255), width=t)

    accent = rgb(C["accent"])
    if lit:  # LED strip along the bottom, dimmed while disabled
        y = bh - 4.5 * t
        led = rgb(C["accent_dim"]) if face == "disabled" else accent
        d.line([(bw * 0.3, y), (bw * 0.7, y)], fill=led + (255,), width=round(1.6 * t))

    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow = 0 if face == "disabled" else (230 if face == "hover" else 130) if primary else (190 if face == "hover" else 0)
    if glow and M:
        g = Image.new("L", (W, H), 0)
        ImageDraw.Draw(g).polygon(chamfer(M, M, M + bw - 1, M + bh - 1, c), outline=255, width=2 * t)
        g = g.filter(ImageFilter.GaussianBlur(2.6 * t)).point(lambda v: min(255, v * 2) * glow // 255)
        halo = Image.new("RGBA", (W, H), accent + (0,))
        halo.putalpha(g)
        out.alpha_composite(halo)
    out.alpha_composite(body_img, (M, M))
    rim = 0 if face == "disabled" else (255 if face == "hover" else 210) if primary else (170 if face == "hover" else 0)
    if rim:
        ImageDraw.Draw(out).polygon(chamfer(M, M, M + bw - 1, M + bh - 1, c), outline=accent + (rim,), width=t)

    # label and icon
    text = label.upper()
    font = pil_font(ORBITRON, round(font_px * SS), 700)
    track = font_px * SS * 0.14
    widths, tw = _tracked(text, font, track)
    s = font_px * SS * 0.95 if icon else 0
    gap = font_px * SS * 0.55 if icon and text else 0
    x = (W - (s + gap + tw)) / 2
    cy = H / 2 + (t if sunken else 0)
    y0, y1 = font.getbbox("H")[1], font.getbbox("H")[3]
    ty = cy - (y0 + y1) / 2
    if face == "disabled":
        fill = (98, 108, 120, 255)
    elif primary or lit:
        fill = (160, 238, 255, 255)
    else:
        fill = (234, 240, 246, 255)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    if icon:
        _icon(ld, icon, x, cy, s, fill, round(1.7 * t))
    _draw_tracked(ld, text, widths, font, track, x + s + gap, ty, fill)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.putalpha(layer.getchannel("A").point(lambda v: v * 170 // 255))
    out.alpha_composite(shadow, (0, round(1.2 * t)))
    if (primary or lit) and face != "disabled":
        bloom = Image.new("RGBA", (W, H), accent + (0,))
        bloom.putalpha(layer.getchannel("A").filter(ImageFilter.GaussianBlur(2.5 * t)).point(lambda v: v * 150 // 255))
        out.alpha_composite(bloom)
    out.alpha_composite(layer)
    return out.resize((w, h), Image.LANCZOS)


def render_title(text, font_px, weight=800, track=0.18):
    """Title lettering with a brushed-steel fill and a cyan glow."""
    font = pil_font(ORBITRON, round(font_px * SS), weight)
    tr = font_px * SS * track
    widths, tw = _tracked(text, font, tr)
    y0, y1 = font.getbbox("H")[1], font.getbbox("H")[3]
    pad = round(font_px * SS * 0.5)
    W, H = round(tw) + 2 * pad, (y1 - y0) + 2 * pad
    mask = Image.new("L", (W, H), 0)
    _draw_tracked(ImageDraw.Draw(mask), text, widths, font, tr, pad, pad - y0, 255)
    steel = _brushed(W, H, [(0.0, (250, 253, 255)), (0.45, (196, 210, 224)), (0.55, (126, 146, 168)),
                            (1.0, (176, 194, 212))])
    fill = Image.fromarray(np.clip(steel, 0, 255).astype(np.uint8)).convert("RGBA")
    fill.putalpha(mask)
    out = Image.new("RGBA", (W, H), rgb(C["accent"]) + (0,))
    out.putalpha(mask.filter(ImageFilter.GaussianBlur(font_px * SS * 0.28)).point(lambda v: min(255, v * 2) * 120 // 255))
    out.alpha_composite(fill)
    return out.resize((W // SS, H // SS), Image.LANCZOS)


def render_icon(size):
    """App icon: a waveform splitting into two stems on a cut-corner tile."""
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = S * 0.22
    d.polygon(chamfer(0, 0, S - 1, S - 1, c), fill=rgb(C["panel"]) + (255,), outline=rgb(C["accent"]) + (255,),
              width=max(SS, S // 24))
    heights = [0.18, 0.34, 0.52, 0.30, 0.44, 0.24, 0.12]
    bw = S * 0.08
    x0 = (S - len(heights) * bw * 1.6 + bw * 0.6) / 2
    mid = S / 2
    for i, hgt in enumerate(heights):
        x = x0 + i * bw * 1.6
        d.rectangle([x, mid - hgt * S * 0.62, x + bw, mid - S * 0.03], fill=rgb(C["accent"]) + (255,))
        d.rectangle([x, mid + S * 0.03, x + bw, mid + hgt * S * 0.5], fill=rgb(C["warn"]) + (230,))
    return img.resize((size, size), Image.LANCZOS)


# ---------------------------------------------------------------- widgets

class MetalButton(tk.Canvas):
    """Brushed-metal push button with hover glow, pressed state and optional toggle 'selected' state."""

    def __init__(self, parent, text="", command=None, width=110, height=32, icon=None, primary=False,
                 font_px=11, margin=6, bg=None):
        self.m = px(margin)
        self.size = (px(width) + 2 * self.m, px(height) + 2 * self.m)
        super().__init__(parent, width=self.size[0], height=self.size[1], bg=bg or parent.cget("bg"),
                         highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        self.opts = dict(label=text, icon=icon, primary=primary, margin=self.m, font_px=px(font_px))
        self.command = command
        self.enabled = True
        self.hover = self.down = self.selected = False
        self._cache = {}
        self._item = self.create_image(0, 0, anchor="nw")
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False))
        self.bind("<ButtonPress-1>", lambda e: self.enabled and self._set(down=True))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<KeyPress-space>", lambda e: self.invoke())
        self.bind("<KeyPress-Return>", lambda e: self.invoke())
        self._draw()

    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self._draw()

    def _release(self, _):
        fire = self.down and self.hover
        self._set(down=False)
        if fire:
            self.invoke()

    def invoke(self):
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, on):
        self.enabled = bool(on)
        self.configure(cursor="hand2" if on else "arrow")
        self._draw()

    def set_selected(self, on):
        self._set(selected=bool(on))

    def _draw(self):
        if not self.enabled:
            face = "disabled"
        elif (self.down and self.hover) or self.selected:
            face = "pressed"
        elif self.hover:
            face = "hover"
        else:
            face = "normal"
        key = (face, self.selected)
        if key not in self._cache:
            img = render_metal(*self.size, face=face, lit=self.selected, **self.opts)
            self._cache[key] = ImageTk.PhotoImage(img, master=self)
        self.itemconfigure(self._item, image=self._cache[key])


class HudPanel(tk.Frame):
    """Panel with cut corners, accent brackets and a numbered section title. Put content in .body."""

    def __init__(self, parent, index, title, fonts):
        super().__init__(parent, bg=C["bg"])
        self.title = f"{index:02d} // {title.upper()}"
        self.font = fonts.mono(9)
        self.canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0, bd=0)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=C["panel"])
        self.body.pack(fill="both", expand=True, padx=px(16), pady=(px(32), px(16)))
        self.bind("<Configure>", self._draw)

    def _draw(self, _=None):
        cv = self.canvas
        cv.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        c, L, t = px(14), px(16), px(2)
        a = C["accent"]
        cv.create_polygon(chamfer(1, 1, w - 2, h - 2, c), fill=C["panel"], outline=C["line"])
        cv.create_line(w - 2 - L, 1, w - 2, 1, w - 2, 1 + L, fill=a, width=t)        # top-right bracket
        cv.create_line(1, h - 2 - L, 1, h - 2, 1 + L, h - 2, fill=a, width=t)        # bottom-left bracket
        cv.create_line(1, 1 + c, 1 + c, 1, fill=a, width=t)                          # top-left cut
        cv.create_line(w - 2 - c, h - 2, w - 2, h - 2 - c, fill=C["accent_dim"], width=t)
        tx, ty = px(18), px(17)
        cv.create_text(tx, ty, text=self.title, anchor="w", fill=a, font=self.font)
        x1 = tx + tkfont.Font(font=self.font).measure(self.title) + px(12)
        cv.create_line(x1, ty, w - px(44), ty, fill=C["line"])
        for k in range(3):
            x = w - px(38) + k * px(7)
            cv.create_rectangle(x, ty - px(2), x + px(4), ty + px(2), outline="",
                                fill=a if k == 0 else C["accent_dim"])


class SegmentBar(tk.Canvas):
    """Segmented LED progress bar. busy(True) shows a sweeping scanner while progress is unknown."""

    def __init__(self, parent, height=16):
        super().__init__(parent, height=px(height), bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self.value = 0.0
        self._job = None
        self._phase = 0
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, value):
        self.busy(False)
        self.value = max(0.0, min(1.0, value))
        self._draw()

    def busy(self, on):
        if on and self._job is None:
            self._tick()
        elif not on and self._job is not None:
            self.after_cancel(self._job)
            self._job = None
            self._draw()

    def _tick(self):
        self._phase += 1
        self._draw()
        self._job = self.after(45, self._tick)

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20:
            return
        self.create_polygon(chamfer(0, 0, w - 1, h - 1, px(6)), fill=C["field"], outline=C["line"])
        padx, pady, sw, gap = px(8), px(4), px(4), px(2)
        n = max(1, (w - 2 * padx + gap) // (sw + gap))
        x0 = (w - (n * (sw + gap) - gap)) // 2
        filled = round(n * self.value)
        head = self._phase % (n + 16) - 8
        for k in range(n):
            if self._job is not None:
                dist = abs(k - head)
                col = C["accent"] if dist == 0 else C["accent_dim"] if dist <= 4 else C["accent_deep"]
            elif k < filled:
                col = "#c9f6ff" if k == filled - 1 and filled < n else C["accent"]
            else:
                col = C["accent_deep"]
            x = x0 + k * (sw + gap)
            self.create_rectangle(x, pady, x + sw - 1, h - pady - 1, fill=col, outline="")


class ToggleSwitch(tk.Canvas):
    """On/off switch bound to a BooleanVar, with a small metal knob."""

    def __init__(self, parent, variable, width=46, height=22):
        self.w, self.h = px(width), px(height)
        super().__init__(parent, width=self.w, height=self.h, bg=parent.cget("bg"), highlightthickness=0, bd=0,
                         cursor="hand2")
        self.var = variable
        self.enabled = True
        kw = self.h - px(6)
        self._knob = {f: ImageTk.PhotoImage(render_metal(kw, kw, face=f, cut=kw * 0.3), master=self)
                      for f in ("normal", "disabled")}
        self.bind("<ButtonRelease-1>", lambda e: self.enabled and self.var.set(not self.var.get()))
        variable.trace_add("write", lambda *a: self._draw())
        self._draw()

    def set_enabled(self, on):
        self.enabled = bool(on)
        self.configure(cursor="hand2" if on else "arrow")
        self._draw()

    def _draw(self):
        self.delete("all")
        on = bool(self.var.get())
        w, h, p = self.w, self.h, px(3)
        live = on and self.enabled
        self.create_polygon(chamfer(0, 0, w - 1, h - 1, px(5)), fill=C["accent_deep"] if live else C["field"],
                            outline=C["accent"] if live else C["line_hi"])
        kw = h - 2 * p
        x = w - p - kw if on else p
        self.create_image(x, p, image=self._knob["normal" if self.enabled else "disabled"], anchor="nw")
        if live:
            self.create_rectangle(x + kw // 2 - px(2), h // 2 - px(2), x + kw // 2 + px(2), h // 2 + px(2),
                                  fill=C["accent"], outline="")


class SegmentedChoice(tk.Frame):
    """Row of metal keys acting as radio buttons for a StringVar."""

    def __init__(self, parent, choices, variable, width=62, height=28):
        super().__init__(parent, bg=parent.cget("bg"))
        self.var = variable
        self.buttons = {}
        for value, label in choices:
            b = MetalButton(self, text=label, width=width, height=height, font_px=10, margin=3,
                            command=lambda v=value: variable.set(v))
            b.pack(side="left")
            self.buttons[value] = b
        variable.trace_add("write", lambda *a: self._sync())
        self._sync()

    def _sync(self):
        for value, b in self.buttons.items():
            b.set_selected(value == self.var.get())

    def set_enabled(self, on):
        for b in self.buttons.values():
            b.set_enabled(on)


class Header(tk.Canvas):
    """Title block with an engine status readout and a glowing rule underneath."""

    STATES = {"idle": "faint", "busy": "accent", "ok": "ok", "err": "err"}

    def __init__(self, parent, fonts, title, subtitle):
        super().__init__(parent, height=px(84), bg=C["bg"], highlightthickness=0, bd=0)
        self.fonts = fonts
        self.subtitle = subtitle
        self.title_img = ImageTk.PhotoImage(render_title(title, px(28)), master=self)
        self.engine = "IDLE"
        self.state = "idle"
        self._pulse = None
        self._on = True
        self.bind("<Configure>", lambda e: self._draw())

    def set_engine(self, text, state):
        self.engine, self.state = text.upper(), state
        if state == "busy" and self._pulse is None:
            self._blink()
        elif state != "busy" and self._pulse is not None:
            self.after_cancel(self._pulse)
            self._pulse = None
            self._on = True
        self._draw()

    def _blink(self):
        self._on = not self._on
        self._draw()
        self._pulse = self.after(520, self._blink)

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        self.create_image(px(2), px(4), image=self.title_img, anchor="nw")
        self.create_text(px(18), px(60), text=self.subtitle, anchor="w", fill=C["dim"], font=self.fonts.mono(9))
        # engine readout, right aligned
        col = C[self.STATES[self.state]] if self._on else C["accent_dim"]
        right = w - px(6)
        tid = self.create_text(right, px(32), text=self.engine, anchor="e", fill=C["text"], font=self.fonts.ui_bold(12))
        x0 = self.bbox(tid)[0]
        r = px(4)
        self.create_oval(x0 - px(12) - r, px(32) - r, x0 - px(12) + r, px(32) + r, fill=col, outline="")
        self.create_text(right, px(54), text="ENGINE STATUS", anchor="e", fill=C["dim"], font=self.fonts.mono(8))
        # glowing rule: bright under the title, fading to the right
        y, n = h - px(6), 48
        a, f = rgb(C["accent"]), rgb(C["line"])
        for k in range(n):
            t = k / (n - 1)
            mix = tuple(round(a[i] + (f[i] - a[i]) * min(1.0, t * 1.6)) for i in range(3))
            self.create_line(w * k / n, y, w * (k + 1) / n + 1, y, fill="#%02x%02x%02x" % mix, width=px(2))
        self.create_rectangle(0, y - px(3), px(60), y - px(2), fill=C["accent"], outline="")
