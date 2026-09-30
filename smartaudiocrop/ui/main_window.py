from pathlib import Path

import numpy as np

from PySide6.QtGui import (
    QAction,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from smartaudiocrop.audio.loading import load_audio
from smartaudiocrop.audio.player import AudioPlayer
from smartaudiocrop.project.session import ProjectSession
from smartaudiocrop.trim.config import TrimConfig
from smartaudiocrop.trim.detector import estimate_trim
from smartaudiocrop.ui.audio_view import AudioView
from smartaudiocrop.ui.trim_settings_dialog import TrimSettingsDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Audio Annotator")
        self.resize(1200, 700)

        # =====================================================
        # Servicios
        # =====================================================

        self.player = AudioPlayer()
        self.session = ProjectSession()

        # Configuración actual del detector.
        self.trim_config = TrimConfig()

        # =====================================================
        # Estado del audio actual
        # =====================================================

        self.audio = np.array(
            [],
            dtype=np.float32,
        )

        self.sr = 0
        self.duration = 0.0

        # Propuesta automática del detector.
        self.auto_start: float | None = None
        self.auto_end: float | None = None

        # =====================================================
        # Construcción de interfaz
        # =====================================================

        self.setup_ui()
        self.setup_menus()
        self.setup_shortcuts()

        # La aplicación parte sin proyecto.
        self.clear_project_view()

        self.update_controls()

    # =========================================================
    # UI
    # =========================================================

    def setup_ui(self):
        container = QWidget()

        layout = QVBoxLayout(container)
        controls = QHBoxLayout()

        self.audio_view = AudioView()
        self.audio_view.connect_region_changed(
            self.on_region_changed
        )

        # -----------------------------------------------------
        # Botones
        # -----------------------------------------------------

        self.prev_button = QPushButton(
            "Prev"
        )

        self.play_button = QPushButton(
            "Play"
        )

        self.reset_button = QPushButton(
            "Reset"
        )

        self.next_button = QPushButton(
            "Next"
        )

        controls.addWidget(
            self.prev_button
        )

        controls.addWidget(
            self.play_button
        )

        controls.addWidget(
            self.reset_button
        )

        controls.addWidget(
            self.next_button
        )

        # -----------------------------------------------------
        # Señales
        # -----------------------------------------------------

        self.prev_button.clicked.connect(
            self.prev_audio
        )

        self.play_button.clicked.connect(
            self.play_selection
        )

        self.reset_button.clicked.connect(
            self.reset_manual_trim
        )

        self.next_button.clicked.connect(
            self.next_audio
        )

        # -----------------------------------------------------
        # Layout
        # -----------------------------------------------------

        layout.addWidget(self.audio_view)

        layout.addLayout(
            controls
        )

        self.setCentralWidget(
            container
        )

    # =========================================================
    # Menús
    # =========================================================

    def setup_menus(self):
        menu_bar = self.menuBar()

        # =====================================================
        # FILE
        # =====================================================

        file_menu = menu_bar.addMenu("File")

        self.new_project_action = QAction(
            "New Project...",
            self,
        )

        self.new_project_action.setShortcut(
            QKeySequence.StandardKey.Open
        )

        self.new_project_action.triggered.connect(
            self.new_project
        )

        file_menu.addAction(
            self.new_project_action
        )

        file_menu.addSeparator()

        exit_action = QAction(
            "Exit",
            self,
        )

        exit_action.triggered.connect(
            self.close
        )

        file_menu.addAction(
            exit_action
        )

        # =====================================================
        # TRIM
        # =====================================================

        trim_menu = menu_bar.addMenu("Trim")

        self.run_trim_action = QAction(
            "Run detector",
            self,
        )

        self.run_trim_action.triggered.connect(
            self.run_auto_trim
        )

        trim_menu.addAction(
            self.run_trim_action
        )

        self.reset_trim_action = QAction(
            "Reset manual selection",
            self,
        )

        self.reset_trim_action.triggered.connect(
            self.reset_manual_trim
        )

        trim_menu.addAction(
            self.reset_trim_action
        )

        trim_menu.addSeparator()

        self.trim_settings_action = QAction(
            "Settings...",
            self,
        )

        self.trim_settings_action.triggered.connect(
            self.open_trim_settings
        )

        trim_menu.addAction(
            self.trim_settings_action
        )

    # =========================================================
    # Shortcuts
    # =========================================================

    def setup_shortcuts(self):
        QShortcut(
            QKeySequence("Left"),
            self,
            activated=self.prev_audio,
        )

        QShortcut(
            QKeySequence("Right"),
            self,
            activated=self.next_audio,
        )

        QShortcut(
            QKeySequence("Space"),
            self,
            activated=self.play_selection,
        )

        QShortcut(
            QKeySequence("R"),
            self,
            activated=self.reset_manual_trim,
        )

    # =========================================================
    # NEW PROJECT
    # =========================================================

    def new_project(self):
        """
        Abre una carpeta y la utiliza como proyecto.

        Actualmente un proyecto consiste simplemente en:
            - una carpeta
            - sus archivos WAV
            - annotations.csv

        No se realiza búsqueda recursiva.
        """

        # -----------------------------------------------------
        # Seleccionar directorio
        # -----------------------------------------------------

        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Audio Project Folder",
        )

        # Cancelar no modifica el proyecto actual.
        if not directory:
            return

        project_dir = Path(
            directory
        )

        # -----------------------------------------------------
        # Buscar WAV
        # -----------------------------------------------------

        files = ProjectSession.discover_audio_files(
            project_dir
        )

        # No cambiamos de proyecto si la carpeta es inválida.
        if not files:
            QMessageBox.warning(
                self,
                "No WAV Files",
                (
                    "The selected folder does not "
                    "contain WAV files."
                ),
            )

            return

        # -----------------------------------------------------
        # Guardar archivo actual antes de abandonar
        # el proyecto previo.
        # -----------------------------------------------------

        if self.session.files:
            self.save_annotation()

        # Detener cualquier reproducción activa.
        self.player.stop()

        # -----------------------------------------------------
        # Inicializar proyecto
        # -----------------------------------------------------

        self.session.project_dir = (
            project_dir
        )

        # Guardar proyecto anterior.
        if self.session.files:
            self.save_annotation()

        # Cerrar DB anterior.
        self.session.close_annotations()

        self.player.stop()

        # Nuevo proyecto.
        self.session.replace(project_dir, files)

        # Limpiar información del audio anterior antes
        # de cargar el nuevo proyecto.
        self.audio = np.array(
            [],
            dtype=np.float32,
        )

        self.sr = 0
        self.duration = 0.0

        self.auto_start = None
        self.auto_end = None

        # -----------------------------------------------------
        # Cargar primer audio
        # -----------------------------------------------------

        self.load_current_audio()

        self.update_controls()

    # =========================================================
    # Estado visual sin proyecto
    # =========================================================

    def clear_project_view(self):
        """
        Deja la aplicación en un estado vacío y seguro.

        Se utiliza al iniciar antes de cargar un proyecto.
        """

        self.audio_view.clear()

        self.setWindowTitle(
            "Audio Annotator"
        )

    # =========================================================
    # Estado de controles
    # =========================================================

    def update_controls(self):
        """
        Habilita o deshabilita controles según el estado
        actual del proyecto y el índice del archivo.
        """

        has_audio = bool(self.session.files)
        has_previous = self.session.has_previous
        has_next = self.session.has_next

        self.prev_button.setEnabled(
            has_previous
        )

        self.next_button.setEnabled(
            has_next
        )

        self.play_button.setEnabled(
            has_audio
        )

        self.reset_button.setEnabled(
            has_audio
        )

        self.run_trim_action.setEnabled(
            has_audio
        )

        self.reset_trim_action.setEnabled(
            has_audio
        )

    # =========================================================
    # Carga
    # =========================================================

    def load_current_audio(self):
        if not self.session.files:
            return

        path = self.session.current_path

        self.audio, self.sr = load_audio(path)

        self.duration = (
            len(self.audio)
            / self.sr
        )

        self.audio_view.show_audio(
            self.audio,
            self.sr,
            self.duration,
        )

        # Primero calculamos el trim automático actual.
        self.run_auto_trim()

        # Si el archivo ya fue editado anteriormente,
        # restauramos su anotación manual.
        self.restore_annotation()

        self.setWindowTitle(
            (
                f"Audio Annotator - "
                f"{path.name} "
                f"({self.session.current_index + 1}"
                f"/{len(self.session.files)})"
            )
        )

        self.update_controls()

    # =========================================================
    # Detector automático
    # =========================================================

    def run_auto_trim(self):
        if not self.session.files:
            return

        result = estimate_trim(
            self.audio,
            self.sr,
            self.trim_config,
        )

        if result is None:
            self.auto_start = 0.0
            self.auto_end = (
                self.duration
            )

        else:
            self.auto_start = (
                result.start
            )

            self.auto_end = (
                result.end
            )

        # Inicializar la selección manual a partir
        # de la propuesta.
        self.audio_view.set_auto_bounds(
            self.auto_start,
            self.auto_end,
        )

        self.on_region_changed()

    # =========================================================
    # Reset manual
    # =========================================================

    def reset_manual_trim(self):
        if not self.session.files:
            return

        if (
            self.auto_start is None
            or self.auto_end is None
        ):
            return

        self.audio_view.set_manual_bounds(
            self.auto_start,
            self.auto_end,
        )

    # =========================================================
    # Región
    # =========================================================

    def on_region_changed(self):
        if not self.session.files:
            return

        self.audio_view.sync_selection_markers()

    # =========================================================
    # Playback
    # =========================================================

    def play_selection(self):
        if not self.session.files:
            return

        start, end = self.audio_view.manual_bounds()

        start_sample = int(
            start * self.sr
        )

        end_sample = int(
            end * self.sr
        )

        segment = self.audio[
            start_sample:end_sample
        ]

        self.player.play(
            segment,
            self.sr,
        )

    # =========================================================
    # Guardar anotación
    # =========================================================

    def save_annotation(self):
        """
        Guarda la anotación del archivo actual.

        No hace nada si no existe un proyecto activo.
        """

        if not self.session.files:
            return

        if (
            self.auto_start is None
            or self.auto_end is None
        ):
            return

        manual_start, manual_end = self.audio_view.manual_bounds()

        self.session.save_annotation(
            duration=self.duration,
            sample_rate=self.sr,
            auto_start=self.auto_start,
            auto_end=self.auto_end,
            manual_start=manual_start,
            manual_end=manual_end,
        )

    def restore_annotation(self):
        """
        Si el archivo actual posee una anotación guardada,
        restaura la selección manual.

        La propuesta automática actual permanece intacta.
        """

        annotation = self.session.get_current_annotation()

        if annotation is None:
            return

        manual_start = annotation[
            "manual_start"
        ]

        manual_end = annotation[
            "manual_end"
        ]

        self.audio_view.set_manual_bounds(
            manual_start,
            manual_end,
        )

        self.on_region_changed()

    def closeEvent(self, event):
        """
        Guarda la anotación actual y cierra recursos
        antes de terminar la aplicación.
        """

        if self.session.files:
            self.save_annotation()

        self.player.stop()

        self.session.close_annotations()

        event.accept()

    # =========================================================
    # Navegación
    # =========================================================

    def change_audio(
        self,
        offset: int,
    ):
        if not self.session.files:
            return

        new_index = (
            self.session.current_index
            + offset
        )

        if not (
            0
            <= new_index
            < len(self.session.files)
        ):
            return

        # Guardar antes de abandonar el WAV.
        self.save_annotation()

        # Detener reproducción previa.
        self.player.stop()

        self.session.change_index(offset)

        self.load_current_audio()

    def next_audio(self):
        self.change_audio(+1)

    def prev_audio(self):
        self.change_audio(-1)

    def open_trim_settings(self):
        """
        Abre el diálogo de configuración del detector.

        Si el usuario acepta:
            1. Se construye un nuevo TrimConfig.
            2. Se valida.
            3. Se reemplaza la configuración actual.
            4. Si hay un audio cargado, se vuelve a ejecutar
            el detector sobre ese archivo.
        """

        dialog = TrimSettingsDialog(
            self.trim_config,
            parent=self,
        )

        result = dialog.exec()

        # Cancelar no modifica nada.
        if result != QDialog.DialogCode.Accepted:
            return

        try:
            new_config = dialog.get_config()

        except ValueError as exc:
            QMessageBox.warning(
                self,
                "Invalid Trim Configuration",
                str(exc),
            )

            return

        # Reemplazamos el objeto completo.
        self.trim_config = new_config

        # Si hay proyecto activo, volver a calcular
        # solamente el archivo actualmente abierto.
        if self.session.files:
            self.run_auto_trim()
