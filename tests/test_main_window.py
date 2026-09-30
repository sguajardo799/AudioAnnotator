import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

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
        self.assertFalse(window.reset_button.isEnabled())
        self.assertFalse(window.run_trim_action.isEnabled())
        self.assertFalse(window.reset_trim_action.isEnabled())

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

    @staticmethod
    def _write_silent_wav(path: Path):
        with wave.open(str(path), "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(8_000)
            audio_file.writeframes(b"\x00\x00" * 2_048)


if __name__ == "__main__":
    unittest.main()
