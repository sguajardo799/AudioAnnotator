from pathlib import Path
from dataclasses import replace

import numpy as np

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from smartaudiocrop.annotations.exporter import (
    AnnotationExportError,
    AnnotationExporter,
)
from smartaudiocrop.audio.loading import load_audio_snapshot
from smartaudiocrop.audio.player import AudioPlayer, PlaybackState
from smartaudiocrop.project.session import ProjectSession
from smartaudiocrop.settings import ApplicationSettings, TrimPreferences
from smartaudiocrop.trim.config import TrimConfig
from smartaudiocrop.trim.providers import (
    HeuristicTrimProvider,
    NoActivityDetected,
    TrimProposal,
    TrimProviderError,
    file_sha256,
)
from smartaudiocrop.ui.audio_view import AudioView
from smartaudiocrop.ui.inference_worker import (
    InferenceRequest,
    InferenceWorker,
    ModelLoadRequest,
)
from smartaudiocrop.ui.trim_settings_dialog import TrimSettingsDialog


FINE_TRIM_STEP_SECONDS = 0.005
COARSE_TRIM_STEP_SECONDS = 0.025


class MainWindow(QMainWindow):
    load_model_requested = Signal(object)
    inference_requested = Signal(object)

    def __init__(
        self,
        player: AudioPlayer | None = None,
        settings: ApplicationSettings | None = None,
    ):
        super().__init__()

        self.setWindowTitle("Audio Annotator")
        self.resize(1200, 700)

        # =====================================================
        # Servicios
        # =====================================================

        self.player = player or AudioPlayer()
        self.session = ProjectSession()
        self.settings = settings or ApplicationSettings()
        preferences = self.settings.trim_preferences()
        self.selected_engine = preferences.engine
        self.model_manifest_path = preferences.manifest_path
        self.auto_run_on_open = preferences.auto_run_on_open

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
        self.audio_sha256 = ""

        # Propuesta automática del detector.
        self.auto_start: float | None = None
        self.auto_end: float | None = None
        self.active_prediction_id: int | None = None
        self.proposal_source: str | None = None
        self.active_proposal: TrimProposal | None = None
        self.manual_dirty = False
        self._setting_bounds = False

        self._request_id = 0
        self._audio_generation = 0
        self._model_revision = 0
        self._loaded_model_revision = 0
        self._loaded_manifest = None
        self._worker_busy = False
        self._pending_auto_run = False
        self._closing = False
        self._deferred_close = False
        self._shutdown_complete = False

        # =====================================================
        # Construcción de interfaz
        # =====================================================

        self.setup_ui()
        self.setup_menus()
        self.setup_shortcuts()
        self.setup_inference_worker()

        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(33)
        self.playback_timer.timeout.connect(
            self.update_playback_ui
        )

        # La aplicación parte sin proyecto.
        self.clear_project_view()

        self.update_playback_ui()

        if self.selected_engine == "onnx_crnn" and self.model_manifest_path:
            self.load_onnx_model(Path(self.model_manifest_path))

    def setup_inference_worker(self):
        self.inference_thread = QThread(self)
        self.inference_worker = InferenceWorker()
        self.inference_worker.moveToThread(self.inference_thread)
        self.load_model_requested.connect(self.inference_worker.load_model)
        self.inference_requested.connect(self.inference_worker.infer)
        self.inference_worker.model_loaded.connect(self.on_model_loaded)
        self.inference_worker.inference_succeeded.connect(
            self.on_inference_succeeded
        )
        self.inference_worker.failed.connect(self.on_inference_failed)
        self.inference_worker.idle.connect(self.on_worker_idle)
        self.inference_thread.finished.connect(
            self.inference_worker.deleteLater
        )
        self.inference_thread.finished.connect(self._finish_deferred_close)
        self.inference_thread.start()

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

        self.stop_button = QPushButton(
            "Stop"
        )

        self.restart_button = QPushButton(
            "Restart"
        )

        self.loop_checkbox = QCheckBox(
            "Loop"
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
            self.stop_button
        )

        controls.addWidget(
            self.restart_button
        )

        controls.addWidget(
            self.reset_button
        )

        controls.addWidget(
            self.next_button
        )

        controls.addStretch()

        controls.addWidget(
            self.loop_checkbox
        )

        tracking = QHBoxLayout()

        self.file_counter_label = QLabel(
            "File 0 of 0"
        )
        self.status_label = QLabel(
            "Status: -"
        )
        self.engine_status_label = QLabel("Engine: Heuristic")
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)

        tracking.addWidget(
            self.file_counter_label
        )
        tracking.addWidget(
            self.status_label
        )
        tracking.addWidget(self.engine_status_label)
        tracking.addStretch()
        tracking.addWidget(
            self.progress_bar,
            stretch=1,
        )

        # -----------------------------------------------------
        # Señales
        # -----------------------------------------------------

        self.prev_button.clicked.connect(
            self.prev_audio
        )

        self.play_button.clicked.connect(
            self.toggle_playback
        )

        self.stop_button.clicked.connect(
            self.stop_playback
        )

        self.restart_button.clicked.connect(
            self.restart_playback
        )

        self.loop_checkbox.toggled.connect(
            self.player.set_loop
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
        layout.addLayout(
            tracking
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

        self.export_annotations_action = QAction(
            "Export Annotations...",
            self,
        )

        self.export_annotations_action.triggered.connect(
            self.export_annotations
        )

        file_menu.addAction(
            self.export_annotations_action
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

        engine_menu = trim_menu.addMenu("Engine")
        self.engine_group = QActionGroup(self)
        self.engine_group.setExclusive(True)
        self.heuristic_engine_action = QAction("Heuristic", self)
        self.heuristic_engine_action.setCheckable(True)
        self.heuristic_engine_action.triggered.connect(
            self.select_heuristic_engine
        )
        self.onnx_engine_action = QAction("ONNX Model", self)
        self.onnx_engine_action.setCheckable(True)
        self.onnx_engine_action.triggered.connect(self.select_onnx_engine)
        self.engine_group.addAction(self.heuristic_engine_action)
        self.engine_group.addAction(self.onnx_engine_action)
        engine_menu.addAction(self.heuristic_engine_action)
        engine_menu.addAction(self.onnx_engine_action)
        self.heuristic_engine_action.setChecked(
            self.selected_engine == "heuristic"
        )
        self.onnx_engine_action.setChecked(
            self.selected_engine == "onnx_crnn"
        )

        self.load_model_action = QAction("Load ONNX Package...", self)
        self.load_model_action.triggered.connect(self.choose_onnx_model)
        trim_menu.addAction(self.load_model_action)

        self.auto_run_action = QAction("Auto-run on open", self)
        self.auto_run_action.setCheckable(True)
        self.auto_run_action.setChecked(self.auto_run_on_open)
        self.auto_run_action.toggled.connect(self.set_auto_run_on_open)
        trim_menu.addAction(self.auto_run_action)

        trim_menu.addSeparator()

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

        self.force_run_action = QAction("Force re-run", self)
        self.force_run_action.triggered.connect(
            lambda: self.run_auto_trim(force=True)
        )
        trim_menu.addAction(self.force_run_action)

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
        self.shortcuts: dict[str, QShortcut] = {}

        self._add_shortcut(
            "Left",
            self.prev_audio,
        )

        self._add_shortcut(
            "Right",
            self.next_audio,
        )

        self._add_shortcut(
            "Space",
            self.toggle_playback,
        )

        self._add_shortcut(
            "R",
            self.reset_manual_trim,
        )

        self._add_shortcut(
            "Return",
            self.confirm_annotation,
            auto_repeat=False,
        )
        self._add_shortcut(
            "Enter",
            self.confirm_annotation,
            auto_repeat=False,
        )

        adjustments = {
            ",": ("start", -FINE_TRIM_STEP_SECONDS),
            ".": ("start", FINE_TRIM_STEP_SECONDS),
            "Shift+,": ("start", -COARSE_TRIM_STEP_SECONDS),
            "Shift+.": ("start", COARSE_TRIM_STEP_SECONDS),
            "Ctrl+,": ("end", -FINE_TRIM_STEP_SECONDS),
            "Ctrl+.": ("end", FINE_TRIM_STEP_SECONDS),
            "Ctrl+Shift+,": ("end", -COARSE_TRIM_STEP_SECONDS),
            "Ctrl+Shift+.": ("end", COARSE_TRIM_STEP_SECONDS),
        }

        for sequence, (edge, delta) in adjustments.items():
            self._add_shortcut(
                sequence,
                lambda edge=edge, delta=delta: self.adjust_manual_bound(
                    edge,
                    delta,
                ),
            )

    def _add_shortcut(
        self,
        sequence: str,
        callback,
        *,
        auto_repeat: bool = True,
    ):
        shortcut = QShortcut(
            QKeySequence(sequence),
            self,
        )
        shortcut.setContext(
            Qt.ShortcutContext.WindowShortcut
        )
        shortcut.setAutoRepeat(auto_repeat)
        shortcut.activated.connect(callback)
        self.shortcuts[sequence] = shortcut

    def adjust_manual_bound(
        self,
        edge: str,
        delta_seconds: float,
    ):
        if not self.session.files:
            return

        start, end = self.audio_view.manual_bounds()

        if edge == "start":
            new_start = max(0.0, start + delta_seconds)
            if new_start >= end:
                return
            start = new_start
        elif edge == "end":
            new_end = min(self.duration, end + delta_seconds)
            if new_end <= start:
                return
            end = new_end
        else:
            raise ValueError(f"Unknown trim edge: {edge}")

        self.audio_view.set_manual_bounds(start, end)
        self.on_region_changed()

    # =========================================================
    # EXPORT ANNOTATIONS
    # =========================================================

    def export_annotations(self):
        store = self.session.annotations

        if store is None or self.session.project_dir is None:
            return

        annotations = store.get_all_for_export()

        if not annotations:
            QMessageBox.warning(
                self,
                "No Annotations",
                "There are no saved annotations to export.",
            )
            return

        default_path = (
            self.session.project_dir
            / "annotations_export.csv"
        )
        destination, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Annotations",
            str(default_path),
            "CSV Files (*.csv)",
        )

        if not destination:
            return

        destination_path = Path(destination).resolve()
        protected_paths = {
            (self.session.project_dir / "annotations.db").resolve(),
            *(path.resolve() for path in self.session.files),
        }

        if destination_path in protected_paths:
            QMessageBox.warning(
                self,
                "Invalid Export Destination",
                (
                    "Annotations cannot be exported over the project "
                    "database or a WAV file."
                ),
            )
            return

        try:
            AnnotationExporter.export_csv(
                annotations,
                destination,
            )
        except AnnotationExportError as exc:
            QMessageBox.warning(
                self,
                "Export Failed",
                str(exc),
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
            - annotations.db

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
            if not self.autosave_annotation():
                return

        # Detener cualquier reproducción activa.
        self.player.stop()

        # -----------------------------------------------------
        # Inicializar proyecto
        # -----------------------------------------------------

        # Nuevo proyecto.
        try:
            self.session.replace(project_dir, files)
        except Exception as exc:
            QMessageBox.warning(self, "Could Not Open Project", str(exc))
            return
        self._request_id += 1

        # Limpiar información del audio anterior antes
        # de cargar el nuevo proyecto.
        self.audio = np.array(
            [],
            dtype=np.float32,
        )

        self.sr = 0
        self.duration = 0.0
        self.audio_sha256 = ""

        self.auto_start = None
        self.auto_end = None
        self.active_prediction_id = None
        self.proposal_source = None
        self.active_proposal = None
        self.manual_dirty = False

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
        self.update_project_tracking_ui()

    # =========================================================
    # Estado de controles
    # =========================================================

    def update_controls(self):
        """
        Habilita o deshabilita controles según el estado
        actual del proyecto y el índice del archivo.
        """

        has_audio = bool(self.session.files) and self.duration > 0
        engine_text = "Engine: Heuristic"
        if self.selected_engine == "onnx_crnn":
            engine_text = "Engine: ONNX"
            if self._loaded_manifest is not None:
                engine_text += (
                    f" · {self._loaded_manifest.model_id} "
                    f"{self._loaded_manifest.model_version}"
                )
        if self._worker_busy:
            engine_text += " · Working..."
        self.engine_status_label.setText(engine_text)
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

        snapshot = self.player.snapshot()
        is_active = snapshot.state in {
            PlaybackState.PLAYING,
            PlaybackState.PAUSED,
        }

        self.stop_button.setEnabled(
            has_audio and is_active
        )

        self.restart_button.setEnabled(
            has_audio
        )

        self.loop_checkbox.setEnabled(
            has_audio
        )

        self.reset_button.setEnabled(
            has_audio
        )

        self.run_trim_action.setEnabled(
            has_audio
            and not self._worker_busy
            and (
                self.selected_engine == "heuristic"
                or self._loaded_manifest is not None
            )
        )
        self.force_run_action.setEnabled(self.run_trim_action.isEnabled())
        self.load_model_action.setEnabled(not self._worker_busy)
        self.trim_settings_action.setEnabled(
            self.selected_engine == "heuristic" and not self._worker_busy
        )

        self.reset_trim_action.setEnabled(
            has_audio
        )

        self.export_annotations_action.setEnabled(
            has_audio
        )

        self.update_project_tracking_ui()

    def update_project_tracking_ui(self):
        total = self.session.total_count
        viewed = self.session.viewed_count

        if not total:
            self.file_counter_label.setText(
                "File 0 of 0"
            )
            self.status_label.setText(
                "Status: -"
            )
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(
                "0/0 reviewed"
            )
            return

        self.file_counter_label.setText(
            (
                f"File {self.session.current_index + 1} "
                f"of {total}"
            )
        )
        self.status_label.setText(
            f"Status: {self.session.current_status}"
        )
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(viewed)
        self.progress_bar.setFormat(
            f"{viewed}/{total} reviewed (%p%)"
        )

    # =========================================================
    # Carga
    # =========================================================

    def load_current_audio(self):
        if not self.session.files:
            return

        path = self.session.current_path
        self._audio_generation += 1
        self._request_id += 1
        self.manual_dirty = False
        self._pending_auto_run = False
        try:
            self.audio, self.sr, self.audio_sha256 = load_audio_snapshot(path)
            if (
                self.sr <= 0 or len(self.audio) == 0
                or self.audio.ndim not in (1, 2)
                or not np.all(np.isfinite(self.audio))
            ):
                raise ValueError("WAV is empty or contains invalid samples")
        except (OSError, ValueError, RuntimeError) as exc:
            self.audio = np.array([], dtype=np.float32)
            self.sr = 0
            self.duration = 0.0
            self.auto_start = self.auto_end = None
            self.active_prediction_id = None
            self.proposal_source = None
            self.active_proposal = None
            self.audio_view.clear()
            self.update_controls()
            QMessageBox.warning(self, "Could Not Load WAV", str(exc))
            return

        self.player.set_source(
            self.audio,
            self.sr,
        )

        self.duration = (
            len(self.audio)
            / self.sr
        )

        self.audio_view.show_audio(
            self.audio,
            self.sr,
            self.duration,
        )
        self._setting_bounds = True
        self.audio_view.set_manual_bounds(0.0, self.duration)
        self._setting_bounds = False
        self.auto_start = None
        self.auto_end = None
        self.active_prediction_id = None
        self.proposal_source = None
        self.active_proposal = None
        self.manual_dirty = False

        annotation = self.restore_annotation()
        if annotation is None:
            if self.selected_engine == "heuristic":
                self.run_auto_trim()
            elif self.auto_run_on_open and self._loaded_manifest is not None:
                if self._worker_busy:
                    self._pending_auto_run = True
                else:
                    self.run_auto_trim()
            else:
                self.audio_view.clear_proposal()
                self.audio_view.set_proposal_text("No active proposal")

        self.setWindowTitle(
            (
                f"Audio Annotator - "
                f"{path.name} "
                f"({self.session.current_index + 1}"
                f"/{len(self.session.files)})"
            )
        )

        self.update_playback_ui()

    # =========================================================
    # Detector automático
    # =========================================================

    def run_auto_trim(self, force: bool = False):
        if not self.session.files or self.duration <= 0:
            return

        if self.selected_engine == "onnx_crnn":
            self.run_onnx_inference(force=force)
            return

        try:
            proposal = HeuristicTrimProvider(self.trim_config).infer(
                self.audio,
                self.sr,
                self.session.current_path,
                self.audio_sha256,
            )
        except NoActivityDetected as exc:
            if self.session.get_current_annotation() is not None or self.manual_dirty:
                QMessageBox.warning(self, "Trim Failed", str(exc))
                return
            self.auto_start = 0.0
            self.auto_end = self.duration
            self.active_prediction_id = None
            self.proposal_source = None
            self.active_proposal = None
            self._setting_bounds = True
            self.audio_view.set_manual_bounds(self.auto_start, self.auto_end)
            self.audio_view.sync_selection_markers()
            self._setting_bounds = False
            self.audio_view.clear_proposal()
            self.audio_view.set_proposal_text("Manual selection")
            return
        except (OSError, ValueError, TrimProviderError) as exc:
            QMessageBox.warning(self, "Trim Failed", str(exc))
            return
        self.apply_proposal(proposal, force=force)

    def apply_proposal(self, proposal: TrimProposal, *, force: bool = False):
        store = self.session.annotations
        if store is None:
            return
        if proposal.audio_sha256 != self.audio_sha256:
            QMessageBox.warning(
                self,
                "Audio Changed",
                "The proposal does not match the loaded WAV and was discarded.",
            )
            return
        try:
            reusable = None
            if not force:
                reusable = store.find_reusable_prediction(
                    filename=self.session.current_path.name,
                    audio_sha256=proposal.audio_sha256,
                    source=proposal.source,
                    config=proposal.config,
                    model_sha256=proposal.model_sha256,
                )
            if reusable is None:
                prediction_id = store.insert_prediction(
                    filename=self.session.current_path.name,
                    audio_sha256=proposal.audio_sha256,
                    source=proposal.source,
                    config=proposal.config,
                    predicted_start=proposal.start,
                    predicted_end=proposal.end,
                    model_id=proposal.model_id,
                    model_version=proposal.model_version,
                    model_sha256=proposal.model_sha256,
                    preprocessing_version=proposal.preprocessing_version,
                    decoder_version=proposal.decoder_version,
                    threshold=proposal.threshold,
                    bridge_ms=proposal.bridge_ms,
                )
            else:
                prediction_id = int(reusable["id"])
                proposal = replace(
                    proposal,
                    start=float(reusable["predicted_start"]),
                    end=float(reusable["predicted_end"]),
                )
        except Exception as exc:
            QMessageBox.warning(self, "Could Not Save Prediction", str(exc))
            return

        annotation = self.session.get_current_annotation()
        if annotation is not None and annotation["status"] == "VIEWED":
            answer = QMessageBox.question(
                self,
                "Activate New Proposal",
                (
                    "A reviewed annotation already exists. Activate the new "
                    "proposal while preserving its manual bounds?"
                ),
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.audio_view.set_proposal_text(
                    self._proposal_text_for_annotation(annotation)
                )
                return

        if annotation is not None:
            try:
                store.select_prediction(
                    filename=self.session.current_path.name,
                    prediction_id=prediction_id,
                )
            except Exception as exc:
                QMessageBox.warning(self, "Could Not Select Prediction", str(exc))
                return

        self.auto_start = proposal.start
        self.auto_end = proposal.end
        self.active_prediction_id = prediction_id
        self.proposal_source = proposal.source
        self.active_proposal = proposal
        self.audio_view.set_proposal_bounds(proposal.start, proposal.end)
        source_text = "Heuristic"
        if proposal.source == "onnx_crnn":
            source_text = f"ONNX · {proposal.model_id} {proposal.model_version}"
        if proposal.truncated:
            source_text += " · input truncated to 6.0 s"
        self.audio_view.set_proposal_text(f"Proposal: {source_text}")

        if annotation is None and not self.manual_dirty:
            self._setting_bounds = True
            self.audio_view.set_manual_bounds(proposal.start, proposal.end)
            self.audio_view.sync_selection_markers()
            self._setting_bounds = False

    def run_onnx_inference(self, *, force: bool = False):
        if self._worker_busy or self._loaded_manifest is None:
            return
        if not force:
            try:
                prediction = self.session.annotations.find_reusable_prediction(
                    filename=self.session.current_path.name,
                    audio_sha256=self.audio_sha256,
                    source="onnx_crnn",
                    config=self._loaded_manifest.config,
                    model_sha256=self._loaded_manifest.model_sha256,
                )
            except Exception as exc:
                QMessageBox.warning(self, "Could Not Read Predictions", str(exc))
                return
            if prediction is not None:
                self.apply_proposal(
                    TrimProposal(
                        start=prediction["predicted_start"],
                        end=prediction["predicted_end"],
                        source="onnx_crnn",
                        audio_sha256=prediction["audio_sha256"],
                        config=self._loaded_manifest.config,
                        model_id=prediction["model_id"],
                        model_version=prediction["model_version"],
                        model_sha256=prediction["model_sha256"],
                        preprocessing_version=prediction["preprocessing_version"],
                        decoder_version=prediction["decoder_version"],
                        threshold=prediction["threshold"],
                        bridge_ms=prediction["bridge_ms"],
                        truncated=self.duration > self._loaded_manifest.max_duration_seconds,
                    )
                )
                return
        self._request_id += 1
        request = InferenceRequest(
            request_id=self._request_id,
            project_generation=self.session.project_generation,
            project_id=str(self.session.project_dir.resolve()),
            audio_generation=self._audio_generation,
            audio_id=self.session.current_path.name,
            model_revision=self._loaded_model_revision,
            audio_path=self.session.current_path,
            audio_sha256=self.audio_sha256,
            audio=np.ascontiguousarray(self.audio.copy()),
            sample_rate=self.sr,
            force=force,
        )
        request.audio.setflags(write=False)
        self._worker_busy = True
        self.audio_view.set_proposal_text("Inferring...")
        self.update_controls()
        self.inference_requested.emit(request)

    def _request_is_current(self, request: InferenceRequest) -> bool:
        return (
            not self._closing
            and bool(self.session.files)
            and request.request_id == self._request_id
            and request.project_generation == self.session.project_generation
            and request.project_id == str(self.session.project_dir.resolve())
            and request.audio_generation == self._audio_generation
            and request.audio_id == self.session.current_path.name
            and request.model_revision == self._loaded_model_revision
        )

    def on_inference_succeeded(
        self,
        request: InferenceRequest,
        proposal: TrimProposal,
    ):
        if not self._request_is_current(request):
            return
        try:
            current_sha256 = file_sha256(self.session.current_path)
        except OSError as exc:
            QMessageBox.warning(self, "Audio Changed", str(exc))
            return
        if current_sha256 != request.audio_sha256:
            QMessageBox.warning(
                self,
                "Audio Changed",
                "The WAV changed during inference; its result was discarded.",
            )
            return
        self.apply_proposal(proposal, force=request.force)

    def on_inference_failed(self, request, message: str):
        if isinstance(request, ModelLoadRequest):
            if request.revision != self._model_revision or self._closing:
                return
            self._loaded_manifest = None
            self._loaded_model_revision = 0
            self.selected_engine = "heuristic"
            self.heuristic_engine_action.setChecked(True)
            self.run_trim_action.setText("Run detector")
            self._save_preferences()
            QMessageBox.warning(self, "ONNX Model Error", message)
            return
        if isinstance(request, InferenceRequest) and self._request_is_current(request):
            annotation = self.session.get_current_annotation()
            if annotation is not None:
                self.audio_view.set_proposal_text(
                    self._proposal_text_for_annotation(annotation)
                )
            else:
                self.audio_view.set_proposal_text("No active proposal")
            QMessageBox.warning(self, "ONNX Inference Failed", message)

    def on_worker_idle(self):
        self._worker_busy = False
        if self._closing:
            return
        self.update_controls()
        if (
            self._pending_auto_run
            and not self._closing
            and self.session.files
            and self.session.get_current_annotation() is None
        ):
            self._pending_auto_run = False
            QTimer.singleShot(0, self.run_auto_trim)

    def choose_onnx_model(self):
        manifest_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select ONNX Model Manifest",
            self.model_manifest_path,
            "Model Manifest (model_manifest.json);;JSON Files (*.json)",
        )
        if manifest_path:
            self.load_onnx_model(Path(manifest_path))

    def load_onnx_model(self, manifest_path: Path):
        if self._worker_busy:
            return
        self._model_revision += 1
        self._worker_busy = True
        self.update_controls()
        self.load_model_requested.emit(
            ModelLoadRequest(self._model_revision, manifest_path.resolve())
        )

    def on_model_loaded(self, request: ModelLoadRequest, manifest):
        if request.revision != self._model_revision or self._closing:
            return
        self._loaded_manifest = manifest
        self._loaded_model_revision = request.revision
        self.model_manifest_path = str(request.manifest_path)
        self.selected_engine = "onnx_crnn"
        self.onnx_engine_action.setChecked(True)
        self.run_trim_action.setText("Run Pre-annotation")
        self._save_preferences()
        if (
            self.session.files
            and self.auto_run_on_open
            and self.session.get_current_annotation() is None
        ):
            QTimer.singleShot(0, self.run_auto_trim)

    def select_heuristic_engine(self):
        self._pending_auto_run = False
        self.selected_engine = "heuristic"
        self.run_trim_action.setText("Run detector")
        self._request_id += 1
        self._save_preferences()
        self.update_controls()

    def select_onnx_engine(self):
        if self._loaded_manifest is None:
            self.onnx_engine_action.setChecked(False)
            self.heuristic_engine_action.setChecked(True)
            if self.model_manifest_path:
                self.load_onnx_model(Path(self.model_manifest_path))
            else:
                self.choose_onnx_model()
            return
        self.selected_engine = "onnx_crnn"
        self.run_trim_action.setText("Run Pre-annotation")
        self._save_preferences()
        self.update_controls()

    def set_auto_run_on_open(self, enabled: bool):
        self.auto_run_on_open = enabled
        self._save_preferences()

    def _save_preferences(self):
        self.settings.save_trim_preferences(
            TrimPreferences(
                engine=self.selected_engine,
                manifest_path=self.model_manifest_path,
                auto_run_on_open=self.auto_run_on_open,
            )
        )

    @staticmethod
    def _proposal_text_for_annotation(annotation: dict) -> str:
        source = annotation.get("proposal_source")
        if source == "heuristic":
            return "Proposal: Heuristic"
        if source == "onnx_crnn":
            return "Proposal: ONNX"
        if source == "legacy":
            return "Proposal: Legacy"
        return "Manual selection"

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
        self.audio_view.sync_selection_markers()
        self.manual_dirty = True

    # =========================================================
    # Región
    # =========================================================

    def on_region_changed(self):
        if not self.session.files:
            return

        self.audio_view.sync_selection_markers()
        if not self._setting_bounds:
            self.manual_dirty = True

    # =========================================================
    # Playback
    # =========================================================

    def toggle_playback(self):
        state = self.player.snapshot().state

        if state is PlaybackState.PLAYING:
            self.player.pause()
        elif state is PlaybackState.PAUSED:
            self.player.resume()
        else:
            self.play_selection()

        self.update_playback_ui()

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

        if start_sample >= end_sample:
            return

        self.player.play(
            start_sample,
            end_sample,
            loop=self.loop_checkbox.isChecked(),
        )

        self.playback_timer.start()

    def stop_playback(self):
        self.player.stop()
        self.update_playback_ui()

    def restart_playback(self):
        if not self.session.files:
            return

        start, end = self.audio_view.manual_bounds()
        start_sample = int(start * self.sr)
        end_sample = int(end * self.sr)
        if start_sample >= end_sample:
            return

        self.player.restart(
            start_sample,
            end_sample,
            loop=self.loop_checkbox.isChecked(),
        )
        self.playback_timer.start()
        self.update_playback_ui()

    def update_playback_ui(self):
        snapshot = self.player.snapshot()

        if snapshot.state is PlaybackState.PLAYING:
            self.play_button.setText("Pause")
            if not self.playback_timer.isActive():
                self.playback_timer.start()
        elif snapshot.state is PlaybackState.PAUSED:
            self.play_button.setText("Resume")
            self.playback_timer.stop()
        else:
            self.play_button.setText("Play")
            self.playback_timer.stop()

        has_position = snapshot.selection_end_frames > snapshot.selection_start_frames
        if has_position:
            self.audio_view.set_playback_position(
                snapshot.position_seconds
            )
            self.audio_view.set_playback_cursor_visible(True)
        else:
            self.audio_view.set_playback_cursor_visible(False)

        self.update_controls()

    # =========================================================
    # Guardar anotación
    # =========================================================

    def save_annotation(self):
        """Explicitly confirm the current manual selection as reviewed."""
        if not self.session.files or self.duration <= 0:
            return False
        values = self._annotation_values()
        try:
            self.session.confirm_current_annotation(**values)
        except Exception as exc:
            QMessageBox.warning(self, "Could Not Save Annotation", str(exc))
            return False
        self.manual_dirty = False
        self.update_project_tracking_ui()
        return True

    def autosave_annotation(self):
        """Save human edits without changing review status."""
        if not self.session.files or not self.manual_dirty:
            return True
        values = self._annotation_values()
        try:
            self.session.autosave_current_annotation(**values)
        except Exception as exc:
            QMessageBox.warning(self, "Could Not Save Draft", str(exc))
            return False
        self.manual_dirty = False
        self.update_project_tracking_ui()
        return True

    def _annotation_values(self) -> dict:
        manual_start, manual_end = self.audio_view.manual_bounds()
        auto_start = self.auto_start
        auto_end = self.auto_end
        if auto_start is None or auto_end is None:
            auto_start, auto_end = manual_start, manual_end
        return {
            "duration": self.duration,
            "sample_rate": self.sr,
            "auto_start": auto_start,
            "auto_end": auto_end,
            "manual_start": manual_start,
            "manual_end": manual_end,
            "proposal_source": self.proposal_source,
            "prediction_id": self.active_prediction_id,
        }

    def restore_annotation(self):
        """
        Restore both the persisted proposal and the editable selection.
        """

        annotation = self.session.get_current_annotation()

        if annotation is None:
            return None

        self.auto_start = float(annotation["auto_start"])
        self.auto_end = float(annotation["auto_end"])
        self.active_prediction_id = annotation["prediction_id"]
        self.proposal_source = annotation["proposal_source"]
        self.audio_view.set_proposal_bounds(self.auto_start, self.auto_end)
        label = "Manual selection"
        if self.proposal_source == "heuristic":
            label = "Proposal: Heuristic"
        elif self.proposal_source == "onnx_crnn":
            prediction = None
            if self.active_prediction_id is not None:
                prediction = self.session.annotations.get_prediction(
                    int(self.active_prediction_id)
                )
            identity = "ONNX"
            if prediction is not None:
                identity += (
                    f" · {prediction['model_id']} {prediction['model_version']}"
                )
            label = f"Proposal: {identity}"
        elif self.proposal_source == "legacy":
            label = "Proposal: Legacy"
        self.audio_view.set_proposal_text(label)
        self._setting_bounds = True
        self.audio_view.set_manual_bounds(
            float(annotation["manual_start"]),
            float(annotation["manual_end"]),
        )
        self.audio_view.sync_selection_markers()
        self._setting_bounds = False
        self.manual_dirty = False
        return annotation

    def closeEvent(self, event):
        """
        Guarda la anotación actual y cierra recursos
        antes de terminar la aplicación.
        """

        if self._shutdown_complete:
            event.accept()
            return
        if self._closing:
            event.ignore()
            return
        if self.session.files:
            if not self.autosave_annotation():
                event.ignore()
                return
        self._closing = True
        self._request_id += 1

        self.playback_timer.stop()
        self.player.close()
        self.inference_thread.requestInterruption()
        self.inference_thread.quit()
        if self._worker_busy and self.inference_thread.isRunning():
            self._deferred_close = True
            event.ignore()
            return
        self.inference_thread.wait(2_000)
        if self.inference_thread.isRunning():
            self._deferred_close = True
            event.ignore()
            return
        self.session.close_annotations()
        self._shutdown_complete = True
        event.accept()

    def _finish_deferred_close(self):
        if not self._deferred_close or self._shutdown_complete:
            return
        self.session.close_annotations()
        self._shutdown_complete = True
        QTimer.singleShot(0, self.close)

    # =========================================================
    # Navegación
    # =========================================================

    def confirm_annotation(self):
        if not self.session.files:
            return

        if not self.save_annotation():
            return

        if self.session.has_next:
            self._change_audio(+1)

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

        # Autosave preserves drafts but never confirms review.
        if not self.autosave_annotation():
            return

        self._change_audio(offset)

    def _change_audio(
        self,
        offset: int,
    ):

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
