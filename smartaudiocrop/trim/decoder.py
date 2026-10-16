"""Temporal decoder for CRNN mask logits."""

from __future__ import annotations

import numpy as np

from smartaudiocrop.trim.model_package import ModelManifest
from smartaudiocrop.trim.providers import NoActivityDetected, TrimProviderError


def decode_crnn_mask(
    logits: np.ndarray,
    valid_frames: int,
    duration: float,
    manifest: ModelManifest,
) -> tuple[float, float]:
    values = np.asarray(logits, dtype=np.float32)
    if values.ndim == 2 and values.shape[0] == 1:
        values = values[0]
    if values.ndim != 1 or valid_frames <= 0 or values.size < valid_frames:
        raise TrimProviderError("Model output has an incompatible shape")
    values = values[:valid_frames]
    if not np.all(np.isfinite(values)):
        raise TrimProviderError("Model output contains non-finite logits")
    probabilities = np.empty_like(values)
    positive = values >= 0
    probabilities[positive] = 1.0 / (1.0 + np.exp(-values[positive]))
    exp_values = np.exp(values[~positive])
    probabilities[~positive] = exp_values / (1.0 + exp_values)
    active = probabilities >= manifest.threshold
    indices = np.flatnonzero(active)
    if indices.size == 0:
        raise NoActivityDetected("The model found no frames above its threshold")

    max_gap = max(
        0,
        round(
            manifest.bridge_ms
            / 1000.0
            * manifest.sample_rate
            / manifest.hop_length
        ),
    )
    for left, right in zip(indices[:-1], indices[1:]):
        if right - left - 1 <= max_gap:
            active[left : right + 1] = True
    changes = np.diff(np.r_[False, active, False].astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    stops = np.flatnonzero(changes == -1)
    best = int(np.argmax(stops - starts))
    first = int(starts[best])
    last = int(stops[best] - 1)
    start = first * manifest.hop_length / manifest.sample_rate
    end = (
        last * manifest.hop_length / manifest.sample_rate
        + manifest.n_fft / manifest.sample_rate
    )
    end = min(float(duration), end)
    if not 0 <= start < end <= duration:
        raise TrimProviderError("Decoded model bounds are invalid")
    return start, end
