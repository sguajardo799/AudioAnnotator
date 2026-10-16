import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from smartaudiocrop.trim.decoder import decode_crnn_mask
from smartaudiocrop.trim.model_package import ModelManifest
from smartaudiocrop.trim.onnx_preprocessing import OnnxAudioPreprocessor
from smartaudiocrop.trim.onnx_provider import OnnxTrimProvider
from smartaudiocrop.trim.providers import NoActivityDetected, TrimProviderError


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "model_packages" / "crnn_baseline-1.0.0" / "model_manifest.json"


class OnnxRuntimeTests(unittest.TestCase):
    def test_frontend_and_logits_match_independent_torchaudio_reference(self):
        provider = OnnxTrimProvider(MANIFEST)
        with np.load(ROOT / "tests/fixtures/onnx_frontend_reference.npz") as reference:
            for rate in (16000, 8000, 44100, 48000):
                with self.subTest(sample_rate=rate):
                    processed = provider.preprocessor.transform(
                        reference[f"audio_{rate}"], rate
                    )
                    np.testing.assert_allclose(
                        processed.features, reference[f"features_{rate}"],
                        atol=1e-4, rtol=1e-5,
                    )
                    self.assertEqual(
                        processed.valid_frames,
                        int(reference[f"valid_frames_{rate}"]),
                    )
                    logits = provider.session.run(
                        [provider.manifest.output_name],
                        {provider.manifest.input_name: processed.features},
                    )[0]
                    np.testing.assert_allclose(
                        logits, reference[f"logits_{rate}"], atol=1e-3, rtol=0,
                    )
                    try:
                        reference_bounds = decode_crnn_mask(
                            reference[f"logits_{rate}"], processed.valid_frames,
                            processed.processed_duration, provider.manifest,
                        )
                    except NoActivityDetected:
                        with self.assertRaises(NoActivityDetected):
                            decode_crnn_mask(
                                logits, processed.valid_frames,
                                processed.processed_duration, provider.manifest,
                            )
                    else:
                        bounds = decode_crnn_mask(
                            logits, processed.valid_frames,
                            processed.processed_duration, provider.manifest,
                        )
                        np.testing.assert_allclose(bounds, reference_bounds, atol=.01, rtol=0)

    def test_bundled_package_loads_and_matches_session_contract(self):
        provider = OnnxTrimProvider(MANIFEST)

        self.assertEqual(provider.manifest.model_id, "crnn_baseline")
        self.assertEqual(provider.manifest.model_version, "1.0.0")
        self.assertEqual(provider.session.get_inputs()[0].shape[2], 64)
        self.assertEqual(len(provider.session.get_outputs()[0].shape), 2)

    def test_preprocessor_handles_stereo_and_truncates_to_six_seconds(self):
        manifest = ModelManifest.load(MANIFEST)
        preprocessor = OnnxAudioPreprocessor(manifest)
        audio = np.zeros((7 * 8_000, 2), dtype=np.float32)
        audio[:, 0] = 0.1
        audio[:, 1] = -0.1

        result = preprocessor.transform(audio, 8_000)

        self.assertEqual(result.features.shape, (1, 1, 64, 598))
        self.assertEqual(result.valid_frames, 598)
        self.assertEqual(result.processed_duration, 6.0)
        self.assertTrue(result.truncated)
        self.assertTrue(np.all(np.isfinite(result.features)))

    def test_decoder_bridges_gap_and_chooses_longest_interval(self):
        manifest = SimpleNamespace(
            threshold=0.5,
            bridge_ms=10,
            sample_rate=1000,
            hop_length=10,
            n_fft=20,
        )
        logits = np.array([10, 10, -10, 10, 10, -10, -10], dtype=np.float32)

        start, end = decode_crnn_mask(logits, 7, 0.08, manifest)

        self.assertEqual(start, 0.0)
        self.assertEqual(end, 0.06)

    def test_decoder_rejects_output_without_positive_frames(self):
        manifest = SimpleNamespace(
            threshold=0.5,
            bridge_ms=200,
            sample_rate=16000,
            hop_length=160,
            n_fft=400,
        )
        with self.assertRaises(NoActivityDetected):
            decode_crnn_mask(np.full(10, -10, dtype=np.float32), 10, 1.0, manifest)

    def test_manifest_rejects_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = MANIFEST.read_text(encoding="utf-8")
            source = source.replace("6ced76fa", "0ced76fa")
            (root / "model_manifest.json").write_text(source, encoding="utf-8")
            (root / "model.onnx").write_bytes(
                (MANIFEST.parent / "model.onnx").read_bytes()
            )

            with self.assertRaises(TrimProviderError):
                ModelManifest.load(root / "model_manifest.json")

    def test_manifest_rejects_frontend_configuration_not_implemented(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
            manifest["preprocessing"]["win_length"] = 320
            (root / "model_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (root / "model.onnx").write_bytes(
                (MANIFEST.parent / "model.onnx").read_bytes()
            )

            with self.assertRaises(TrimProviderError):
                ModelManifest.load(root / "model_manifest.json")


if __name__ == "__main__":
    unittest.main()
