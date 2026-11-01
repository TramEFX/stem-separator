"""Installer for Stem Separator: creates .venv next to this file and installs PyTorch for your GPU plus audio-separator.

Run through install.bat (it finds Python 3.12). Pass a target key to skip the menu, e.g. `install.bat amd-rx9070`.
Uses uv when it is on PATH (faster, cached), otherwise pip.
"""
import os
import re
import shutil
import subprocess
import sys
import venv

HERE = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(HERE, ".venv")
PY = os.path.join(VENV, "Scripts", "python.exe")
AMD_INDEX = "https://repo.amd.com/rocm/whl-multi-arch/"
TORCH, TORCHVISION, ROCM = "2.12.0", "0.27.0", "rocm7.14.1"

# key, menu label, backend, AMD device extra or CUDA tag, regex matched against the lowercase GPU name
TARGETS = [
    ("amd-rx9070", "AMD Radeon RX 9070 / 9070 XT / 9070 GRE  (RDNA4, gfx1201)  [tested]", "rocm", "gfx1201", r"rx 9070"),
    ("amd-rx9060", "AMD Radeon RX 9060 / 9060 XT  (RDNA4, gfx1200)", "rocm", "gfx1200", r"rx 9060"),
    ("amd-rx7900", "AMD Radeon RX 7900 XTX / XT / GRE  (RDNA3, gfx1100)", "rocm", "gfx1100", r"rx 79\d\d"),
    ("amd-rx7800", "AMD Radeon RX 7800 XT / 7700 XT  (RDNA3, gfx1101)", "rocm", "gfx1101", r"rx 7[78]\d\d"),
    ("amd-rx7600", "AMD Radeon RX 7600 / 7600 XT  (RDNA3, gfx1102)", "rocm", "gfx1102", r"rx 76\d\d"),
    ("amd-rx6800", "AMD Radeon RX 6800 / 6900 / 6950  (RDNA2, gfx1030)", "rocm", "gfx1030", r"rx 6[89]\d\d"),
    ("amd-rx6700", "AMD Radeon RX 6700 / 6750  (RDNA2, gfx1031)", "rocm", "gfx1031", r"rx 67\d\d"),
    ("amd-rx6600", "AMD Radeon RX 6600 / 6650  (RDNA2, gfx1032)", "rocm", "gfx1032", r"rx 66\d\d"),
    ("amd-strix-halo", "AMD Ryzen AI Max, Radeon 8060S / 8050S  (gfx1151)", "rocm", "gfx1151", r"8060s|8050s|ryzen ai max"),
    ("amd-strix", "AMD Ryzen AI 300, Radeon 890M / 880M  (gfx1150)", "rocm", "gfx1150", r"890m|880m"),
    ("nvidia-legacy", "NVIDIA GTX 10-series, or a driver older than 580  (CUDA 12.6)", "cuda", "cu126", r"gtx 10\d\d"),
    ("nvidia", "NVIDIA GeForce RTX 20-series or newer  (CUDA 13.0)", "cuda", "cu130", r"nvidia|geforce|rtx|quadro"),
    ("cpu", "No supported GPU: CPU only (very slow)", "cpu", None, None),
]


def detect_gpus():
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def suggest(gpus):
    for target in TARGETS:
        if target[4] and any(re.search(target[4], g.lower()) for g in gpus):
            return target
    return TARGETS[-1]


def choose(argv):
    keys = {t[0]: t for t in TARGETS}
    if argv:
        if argv[0] not in keys:
            sys.exit(f"Unknown target '{argv[0]}'. Choose one of: {', '.join(keys)}")
        return keys[argv[0]]
    gpus = detect_gpus()
    default = suggest(gpus)
    print("Graphics detected:", ", ".join(gpus) or "none")
    print()
    for i, t in enumerate(TARGETS, 1):
        print(f"  {i:2d}) {t[1]}{'   <- suggested' if t is default else ''}")
    print()
    while True:
        answer = input(f"Install for which GPU? [Enter = {TARGETS.index(default) + 1}]: ").strip()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(TARGETS):
            return TARGETS[int(answer) - 1]
        print("Please type a number from the list.")


def run(cmd):
    print(">", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def ensure_ffmpeg(interactive):
    """audio-separator writes stems through ffmpeg (pydub) and refuses to run without it."""
    if shutil.which("ffmpeg"):
        return
    print("\nffmpeg was not found on PATH. Stem Separator needs it to write audio files.")
    if interactive and shutil.which("winget") and input("Install ffmpeg now with winget? [Y/n]: ").strip().lower() in ("", "y", "yes"):
        subprocess.run(["winget", "install", "--id", "Gyan.FFmpeg", "-e"])
        print("If ffmpeg was installed, it is available in newly opened windows.")
    else:
        print("Install it with:  winget install Gyan.FFmpeg   (or from https://ffmpeg.org) and make sure it is on PATH.")


def main():
    if sys.version_info[:2] != (3, 12):
        sys.exit(f"Python 3.12 is required (this is {sys.version.split()[0]}).")
    key, label, backend, tag, _ = choose(sys.argv[1:])
    print(f"\nInstalling for: {label}\n")

    if not os.path.isfile(PY):
        print("Creating virtual environment in .venv ...", flush=True)
        venv.create(VENV, with_pip=shutil.which("uv") is None)
    uv = shutil.which("uv")
    pip = [uv, "pip", "install", "--python", PY] if uv else [PY, "-m", "pip", "install", "--disable-pip-version-check"]

    if backend == "rocm":
        run(pip + ["--index-url", AMD_INDEX, f"torch[device-{tag}]=={TORCH}+{ROCM}",
                   f"torchvision[device-{tag}]=={TORCHVISION}+{ROCM}"])
    elif backend == "cuda":
        run(pip + ["--index-url", f"https://download.pytorch.org/whl/{tag}", f"torch=={TORCH}+{tag}",
                   f"torchvision=={TORCHVISION}+{tag}"])
    else:
        run(pip + [f"torch=={TORCH}", f"torchvision=={TORCHVISION}"])
    run(pip + ["-r", os.path.join(HERE, "requirements.txt")])

    print("\nChecking the installation ...", flush=True)
    check = ("import torch, audio_separator.separator; ok = torch.cuda.is_available(); "
             "print('torch', torch.__version__, '| GPU:', torch.cuda.get_device_name(0) if ok else 'not available')")
    subprocess.run([PY, "-c", check], check=True)
    ensure_ffmpeg(interactive=not sys.argv[1:])
    print("\nDone. Start the app with 'Stem Separator.bat'.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"\nInstallation failed (command exited with code {e.returncode}). See the messages above.")
    except KeyboardInterrupt:
        sys.exit("\nCancelled.")
