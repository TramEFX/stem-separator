"""Separation worker for stem_gui.py, run as a subprocess so Cancel can simply kill it (and free VRAM).

Writes events to stdout as lines of '@@' + JSON. Anything else on stdout/stderr is plain log output.
Outputs go to <out>/<song> [<tag>]/<song> - <Stem> [<tag>].<ext>; repeat runs get ' (2)', ' (3)' ... on both.
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
import traceback
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def emit(**event):
    sys.stdout.write("@@" + json.dumps(event) + "\n")
    sys.stdout.flush()


class Progress:
    """Stands in for tqdm inside audio-separator so chunk and download progress reach the GUI."""

    def __init__(self, iterable=None, total=None, unit="it", **_):
        self.iterable = iterable
        if total is None and hasattr(iterable, "__len__"):
            total = len(iterable)
        self.total = total or 0
        self.n = 0
        self.kind = "download" if unit == "iB" else "separate"
        self._last = 0.0
        self._emit(force=True)

    def __iter__(self):
        for item in self.iterable:
            yield item
            self.update()

    def update(self, n=1):
        self.n += n
        self._emit()

    def _emit(self, force=False):
        now = time.monotonic()
        if force or now - self._last >= 0.25 or self.n >= self.total:
            self._last = now
            emit(event="progress", kind=self.kind, n=self.n, total=self.total)

    def close(self):
        pass


def safe_name(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip(" .") or "output"


def new_run_folder(out_dir, base):
    """Create '<base>' for the first run, then '<base> (2)', '(3)' ... one above the highest existing number."""
    pattern = re.compile(re.escape(base) + r"(?: \((\d+)\))?", re.IGNORECASE)
    runs = [int(m.group(1) or 1) for name in os.listdir(out_dir) if (m := pattern.fullmatch(name))]
    n = max(runs, default=0) + 1
    while True:
        path = os.path.join(out_dir, base if n == 1 else f"{base} ({n})")
        try:
            os.mkdir(path)
            return path, n
        except FileExistsError:
            n += 1


def move_outputs(files, out_dir, song, tag):
    """Move audio-separator's '<song>_(<Stem>)_<model>.<ext>' files into a new folder for this run.

    Earlier runs are never overwritten, and every file name carries the model tag and run number, so stems from
    many runs stay distinct when they are used together.
    """
    dest_dir, n = new_run_folder(out_dir, safe_name(f"{song} [{tag}]" if tag else song))
    suffix = (f" [{tag}]" if tag else "") + (f" ({n})" if n > 1 else "")
    moved = []
    for f in files:
        src = f if os.path.isabs(f) else os.path.join(out_dir, f)
        name = os.path.basename(src)
        m = re.search(r"_\(([^()]+)\)_[^()]*$", name)
        stem = m.group(1) if m else os.path.splitext(name)[0]
        stem = stem[:1].upper() + stem[1:]  # BS-Roformer SW names its stems in lower case
        dest = os.path.join(dest_dir, safe_name(f"{song} - {stem}{suffix}") + os.path.splitext(name)[1])
        shutil.move(src, dest)
        moved.append(dest)
    return dest_dir, moved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", default="")
    ap.add_argument("--format", default="WAV", choices=["WAV", "FLAC", "MP3"])
    ap.add_argument("--cpu", action="store_true")
    ap.add_argument("--fp16", action="store_true")
    ap.add_argument("--model-dir", default=os.path.join(HERE, "models"))
    a = ap.parse_args()

    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=SyntaxWarning)  # pydub's regexes
    emit(event="status", msg="Starting PyTorch…")
    import rocm_patches  # sets env and patches SDPA; must come before any GPU work
    import torch

    if a.cpu:
        torch.cuda.is_available = lambda: False  # audio-separator picks its device from this

    import logging
    from audio_separator.separator import Separator
    from audio_separator.separator import separator as separator_module
    from audio_separator.separator.architectures import mdxc_separator

    separator_module.tqdm = Progress
    mdxc_separator.tqdm = Progress

    device = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
    emit(event="status", msg=f"Loading model on {device}…")
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.model_dir, exist_ok=True)
    sep = Separator(
        log_level=logging.WARNING,
        model_file_dir=a.model_dir,
        output_dir=a.out,
        output_format=a.format,
        output_bitrate="320k" if a.format == "MP3" else None,
        use_autocast=a.fp16 and device != "CPU",
    )
    sep.load_model(model_filename=a.model)
    emit(event="ready", device=device)

    failed = 0
    for i, path in enumerate(a.files):
        song = os.path.splitext(os.path.basename(path))[0]
        emit(event="file", index=i, count=len(a.files), name=os.path.basename(path))
        t0 = time.perf_counter()
        try:
            outputs = sep.separate(path)
            folder, moved = move_outputs(outputs, a.out, song, a.tag)
        except Exception as e:
            failed += 1
            traceback.print_exc()
            emit(event="file_error", index=i, msg=f"{type(e).__name__}: {e}")
            continue
        emit(event="file_done", index=i, seconds=round(time.perf_counter() - t0, 1), folder=folder, outputs=moved)
    emit(event="done", failed=failed)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        traceback.print_exc()
        emit(event="fatal", msg=f"{type(e).__name__}: {e}")
        sys.exit(1)
