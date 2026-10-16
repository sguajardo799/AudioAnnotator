import unittest
import tempfile
import wave
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import numpy as np

from smartaudiocrop.audio.loading import load_audio, load_audio_snapshot


class AudioLoadingTests(unittest.TestCase):
    def test_snapshot_hash_identifies_the_exact_decoded_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.wav"
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(np.zeros(400, dtype="<i2").tobytes())
            expected_hash = sha256(path.read_bytes()).hexdigest()
            audio, sample_rate, digest = load_audio_snapshot(path)
            self.assertEqual(sample_rate, 16000)
            self.assertEqual(audio.shape, (400,))
            self.assertEqual(digest, expected_hash)

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
