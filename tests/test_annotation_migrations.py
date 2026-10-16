import sqlite3
import tempfile
import unittest
from pathlib import Path

from smartaudiocrop.annotations.store import (
    SCHEMA_VERSION,
    STATUS_NOT_VIEWED,
    STATUS_VIEWED,
    AnnotationStore,
    AnnotationStoreError,
)


class AnnotationMigrationTests(unittest.TestCase):
    def test_newer_database_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "annotations.db"
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA user_version = 99")
            connection.close()

            with self.assertRaises(AnnotationStoreError):
                AnnotationStore(path)

    def test_legacy_database_is_migrated_without_changing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "annotations.db"
            connection = sqlite3.connect(path)
            connection.execute(
                """
                CREATE TABLE annotations (
                    filename TEXT PRIMARY KEY,
                    duration REAL NOT NULL,
                    sample_rate INTEGER NOT NULL,
                    auto_start REAL NOT NULL,
                    auto_end REAL NOT NULL,
                    manual_start REAL NOT NULL,
                    manual_end REAL NOT NULL,
                    delta_start_ms REAL NOT NULL,
                    delta_end_ms REAL NOT NULL,
                    status TEXT NOT NULL,
                    is_modified INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO annotations VALUES (
                    'legacy.wav', 2.0, 16000, 0.2, 1.8, 0.25, 1.7,
                    50.0, -100.0, 'VIEWED', 1, '2026-01-02 03:04:05'
                )
                """
            )
            connection.commit()
            connection.close()

            store = AnnotationStore(path)
            row = store.get("legacy.wav")
            version = store.connection.execute("PRAGMA user_version").fetchone()[0]

            self.assertEqual(version, SCHEMA_VERSION)
            self.assertEqual(row["proposal_source"], "legacy")
            self.assertIsNone(row["prediction_id"])
            self.assertEqual(row["manual_start"], 0.25)
            self.assertEqual(row["updated_at"], "2026-01-02 03:04:05")
            store.close()

            reopened = AnnotationStore(path)
            self.assertEqual(reopened.get("legacy.wav"), row)
            reopened.close()

    def test_prediction_selection_preserves_manual_and_review_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AnnotationStore(Path(directory) / "annotations.db")
            first = store.insert_prediction(
                filename="sample.wav",
                audio_sha256="a" * 64,
                source="onnx_crnn",
                config={"threshold": 0.5},
                predicted_start=0.2,
                predicted_end=1.8,
            )
            second = store.insert_prediction(
                filename="sample.wav",
                audio_sha256="a" * 64,
                source="onnx_crnn",
                config={"threshold": 0.6},
                predicted_start=0.3,
                predicted_end=1.7,
            )
            store.save_manual_draft(
                filename="sample.wav",
                duration=2.0,
                sample_rate=16000,
                auto_start=0.2,
                auto_end=1.8,
                manual_start=0.25,
                manual_end=1.75,
                proposal_source="onnx_crnn",
                prediction_id=first,
            )

            store.select_prediction(filename="sample.wav", prediction_id=second)
            row = store.get("sample.wav")

            self.assertEqual(row["status"], STATUS_NOT_VIEWED)
            self.assertEqual(row["prediction_id"], second)
            self.assertEqual(row["manual_start"], 0.25)
            self.assertEqual(row["manual_end"], 1.75)
            self.assertAlmostEqual(row["delta_start_ms"], -50.0)
            store.confirm_annotation(
                filename="sample.wav",
                duration=2.0,
                sample_rate=16000,
                auto_start=0.3,
                auto_end=1.7,
                manual_start=0.25,
                manual_end=1.75,
                proposal_source="onnx_crnn",
                prediction_id=second,
            )
            self.assertEqual(store.get("sample.wav")["status"], STATUS_VIEWED)
            self.assertEqual(store.prediction_count(), 2)
            store.close()

    def test_manual_only_source_remains_null_after_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "annotations.db"
            store = AnnotationStore(path)
            store.save_manual_draft(
                filename="manual.wav",
                duration=1.0,
                sample_rate=16000,
                auto_start=0.1,
                auto_end=0.9,
                manual_start=0.1,
                manual_end=0.9,
                proposal_source=None,
                prediction_id=None,
            )
            store.close()

            reopened = AnnotationStore(path)
            self.assertIsNone(reopened.get("manual.wav")["proposal_source"])
            reopened.close()

    def test_failed_confirmation_rolls_back_manual_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AnnotationStore(Path(directory) / "annotations.db")
            values = dict(
                filename="sample.wav", duration=1.0, sample_rate=16000,
                auto_start=0.0, auto_end=1.0, manual_start=0.1,
                manual_end=0.9, proposal_source=None, prediction_id=None,
            )
            store.save_manual_draft(**values)
            before = store.get("sample.wav")
            store.connection.execute(
                """CREATE TRIGGER fail_confirmation BEFORE UPDATE ON annotations
                WHEN NEW.status = 'VIEWED'
                BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END"""
            )
            values["manual_start"] = 0.2
            with self.assertRaises(sqlite3.IntegrityError):
                store.confirm_annotation(**values)
            self.assertEqual(store.get("sample.wav"), before)
            store.close()


if __name__ == "__main__":
    unittest.main()
