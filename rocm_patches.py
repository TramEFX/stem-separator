"""Runtime workarounds for audio-separator on AMD ROCm (RX 9070 XT / gfx1201, torch 2.12.0+rocm7.14.1, Windows).

Import this before running a separation. Safe to import on CPU-only setups.

Problem: the memory-efficient SDPA backend (AOTriton) fails to launch on this build with
"hipErrorInvalidValue" for every shape tested, and flash attention has no kernel at all. audio-separator's
Roformer Attend asks for [EFFICIENT, MATH, CUDNN] on non-A100 GPUs, so torch picks the broken backend; the
error then surfaces at the *next* kernel launch (the attention gate multiply in bs_roformer.py). Restricting
SDPA to the MATH backend is correct and works.
"""
import os

# AMD known issue: GPU resets on RX 9070 series with hipBLASLt. Benchmarked on this machine with BS-Roformer:
# no speed difference with it off, so default to off. Set TORCH_BLAS_PREFER_HIPBLASLT=1 to override.
os.environ.setdefault("TORCH_BLAS_PREFER_HIPBLASLT", "0")

import torch
from torch.nn.attention import SDPBackend

IS_ROCM = torch.version.hip is not None


def apply():
    if not IS_ROCM:
        return
    from audio_separator.separator.uvr_lib_v5.roformer import attend

    if getattr(attend, "_rocm_math_only", False):
        return
    attend._sdpa_backends = lambda config: [SDPBackend.MATH]
    attend._rocm_math_only = True


apply()
