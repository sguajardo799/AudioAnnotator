import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "smartaudiocrop"


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])

    return imports


class ArchitectureTests(unittest.TestCase):
    def test_trim_core_has_no_ui_or_infrastructure_dependencies(self):
        forbidden = {
            "PySide6",
            "pyqtgraph",
            "sounddevice",
            "soundfile",
            "sqlite3",
        }

        for path in (ROOT / "trim").glob("*.py"):
            with self.subTest(path=path.name):
                self.assertTrue(imported_roots(path).isdisjoint(forbidden))

    def test_main_window_does_not_import_concrete_io_libraries(self):
        imports = imported_roots(ROOT / "ui" / "main_window.py")

        self.assertTrue(
            imports.isdisjoint(
                {
                    "pyqtgraph",
                    "scipy",
                    "sounddevice",
                    "soundfile",
                    "sqlite3",
                    "csv",
                }
            )
        )

    def test_annotation_exporter_has_no_ui_dependencies(self):
        imports = imported_roots(
            ROOT / "annotations" / "exporter.py"
        )

        self.assertTrue(
            imports.isdisjoint(
                {
                    "PySide6",
                    "pyqtgraph",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
