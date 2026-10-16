"""Tabular exports for persisted annotations."""

import csv
import os
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path

from smartaudiocrop.annotations.store import STATUS_VIEWED


CSV_COLUMNS = (
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
    "proposal_source",
    "prediction_id",
    "model_id",
    "model_version",
    "model_sha256",
    "threshold",
)


class AnnotationExportError(Exception):
    """Raised when an annotation export cannot be written."""


class AnnotationExporter:
    @staticmethod
    def export_csv(
        annotations: Iterable[Mapping],
        destination: str | Path,
    ) -> None:
        """Write annotations using the stable CSV export schema."""

        destination = Path(destination)
        temporary_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                temporary_path = Path(output.name)
                writer = csv.DictWriter(
                    output,
                    fieldnames=CSV_COLUMNS,
                    lineterminator="\n",
                )
                writer.writeheader()

                for annotation in annotations:
                    writer.writerow(
                        {
                            "filename": annotation["filename"],
                            "duration": annotation["duration"],
                            "sample_rate": annotation["sample_rate"],
                            "auto_start": annotation["auto_start"],
                            "auto_end": annotation["auto_end"],
                            "manual_start": annotation["manual_start"],
                            "manual_end": annotation["manual_end"],
                            "delta_start_ms": annotation["delta_start_ms"],
                            "delta_end_ms": annotation["delta_end_ms"],
                            "reviewed": (
                                "true"
                                if annotation["status"] == STATUS_VIEWED
                                else "false"
                            ),
                            "updated_at": annotation["updated_at"],
                            "proposal_source": annotation.get("proposal_source"),
                            "prediction_id": annotation.get("prediction_id"),
                            "model_id": annotation.get("model_id"),
                            "model_version": annotation.get("model_version"),
                            "model_sha256": annotation.get("model_sha256"),
                            "threshold": annotation.get("threshold"),
                        }
                    )

            os.replace(temporary_path, destination)
        except (OSError, csv.Error) as exc:
            raise AnnotationExportError(
                f"Could not write annotation export: {exc}"
            ) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
