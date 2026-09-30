"""Stateful audio playback backed by a reusable output stream."""

from dataclasses import dataclass
from enum import Enum
import threading
from typing import Callable

import numpy as np
import sounddevice as sd


class PlaybackState(Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


@dataclass(frozen=True)
class PlaybackSnapshot:
    state: PlaybackState
    position_frames: int
    position_seconds: float
    selection_start_frames: int
    selection_end_frames: int
    loop: bool


class AudioPlayer:
    def __init__(self, stream_factory: Callable | None = None):
        self._stream_factory = stream_factory or sd.OutputStream
        self._stream = None
        self._stream_format: tuple[int, int] | None = None
        self._source: np.ndarray | None = None
        self._sample_rate = 0
        self._channels = 0
        self._selection_start = 0
        self._selection_end = 0
        self._position = 0
        self._state = PlaybackState.STOPPED
        self._loop = False
        self._finishing = False
        self._finish_time = 0.0
        self._queued_frames = 0
        self._callback_time = 0.0
        self._lock = threading.Lock()

    def set_source(self, audio: np.ndarray, sample_rate: int) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")

        source = np.asarray(audio, dtype=np.float32)
        if source.ndim == 1:
            source = source[:, np.newaxis]
        elif source.ndim != 2:
            raise ValueError("audio must have shape (frames,) or (frames, channels)")
        if source.shape[1] < 1:
            raise ValueError("audio must contain at least one channel")
        source = np.ascontiguousarray(source)

        with self._lock:
            self._state = PlaybackState.STOPPED
            self._finishing = False
            self._queued_frames = 0

        new_format = (int(sample_rate), int(source.shape[1]))
        if self._stream is not None and self._stream_format != new_format:
            self._halt_stream(immediate=True)
            self._stream.close()
            self._stream = None
            self._stream_format = None

        with self._lock:
            self._source = source
            self._sample_rate = new_format[0]
            self._channels = new_format[1]
            self._selection_start = 0
            self._selection_end = 0
            self._position = 0
            self._state = PlaybackState.STOPPED
            self._finishing = False
            self._finish_time = 0.0
            self._queued_frames = 0

    def play(
        self,
        start_frame: int,
        end_frame: int,
        *,
        loop: bool | None = None,
    ) -> None:
        with self._lock:
            if self._source is None:
                raise RuntimeError("no audio source is loaded")
            frame_count = len(self._source)

        start_frame = max(0, min(int(start_frame), frame_count))
        end_frame = max(0, min(int(end_frame), frame_count))
        if start_frame >= end_frame:
            raise ValueError("playback selection must contain at least one frame")

        self._ensure_stream()

        with self._lock:
            self._selection_start = start_frame
            self._selection_end = end_frame
            self._position = start_frame
            if loop is not None:
                self._loop = bool(loop)
            self._state = PlaybackState.PLAYING
            self._finishing = False
            self._finish_time = 0.0
            self._queued_frames = 0

        if self._stream.active:
            return

        try:
            self._stream.start()
        except Exception:
            with self._lock:
                self._state = PlaybackState.STOPPED
                self._position = self._selection_start
            raise

    def pause(self) -> None:
        with self._lock:
            if self._state is not PlaybackState.PLAYING:
                return
            self._state = PlaybackState.PAUSED
            self._finishing = False

    def resume(self) -> None:
        with self._lock:
            if self._state is not PlaybackState.PAUSED:
                return
            self._state = PlaybackState.PLAYING

        self._ensure_stream()
        if self._stream.active:
            return

        try:
            self._stream.start()
        except Exception:
            with self._lock:
                self._state = PlaybackState.PAUSED
            raise

    def stop(self) -> None:
        with self._lock:
            self._state = PlaybackState.STOPPED
            self._position = self._selection_start
            self._finishing = False
            self._finish_time = 0.0
            self._queued_frames = 0

    def restart(
        self,
        start_frame: int,
        end_frame: int,
        *,
        loop: bool | None = None,
    ) -> None:
        self.play(start_frame, end_frame, loop=loop)

    def set_loop(self, enabled: bool) -> None:
        with self._lock:
            self._loop = bool(enabled)

    def snapshot(self) -> PlaybackSnapshot:
        with self._lock:
            sample_rate = self._sample_rate
            position = self._position
            state = self._state
            selection_start = self._selection_start
            selection_end = self._selection_end
            loop = self._loop
            queued_frames = self._queued_frames
            callback_time = self._callback_time
            finishing = self._finishing

        if state is PlaybackState.PLAYING and queued_frames:
            try:
                elapsed = max(0.0, self._stream.time - callback_time)
            except (AttributeError, RuntimeError, sd.PortAudioError):
                elapsed = 0.0
            elapsed_frames = round(elapsed * sample_rate)
            remaining = max(0, queued_frames - elapsed_frames)
            if loop and selection_end > selection_start:
                length = selection_end - selection_start
                position = selection_start + (
                    position - selection_start - remaining
                ) % length
            else:
                position = max(selection_start, position - remaining)

            if finishing and remaining == 0:
                with self._lock:
                    if self._finishing:
                        self._state = PlaybackState.STOPPED
                        self._position = self._selection_end
                        self._finishing = False
                        self._queued_frames = 0
                    state = self._state
                    position = self._position

        return PlaybackSnapshot(
            state=state,
            position_frames=position,
            position_seconds=(position / sample_rate if sample_rate else 0.0),
            selection_start_frames=selection_start,
            selection_end_frames=selection_end,
            loop=loop,
        )

    def close(self) -> None:
        self.stop()
        if self._stream is not None:
            self._halt_stream(immediate=True)
            self._stream.close()
            self._stream = None
            self._stream_format = None
        with self._lock:
            self._source = None
            self._sample_rate = 0
            self._channels = 0

    def _ensure_stream(self) -> None:
        if self._stream is not None:
            return

        with self._lock:
            if self._source is None:
                raise RuntimeError("no audio source is loaded")
            sample_rate = self._sample_rate
            channels = self._channels

        self._stream = self._stream_factory(
            samplerate=sample_rate,
            channels=channels,
            dtype="float32",
            callback=self._audio_callback,
        )
        self._stream_format = (sample_rate, channels)

    def _halt_stream(self, *, immediate: bool) -> None:
        stream = self._stream
        if stream is None or not stream.active:
            return
        if immediate:
            stream.abort()
        else:
            stream.stop()

    def _audio_callback(self, outdata, frames, _time_info, _status) -> None:
        outdata.fill(0)
        if self._finishing:
            try:
                finished = _time_info.currentTime >= self._finish_time
            except AttributeError:
                finished = True
            if finished:
                self._state = PlaybackState.STOPPED
                self._position = self._selection_end
                self._finishing = False
                self._queued_frames = 0
            return

        if self._state is not PlaybackState.PLAYING or self._source is None:
            return

        source = self._source
        written = 0
        completed = False
        while written < frames:
            available = self._selection_end - self._position
            if available <= 0:
                if self._loop:
                    self._position = self._selection_start
                    continue
                completed = True
                break

            count = min(available, frames - written)
            outdata[written : written + count] = source[
                self._position : self._position + count
            ]
            self._position += count
            written += count

            if self._position == self._selection_end:
                if self._loop:
                    self._position = self._selection_start
                else:
                    completed = True
                    break

        try:
            latency = max(
                0,
                round(
                    (_time_info.outputBufferDacTime - _time_info.currentTime)
                    * self._sample_rate
                ),
            )
            self._callback_time = float(_time_info.currentTime)
            self._queued_frames = latency + written
        except AttributeError:
            self._queued_frames = 0

        if completed:
            try:
                self._finish_time = (
                    _time_info.outputBufferDacTime
                    + written / self._sample_rate
                )
                self._finishing = self._state is PlaybackState.PLAYING
            except AttributeError:
                self._state = PlaybackState.STOPPED
                self._position = self._selection_end
                self._finishing = False
                self._queued_frames = 0
