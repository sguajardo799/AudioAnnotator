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


if __name__ == "__main__":
    unittest.main()
