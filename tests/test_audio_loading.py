import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from smartaudiocrop.audio.loading import load_audio


class AudioLoadingTests(unittest.TestCase):
    def test_loader_preserves_soundfile_dtype_contract(self):
        expected = np.array([0.0], dtype=np.float32)

        with patch(
            "smartaudiocrop.audio.loading.sf.read",
            return_value=(expected, 48_000),
        ) as read:
            audio, sample_rate = load_audio(Path("sample.wav"))

        read.assert_called_once_with(
            Path("sample.wav"),
            dtype="float32",
        )
        self.assertIs(audio, expected)
        self.assertEqual(sample_rate, 48_000)
