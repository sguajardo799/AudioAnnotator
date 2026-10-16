"""NumPy/SciPy frontend matching the CRNN training log-Mel pipeline."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.signal import get_window

from smartaudiocrop.trim.model_package import ModelManifest
from smartaudiocrop.trim.providers import TrimProviderError


@dataclass(frozen=True)
class PreprocessedAudio:
    features: np.ndarray
    valid_frames: int
    processed_duration: float
    truncated: bool


class OnnxAudioPreprocessor:
    def __init__(self, manifest: ModelManifest):
        self.manifest = manifest
        self._window = get_window(
            "hann", manifest.win_length, fftbins=True
        ).astype(np.float32)
        self._mel_filters = self._build_mel_filters()

    @staticmethod
    def _hz_to_mel(frequency):
        return 2595.0 * np.log10(1.0 + np.asarray(frequency) / 700.0)

    @staticmethod
    def _mel_to_hz(mel):
        return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)

    def _build_mel_filters(self) -> np.ndarray:
        frequencies = np.linspace(
            0.0,
            self.manifest.sample_rate / 2,
            self.manifest.n_fft // 2 + 1,
            dtype=np.float32,
        )
        mel_points = np.linspace(
            self._hz_to_mel(self.manifest.f_min),
            self._hz_to_mel(self.manifest.f_max),
            self.manifest.n_mels + 2,
            dtype=np.float32,
        )
        hz_points = self._mel_to_hz(mel_points)
        lower = (frequencies[:, None] - hz_points[:-2]) / (
            hz_points[1:-1] - hz_points[:-2]
        )
        upper = (hz_points[2:] - frequencies[:, None]) / (
            hz_points[2:] - hz_points[1:-1]
        )
        return np.maximum(0.0, np.minimum(lower, upper)).astype(np.float32)

    def _resample(self, values: np.ndarray, sample_rate: int) -> np.ndarray:
        target_rate = self.manifest.sample_rate
        divisor = math.gcd(sample_rate, target_rate)
        original = sample_rate // divisor
        target = target_rate // divisor
        filter_width = self.manifest.resampling_lowpass_filter_width
        base_frequency = min(original, target) * self.manifest.resampling_rolloff
        width = math.ceil(filter_width * original / base_frequency)

        indices = (
            np.arange(-width, width + original, dtype=np.float32)[None, None, :]
            / original
        )
        phases = (
            np.arange(0, -target, -1, dtype=np.float32)[:, None, None]
            / target
        )
        positions = np.clip(
            (phases + indices) * base_frequency,
            -filter_width,
            filter_width,
        )
        positions = positions.astype(np.float32, copy=False)
        angles = positions * np.float32(np.pi)
        window = np.cos(angles / np.float32(filter_width * 2.0)) ** 2
        sinc = np.divide(
            np.sin(angles),
            angles,
            out=np.ones_like(angles),
            where=angles != 0,
        )
        kernels = sinc * window * np.float32(base_frequency / original)
        kernels = kernels[:, 0, :].astype(np.float32)

        padded = np.pad(values, (width, width + original))
        frames = np.lib.stride_tricks.sliding_window_view(
            padded, kernels.shape[1]
        )[::original]
        resampled = (frames @ kernels.T).reshape(-1)
        target_length = math.ceil(target * len(values) / original)
        return np.ascontiguousarray(resampled[:target_length], dtype=np.float32)

    def transform(self, audio: np.ndarray, sample_rate: int) -> PreprocessedAudio:
        values = np.asarray(audio, dtype=np.float32)
        if sample_rate <= 0:
            raise TrimProviderError("Audio sample rate must be positive")
        if values.ndim == 2:
            if values.shape[1] == 0:
                raise TrimProviderError("Audio has no channels")
            values = values.mean(axis=1, dtype=np.float32)
        elif values.ndim != 1:
            raise TrimProviderError("Audio must be mono or samples-by-channels")
        if values.size == 0:
            raise TrimProviderError("Audio is empty")
        if not np.all(np.isfinite(values)):
            raise TrimProviderError("Audio contains non-finite samples")

        if sample_rate != self.manifest.sample_rate:
            values = self._resample(values, sample_rate)

        maximum = int(
            round(
                self.manifest.max_duration_seconds
                * self.manifest.sample_rate
            )
        )
        truncated = values.size > maximum
        values = values[:maximum]
        actual_samples = values.size
        if actual_samples == 0:
            raise TrimProviderError("Audio is empty after resampling")
        valid_frames = max(
            1,
            min(
                1 + max(0, (maximum - self.manifest.n_fft) // self.manifest.hop_length),
                1
                + max(
                    0,
                    (actual_samples - self.manifest.n_fft)
                    // self.manifest.hop_length,
                ),
            ),
        )
        values = np.pad(values, (0, maximum - actual_samples))
        frames = np.lib.stride_tricks.sliding_window_view(
            values, self.manifest.win_length
        )[:: self.manifest.hop_length]
        spectrum = np.fft.rfft(
            frames * self._window, n=self.manifest.n_fft
        ).astype(np.complex64)
        power = np.abs(spectrum).astype(np.float32) ** 2
        mel = power @ self._mel_filters
        features = np.log(
            np.maximum(mel, np.float32(self.manifest.log_floor))
        ).T
        valid = features[:, :valid_frames]
        mean = np.mean(valid, dtype=np.float32)
        std = np.std(valid, ddof=1, dtype=np.float32)
        features = (features - np.float32(mean)) / np.float32(max(std, 1e-5))
        tensor = np.ascontiguousarray(features[None, None, :, :], dtype=np.float32)
        return PreprocessedAudio(
            features=tensor,
            valid_frames=valid_frames,
            processed_duration=actual_samples / self.manifest.sample_rate,
            truncated=truncated,
        )
