"""State and persistence resources for the active project."""

from pathlib import Path

from smartaudiocrop.annotations.store import (
    STATUS_NOT_VIEWED,
    STATUS_VIEWED,
    AnnotationStore,
)


class ProjectSession:
    def __init__(self):
        self.project_dir: Path | None = None
        self.files: list[Path] = []
        self.current_index = 0
        self.annotations: AnnotationStore | None = None

    @staticmethod
    def discover_audio_files(project_dir: Path) -> list[Path]:
        return sorted(
            path
            for path in project_dir.iterdir()
            if path.is_file() and path.suffix.lower() == ".wav"
        )

    @property
    def current_path(self) -> Path:
        return self.files[self.current_index]

    @property
    def has_previous(self) -> bool:
        return bool(self.files) and self.current_index > 0

    @property
    def has_next(self) -> bool:
        return (
            bool(self.files)
            and self.current_index < len(self.files) - 1
        )

    @property
    def total_count(self) -> int:
        return len(self.files)

    @property
    def viewed_count(self) -> int:
        if self.annotations is None:
            return 0

        project_filenames = {
            path.name
            for path in self.files
        }
        return len(
            project_filenames
            & self.annotations.viewed_filenames()
        )

    @property
    def current_status(self) -> str:
        annotation = self.get_current_annotation()

        if annotation is None:
            return STATUS_NOT_VIEWED

        return str(annotation["status"])

    @property
    def progress_percent(self) -> int:
        if not self.files:
            return 0

        return round(
            self.viewed_count
            / self.total_count
            * 100
        )

    def close_annotations(self):
        if self.annotations is not None:
            self.annotations.close()

    def replace(self, project_dir: Path, files: list[Path]):
        self.project_dir = project_dir
        self.files = files
        self.current_index = 0
        self.annotations = AnnotationStore(
            project_dir / "annotations.db"
        )

    def change_index(self, offset: int) -> bool:
        new_index = self.current_index + offset

        if not 0 <= new_index < len(self.files):
            return False

        self.current_index = new_index
        return True

    def save_annotation(self, **values):
        if self.annotations is None or not self.files:
            return

        self.annotations.save(
            filename=self.current_path.name,
            status=STATUS_VIEWED,
            **values,
        )

    def get_current_annotation(self) -> dict | None:
        if self.annotations is None or not self.files:
            return None

        return self.annotations.get(
            self.current_path.name
        )
