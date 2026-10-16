"""Validation of local ONNX model packages."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from smartaudiocrop.trim.providers import TrimProviderError


SUPPORTED_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ModelManifest:
    path: Path
    model_path: Path
    schema_version: int
    model_id: str
    model_version: str
    model_type: str
    model_sha256: str
    input_name: str
    output_name: str
    sample_rate: int
    channel_policy: str
    resampling_method: str
    resampling_lowpass_filter_width: int
    resampling_rolloff: float
    max_duration_seconds: float
    n_fft: int
    win_length: int
    hop_length: int
    n_mels: int
    f_min: float
    f_max: float
    log_floor: float
    threshold: float
    bridge_ms: float
    preprocessing_version: str
    decoder_version: str
    config: dict

    @classmethod
    def load(cls, path: str | Path) -> "ModelManifest":
        manifest_path = Path(path).expanduser().resolve()
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TrimProviderError(f"Could not read model manifest: {exc}") from exc
        if not isinstance(raw, dict):
            raise TrimProviderError("Model manifest must be a JSON object")

        required = {
            "schema_version",
            "model_id",
            "model_version",
            "model_type",
            "model_file",
            "model_sha256",
            "input_name",
            "output_name",
            "input_dtype",
            "input_axes",
            "output_axes",
            "preprocessing",
            "decoder",
        }
        missing = required - raw.keys()
        if missing:
            raise TrimProviderError(
                f"Model manifest is missing: {', '.join(sorted(missing))}"
            )
        if raw["schema_version"] != SUPPORTED_SCHEMA_VERSION:
            raise TrimProviderError("Unsupported model manifest schema version")
        if raw["model_type"] != "crnn_mask":
            raise TrimProviderError("Only crnn_mask models are supported")
        if raw["input_dtype"] != "float32":
            raise TrimProviderError("Only float32 model inputs are supported")
        if raw["input_axes"] != ["batch", "channel", "mel", "frame"]:
            raise TrimProviderError("Unsupported ONNX input axes")
        if raw["output_axes"] != ["batch", "frame"]:
            raise TrimProviderError("Unsupported ONNX output axes")

        model_file = Path(str(raw["model_file"]))
        if model_file.is_absolute() or ".." in model_file.parts:
            raise TrimProviderError("model_file must stay inside the model package")
        model_path = (manifest_path.parent / model_file).resolve()
        if model_path.parent != manifest_path.parent:
            raise TrimProviderError("model_file must stay inside the model package")
        if not model_path.is_file():
            raise TrimProviderError(f"ONNX model does not exist: {model_path}")

        actual_sha = hashlib.sha256(model_path.read_bytes()).hexdigest()
        expected_sha = str(raw["model_sha256"]).lower()
        if actual_sha != expected_sha:
            raise TrimProviderError("ONNX model checksum does not match the manifest")

        prep = raw["preprocessing"]
        decoder = raw["decoder"]
        if not isinstance(prep, dict) or not isinstance(decoder, dict):
            raise TrimProviderError("Preprocessing and decoder must be JSON objects")
        prep_required = {
            "sample_rate",
            "channel_policy",
            "resampling_method",
            "resampling_lowpass_filter_width",
            "resampling_rolloff",
            "max_duration_seconds",
            "overlong_policy",
            "padding_policy",
            "n_fft",
            "win_length",
            "hop_length",
            "n_mels",
            "f_min",
            "f_max",
            "window",
            "center",
            "stft_pad",
            "power",
            "mel_scale",
            "mel_norm",
            "log_floor",
            "normalization",
            "std_correction",
            "version",
        }
        decoder_required = {
            "threshold",
            "bridge_ms",
            "interval_policy",
            "empty_positive_policy",
            "version",
        }
        missing = (prep_required - prep.keys()) | (decoder_required - decoder.keys())
        if missing:
            raise TrimProviderError(
                f"Model configuration is missing: {', '.join(sorted(missing))}"
            )
        supported = {
            "channel_policy": "mean",
            "resampling_method": "sinc_interp_hann",
            "overlong_policy": "truncate",
            "padding_policy": "right_zero",
            "window": "hann_periodic",
            "center": False,
            "power": 2.0,
            "mel_scale": "htk",
            "mel_norm": None,
            "normalization": "per_example_valid_frames",
            "std_correction": 1,
        }
        for key, expected in supported.items():
            if prep[key] != expected:
                raise TrimProviderError(f"Unsupported preprocessing value: {key}")
        if prep["win_length"] != prep["n_fft"]:
            raise TrimProviderError("win_length must equal n_fft for this frontend")
        if prep["stft_pad"] != 0:
            raise TrimProviderError("Only zero STFT padding is supported")
        if float(prep["f_min"]) != 0.0:
            raise TrimProviderError("Only f_min=0 is supported")
        if float(prep["f_max"]) != float(prep["sample_rate"]) / 2:
            raise TrimProviderError("f_max must equal the Nyquist frequency")
        if not math.isfinite(float(prep["log_floor"])) or float(prep["log_floor"]) <= 0:
            raise TrimProviderError("log_floor must be positive and finite")
        if int(prep["resampling_lowpass_filter_width"]) <= 0:
            raise TrimProviderError("Resampling filter width must be positive")
        if not 0 < float(prep["resampling_rolloff"]) <= 1:
            raise TrimProviderError("Resampling rolloff must be in (0, 1]")
        if decoder["interval_policy"] != "longest_run_first_on_tie":
            raise TrimProviderError("Unsupported decoder interval policy")
        if decoder["empty_positive_policy"] != "error":
            raise TrimProviderError("Unsupported decoder empty-positive policy")

        numeric = (
            prep["sample_rate"],
            prep["max_duration_seconds"],
            prep["n_fft"],
            prep["win_length"],
            prep["hop_length"],
            prep["n_mels"],
            prep["f_max"],
        )
        if any(not math.isfinite(float(value)) or float(value) <= 0 for value in numeric):
            raise TrimProviderError("Model configuration contains invalid numbers")
        if not math.isfinite(float(decoder["bridge_ms"])) or decoder["bridge_ms"] < 0:
            raise TrimProviderError("bridge_ms must be finite and nonnegative")
        for key in ("sample_rate", "n_fft", "win_length", "hop_length", "n_mels"):
            if isinstance(prep[key], bool) or int(prep[key]) != prep[key]:
                raise TrimProviderError(f"{key} must be an integer")
        if round(prep["sample_rate"] * prep["max_duration_seconds"]) < prep["n_fft"]:
            raise TrimProviderError("The padded input must contain a full STFT window")
        threshold = float(decoder["threshold"])
        if not 0 < threshold < 1:
            raise TrimProviderError("Decoder threshold must be between 0 and 1")

        return cls(
            path=manifest_path,
            model_path=model_path,
            schema_version=int(raw["schema_version"]),
            model_id=str(raw["model_id"]),
            model_version=str(raw["model_version"]),
            model_type=str(raw["model_type"]),
            model_sha256=expected_sha,
            input_name=str(raw["input_name"]),
            output_name=str(raw["output_name"]),
            sample_rate=int(prep["sample_rate"]),
            channel_policy=str(prep["channel_policy"]),
            resampling_method=str(prep["resampling_method"]),
            resampling_lowpass_filter_width=int(
                prep["resampling_lowpass_filter_width"]
            ),
            resampling_rolloff=float(prep["resampling_rolloff"]),
            max_duration_seconds=float(prep["max_duration_seconds"]),
            n_fft=int(prep["n_fft"]),
            win_length=int(prep["win_length"]),
            hop_length=int(prep["hop_length"]),
            n_mels=int(prep["n_mels"]),
            f_min=float(prep["f_min"]),
            f_max=float(prep["f_max"]),
            log_floor=float(prep["log_floor"]),
            threshold=threshold,
            bridge_ms=float(decoder["bridge_ms"]),
            preprocessing_version=str(prep["version"]),
            decoder_version=str(decoder["version"]),
            config={
                "preprocessing": prep,
                "decoder": decoder,
                "model_id": raw["model_id"],
                "model_version": raw["model_version"],
            },
        )
