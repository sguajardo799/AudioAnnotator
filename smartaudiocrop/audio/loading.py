"""Audio file loading."""

from pathlib import Path
from hashlib import sha256
from io import BytesIO

import numpy as np
import soundfile as sf


def load_audio(path: str | Path) -> tuple[np.ndarray, int]:
    """Load an audio file using the application's existing format."""

    return sf.read(
        path,
        dtype="float32",
    )


def load_audio_snapshot(path: str | Path) -> tuple[np.ndarray, int, str]:
    """Decode and identify the exact same file bytes, even if the path changes."""

    payload = Path(path).read_bytes()
    audio, sample_rate = sf.read(BytesIO(payload), dtype="float32")
    return audio, sample_rate, sha256(payload).hexdigest()
