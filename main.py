import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import pyqtgraph as pg

from PySide6.QtCore import QRectF
from PySide6.QtGui import (
    QAction,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from audio_processing import spectrogram
from audio_player import AudioPlayer
from annotation_store import AnnotationStore

from trim.config import TrimConfig
from trim.detector import estimate_trim
from trim.settings_dialog import TrimSettingsDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Audio Annotator")
        self.resize(1200, 700)

        # =====================================================
        # Servicios
        # =====================================================

        self.player = AudioPlayer()

        # Configuración actual del detector.
        self.trim_config = TrimConfig()

        # AnnotationStore se crea al abrir un proyecto,
        # porque el CSV pertenecerá a la carpeta seleccionada.
        self.annotations: AnnotationStore | None = None

        # =====================================================
        # Estado del proyecto
        # =====================================================

        # Al iniciar no existe ningún proyecto abierto.
        self.project_dir: Path | None = None

        # Lista de WAV del proyecto actual.
        self.files: list[Path] = []

        self.current_index = 0

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

        # -----------------------------------------------------
        # Waveform
        # -----------------------------------------------------

        self.plot = pg.PlotWidget()

        self.waveform_curve = (
            self.plot.plot()
        )

        self.plot.setLabel(
            "bottom",
            "Time",
            units="s",
        )

        # -----------------------------------------------------
        # Región manual
        # -----------------------------------------------------

        self.region = (
            pg.LinearRegionItem()
        )

        self.plot.addItem(
            self.region
        )

        self.region.sigRegionChangeFinished.connect(
            self.on_region_changed
        )

        # -----------------------------------------------------
        # Marcadores automáticos
        # -----------------------------------------------------

        self.auto_start_line = (
            pg.InfiniteLine(
                angle=90,
                movable=False,
            )
        )

        self.auto_end_line = (
            pg.InfiniteLine(
                angle=90,
                movable=False,
            )
        )

        self.plot.addItem(
            self.auto_start_line
        )

        self.plot.addItem(
            self.auto_end_line
        )

        # -----------------------------------------------------
        # Spectrogram
        # -----------------------------------------------------

        self.spec_plot = (
            pg.PlotWidget()
        )

        self.spec_image = (
            pg.ImageItem()
        )

        self.spec_plot.addItem(
            self.spec_image
        )

        # Vincular ambos ejes temporales.
        self.spec_plot.setXLink(
            self.plot
        )

        self.spec_plot.setLabel(
            "bottom",
            "Time",
            units="s",
        )

        self.spec_plot.setLabel(
            "left",
            "Frequency",
            units="Hz",
        )

        # Misma reserva para eje Y.
        self.plot.getAxis(
            "left"
        ).setWidth(60)

        self.spec_plot.getAxis(
            "left"
        ).setWidth(60)

        # -----------------------------------------------------
        # Límites manuales en spectrogram
        # -----------------------------------------------------

        self.spec_start_line = (
            pg.InfiniteLine(
                angle=90,
                movable=False,
            )
        )

        self.spec_end_line = (
            pg.InfiniteLine(
                angle=90,
                movable=False,
            )
        )

        self.spec_plot.addItem(
            self.spec_start_line
        )

        self.spec_plot.addItem(
            self.spec_end_line
        )

        # -----------------------------------------------------
        # Colormap
        # -----------------------------------------------------

        cmap = pg.colormap.get(
            "inferno"
        )

        self.spec_image.setLookupTable(
            cmap.getLookupTable()
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

        layout.addWidget(
            self.plot
        )

        layout.addWidget(
            self.spec_plot
        )

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

        files = sorted(
            path
            for path in project_dir.iterdir()
            if (
                path.is_file()
                and path.suffix.lower()
                == ".wav"
            )
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

        if self.files:
            self.save_annotation()

        # Detener cualquier reproducción activa.
        self.player.stop()

        # -----------------------------------------------------
        # Inicializar proyecto
        # -----------------------------------------------------

        self.project_dir = (
            project_dir
        )

        # Guardar proyecto anterior.
        if self.files:
            self.save_annotation()

        # Cerrar DB anterior.
        if self.annotations is not None:
            self.annotations.close()

        self.player.stop()

        # Nuevo proyecto.
        self.project_dir = project_dir
        self.files = files
        self.current_index = 0

        self.annotations = AnnotationStore(
            project_dir / "annotations.db"
        )

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

        self.waveform_curve.setData(
            [],
            [],
        )

        self.spec_image.clear()

        self.plot.setTitle(
            "Open a project to begin"
        )

        self.spec_plot.setTitle(
            ""
        )

        self.setWindowTitle(
            "Audio Annotator"
        )

        # Ocultar overlays mientras no exista audio.
        self.region.hide()

        self.auto_start_line.hide()
        self.auto_end_line.hide()

        self.spec_start_line.hide()
        self.spec_end_line.hide()

    # =========================================================
    # Estado de controles
    # =========================================================

    def update_controls(self):
        """
        Habilita o deshabilita controles según el estado
        actual del proyecto y el índice del archivo.
        """

        has_audio = bool(
            self.files
        )

        has_previous = (
            has_audio
            and self.current_index > 0
        )

        has_next = (
            has_audio
            and self.current_index
            < len(self.files) - 1
        )

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
        if not self.files:
            return

        path = self.files[
            self.current_index
        ]

        self.audio, self.sr = sf.read(
            path,
            dtype="float32",
        )

        self.duration = (
            len(self.audio)
            / self.sr
        )

        self.region.show()
        self.auto_start_line.show()
        self.auto_end_line.show()
        self.spec_start_line.show()
        self.spec_end_line.show()

        self.plot.setTitle("")

        self.update_waveform()
        self.update_spectrogram()

        # Primero calculamos el trim automático actual.
        self.run_auto_trim()

        # Si el archivo ya fue editado anteriormente,
        # restauramos su anotación manual.
        self.restore_annotation()

        self.setWindowTitle(
            (
                f"Audio Annotator - "
                f"{path.name} "
                f"({self.current_index + 1}"
                f"/{len(self.files)})"
            )
        )

        self.update_controls()

    # =========================================================
    # Waveform
    # =========================================================

    def update_waveform(self):
        if not self.files:
            return

        time = (
            np.arange(
                len(self.audio)
            )
            / self.sr
        )

        self.waveform_curve.setData(
            time,
            self.audio,
        )

        self.region.setBounds([
            0,
            self.duration,
        ])

        self.plot.setXRange(
            0,
            self.duration,
            padding=0,
        )

    # =========================================================
    # Spectrogram
    # =========================================================

    def update_spectrogram(self):
        if not self.files:
            return

        spec, times, frequencies = spectrogram(
            self.audio,
            self.sr,
        )

        self.spec_image.setImage(
            spec,
            autoLevels=False,
            levels=[
                -80,
                0,
            ],
        )

        self.spec_image.setRect(
            QRectF(
                0,
                0,
                self.duration,
                self.sr / 2,
            )
        )

        self.spec_plot.setXRange(
            0,
            self.duration,
            padding=0,
        )

        self.spec_plot.setYRange(
            0,
            self.sr / 2,
            padding=0,
        )

    # =========================================================
    # Detector automático
    # =========================================================

    def run_auto_trim(self):
        if not self.files:
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

        # Línea de referencia automática.
        self.auto_start_line.setPos(
            self.auto_start
        )

        self.auto_end_line.setPos(
            self.auto_end
        )

        # Inicializar la selección manual a partir
        # de la propuesta.
        self.region.setRegion([
            self.auto_start,
            self.auto_end,
        ])

        self.on_region_changed()

    # =========================================================
    # Reset manual
    # =========================================================

    def reset_manual_trim(self):
        if not self.files:
            return

        if (
            self.auto_start is None
            or self.auto_end is None
        ):
            return

        self.region.setRegion([
            self.auto_start,
            self.auto_end,
        ])

    # =========================================================
    # Región
    # =========================================================

    def on_region_changed(self):
        if not self.files:
            return

        start, end = (
            self.region.getRegion()
        )

        self.spec_start_line.setPos(
            start
        )

        self.spec_end_line.setPos(
            end
        )

    # =========================================================
    # Playback
    # =========================================================

    def play_selection(self):
        if not self.files:
            return

        start, end = (
            self.region.getRegion()
        )

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

        if self.annotations is None:
            return

        if not self.files:
            return

        if (
            self.auto_start is None
            or self.auto_end is None
        ):
            return

        manual_start, manual_end = (
            self.region.getRegion()
        )

        path = self.files[
            self.current_index
        ]

        self.annotations.save(
            filename=path.name,
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

        if self.annotations is None:
            return

        if not self.files:
            return

        path = self.files[
            self.current_index
        ]

        annotation = self.annotations.get(
            path.name
        )

        if annotation is None:
            return

        manual_start = annotation[
            "manual_start"
        ]

        manual_end = annotation[
            "manual_end"
        ]

        self.region.setRegion([
            manual_start,
            manual_end,
        ])

        self.on_region_changed()

    def closeEvent(self, event):
        """
        Guarda la anotación actual y cierra recursos
        antes de terminar la aplicación.
        """

        if self.files:
            self.save_annotation()

        self.player.stop()

        if self.annotations is not None:
            self.annotations.close()

        event.accept()

    # =========================================================
    # Navegación
    # =========================================================

    def change_audio(
        self,
        offset: int,
    ):
        if not self.files:
            return

        new_index = (
            self.current_index
            + offset
        )

        if not (
            0
            <= new_index
            < len(self.files)
        ):
            return

        # Guardar antes de abandonar el WAV.
        self.save_annotation()

        # Detener reproducción previa.
        self.player.stop()

        self.current_index = (
            new_index
        )

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
        if self.files:
            self.run_auto_trim()


# =============================================================
# Main
# =============================================================

if __name__ == "__main__":
    app = QApplication(
        sys.argv
    )

    window = MainWindow()
    window.show()

    sys.exit(
        app.exec()
    )