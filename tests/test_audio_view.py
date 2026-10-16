import os
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from smartaudiocrop.ui.audio_view import AudioView


AUTO_COLOR = "#e69f00"
MANUAL_COLOR = "#0072b2"
PLAYBACK_COLOR = "#cc79a7"


class AudioViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = AudioView()

    def tearDown(self):
        self.view.close()

    def test_automatic_and_manual_markers_have_distinct_styles(self):
        auto_pen = self.view.auto_start_line.pen
        manual_pen = self.view.region.lines[0].pen

        self.assertEqual(auto_pen.color().name(), AUTO_COLOR)
        self.assertEqual(auto_pen.style(), Qt.PenStyle.DashLine)
        self.assertEqual(manual_pen.color().name(), MANUAL_COLOR)
        self.assertEqual(manual_pen.style(), Qt.PenStyle.SolidLine)
        self.assertGreater(
            self.view.region.lines[0].hoverPen.widthF(),
            manual_pen.widthF(),
        )
        self.assertGreater(
            self.view.region.hoverBrush.color().alpha(),
            self.view.region.brush.color().alpha(),
        )
        self.assertGreater(
            self.view.auto_start_line.zValue(),
            self.view.region.zValue(),
        )
        self.assertFalse(self.view.auto_start_line.movable)
        self.assertTrue(self.view.region.movable)

    def test_spectrogram_markers_use_manual_style(self):
        self.assertEqual(
            self.view.spec_start_line.pen.color().name(),
            MANUAL_COLOR,
        )

    def test_proposal_markers_are_mirrored_on_spectrogram(self):
        self.view.set_proposal_bounds(0.25, 0.75)

        self.assertEqual(self.view.spec_auto_start_line.value(), 0.25)
        self.assertEqual(self.view.spec_auto_end_line.value(), 0.75)
        self.assertEqual(
            self.view.spec_auto_start_line.pen.style(),
            Qt.PenStyle.DashLine,
        )
        self.assertEqual(
            self.view.spec_start_line.pen.style(),
            Qt.PenStyle.SolidLine,
        )

    def test_manual_bounds_do_not_change_automatic_markers(self):
        self.view.set_auto_bounds(0.25, 0.75)
        self.view.set_manual_bounds(0.1, 0.9)

        self.assertEqual(self.view.auto_start_line.value(), 0.25)
        self.assertEqual(self.view.auto_end_line.value(), 0.75)
        self.assertEqual(self.view.manual_bounds(), (0.1, 0.9))

    def test_sync_selection_markers_updates_spectrogram(self):
        self.view.set_manual_bounds(0.2, 0.8)
        self.view.sync_selection_markers()

        self.assertEqual(self.view.spec_start_line.value(), 0.2)
        self.assertEqual(self.view.spec_end_line.value(), 0.8)

    def test_legend_and_markers_follow_audio_visibility(self):
        self.view.clear()

        self.assertTrue(self.view.selection_legend.isHidden())
        self.assertFalse(self.view.region.isVisible())
        self.assertFalse(self.view.auto_start_line.isVisible())

        self.view.show_audio(
            np.zeros(2_048, dtype=np.float32),
            sample_rate=8_000,
            duration=0.256,
        )

        self.assertFalse(self.view.selection_legend.isHidden())
        self.assertTrue(self.view.region.isVisible())
        self.assertTrue(self.view.auto_start_line.isVisible())
        legend_text = {
            label.text()
            for label in self.view.selection_legend.findChildren(QLabel)
        }
        self.assertEqual(
            legend_text,
            {"Automatic proposal", "Manual selection"},
        )

    def test_playback_cursor_updates_both_plots(self):
        self.view.set_playback_position(0.42)
        self.view.set_playback_cursor_visible(True)

        self.assertEqual(self.view.playback_line.value(), 0.42)
        self.assertEqual(self.view.spec_playback_line.value(), 0.42)
        self.assertTrue(self.view.playback_line.isVisible())
        self.assertTrue(self.view.spec_playback_line.isVisible())
        self.assertEqual(
            self.view.playback_line.pen.color().name(),
            PLAYBACK_COLOR,
        )
        self.assertGreater(
            self.view.playback_line.zValue(),
            self.view.auto_start_line.zValue(),
        )

    def test_clear_hides_playback_cursor(self):
        self.view.set_playback_cursor_visible(True)

        self.view.clear()

        self.assertFalse(self.view.playback_line.isVisible())
        self.assertFalse(self.view.spec_playback_line.isVisible())


if __name__ == "__main__":
    unittest.main()
