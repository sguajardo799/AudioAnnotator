from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QVBoxLayout,
    QWidget,
)

from trim.config import TrimConfig


class TrimSettingsDialog(QDialog):
    """
    Ventana para modificar los parámetros del detector.

    El diálogo no modifica directamente la configuración
    recibida. Al aceptar, genera una nueva instancia
    de TrimConfig.
    """

    def __init__(
        self,
        config: TrimConfig,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.setWindowTitle("Trim Settings")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # -----------------------------------------------------
        # Noise percentile
        # -----------------------------------------------------

        self.noise_percentile = self._create_spinbox(
            value=config.noise_percentile,
            minimum=0.0,
            maximum=100.0,
            step=1.0,
            decimals=1,
        )

        form.addRow(
            "Noise percentile:",
            self.noise_percentile,
        )

        # -----------------------------------------------------
        # SNR thresholds
        # -----------------------------------------------------

        self.start_snr_db = self._create_spinbox(
            value=config.start_snr_db,
            minimum=0.0,
            maximum=60.0,
            step=0.5,
            decimals=1,
            suffix=" dB",
        )

        form.addRow(
            "Start SNR:",
            self.start_snr_db,
        )

        self.end_snr_db = self._create_spinbox(
            value=config.end_snr_db,
            minimum=0.0,
            maximum=60.0,
            step=0.5,
            decimals=1,
            suffix=" dB",
        )

        form.addRow(
            "End SNR:",
            self.end_snr_db,
        )

        # -----------------------------------------------------
        # Frame analysis
        # -----------------------------------------------------

        self.window_ms = self._create_spinbox(
            value=config.window_ms,
            minimum=1.0,
            maximum=1000.0,
            step=1.0,
            decimals=1,
            suffix=" ms",
        )

        form.addRow(
            "Window:",
            self.window_ms,
        )

        self.hop_ms = self._create_spinbox(
            value=config.hop_ms,
            minimum=1.0,
            maximum=1000.0,
            step=1.0,
            decimals=1,
            suffix=" ms",
        )

        form.addRow(
            "Hop:",
            self.hop_ms,
        )

        # -----------------------------------------------------
        # Activity requirements
        # -----------------------------------------------------

        self.start_min_active_ms = self._create_spinbox(
            value=config.start_min_active_ms,
            minimum=1.0,
            maximum=2000.0,
            step=5.0,
            decimals=1,
            suffix=" ms",
        )

        form.addRow(
            "Start minimum activity:",
            self.start_min_active_ms,
        )

        self.end_min_active_ms = self._create_spinbox(
            value=config.end_min_active_ms,
            minimum=1.0,
            maximum=2000.0,
            step=5.0,
            decimals=1,
            suffix=" ms",
        )

        form.addRow(
            "End minimum activity:",
            self.end_min_active_ms,
        )

        # -----------------------------------------------------
        # Padding
        # -----------------------------------------------------

        self.start_padding_ms = self._create_spinbox(
            value=config.start_padding_ms,
            minimum=0.0,
            maximum=2000.0,
            step=10.0,
            decimals=1,
            suffix=" ms",
        )

        form.addRow(
            "Start padding:",
            self.start_padding_ms,
        )

        self.end_padding_ms = self._create_spinbox(
            value=config.end_padding_ms,
            minimum=0.0,
            maximum=2000.0,
            step=10.0,
            decimals=1,
            suffix=" ms",
        )

        form.addRow(
            "End padding:",
            self.end_padding_ms,
        )

        # -----------------------------------------------------
        # End hysteresis
        # -----------------------------------------------------

        self.end_hangover_ms = self._create_spinbox(
            value=config.end_hangover_ms,
            minimum=1.0,
            maximum=3000.0,
            step=10.0,
            decimals=1,
            suffix=" ms",
        )

        form.addRow(
            "End hangover:",
            self.end_hangover_ms,
        )

        self.end_max_extension_ms = self._create_spinbox(
            value=config.end_max_extension_ms,
            minimum=1.0,
            maximum=5000.0,
            step=10.0,
            decimals=1,
            suffix=" ms",
        )

        form.addRow(
            "Maximum end extension:",
            self.end_max_extension_ms,
        )

        layout.addLayout(form)

        # -----------------------------------------------------
        # OK / Cancel
        # -----------------------------------------------------

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )

        buttons.accepted.connect(
            self.accept
        )

        buttons.rejected.connect(
            self.reject
        )

        layout.addWidget(buttons)

    @staticmethod
    def _create_spinbox(
        *,
        value: float,
        minimum: float,
        maximum: float,
        step: float,
        decimals: int,
        suffix: str = "",
    ) -> QDoubleSpinBox:
        """Crea un QDoubleSpinBox con configuración común."""

        spin = QDoubleSpinBox()

        spin.setRange(
            minimum,
            maximum,
        )

        spin.setSingleStep(
            step
        )

        spin.setDecimals(
            decimals
        )

        spin.setValue(
            value
        )

        if suffix:
            spin.setSuffix(
                suffix
            )

        return spin

    def get_config(self) -> TrimConfig:
        """
        Construye una nueva configuración a partir
        de los valores del formulario.
        """

        config = TrimConfig(
            noise_percentile=self.noise_percentile.value(),
            start_snr_db=self.start_snr_db.value(),
            end_snr_db=self.end_snr_db.value(),
            window_ms=self.window_ms.value(),
            hop_ms=self.hop_ms.value(),
            start_min_active_ms=self.start_min_active_ms.value(),
            end_min_active_ms=self.end_min_active_ms.value(),
            start_padding_ms=self.start_padding_ms.value(),
            end_padding_ms=self.end_padding_ms.value(),
            end_hangover_ms=self.end_hangover_ms.value(),
            end_max_extension_ms=self.end_max_extension_ms.value(),
        )

        # Utilizamos la misma validación del backend.
        config.validate()

        return config