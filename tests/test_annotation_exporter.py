import csv
import tempfile
import unittest
from pathlib import Path

from smartaudiocrop.annotations.exporter import (
    CSV_COLUMNS,
    AnnotationExportError,
    AnnotationExporter,
)
from smartaudiocrop.annotations.store import (
    STATUS_VIEWED,
    AnnotationStore,
)


class AnnotationExporterTests(unittest.TestCase):
    def test_csv_has_stable_schema_values_and_boolean_review_state(self):
        annotations = [
            self._annotation(
                filename='áudio, "one".wav',
                status="VIEWED",
                manual_start=0.30000000000000004,
            ),
            self._annotation(
                filename="two.wav",
                status="NOT_VIEWED",
                manual_start=0.2,
            ),
        ]

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "annotations.csv"
            AnnotationExporter.export_csv(annotations, destination)

            with destination.open(encoding="utf-8", newline="") as source:
                rows = list(csv.DictReader(source))

            self.assertEqual(tuple(rows[0]), CSV_COLUMNS)
            self.assertEqual(rows[0]["filename"], 'áudio, "one".wav')
            self.assertEqual(rows[0]["reviewed"], "true")
            self.assertEqual(rows[1]["reviewed"], "false")
            self.assertEqual(
                float(rows[0]["manual_start"]),
                0.30000000000000004,
            )
            self.assertEqual(int(rows[0]["sample_rate"]), 48_000)

    def test_repeated_export_produces_identical_bytes(self):
        annotations = [self._annotation()]

        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.csv"
            second = Path(directory) / "second.csv"

            AnnotationExporter.export_csv(annotations, first)
            AnnotationExporter.export_csv(annotations, second)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertTrue(first.read_bytes().endswith(b"\n"))

    def test_failed_export_preserves_existing_destination(self):
        def failing_annotations():
            yield self._annotation()
            raise OSError("simulated write failure")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "annotations.csv"
            destination.write_text("existing data", encoding="utf-8")

            with self.assertRaises(AnnotationExportError):
                AnnotationExporter.export_csv(
                    failing_annotations(),
                    destination,
                )

            self.assertEqual(
                destination.read_text(encoding="utf-8"),
                "existing data",
            )
            self.assertEqual(list(root.glob("*.tmp")), [])

    def test_persisted_deltas_export_without_modifying_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "annotations.db"
            destination = root / "annotations.csv"
            store = AnnotationStore(database)
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
            database_before = database.read_bytes()
            persisted = store.get_all()

            AnnotationExporter.export_csv(persisted, destination)

            with destination.open(encoding="utf-8", newline="") as source:
                row = next(csv.DictReader(source))

            database_after = database.read_bytes()
            store.close()

            self.assertEqual(
                float(row["delta_start_ms"]),
                persisted[0]["delta_start_ms"],
            )
            self.assertEqual(
                float(row["delta_end_ms"]),
                persisted[0]["delta_end_ms"],
            )
            self.assertEqual(row["reviewed"], "true")
            self.assertEqual(database_after, database_before)

    def test_provenance_columns_are_appended_after_legacy_columns(self):
        legacy_prefix = (
            "filename",
            "duration",
            "sample_rate",
            "auto_start",
            "auto_end",
            "manual_start",
            "manual_end",
            "delta_start_ms",
            "delta_end_ms",
            "reviewed",
            "updated_at",
        )

        self.assertEqual(CSV_COLUMNS[: len(legacy_prefix)], legacy_prefix)
        self.assertEqual(
            CSV_COLUMNS[len(legacy_prefix) :],
            (
                "proposal_source",
                "prediction_id",
                "model_id",
                "model_version",
                "model_sha256",
                "threshold",
            ),
        )

    @staticmethod
    def _annotation(
        *,
        filename="sample.wav",
        status="VIEWED",
        manual_start=0.25,
    ):
        return {
            "filename": filename,
            "duration": 2.0,
            "sample_rate": 48_000,
            "auto_start": 0.2,
            "auto_end": 1.8,
            "manual_start": manual_start,
            "manual_end": 1.7,
            "delta_start_ms": (manual_start - 0.2) * 1000.0,
            "delta_end_ms": -100.0,
            "status": status,
            "is_modified": True,
            "updated_at": "2026-10-01 10:30:00",
        }


if __name__ == "__main__":
    unittest.main()
