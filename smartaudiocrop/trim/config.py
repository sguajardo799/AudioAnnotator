"""Configuración del detector automático de recorte."""

from dataclasses import dataclass
import math

@dataclass(frozen=True)
class TrimConfig:
    """
    Parámetros utilizados por el detector automático de inicio/fin.

    La clase es inmutable (frozen=True):
    cuando posteriormente modifiquemos los parámetros desde la GUI,
    crearemos una nueva instancia en vez de modificar la existente.
    """

    # Percentil de los niveles RMS utilizado para estimar el piso de ruido.
    noise_percentile: float = 10.0

    # Margen sobre el piso de ruido necesario para CONFIRMAR actividad.
    start_snr_db: float = 8.0

    # Umbral más permisivo utilizado para mantener actividad hacia el final.
    # Esto crea una histéresis entre detección y mantenimiento.
    end_snr_db: float = 2.0

    # Tamaño de cada ventana RMS.
    window_ms: float = 20.0

    # Desplazamiento entre ventanas consecutivas.
    hop_ms: float = 5.0

    # Actividad continua mínima necesaria para aceptar un inicio.
    start_min_active_ms: float = 30.0

    # Actividad mínima utilizada para confirmar actividad al final.
    end_min_active_ms: float = 20.0

    # Margen conservado antes de la detección inicial.
    start_padding_ms: float = 50.0

    # Margen conservado después del final detectado.
    end_padding_ms: float = 150.0

    # Tiempo de inactividad continua requerido para cerrar el utterance.
    end_hangover_ms: float = 100.0

    # Extensión máxima permitida después de la última actividad confirmada.
    end_max_extension_ms: float = 350.0

    def validate(self) -> None:
        """Valida relaciones y rangos entre parámetros."""

        if not math.isfinite(self.noise_percentile) or not (
            0 <= self.noise_percentile <= 100
        ):
            raise ValueError(
                "noise_percentile debe estar entre 0 y 100"
            )

        for name, value in (
            ("start_snr_db", self.start_snr_db),
            ("end_snr_db", self.end_snr_db),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(
                    f"{name} debe ser un número finito mayor o igual que 0"
                )

        if self.end_snr_db > self.start_snr_db:
            raise ValueError(
                "end_snr_db debe ser menor o igual que start_snr_db"
            )

        for name, value in (
            ("window_ms", self.window_ms),
            ("hop_ms", self.hop_ms),
            ("start_min_active_ms", self.start_min_active_ms),
            ("end_min_active_ms", self.end_min_active_ms),
            ("end_hangover_ms", self.end_hangover_ms),
            ("end_max_extension_ms", self.end_max_extension_ms),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(
                    f"{name} debe ser un número finito mayor que 0"
                )

        if self.hop_ms > self.window_ms:
            raise ValueError(
                "hop_ms debe ser menor o igual que window_ms"
            )

        for name, value in (
            ("start_padding_ms", self.start_padding_ms),
            ("end_padding_ms", self.end_padding_ms),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(
                    f"{name} debe ser un número finito mayor o igual que 0"
                )
