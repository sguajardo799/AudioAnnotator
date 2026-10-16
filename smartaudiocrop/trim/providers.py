"""Provider-neutral trim proposal contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from smartaudiocrop.trim.config import TrimConfig
from smartaudiocrop.trim.detector import estimate_trim


class TrimProviderError(RuntimeError):
    """Base error suitable for presentation to the user."""


class NoActivityDetected(TrimProviderError):
    """Raised when a provider cannot produce a valid interval."""


@dataclass(frozen=True)
class TrimProposal:
    start: float
    end: float
    source: str
    audio_sha256: str
    config: dict
    model_id: str | None = None
    model_version: str | None = None
    model_sha256: str | None = None
    preprocessing_version: str | None = None
    decoder_version: str | None = None
    threshold: float | None = None
    bridge_ms: float | None = None
    truncated: bool = False


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def config_fingerprint(config: dict) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class HeuristicTrimProvider:
    source = "heuristic"

    def __init__(self, config: TrimConfig):
        self.config = config

    def infer(
        self,
        audio: np.ndarray,
        sample_rate: int,
        audio_path: str | Path,
        audio_sha256: str | None = None,
    ) -> TrimProposal:
        result = estimate_trim(audio, sample_rate, self.config)
        if result is None:
            raise NoActivityDetected("The heuristic detector found no activity")
        return TrimProposal(
            start=result.start,
            end=result.end,
            source=self.source,
            audio_sha256=audio_sha256 or file_sha256(audio_path),
            config=asdict(self.config),
        )
