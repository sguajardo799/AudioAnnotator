import sqlite3
from pathlib import Path


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
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)

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
                updated_at
            FROM annotations
            WHERE filename = ?
            """,
            (filename,),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        columns = [
            "filename",
            "duration",
            "sample_rate",
            "auto_start",
            "auto_end",
            "manual_start",
            "manual_end",
            "delta_start_ms",
            "delta_end_ms",
            "updated_at",
        ]

        return dict(
            zip(columns, row)
        )

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
