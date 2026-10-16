"""Qt worker that owns ONNX session creation and inference."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from smartaudiocrop.trim.onnx_provider import OnnxTrimProvider
from smartaudiocrop.trim.providers import file_sha256, TrimProviderError


@dataclass(frozen=True)
class ModelLoadRequest:
    revision: int
    manifest_path: Path


@dataclass(frozen=True)
class InferenceRequest:
    request_id: int
    project_generation: int
    project_id: str
    audio_generation: int
    audio_id: str
    model_revision: int
    audio_path: Path
    audio_sha256: str
    audio: np.ndarray
    sample_rate: int
    force: bool = False


class InferenceWorker(QObject):
    model_loaded = Signal(object, object)
    inference_succeeded = Signal(object, object)
    failed = Signal(object, str)
    idle = Signal()

    def __init__(self):
        super().__init__()
        self._provider: OnnxTrimProvider | None = None
        self._model_revision = 0

    @Slot(object)
    def load_model(self, request: ModelLoadRequest) -> None:
        try:
            provider = OnnxTrimProvider(request.manifest_path)
        except Exception as exc:
            self.failed.emit(request, str(exc))
            self.idle.emit()
            return
        self._provider = provider
        self._model_revision = request.revision
        self.model_loaded.emit(request, provider.manifest)
        self.idle.emit()

    @Slot(object)
    def infer(self, request: InferenceRequest) -> None:
        if self._provider is None or request.model_revision != self._model_revision:
            self.failed.emit(request, "The selected ONNX model is not loaded")
            self.idle.emit()
            return
        try:
            if file_sha256(request.audio_path) != request.audio_sha256:
                raise TrimProviderError("The WAV changed since it was loaded; reopen it")
            proposal = self._provider.infer(
                request.audio,
                request.sample_rate,
                request.audio_path,
                request.audio_sha256,
            )
            if file_sha256(request.audio_path) != request.audio_sha256:
                raise TrimProviderError("The WAV changed during inference; result discarded")
        except Exception as exc:
            self.failed.emit(request, str(exc))
        else:
            self.inference_succeeded.emit(request, proposal)
        finally:
            self.idle.emit()
