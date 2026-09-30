"""Audio file loading."""

from pathlib import Path

import numpy as np
import soundfile as sf


def load_audio(path: str | Path) -> tuple[np.ndarray, int]:
    """Load an audio file using the application's existing format."""

    return sf.read(
        path,
        dtype="float32",
    )
