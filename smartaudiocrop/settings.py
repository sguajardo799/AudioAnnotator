"""User-level application preferences."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings


@dataclass(frozen=True)
class TrimPreferences:
    engine: str = "heuristic"
    manifest_path: str = ""
    auto_run_on_open: bool = False


class ApplicationSettings:
    def __init__(self, settings: QSettings | None = None):
        self.settings = settings or QSettings("SmartAudioCrop", "AudioAnnotator")

    def trim_preferences(self) -> TrimPreferences:
        engine = str(self.settings.value("trim/engine", "heuristic"))
        if engine not in {"heuristic", "onnx_crnn"}:
            engine = "heuristic"
        auto_run = self.settings.value(
            "trim/auto_run_on_open", False, type=bool
        )
        return TrimPreferences(
            engine=engine,
            manifest_path=str(self.settings.value("trim/onnx_manifest_path", "")),
            auto_run_on_open=bool(auto_run),
        )

    def save_trim_preferences(self, preferences: TrimPreferences) -> None:
        self.settings.setValue("trim/engine", preferences.engine)
        self.settings.setValue(
            "trim/onnx_manifest_path", preferences.manifest_path
        )
        self.settings.setValue(
            "trim/auto_run_on_open", preferences.auto_run_on_open
        )
