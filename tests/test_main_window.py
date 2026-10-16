import os
import tempfile
import unittest
import wave
import threading
from pathlib import Path
from unittest.mock import Mock, call, patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from smartaudiocrop.annotations.exporter import AnnotationExportError
from smartaudiocrop.audio.player import (
    AudioPlayer,
    PlaybackSnapshot,
    PlaybackState,
)
from smartaudiocrop.settings import ApplicationSettings
from smartaudiocrop.trim.providers import TrimProposal
from smartaudiocrop.ui.main_window import (
    COARSE_TRIM_STEP_SECONDS,
    FINE_TRIM_STEP_SECONDS,
    MainWindow,
)
from smartaudiocrop.ui.inference_worker import InferenceRequest
from smartaudiocrop.ui.trim_settings_dialog import TrimSettingsDialog


class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = ApplicationSettings(QSettings(
            str(Path(directory.name) / "preferences.ini"),
            QSettings.Format.IniFormat,
        ))
        settings_patch = patch(
            "smartaudiocrop.ui.main_window.ApplicationSettings",
            return_value=settings,
        )
        settings_patch.start()
        self.addCleanup(settings_patch.stop)

    def test_initial_state_has_no_project_and_controls_are_disabled(self):
        window = MainWindow()

        self.assertFalse(window.session.files)
        self.assertFalse(window.prev_button.isEnabled())
        self.assertFalse(window.next_button.isEnabled())
        self.assertFalse(window.play_button.isEnabled())
        self.assertFalse(window.stop_button.isEnabled())
        self.assertFalse(window.restart_button.isEnabled())
        self.assertFalse(window.loop_checkbox.isEnabled())
        self.assertFalse(window.reset_button.isEnabled())
        self.assertFalse(window.run_trim_action.isEnabled())
        self.assertFalse(window.reset_trim_action.isEnabled())
        self.assertFalse(window.export_annotations_action.isEnabled())
        self.assertEqual(window.file_counter_label.text(), "File 0 of 0")
        self.assertEqual(window.status_label.text(), "Status: -")
        self.assertEqual(window.progress_bar.value(), 0)
        self.assertEqual(window.progress_bar.format(), "0/0 reviewed")

        window.close()

    def test_export_action_is_enabled_for_an_open_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")

            window = self._open_project(root)

            self.assertEqual(
                window.export_annotations_action.text(),
                "Export Annotations...",
            )
            self.assertTrue(window.export_annotations_action.isEnabled())
            window.close()

    def test_export_with_no_saved_annotations_warns_before_opening_dialog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            window = self._open_project(root)

            with (
                patch(
                    "smartaudiocrop.ui.main_window.QMessageBox.warning"
                ) as warning,
                patch(
                    "smartaudiocrop.ui.main_window."
                    "QFileDialog.getSaveFileName"
                ) as save_dialog,
            ):
                window.export_annotations()

            warning.assert_called_once_with(
                window,
                "No Annotations",
                "There are no saved annotations to export.",
            )
            save_dialog.assert_not_called()
            window.close()

    def test_export_cancel_does_not_write_or_save_current_annotation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            window = self._open_project(root)
            window.save_annotation()
            window.save_annotation = Mock()

            with (
                patch(
                    "smartaudiocrop.ui.main_window."
                    "QFileDialog.getSaveFileName",
                    return_value=("", ""),
                ),
                patch(
                    "smartaudiocrop.ui.main_window."
                    "AnnotationExporter.export_csv"
                ) as export_csv,
            ):
                window.export_annotations()

            export_csv.assert_not_called()
            window.save_annotation.assert_not_called()
            window.close()

    def test_export_delegates_persisted_rows_and_selected_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "dataset.csv"
            self._write_silent_wav(root / "a.wav")
            window = self._open_project(root)
            window.save_annotation()
            persisted = window.session.annotations.get_all_for_export()
            window.save_annotation = Mock()

            with (
                patch(
                    "smartaudiocrop.ui.main_window."
                    "QFileDialog.getSaveFileName",
                    return_value=(str(destination), "CSV Files (*.csv)"),
                ),
                patch(
                    "smartaudiocrop.ui.main_window."
                    "AnnotationExporter.export_csv"
                ) as export_csv,
            ):
                window.export_annotations()

            export_csv.assert_called_once_with(
                persisted,
                str(destination),
            )
            window.save_annotation.assert_not_called()
            window.close()

    def test_export_write_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "dataset.csv"
            self._write_silent_wav(root / "a.wav")
            window = self._open_project(root)
            window.save_annotation()

            error = AnnotationExportError("Could not write export")
            with (
                patch(
                    "smartaudiocrop.ui.main_window."
                    "QFileDialog.getSaveFileName",
                    return_value=(str(destination), "CSV Files (*.csv)"),
                ),
                patch(
                    "smartaudiocrop.ui.main_window."
                    "AnnotationExporter.export_csv",
                    side_effect=error,
                ),
                patch(
                    "smartaudiocrop.ui.main_window.QMessageBox.warning"
                ) as warning,
            ):
                window.export_annotations()

            warning.assert_called_once_with(
                window,
                "Export Failed",
                "Could not write export",
            )
            window.close()

    def test_export_cannot_overwrite_project_database_or_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav_path = root / "a.wav"
            self._write_silent_wav(wav_path)
            window = self._open_project(root)
            window.save_annotation()
            database = root / "annotations.db"

            with (
                patch(
                    "smartaudiocrop.ui.main_window."
                    "QFileDialog.getSaveFileName",
                    side_effect=[
                        (str(database), "CSV Files (*.csv)"),
                        (str(wav_path), "CSV Files (*.csv)"),
                    ],
                ),
                patch(
                    "smartaudiocrop.ui.main_window."
                    "AnnotationExporter.export_csv"
                ) as export_csv,
                patch(
                    "smartaudiocrop.ui.main_window.QMessageBox.warning"
                ) as warning,
            ):
                window.export_annotations()
                window.export_annotations()

            export_csv.assert_not_called()
            warning.assert_has_calls(
                [
                    call(
                        window,
                        "Invalid Export Destination",
                        (
                            "Annotations cannot be exported over the project "
                            "database or a WAV file."
                        ),
                    ),
                    call(
                        window,
                        "Invalid Export Destination",
                        (
                            "Annotations cannot be exported over the project "
                            "database or a WAV file."
                        ),
                    ),
                ]
            )
            window.close()

    def test_project_switch_preserves_existing_save_and_stop_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_project = root / "first"
            second_project = root / "second"
            first_project.mkdir()
            second_project.mkdir()
            self._write_silent_wav(first_project / "a.wav")
            self._write_silent_wav(second_project / "b.wav")

            window = MainWindow()

            with patch(
                "smartaudiocrop.ui.main_window."
                "QFileDialog.getExistingDirectory",
                return_value=str(first_project),
            ):
                window.new_project()

            original_autosave = window.autosave_annotation
            window.autosave_annotation = Mock(wraps=original_autosave)
            window.player.stop = Mock()

            with patch(
                "smartaudiocrop.ui.main_window."
                "QFileDialog.getExistingDirectory",
                return_value=str(second_project),
            ):
                window.new_project()

            self.assertEqual(window.autosave_annotation.call_count, 1)
            self.assertEqual(window.player.stop.call_count, 1)
            self.assertEqual(window.session.current_path.name, "b.wav")
            self.assertEqual(window.session.project_dir, second_project)

            window.close()

    def test_play_uses_current_manual_bounds_and_loop_setting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            window = self._open_project(root)
            window.audio_view.set_manual_bounds(0.01, 0.02)
            window.loop_checkbox.setChecked(True)
            window.player.play = Mock()

            window.play_selection()

            window.player.play.assert_called_once_with(80, 160, loop=True)
            window.close()

    def test_toggle_pauses_and_updates_contextual_button(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            window = self._open_project(root)
            playing = self._snapshot(PlaybackState.PLAYING, 80)
            paused = self._snapshot(PlaybackState.PAUSED, 80)
            window.player.snapshot = Mock(
                side_effect=[playing, paused, paused]
            )
            window.player.pause = Mock()

            window.toggle_playback()

            window.player.pause.assert_called_once_with()
            self.assertEqual(window.play_button.text(), "Resume")
            self.assertEqual(window.audio_view.playback_line.value(), 0.01)
            window.close()

    def test_restart_reads_new_bounds_instead_of_paused_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            window = self._open_project(root)
            window.audio_view.set_manual_bounds(0.03, 0.05)
            window.player.restart = Mock()

            window.restart_playback()

            window.player.restart.assert_called_once_with(
                240,
                400,
                loop=False,
            )
            window.close()

    def test_navigation_from_pause_resets_playback_ui(self):
        class FakeStream:
            def __init__(self, **_kwargs):
                self.active = False

            def start(self):
                self.active = True

            def stop(self):
                self.active = False

            def abort(self):
                self.active = False

            def close(self):
                self.active = False

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            self._write_silent_wav(root / "b.wav")
            player = AudioPlayer(stream_factory=FakeStream)
            window = self._open_project(root, player=player)
            player.play(10, 100)
            player.pause()
            window.update_playback_ui()
            self.assertEqual(window.play_button.text(), "Resume")

            window.next_audio()

            self.assertEqual(player.snapshot().state, PlaybackState.STOPPED)
            self.assertEqual(window.play_button.text(), "Play")
            self.assertFalse(window.playback_timer.isActive())
            self.assertFalse(window.audio_view.playback_line.isVisible())
            window.close()

    def test_sub_frame_selection_does_not_start_playback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            window = self._open_project(root)
            window.audio_view.set_manual_bounds(0.01, 0.01001)
            window.player.play = Mock()
            window.player.restart = Mock()

            window.play_selection()
            window.restart_playback()

            window.player.play.assert_not_called()
            window.player.restart.assert_not_called()
            window.close()

    @staticmethod
    def _snapshot(state: PlaybackState, position: int):
        return PlaybackSnapshot(
            state=state,
            position_frames=position,
            position_seconds=position / 8_000,
            selection_start_frames=40,
            selection_end_frames=160,
            loop=False,
        )

    @staticmethod
    def _open_project(root: Path, player=None):
        window = MainWindow(player=player)
        with patch(
            "smartaudiocrop.ui.main_window.QFileDialog.getExistingDirectory",
            return_value=str(root),
        ):
            window.new_project()
        return window

    def test_navigation_saves_draft_without_marking_reviewed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            self._write_silent_wav(root / "b.wav")

            window = MainWindow()

            with patch(
                "smartaudiocrop.ui.main_window."
                "QFileDialog.getExistingDirectory",
                return_value=str(root),
            ):
                window.new_project()

            self.assertEqual(window.file_counter_label.text(), "File 1 of 2")
            self.assertEqual(window.status_label.text(), "Status: NOT_VIEWED")
            self.assertEqual(window.progress_bar.value(), 0)

            window.audio_view.set_manual_bounds(
                0.01,
                window.duration,
            )
            window.next_audio()

            first = window.session.annotations.get("a.wav")
            self.assertEqual(first["status"], "NOT_VIEWED")
            self.assertTrue(first["is_modified"])
            self.assertEqual(window.file_counter_label.text(), "File 2 of 2")
            self.assertEqual(window.status_label.text(), "Status: NOT_VIEWED")
            self.assertEqual(window.progress_bar.value(), 0)
            self.assertEqual(
                window.progress_bar.format(),
                "0/2 reviewed (%p%)",
            )

            window.prev_audio()

            self.assertEqual(window.status_label.text(), "Status: NOT_VIEWED")
            self.assertEqual(window.progress_bar.value(), 0)
            window.close()

    def test_confirm_saves_once_and_advances(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            self._write_silent_wav(root / "b.wav")
            window = self._open_project(root)
            original_save = window.save_annotation
            window.save_annotation = Mock(wraps=original_save)

            window.confirm_annotation()

            window.save_annotation.assert_called_once_with()
            self.assertEqual(window.session.current_index, 1)
            self.assertEqual(window.session.viewed_count, 1)
            window.close()

    def test_confirm_on_last_file_saves_once_without_navigating(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            window = self._open_project(root)
            original_save = window.save_annotation
            window.save_annotation = Mock(wraps=original_save)
            window.player.stop = Mock()

            window.confirm_annotation()

            window.save_annotation.assert_called_once_with()
            window.player.stop.assert_not_called()
            self.assertEqual(window.session.current_index, 0)
            self.assertEqual(window.session.viewed_count, 1)
            window.close()

    def test_close_without_manual_edit_does_not_create_reviewed_annotation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            window = self._open_project(root)

            window.close()

            from smartaudiocrop.annotations.store import AnnotationStore

            store = AnnotationStore(root / "annotations.db")
            self.assertEqual(store.viewed_filenames(), set())
            store.close()

    def test_onnx_inference_runs_in_worker_and_only_persists_prediction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav_path = root / "tone.wav"
            sample_rate = 16_000
            time = np.arange(sample_rate * 2) / sample_rate
            samples = np.concatenate(
                [
                    np.zeros(sample_rate // 2),
                    0.3 * np.sin(2 * np.pi * 220 * time[:sample_rate]),
                    np.zeros(sample_rate // 2),
                ]
            )
            with wave.open(str(wav_path), "wb") as audio_file:
                audio_file.setnchannels(1)
                audio_file.setsampwidth(2)
                audio_file.setframerate(sample_rate)
                audio_file.writeframes(
                    (samples * 32767).astype("<i2").tobytes()
                )

            qt_settings = QSettings(
                str(root / "settings.ini"),
                QSettings.Format.IniFormat,
            )
            window = MainWindow(settings=ApplicationSettings(qt_settings))
            manifest = (
                Path(__file__).resolve().parents[1]
                / "model_packages"
                / "crnn_baseline-1.0.0"
                / "model_manifest.json"
            )
            window.load_onnx_model(manifest)
            self._wait_until(lambda: not window._worker_busy)
            with patch(
                "smartaudiocrop.ui.main_window.QFileDialog.getExistingDirectory",
                return_value=str(root),
            ):
                window.new_project()

            window.run_auto_trim()
            self._wait_until(lambda: not window._worker_busy)

            self.assertEqual(window.proposal_source, "onnx_crnn")
            self.assertEqual(window.session.annotations.prediction_count(), 1)
            self.assertIsNone(window.session.get_current_annotation())
            window.run_auto_trim()
            self.assertFalse(window._worker_busy)
            self.assertEqual(window.session.annotations.prediction_count(), 1)
            window.run_auto_trim(force=True)
            self._wait_until(lambda: not window._worker_busy)
            self.assertEqual(window.session.annotations.prediction_count(), 2)
            self.assertAlmostEqual(window.auto_start, 0.47, places=2)
            self.assertAlmostEqual(window.auto_end, 1.525, places=2)
            window.audio_view.set_manual_bounds(0.48, 1.50)
            window.on_region_changed()
            window.save_annotation()
            saved = window.session.get_current_annotation()
            self.assertEqual(saved["status"], "VIEWED")
            self.assertEqual(saved["proposal_source"], "onnx_crnn")
            window.close()

            reopened_settings = QSettings(
                str(root / "settings.ini"),
                QSettings.Format.IniFormat,
            )
            reopened = MainWindow(
                settings=ApplicationSettings(reopened_settings)
            )
            self._wait_until(lambda: not reopened._worker_busy)
            with patch(
                "smartaudiocrop.ui.main_window.QFileDialog.getExistingDirectory",
                return_value=str(root),
            ):
                reopened.new_project()
            self.assertEqual(reopened.audio_view.manual_bounds(), (0.48, 1.5))
            self.assertEqual(reopened.proposal_source, "onnx_crnn")
            self.assertEqual(reopened.session.viewed_count, 1)
            reopened.close()

    def test_failed_heuristic_rerun_preserves_existing_manual_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            window = self._open_project(root)
            window.audio_view.set_manual_bounds(0.02, 0.2)
            window.save_annotation()

            with patch(
                "smartaudiocrop.ui.main_window.QMessageBox.warning"
            ) as warning:
                window.run_auto_trim(force=True)

            self.assertEqual(window.audio_view.manual_bounds(), (0.02, 0.2))
            warning.assert_called_once()
            window.close()

    def test_stale_inference_result_does_not_touch_new_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            self._write_silent_wav(root / "b.wav")
            window = self._open_project(root)
            request = InferenceRequest(
                request_id=window._request_id,
                project_generation=window.session.project_generation,
                project_id=str(root.resolve()),
                audio_generation=window._audio_generation,
                audio_id="a.wav",
                model_revision=window._loaded_model_revision,
                audio_path=root / "a.wav",
                audio_sha256=window.audio_sha256,
                audio=window.audio.copy(),
                sample_rate=window.sr,
            )
            proposal = TrimProposal(
                start=0.01,
                end=0.2,
                source="onnx_crnn",
                audio_sha256=window.audio_sha256,
                config={"threshold": 0.5},
            )

            window.next_audio()
            window.on_inference_succeeded(request, proposal)

            self.assertEqual(window.session.current_path.name, "b.wav")
            self.assertEqual(window.session.annotations.prediction_count(), 0)
            window.close()

    def test_close_while_worker_is_busy_is_deferred_without_blocking(self):
        window = MainWindow()
        window._worker_busy = True

        window.close()

        self.assertTrue(window._deferred_close)
        self._wait_until(lambda: window._shutdown_complete)
        self.assertFalse(window.inference_thread.isRunning())

    def test_real_worker_keeps_navigation_responsive_and_closes_safely(self):
        started = threading.Event()
        release = threading.Event()
        worker_threads = []

        class FakeProvider:
            def __init__(self, path):
                from smartaudiocrop.trim.model_package import ModelManifest
                self.manifest = ModelManifest.load(path)

            def infer(self, audio, sample_rate, path, audio_hash):
                worker_threads.append(threading.get_ident())
                started.set()
                release.wait(5)
                return TrimProposal(
                    start=0.01, end=0.2, source="onnx_crnn",
                    audio_sha256=audio_hash, config=self.manifest.config,
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            self._write_silent_wav(root / "b.wav")
            manifest = Path(__file__).resolve().parents[1] / (
                "model_packages/crnn_baseline-1.0.0/model_manifest.json"
            )
            with patch(
                "smartaudiocrop.ui.inference_worker.OnnxTrimProvider", FakeProvider
            ):
                window = self._open_project(root)
                try:
                    window.load_onnx_model(manifest)
                    self._wait_until(lambda: not window._worker_busy)
                    window.run_auto_trim()
                    self._wait_until(started.is_set)
                    window.update_playback_ui()
                    self.assertFalse(window.run_trim_action.isEnabled())
                    self.assertTrue(window.play_button.isEnabled())
                    window.next_audio()
                    self.assertEqual(window.session.current_path.name, "b.wav")
                    window.close()
                    self.assertTrue(window._deferred_close)
                    self.assertNotEqual(worker_threads[0], threading.get_ident())
                finally:
                    release.set()
                    self._wait_until(lambda: not window.inference_thread.isRunning())
                    self.app.processEvents()
                    window.close()

    def test_failed_autosave_keeps_dirty_edits_and_current_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            self._write_silent_wav(root / "b.wav")
            window = self._open_project(root)
            window.audio_view.set_manual_bounds(0.02, 0.2)
            window.on_region_changed()
            with patch.object(
                window.session, "autosave_current_annotation",
                side_effect=RuntimeError("database failure"),
            ), patch("smartaudiocrop.ui.main_window.QMessageBox.warning"):
                window.next_audio()
            self.assertEqual(window.session.current_path.name, "a.wav")
            self.assertTrue(window.manual_dirty)
            self.assertEqual(window.session.viewed_count, 0)
            window.close()

    def test_shortcuts_use_window_context_and_safe_auto_repeat(self):
        window = MainWindow()

        self.assertEqual(
            set(window.shortcuts),
            {
                "Left",
                "Right",
                "Space",
                "R",
                "Return",
                "Enter",
                ",",
                ".",
                "Shift+,",
                "Shift+.",
                "Ctrl+,",
                "Ctrl+.",
                "Ctrl+Shift+,",
                "Ctrl+Shift+.",
            },
        )
        for shortcut in window.shortcuts.values():
            self.assertEqual(
                shortcut.context(),
                Qt.ShortcutContext.WindowShortcut,
            )

        self.assertFalse(window.shortcuts["Return"].autoRepeat())
        self.assertFalse(window.shortcuts["Enter"].autoRepeat())
        self.assertTrue(window.shortcuts[","].autoRepeat())
        self.assertTrue(window.shortcuts["Ctrl+Shift+."].autoRepeat())
        window.close()

    def test_modal_dialog_does_not_trigger_annotation_shortcuts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            window = self._open_project(root)
            window.show()
            self.app.processEvents()
            window.audio_view.set_manual_bounds(0.1, 0.2)
            window.save_annotation = Mock()
            window.player.play = Mock()
            dialog = TrimSettingsDialog(window.trim_config, parent=window)
            dialog.open()
            self.app.processEvents()

            QTest.keyClick(dialog, Qt.Key.Key_Space)
            QTest.keyClick(dialog, Qt.Key.Key_Period)
            QTest.keyClick(dialog, Qt.Key.Key_Return)
            self.app.processEvents()

            window.player.play.assert_not_called()
            window.save_annotation.assert_not_called()
            self.assertEqual(window.audio_view.manual_bounds(), (0.1, 0.2))
            dialog.reject()
            window.close()

    def test_shortcut_adjustments_move_the_expected_edge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            window = self._open_project(root)

            cases = (
                (",", 0.1 - FINE_TRIM_STEP_SECONDS, 0.2),
                (".", 0.1 + FINE_TRIM_STEP_SECONDS, 0.2),
                ("Shift+,", 0.1 - COARSE_TRIM_STEP_SECONDS, 0.2),
                ("Shift+.", 0.1 + COARSE_TRIM_STEP_SECONDS, 0.2),
                ("Ctrl+,", 0.1, 0.2 - FINE_TRIM_STEP_SECONDS),
                ("Ctrl+.", 0.1, 0.2 + FINE_TRIM_STEP_SECONDS),
                ("Ctrl+Shift+,", 0.1, 0.2 - COARSE_TRIM_STEP_SECONDS),
                ("Ctrl+Shift+.", 0.1, 0.2 + COARSE_TRIM_STEP_SECONDS),
            )

            for sequence, expected_start, expected_end in cases:
                with self.subTest(sequence=sequence):
                    window.audio_view.set_manual_bounds(0.1, 0.2)
                    window.shortcuts[sequence].activated.emit()
                    start, end = window.audio_view.manual_bounds()
                    self.assertAlmostEqual(start, expected_start)
                    self.assertAlmostEqual(end, expected_end)

            window.close()

    def test_adjustments_clamp_to_audio_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            window = self._open_project(root)

            window.audio_view.set_manual_bounds(0.001, 0.25)
            window.adjust_manual_bound("start", -FINE_TRIM_STEP_SECONDS)
            window.adjust_manual_bound("end", COARSE_TRIM_STEP_SECONDS)

            start, end = window.audio_view.manual_bounds()
            self.assertEqual(start, 0.0)
            self.assertEqual(end, window.duration)
            window.close()

    def test_adjustments_reject_equal_or_crossed_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            window = self._open_project(root)

            window.audio_view.set_manual_bounds(0.1, 0.105)
            window.adjust_manual_bound("start", FINE_TRIM_STEP_SECONDS)
            self.assertEqual(window.audio_view.manual_bounds(), (0.1, 0.105))

            window.adjust_manual_bound("end", -COARSE_TRIM_STEP_SECONDS)
            self.assertEqual(window.audio_view.manual_bounds(), (0.1, 0.105))
            window.close()

    def test_adjustment_immediately_syncs_spectrogram_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_silent_wav(root / "a.wav")
            window = self._open_project(root)
            window.audio_view.set_manual_bounds(0.1, 0.2)

            window.adjust_manual_bound("start", FINE_TRIM_STEP_SECONDS)

            start, end = window.audio_view.manual_bounds()
            self.assertEqual(window.audio_view.spec_start_line.value(), start)
            self.assertEqual(window.audio_view.spec_end_line.value(), end)
            window.close()

    @staticmethod
    def _write_silent_wav(path: Path):
        with wave.open(str(path), "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(8_000)
            audio_file.writeframes(b"\x00\x00" * 2_048)

    @classmethod
    def _wait_until(cls, predicate, timeout_ms=5_000):
        elapsed = 0
        while not predicate() and elapsed < timeout_ms:
            QTest.qWait(20)
            elapsed += 20
        cls.app.processEvents()
        if not predicate():
            raise AssertionError("Timed out waiting for Qt worker")


if __name__ == "__main__":
    unittest.main()
