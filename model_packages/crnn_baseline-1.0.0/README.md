# CRNN Baseline 1.0.0

Local CPU ONNX package for SmartAudioCrop pre-annotation.

The model receives normalized log-Mel features, not waveform samples. Audio is
mixed to mono, resampled to 16 kHz, right-padded or truncated to 6 seconds, and
decoded according to `model_manifest.json`.

The original ONNX/PyTorch validation covered 921 files with maximum absolute
logit difference `2.574920654296875e-05` and maximum boundary difference `0 ms`.
