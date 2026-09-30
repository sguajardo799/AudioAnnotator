"""Detector de límites temporales para recorte automático."""

from dataclasses import dataclass

import numpy as np

from .config import TrimConfig


@dataclass(frozen=True)
class TrimBounds:
    """
    Intervalo [start, stop) que debe conservarse.

    Los valores están expresados en muestras, no segundos.
    """

    start: int
    stop: int


def _milliseconds_to_samples(
    milliseconds: float,
    samplerate: int,
) -> int:
    """Convierte milisegundos a número de muestras."""

    return max(
        1,
        int(round(milliseconds * samplerate / 1000.0)),
    )


def _scaled_rms_dbfs(
    values: np.ndarray,
    axis: int,
) -> np.ndarray:
    """
    Calcula RMS en dBFS.

    Se conserva la implementación del detector original.
    """

    peaks = np.max(
        np.abs(values),
        axis=axis,
    )

    normalized = np.divide(
        values,
        np.expand_dims(peaks, axis=axis),
        out=np.zeros_like(values),
        where=np.expand_dims(peaks, axis=axis) != 0,
    )

    normalized_rms = np.sqrt(
        np.mean(
            np.square(normalized),
            axis=axis,
        )
    )

    levels_dbfs = np.full(
        peaks.shape,
        -np.inf,
        dtype=np.float64,
    )

    nonzero = peaks > 0

    levels_dbfs[nonzero] = 20.0 * (
        np.log10(peaks[nonzero])
        + np.log10(normalized_rms[nonzero])
    )

    return levels_dbfs


