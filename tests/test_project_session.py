import tempfile
import unittest
from pathlib import Path

from smartaudiocrop.project.session import ProjectSession


class ProjectSessionTests(unittest.TestCase):
    def test_discovery_is_sorted_case_insensitive_and_non_recursive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "b.WAV").touch()
            (root / "a.wav").touch()
            (root / "ignored.txt").touch()
            nested = root / "nested"
            nested.mkdir()
            (nested / "nested.wav").touch()

            files = ProjectSession.discover_audio_files(root)

            self.assertEqual(
                files,
                [root / "a.wav", root / "b.WAV"],
            )

    def test_navigation_keeps_bounds(self):
        session = ProjectSession()
        session.files = [Path("a.wav"), Path("b.wav")]

        self.assertFalse(session.has_previous)
        self.assertTrue(session.has_next)
        self.assertFalse(session.change_index(-1))
        self.assertEqual(session.current_index, 0)

        self.assertTrue(session.change_index(1))
        self.assertEqual(session.current_path, Path("b.wav"))
        self.assertTrue(session.has_previous)
        self.assertFalse(session.has_next)
        self.assertFalse(session.change_index(1))
        self.assertEqual(session.current_index, 1)

    def test_review_progress_persists_and_ignores_stale_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = [root / "a.wav", root / "b.wav"]
            for path in files:
                path.touch()

            session = ProjectSession()
            session.replace(root, files)

            self.assertEqual(session.total_count, 2)
            self.assertEqual(session.viewed_count, 0)
            self.assertEqual(session.current_status, "NOT_VIEWED")
            self.assertEqual(session.progress_percent, 0)

            session.save_annotation(
                duration=2.0,
                sample_rate=48_000,
                auto_start=0.2,
                auto_end=1.8,
                manual_start=0.2,
                manual_end=1.8,
            )
            session.annotations.save(
                filename="removed.wav",
                duration=2.0,
                sample_rate=48_000,
                auto_start=0.2,
                auto_end=1.8,
                manual_start=0.2,
                manual_end=1.8,
                status="VIEWED",
            )

            self.assertEqual(session.current_status, "VIEWED")
            self.assertEqual(session.viewed_count, 1)
            self.assertEqual(session.progress_percent, 50)
            session.close_annotations()

            reopened = ProjectSession()
            reopened.replace(root, files)
            self.assertEqual(reopened.viewed_count, 1)
            self.assertEqual(reopened.current_status, "VIEWED")
            reopened.close_annotations()


if __name__ == "__main__":
    unittest.main()
