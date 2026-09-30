import unittest

import numpy as np

from smartaudiocrop.audio.analysis import spectrogram


class SpectrogramTests(unittest.TestCase):
    def test_output_keeps_time_frequency_orientation_and_peak_level(self):
        sample_rate = 8_000
        time = np.arange(sample_rate, dtype=np.float64) / sample_rate
        audio = np.sin(2 * np.pi * 440 * time)

        result, times, frequencies = spectrogram(
            audio,
            sample_rate,
        )

        self.assertEqual(result.shape, (len(times), len(frequencies)))
        self.assertAlmostEqual(float(result.max()), 0.0)
        self.assertTrue(np.all(np.isfinite(result)))


if __name__ == "__main__":
    unittest.main()
