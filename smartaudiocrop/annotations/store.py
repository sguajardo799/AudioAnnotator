"""SQLite persistence for annotations and immutable trim predictions."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Mapping
from hashlib import sha256
from math import isclose
from pathlib import Path


STATUS_NOT_VIEWED = "NOT_VIEWED"
STATUS_VIEWED = "VIEWED"
SCHEMA_VERSION = 1

ANNOTATION_COLUMNS = (
    "filename",
    "duration",
    "sample_rate",
    "auto_start",
    "auto_end",
    "manual_start",
    "manual_end",
    "delta_start_ms",
    "delta_end_ms",
    "status",
    "is_modified",
    "updated_at",
    "proposal_source",
    "prediction_id",
)

PREDICTION_COLUMNS = (
    "id",
    "filename",
    "audio_sha256",
    "source",
    "model_id",
    "model_version",
    "model_sha256",
    "preprocessing_version",
    "decoder_version",
    "threshold",
    "bridge_ms",
    "config_json",
    "config_sha256",
    "predicted_start",
    "predicted_end",
    "created_at",
)


class AnnotationStoreError(ValueError):
    """Raised when a persistence operation would violate domain invariants."""


def canonical_config(config: Mapping) -> tuple[str, str]:
    """Return stable JSON and SHA-256 for prediction reuse."""

    text = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return text, sha256(text.encode("utf-8")).hexdigest()


class AnnotationStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        try:
            self._migrate()
        except Exception:
            self.connection.close()
            raise

    def _migrate(self) -> None:
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            current_version = int(
                self.connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if current_version > SCHEMA_VERSION:
                raise AnnotationStoreError(
                    "Database schema is newer than this application supports"
                )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS annotations (
                    filename TEXT PRIMARY KEY,
                    duration REAL NOT NULL,
                    sample_rate INTEGER NOT NULL,
                    auto_start REAL NOT NULL,
                    auto_end REAL NOT NULL,
                    manual_start REAL NOT NULL,
                    manual_end REAL NOT NULL,
                    delta_start_ms REAL NOT NULL,
                    delta_end_ms REAL NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN ('NOT_VIEWED', 'VIEWED')),
                    is_modified INTEGER NOT NULL
                        CHECK (is_modified IN (0, 1)),
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            columns = {
                row["name"]
                for row in self.connection.execute(
                    "PRAGMA table_info(annotations)"
                )
            }
            added_proposal_source = "proposal_source" not in columns
            if added_proposal_source:
                self.connection.execute(
                    "ALTER TABLE annotations ADD COLUMN proposal_source TEXT"
                )
            if "prediction_id" not in columns:
                self.connection.execute(
                    "ALTER TABLE annotations ADD COLUMN prediction_id INTEGER"
                )

            if current_version == 0:
                self.connection.execute(
                    """
                    UPDATE annotations
                    SET proposal_source = 'legacy'
                    WHERE proposal_source IS NULL
                      AND prediction_id IS NULL
                    """
                )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    audio_sha256 TEXT NOT NULL,
                    source TEXT NOT NULL
                        CHECK (source IN ('onnx_crnn', 'heuristic')),
                    model_id TEXT,
                    model_version TEXT,
                    model_sha256 TEXT,
                    preprocessing_version TEXT,
                    decoder_version TEXT,
                    threshold REAL,
                    bridge_ms REAL,
                    config_json TEXT NOT NULL,
                    config_sha256 TEXT NOT NULL,
                    predicted_start REAL NOT NULL,
                    predicted_end REAL NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CHECK (predicted_start >= 0),
                    CHECK (predicted_end > predicted_start)
                )
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_predictions_reuse
                ON predictions (
                    filename,
                    source,
                    audio_sha256,
                    model_sha256,
                    config_sha256,
                    id
                )
                """
            )
            self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @staticmethod
    def _validate_bounds(start: float, end: float, duration: float) -> None:
        if not all(math.isfinite(value) for value in (start, end, duration)):
            raise AnnotationStoreError("Trim bounds and duration must be finite")
        if duration <= 0 or not 0 <= start < end <= duration:
            raise AnnotationStoreError(
                f"Invalid trim bounds {start}, {end} for duration {duration}"
            )

    @staticmethod
    def _derived(
        auto_start: float,
        auto_end: float,
        manual_start: float,
        manual_end: float,
    ) -> tuple[float, float, int]:
        delta_start_ms = (manual_start - auto_start) * 1000.0
        delta_end_ms = (manual_end - auto_end) * 1000.0
        is_modified = not (
            isclose(manual_start, auto_start, rel_tol=0.0, abs_tol=1e-6)
            and isclose(manual_end, auto_end, rel_tol=0.0, abs_tol=1e-6)
        )
        return delta_start_ms, delta_end_ms, int(is_modified)

    def save(
        self,
        *,
        filename: str,
        duration: float,
        sample_rate: int,
        auto_start: float,
        auto_end: float,
        manual_start: float,
        manual_end: float,
        status: str,
        proposal_source: str | None = None,
        prediction_id: int | None = None,
    ) -> None:
        """Compatibility API for callers that explicitly provide complete state."""

        self._validate_bounds(auto_start, auto_end, duration)
        self._validate_bounds(manual_start, manual_end, duration)
        if status not in {STATUS_NOT_VIEWED, STATUS_VIEWED}:
            raise AnnotationStoreError(f"Unknown annotation status: {status}")
        self._validate_prediction_reference(
            filename, proposal_source, prediction_id
        )
        with self.connection:
            self._write_complete_annotation(
                filename=filename,
                duration=duration,
                sample_rate=sample_rate,
                auto_start=auto_start,
                auto_end=auto_end,
                manual_start=manual_start,
                manual_end=manual_end,
                status=status,
                proposal_source=proposal_source,
                prediction_id=prediction_id,
            )

    def _validate_prediction_reference(
        self,
        filename: str,
        proposal_source: str | None,
        prediction_id: int | None,
    ) -> None:
        if proposal_source not in {None, "legacy", "heuristic", "onnx_crnn"}:
            raise AnnotationStoreError(f"Unknown proposal source: {proposal_source}")
        if prediction_id is None:
            if proposal_source in {"heuristic", "onnx_crnn"}:
                raise AnnotationStoreError("A detector proposal requires prediction_id")
            return
        prediction = self.get_prediction(prediction_id)
        if prediction is None or prediction["filename"] != filename:
            raise AnnotationStoreError("Prediction does not belong to this audio file")
        if prediction["source"] != proposal_source:
            raise AnnotationStoreError("Prediction source does not match annotation")

    def _write_complete_annotation(
        self,
        *,
        filename: str,
        duration: float,
        sample_rate: int,
        auto_start: float,
        auto_end: float,
        manual_start: float,
        manual_end: float,
        status: str,
        proposal_source: str | None,
        prediction_id: int | None,
    ) -> None:
        delta_start, delta_end, modified = self._derived(
            auto_start, auto_end, manual_start, manual_end
        )
        self.connection.execute(
            """
            INSERT INTO annotations (
                filename, duration, sample_rate, auto_start, auto_end,
                manual_start, manual_end, delta_start_ms, delta_end_ms,
                status, is_modified, updated_at, proposal_source,
                prediction_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
            ON CONFLICT(filename) DO UPDATE SET
                duration = excluded.duration,
                sample_rate = excluded.sample_rate,
                auto_start = excluded.auto_start,
                auto_end = excluded.auto_end,
                manual_start = excluded.manual_start,
                manual_end = excluded.manual_end,
                delta_start_ms = excluded.delta_start_ms,
                delta_end_ms = excluded.delta_end_ms,
                status = excluded.status,
                is_modified = excluded.is_modified,
                proposal_source = excluded.proposal_source,
                prediction_id = excluded.prediction_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                filename,
                duration,
                sample_rate,
                auto_start,
                auto_end,
                manual_start,
                manual_end,
                delta_start,
                delta_end,
                status,
                modified,
                proposal_source,
                prediction_id,
            ),
        )

    def insert_prediction(
        self,
        *,
        filename: str,
        audio_sha256: str,
        source: str,
        config: Mapping,
        predicted_start: float,
        predicted_end: float,
        model_id: str | None = None,
        model_version: str | None = None,
        model_sha256: str | None = None,
        preprocessing_version: str | None = None,
        decoder_version: str | None = None,
        threshold: float | None = None,
        bridge_ms: float | None = None,
    ) -> int:
        if source not in {"heuristic", "onnx_crnn"}:
            raise AnnotationStoreError(f"Unknown prediction source: {source}")
        if not (
            math.isfinite(predicted_start)
            and math.isfinite(predicted_end)
            and 0 <= predicted_start < predicted_end
        ):
            raise AnnotationStoreError("Prediction bounds are invalid")
        config_json, config_sha256 = canonical_config(config)
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO predictions (
                    filename, audio_sha256, source, model_id, model_version,
                    model_sha256, preprocessing_version, decoder_version,
                    threshold, bridge_ms, config_json, config_sha256,
                    predicted_start, predicted_end
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    filename,
                    audio_sha256,
                    source,
                    model_id,
                    model_version,
                    model_sha256,
                    preprocessing_version,
                    decoder_version,
                    threshold,
                    bridge_ms,
                    config_json,
                    config_sha256,
                    predicted_start,
                    predicted_end,
                ),
            )
        return int(cursor.lastrowid)

    def find_reusable_prediction(
        self,
        *,
        filename: str,
        audio_sha256: str,
        source: str,
        config: Mapping,
        model_sha256: str | None = None,
    ) -> dict | None:
        _config_json, config_sha256 = canonical_config(config)
        row = self.connection.execute(
            """
            SELECT * FROM predictions
            WHERE filename = ? AND audio_sha256 = ? AND source = ?
              AND config_sha256 = ? AND model_sha256 IS ?
            ORDER BY id DESC LIMIT 1
            """,
            (filename, audio_sha256, source, config_sha256, model_sha256),
        ).fetchone()
        return self._row_to_prediction(row) if row else None

    def get_prediction(self, prediction_id: int) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM predictions WHERE id = ?", (prediction_id,)
        ).fetchone()
        return self._row_to_prediction(row) if row else None

    def select_prediction(self, *, filename: str, prediction_id: int) -> None:
        prediction = self.get_prediction(prediction_id)
        annotation = self.get(filename)
        if prediction is None or prediction["filename"] != filename:
            raise AnnotationStoreError("Prediction does not belong to this audio file")
        if annotation is None:
            raise AnnotationStoreError("Cannot select a prediction without an annotation")
        auto_start = float(prediction["predicted_start"])
        auto_end = float(prediction["predicted_end"])
        self._validate_bounds(auto_start, auto_end, float(annotation["duration"]))
        delta_start, delta_end, modified = self._derived(
            auto_start,
            auto_end,
            float(annotation["manual_start"]),
            float(annotation["manual_end"]),
        )
        with self.connection:
            self.connection.execute(
                """
                UPDATE annotations SET
                    auto_start = ?, auto_end = ?, proposal_source = ?,
                    prediction_id = ?, delta_start_ms = ?, delta_end_ms = ?,
                    is_modified = ?, updated_at = CURRENT_TIMESTAMP
                WHERE filename = ?
                """,
                (
                    auto_start,
                    auto_end,
                    prediction["source"],
                    prediction_id,
                    delta_start,
                    delta_end,
                    modified,
                    filename,
                ),
            )

    def save_manual_draft(
        self,
        *,
        filename: str,
        duration: float,
        sample_rate: int,
        auto_start: float,
        auto_end: float,
        manual_start: float,
        manual_end: float,
        proposal_source: str | None,
        prediction_id: int | None,
    ) -> None:
        """Persist manual work without changing review status or selected proposal."""

        self._validate_bounds(auto_start, auto_end, duration)
        self._validate_bounds(manual_start, manual_end, duration)
        self._validate_prediction_reference(
            filename, proposal_source, prediction_id
        )
        with self.connection:
            self._save_manual_draft(
                filename=filename,
                duration=duration,
                sample_rate=sample_rate,
                auto_start=auto_start,
                auto_end=auto_end,
                manual_start=manual_start,
                manual_end=manual_end,
                proposal_source=proposal_source,
                prediction_id=prediction_id,
            )

    def _save_manual_draft(
        self,
        *,
        filename: str,
        duration: float,
        sample_rate: int,
        auto_start: float,
        auto_end: float,
        manual_start: float,
        manual_end: float,
        proposal_source: str | None,
        prediction_id: int | None,
    ) -> None:
        current = self.get(filename)
        if current is None:
            self._write_complete_annotation(
                filename=filename,
                duration=duration,
                sample_rate=sample_rate,
                auto_start=auto_start,
                auto_end=auto_end,
                manual_start=manual_start,
                manual_end=manual_end,
                status=STATUS_NOT_VIEWED,
                proposal_source=proposal_source,
                prediction_id=prediction_id,
            )
            return

        self._validate_bounds(manual_start, manual_end, float(current["duration"]))
        delta_start, delta_end, modified = self._derived(
            float(current["auto_start"]),
            float(current["auto_end"]),
            manual_start,
            manual_end,
        )
        self.connection.execute(
            """
            UPDATE annotations SET
                duration = ?, sample_rate = ?, manual_start = ?,
                manual_end = ?, delta_start_ms = ?, delta_end_ms = ?,
                is_modified = ?, updated_at = CURRENT_TIMESTAMP
            WHERE filename = ?
            """,
            (
                duration,
                sample_rate,
                manual_start,
                manual_end,
                delta_start,
                delta_end,
                modified,
                filename,
            ),
        )

    def confirm_annotation(self, **values) -> None:
        self._validate_bounds(
            values["auto_start"], values["auto_end"], values["duration"]
        )
        self._validate_bounds(
            values["manual_start"], values["manual_end"], values["duration"]
        )
        self._validate_prediction_reference(
            values["filename"],
            values["proposal_source"],
            values["prediction_id"],
        )
        with self.connection:
            self._save_manual_draft(**values)
            self.connection.execute(
                """
                UPDATE annotations
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE filename = ?
                """,
                (STATUS_VIEWED, values["filename"]),
            )

    def get(self, filename: str) -> dict | None:
        row = self.connection.execute(
            f"SELECT {', '.join(ANNOTATION_COLUMNS)} FROM annotations WHERE filename = ?",
            (filename,),
        ).fetchone()
        return self._row_to_annotation(row) if row else None

    def get_all(self) -> list[dict]:
        rows = self.connection.execute(
            f"SELECT {', '.join(ANNOTATION_COLUMNS)} FROM annotations ORDER BY filename"
        ).fetchall()
        return [self._row_to_annotation(row) for row in rows]

    def get_all_for_export(self) -> list[dict]:
        rows = self.connection.execute(
            """
            SELECT a.*, p.model_id, p.model_version, p.model_sha256,
                   p.threshold
            FROM annotations AS a
            LEFT JOIN predictions AS p ON p.id = a.prediction_id
            ORDER BY a.filename
            """
        ).fetchall()
        return [self._row_to_annotation(row) for row in rows]

    @staticmethod
    def _row_to_annotation(row: sqlite3.Row) -> dict:
        annotation = dict(row)
        annotation["is_modified"] = bool(annotation["is_modified"])
        return annotation

    @staticmethod
    def _row_to_prediction(row: sqlite3.Row) -> dict:
        return dict(row)

    def viewed_filenames(self) -> set[str]:
        rows = self.connection.execute(
            "SELECT filename FROM annotations WHERE status = ?",
            (STATUS_VIEWED,),
        ).fetchall()
        return {str(row[0]) for row in rows}

    def exists(self, filename: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM annotations WHERE filename = ? LIMIT 1", (filename,)
        ).fetchone() is not None

    def count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM annotations").fetchone()[0])

    def prediction_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0])

    def close(self) -> None:
        self.connection.close()