def _frame_rms_dbfs(
    audio: np.ndarray,
    window_samples: int,
    hop_samples: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Calcula el nivel RMS de cada frame.

    Devuelve:
        levels_dbfs
        frame_starts
        frame_stops
    """

    frame_starts = np.arange(
        0,
        len(audio),
        hop_samples,
        dtype=np.int64,
    )

    frame_stops = np.minimum(
        frame_starts + window_samples,
        len(audio),
    )

    levels_dbfs = np.full(
        (len(frame_starts), audio.shape[1]),
        -np.inf,
        dtype=np.float64,
    )

    # Frames que poseen exactamente window_samples muestras.
    full_frame_indices = np.flatnonzero(
        frame_stops - frame_starts == window_samples
    )

    if len(full_frame_indices):
        windows = np.lib.stride_tricks.sliding_window_view(
            audio,
            window_shape=window_samples,
            axis=0,
        )

        elements_per_frame = (
            window_samples * audio.shape[1]
        )

        chunk_size = max(
            1,
            1_000_000 // elements_per_frame,
        )

        for chunk_start in range(
            0,
            len(full_frame_indices),
            chunk_size,
        ):
            indices = full_frame_indices[
                chunk_start : chunk_start + chunk_size
            ]

            frames = np.moveaxis(
                windows[frame_starts[indices]],
                -1,
                1,
            )

            levels_dbfs[indices] = _scaled_rms_dbfs(
                frames,
                axis=1,
            )

    # Último frame si no alcanza el tamaño completo.
    partial_frame_indices = np.flatnonzero(
        frame_stops - frame_starts < window_samples
    )

    for index in partial_frame_indices:
        frame = audio[
            frame_starts[index] : frame_stops[index]
        ]

        levels_dbfs[index] = _scaled_rms_dbfs(
            frame,
            axis=0,
        )

    return (
        levels_dbfs,
        frame_starts,
        frame_stops,
    )


def _qualifying_runs(
    active_frames: np.ndarray,
    frame_starts: np.ndarray,
    frame_stops: np.ndarray,
    minimum_samples: int,
    overlap_samples: int,
) -> list[tuple[int, int]]:
    """
    Busca secuencias consecutivas de frames activos
    suficientemente largas.
    """

    padded = np.pad(
        active_frames.astype(np.int8),
        (1, 1),
    )

    transitions = np.diff(padded)

    starts = np.flatnonzero(transitions == 1)
    stops = np.flatnonzero(transitions == -1)

    qualifying = []

    audio_length = int(frame_stops[-1])

    for start, stop in zip(starts, stops):
        first_start = int(
            frame_starts[start]
        )

        last_stop = int(
            frame_stops[stop - 1]
        )

        boundary_expansion = (
            min(overlap_samples, first_start)
            + min(
                overlap_samples,
                audio_length - last_stop,
            )
        )

        if (
            last_stop
            - first_start
            - boundary_expansion
            >= minimum_samples
        ):
            qualifying.append(
                (int(start), int(stop))
            )

    return qualifying


def _active_frames(
    levels_dbfs: np.ndarray,
    threshold_dbfs: float,
) -> np.ndarray:
    """Determina qué frames superan el threshold."""

    return np.any(
        np.isfinite(levels_dbfs)
        & (levels_dbfs >= threshold_dbfs),
        axis=1,
    )


def _end_hysteresis_stop(
    confirming_runs: list[tuple[int, int]],
    sustaining_frames: np.ndarray,
    frame_starts: np.ndarray,
    frame_stops: np.ndarray,
    hop_samples: int,
    hangover_samples: int,
    max_extension_samples: int,
) -> int | None:
    """
    Extiende el final mientras continúe existiendo
    actividad sobre el threshold más permisivo.
    """

    if not confirming_runs:
        return None

    last_confirmed_frame = (
        confirming_runs[-1][1] - 1
    )

    last_active_stop = int(
        frame_stops[last_confirmed_frame]
    )

    max_stop = min(
        int(frame_stops[-1]),
        last_active_stop + max_extension_samples,
    )

    inactive_samples = 0

    for index in range(
        last_confirmed_frame + 1,
        len(sustaining_frames),
    ):
        frame_start = int(
            frame_starts[index]
        )

        if frame_start >= max_stop:
            return max_stop

        if sustaining_frames[index]:
            last_active_stop = min(
                int(frame_stops[index]),
                max_stop,
            )

            inactive_samples = 0

        else:
            inactive_samples += min(
                hop_samples,
                max_stop - frame_start,
            )

            if inactive_samples >= hangover_samples:
                return last_active_stop

        if int(frame_stops[index]) >= max_stop:
            return max_stop

    return int(frame_stops[-1])


def detect_trim_bounds(
    audio: np.ndarray,
    samplerate: int,
    config: TrimConfig,
) -> TrimBounds | None:
    """
    Detecta los límites automáticos del utterance.

    IMPORTANTE:
    esta función NO modifica ni escribe el audio.

    Devuelve límites expresados en muestras.
    """

    config.validate()

    if samplerate <= 0:
        raise ValueError(
            "samplerate debe ser mayor que 0"
        )

    audio = np.asarray(
        audio,
        dtype=np.float64,
    )

    # La implementación interna trabaja siempre como:
    #
    # [samples, channels]
    #
    # Incluso si la entrada es mono.
    if audio.ndim == 1:
        audio = audio[:, np.newaxis]

    if audio.ndim != 2:
        raise ValueError(
            "audio debe tener forma "
            "(muestras,) o (muestras, canales)"
        )

    if audio.shape[1] == 0:
        raise ValueError(
            "audio debe contener al menos un canal"
        )

    if len(audio) == 0:
        return None

    if not np.all(np.isfinite(audio)):
        raise ValueError(
            "audio contiene muestras no finitas"
        )

    # ---------------------------------------------------------
    # Configuración temporal -> muestras
    # ---------------------------------------------------------

    window_samples = _milliseconds_to_samples(
        config.window_ms,
        samplerate,
    )

    hop_samples = _milliseconds_to_samples(
        config.hop_ms,
        samplerate,
    )

    start_minimum_samples = _milliseconds_to_samples(
        config.start_min_active_ms,
        samplerate,
    )

    end_minimum_samples = _milliseconds_to_samples(
        config.end_min_active_ms,
        samplerate,
    )

    hangover_samples = _milliseconds_to_samples(
        config.end_hangover_ms,
        samplerate,
    )

    max_extension_samples = _milliseconds_to_samples(
        config.end_max_extension_ms,
        samplerate,
    )

    overlap_samples = max(
        0,
        window_samples - hop_samples,
    )

    start_padding_samples = int(
        round(
            config.start_padding_ms
            * samplerate
            / 1000.0
        )
    )

    end_padding_samples = int(
        round(
            config.end_padding_ms
            * samplerate
            / 1000.0
        )
    )

    # ---------------------------------------------------------
    # Análisis RMS
    # ---------------------------------------------------------

    (
        levels_dbfs,
        frame_starts,
        frame_stops,
    ) = _frame_rms_dbfs(
        audio,
        window_samples,
        hop_samples,
    )

    # Un único nivel por frame.
    frame_levels_dbfs = np.max(
        levels_dbfs,
        axis=1,
    )

    # Piso de ruido adaptativo.
    noise_floor_dbfs = float(
        np.percentile(
            frame_levels_dbfs,
            config.noise_percentile,
            method="lower",
        )
    )

    # Threshold alto:
    # confirma que efectivamente comenzó actividad.
    start_threshold_dbfs = (
        noise_floor_dbfs
        + config.start_snr_db
    )

    # Threshold bajo:
    # permite conservar componentes débiles al final.
    end_threshold_dbfs = (
        noise_floor_dbfs
        + config.end_snr_db
    )

    confirming_frames = _active_frames(
        levels_dbfs,
        start_threshold_dbfs,
    )

    # ---------------------------------------------------------
    # Detectar comienzo
    # ---------------------------------------------------------

    start_runs = _qualifying_runs(
        confirming_frames,
        frame_starts,
        frame_stops,
        start_minimum_samples,
        overlap_samples,
    )

    # ---------------------------------------------------------
    # Detectar final
    # ---------------------------------------------------------

    confirming_end_runs = _qualifying_runs(
        confirming_frames,
        frame_starts,
        frame_stops,
        end_minimum_samples,
        overlap_samples,
    )

    end_stop = _end_hysteresis_stop(
        confirming_end_runs,
        _active_frames(
            levels_dbfs,
            end_threshold_dbfs,
        ),
        frame_starts,
        frame_stops,
        hop_samples,
        hangover_samples,
        max_extension_samples,
    )

    if not start_runs or end_stop is None:
        return None

    # ---------------------------------------------------------
    # Convertir detecciones a límites finales
    # ---------------------------------------------------------

    first_active_frame = start_runs[0][0]

    start = max(
        0,
        int(frame_starts[first_active_frame])
        - start_padding_samples,
    )

    stop = min(
        len(audio),
        end_stop + end_padding_samples,
    )

    if start >= stop:
        return None

    return TrimBounds(
        start=start,
        stop=stop,
    )

@dataclass(frozen=True)
class TrimTimes:
    """
    Límites temporales expresados en segundos.

    Esta representación es más cómoda para la GUI.
    """

    start: float
    end: float


def estimate_trim(
    audio: np.ndarray,
    samplerate: int,
    config: TrimConfig,
) -> TrimTimes | None:
    """
    Interfaz de alto nivel utilizada por la aplicación.

    Internamente utiliza detect_trim_bounds(), que trabaja
    en muestras, pero devuelve tiempos en segundos.
    """

    bounds = detect_trim_bounds(
        audio,
        samplerate,
        config,
    )

    if bounds is None:
        return None

    return TrimTimes(
        start=bounds.start / samplerate,
        end=bounds.stop / samplerate,
    )