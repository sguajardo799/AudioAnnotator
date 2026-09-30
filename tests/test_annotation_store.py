import tempfile
import unittest
from pathlib import Path

from smartaudiocrop.annotations.store import (
    STATUS_VIEWED,
    AnnotationStore,
)


class AnnotationStoreTests(unittest.TestCase):
    def test_save_and_update_preserve_schema_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AnnotationStore(Path(directory) / "annotations.db")

            store.save(
                filename="sample.wav",
                duration=2.0,
                sample_rate=48_000,
                auto_start=0.2,
                auto_end=1.8,
                manual_start=0.25,
                manual_end=1.7,
                status=STATUS_VIEWED,
            )

            annotation = store.get("sample.wav")
            self.assertIsNotNone(annotation)
            self.assertEqual(store.count(), 1)
            self.assertTrue(store.exists("sample.wav"))
            self.assertAlmostEqual(annotation["delta_start_ms"], 50.0)
            self.assertAlmostEqual(annotation["delta_end_ms"], -100.0)
            self.assertEqual(annotation["status"], STATUS_VIEWED)
            self.assertTrue(annotation["is_modified"])
            self.assertEqual(
                store.viewed_filenames(),
                {"sample.wav"},
            )

            store.save(
                filename="sample.wav",
                duration=2.0,
                sample_rate=48_000,
                auto_start=0.2,
                auto_end=1.8,
                manual_start=0.3,
                manual_end=1.6,
                status=STATUS_VIEWED,
            )

            self.assertEqual(store.count(), 1)
            updated = store.get("sample.wav")
            self.assertAlmostEqual(updated["manual_start"], 0.3)
            self.assertAlmostEqual(updated["manual_end"], 1.6)
            store.close()

    def test_equal_bounds_are_not_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AnnotationStore(Path(directory) / "annotations.db")

            store.save(
                filename="unchanged.wav",
                duration=2.0,
                sample_rate=48_000,
                auto_start=0.2,
                auto_end=1.8,
                manual_start=0.2,
                manual_end=1.8,
                status=STATUS_VIEWED,
            )

            annotation = store.get("unchanged.wav")
            self.assertFalse(annotation["is_modified"])
            store.close()


if __name__ == "__main__":
    unittest.main()
