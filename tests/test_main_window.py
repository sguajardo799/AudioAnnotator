import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from smartaudiocrop.audio.player import (
    AudioPlayer,
    PlaybackSnapshot,
    PlaybackState,
)
from smartaudiocrop.ui.main_window import MainWindow


class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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
        self.assertEqual(window.file_counter_label.text(), "File 0 of 0")
        self.assertEqual(window.status_label.text(), "Status: -")
        self.assertEqual(window.progress_bar.value(), 0)
        self.assertEqual(window.progress_bar.format(), "0/0 reviewed")

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

            original_save = window.save_annotation
            window.save_annotation = Mock(wraps=original_save)
            window.player.stop = Mock()

            with patch(
                "smartaudiocrop.ui.main_window."
                "QFileDialog.getExistingDirectory",
                return_value=str(second_project),
            ):
                window.new_project()

            self.assertEqual(window.save_annotation.call_count, 2)
            self.assertEqual(window.player.stop.call_count, 2)
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

    def test_navigation_updates_review_progress_and_modified_state(self):
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
            self.assertEqual(first["status"], "VIEWED")
            self.assertTrue(first["is_modified"])
            self.assertEqual(window.file_counter_label.text(), "File 2 of 2")
            self.assertEqual(window.status_label.text(), "Status: NOT_VIEWED")
            self.assertEqual(window.progress_bar.value(), 1)
            self.assertEqual(
                window.progress_bar.format(),
                "1/2 reviewed (%p%)",
            )

            window.prev_audio()

            self.assertEqual(window.status_label.text(), "Status: VIEWED")
            self.assertEqual(window.progress_bar.value(), 2)
            window.close()

    @staticmethod
    def _write_silent_wav(path: Path):
        with wave.open(str(path), "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(8_000)
            audio_file.writeframes(b"\x00\x00" * 2_048)


if __name__ == "__main__":
    unittest.main()
