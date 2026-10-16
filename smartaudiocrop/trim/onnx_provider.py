"""ONNX Runtime trim provider."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import onnxruntime as ort

from smartaudiocrop.trim.decoder import decode_crnn_mask
from smartaudiocrop.trim.model_package import ModelManifest
from smartaudiocrop.trim.onnx_preprocessing import OnnxAudioPreprocessor
from smartaudiocrop.trim.providers import TrimProposal, TrimProviderError, file_sha256


class OnnxTrimProvider:
    source = "onnx_crnn"

    def __init__(self, manifest_path: str | Path):
        self.manifest = ModelManifest.load(manifest_path)
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(self.manifest.model_path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self._validate_session()
        self.preprocessor = OnnxAudioPreprocessor(self.manifest)

    def _validate_session(self) -> None:
        inputs = self.session.get_inputs()
        outputs = self.session.get_outputs()
        if len(inputs) != 1 or len(outputs) != 1:
            raise TrimProviderError("The model must have one input and one output")
        model_input = inputs[0]
        model_output = outputs[0]
        if model_input.name != self.manifest.input_name:
            raise TrimProviderError("The ONNX input name does not match the manifest")
        if model_output.name != self.manifest.output_name:
            raise TrimProviderError("The ONNX output name does not match the manifest")
        if model_input.type != "tensor(float)" or len(model_input.shape) != 4:
            raise TrimProviderError("The ONNX input must be a rank-4 float tensor")
        if isinstance(model_input.shape[0], int) and model_input.shape[0] != 1:
            raise TrimProviderError("The ONNX batch dimension is incompatible")
        if model_input.shape[1] != 1:
            raise TrimProviderError("The ONNX channel dimension must be one")
        if isinstance(model_input.shape[2], int) and model_input.shape[2] != self.manifest.n_mels:
            raise TrimProviderError("The ONNX Mel dimension does not match the manifest")
        if isinstance(model_input.shape[3], int):
            raise TrimProviderError("The ONNX frame input dimension must be dynamic")
        if model_output.type != "tensor(float)" or len(model_output.shape) != 2:
            raise TrimProviderError("The ONNX output must be a rank-2 float tensor")
        if isinstance(model_output.shape[0], int) and model_output.shape[0] != 1:
            raise TrimProviderError("The ONNX output batch dimension is incompatible")
        if isinstance(model_output.shape[1], int):
            raise TrimProviderError("The ONNX frame output dimension must be dynamic")
        probe_frames = 17
        probe = np.zeros(
            (1, 1, self.manifest.n_mels, probe_frames), dtype=np.float32
        )
        probe_output = self.session.run(
            [self.manifest.output_name],
            {self.manifest.input_name: probe},
        )[0]
        if probe_output.shape != (1, probe_frames):
            raise TrimProviderError("ONNX input and output frame axes are incompatible")

    def infer(
        self,
        audio: np.ndarray,
        sample_rate: int,
        audio_path: str | Path,
        audio_sha256: str | None = None,
    ) -> TrimProposal:
        processed = self.preprocessor.transform(audio, sample_rate)
        output = self.session.run(
            [self.manifest.output_name],
            {self.manifest.input_name: processed.features},
        )[0]
        start, end = decode_crnn_mask(
            output,
            processed.valid_frames,
            processed.processed_duration,
            self.manifest,
        )
        return TrimProposal(
            start=start,
            end=end,
            source=self.source,
            audio_sha256=audio_sha256 or file_sha256(audio_path),
            config=self.manifest.config,
            model_id=self.manifest.model_id,
            model_version=self.manifest.model_version,
            model_sha256=self.manifest.model_sha256,
            preprocessing_version=self.manifest.preprocessing_version,
            decoder_version=self.manifest.decoder_version,
            threshold=self.manifest.threshold,
            bridge_ms=self.manifest.bridge_ms,
            truncated=processed.truncated,
        )
