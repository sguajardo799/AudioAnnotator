import sqlite3
from math import isclose
from pathlib import Path


STATUS_NOT_VIEWED = "NOT_VIEWED"
STATUS_VIEWED = "VIEWED"

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
)


class AnnotationStore:
    """
    Persistencia de anotaciones utilizando SQLite.

    Cada archivo WAV posee como máximo una anotación.
    Guardar nuevamente el mismo filename actualiza
    la fila existente.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

        self.connection = sqlite3.connect(
            self.path
        )

        self._create_schema()

    def _create_schema(self):
        """
        Crea la tabla si todavía no existe.
        """

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

                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        self.connection.commit()

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
    ):
        """
        Inserta o actualiza la anotación de un archivo.

        filename es UNIQUE porque funciona como PRIMARY KEY.
        """

        delta_start_ms = (
            manual_start - auto_start
        ) * 1000.0

        delta_end_ms = (
            manual_end - auto_end
        ) * 1000.0

        is_modified = not (
            isclose(
                manual_start,
                auto_start,
                rel_tol=0.0,
                abs_tol=1e-6,
            )
            and isclose(
                manual_end,
                auto_end,
                rel_tol=0.0,
                abs_tol=1e-6,
            )
        )

        self.connection.execute(
            """
            INSERT INTO annotations (
                filename,
                duration,
                sample_rate,
                auto_start,
                auto_end,
                manual_start,
                manual_end,
                delta_start_ms,
                delta_end_ms,
                status,
                is_modified,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)

            ON CONFLICT(filename)
            DO UPDATE SET

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
                delta_start_ms,
                delta_end_ms,
                status,
                int(is_modified),
            ),
        )

        self.connection.commit()

    def get(
        self,
        filename: str,
    ) -> dict | None:
        """
        Obtiene la anotación existente para un archivo.

        Devuelve None si el archivo todavía no ha sido anotado.
        """

        cursor = self.connection.execute(
            """
            SELECT
                filename,
                duration,
                sample_rate,
                auto_start,
                auto_end,
                manual_start,
                manual_end,
                delta_start_ms,
                delta_end_ms,
                status,
                is_modified,
                updated_at
            FROM annotations
            WHERE filename = ?
            """,
            (filename,),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_annotation(row)

    def get_all(self) -> list[dict]:
        """Devuelve todas las anotaciones ordenadas por filename."""

        cursor = self.connection.execute(
            """
            SELECT
                filename,
                duration,
                sample_rate,
                auto_start,
                auto_end,
                manual_start,
                manual_end,
                delta_start_ms,
                delta_end_ms,
                status,
                is_modified,
                updated_at
            FROM annotations
            ORDER BY filename
            """
        )

        return [
            self._row_to_annotation(row)
            for row in cursor.fetchall()
        ]

    @staticmethod
    def _row_to_annotation(row) -> dict:
        annotation = dict(
            zip(ANNOTATION_COLUMNS, row)
        )
        annotation["is_modified"] = bool(
            annotation["is_modified"]
        )
        return annotation

    def viewed_filenames(self) -> set[str]:
        """Devuelve los archivos marcados como revisados."""

        cursor = self.connection.execute(
            """
            SELECT filename
            FROM annotations
            WHERE status = ?
            """,
            (STATUS_VIEWED,),
        )

        return {
            str(row[0])
            for row in cursor.fetchall()
        }

    def exists(
        self,
        filename: str,
    ) -> bool:
        """
        Comprueba si un WAV ya posee una anotación.
        """

        cursor = self.connection.execute(
            """
            SELECT 1
            FROM annotations
            WHERE filename = ?
            LIMIT 1
            """,
            (filename,),
        )

        return (
            cursor.fetchone()
            is not None
        )

    def count(self) -> int:
        """
        Número total de archivos anotados.
        """

        cursor = self.connection.execute(
            """
            SELECT COUNT(*)
            FROM annotations
            """
        )

        return int(
            cursor.fetchone()[0]
        )

    def close(self):
        """
        Cierra explícitamente la conexión SQLite.
        """

        self.connection.close()
