# SmartAudioCrop

SmartAudioCrop is a desktop application for reviewing proposed trim boundaries in WAV recordings. It displays each recording as a waveform and spectrogram, estimates the useful audio interval, lets the user correct that interval manually, and stores the result in the project directory.

The application is an annotation tool. It does not modify, overwrite, or export cropped audio files.

## Capabilities

- Open a directory as an audio project.
- Discover top-level `.wav` files with case-insensitive extensions.
- Navigate recordings in sorted filename order.
- Display synchronized waveform and spectrogram views.
- Estimate start and end boundaries with an adaptive RMS detector.
- Display automatic boundaries separately from the editable selection.
- Adjust the manual selection directly in the waveform.
- Play, pause, resume, stop, restart, or loop the selected audio interval.
- Follow playback with a synchronized cursor in the waveform and spectrogram.
- Reset the manual selection to the current automatic proposal.
- Configure detector thresholds, timing, padding, and end hysteresis.
- Save annotations automatically when navigating, changing projects, or closing the application.
- Restore a previously saved manual selection when a recording is opened again.
- Show the current file, review status, and overall project progress.
- Export saved project annotations to CSV for external analysis.

## Current Scope

SmartAudioCrop currently:

- Supports WAV files only.
- Searches only the selected directory, not its subdirectories.
- Processes one recording at a time in the desktop interface.
- Uses the system's default audio output device.
- Stores detector settings only for the current application session.
- Stores annotations in SQLite and exports them to CSV on demand.
- Records trim boundaries but does not create cropped audio files.

## Requirements

- Python 3.14 or newer
- A working audio output device for playback
- [uv](https://docs.astral.sh/uv/) for the recommended environment setup

The Python dependencies include PySide6, pyqtgraph, NumPy, SciPy, SoundFile, and SoundDevice. Depending on the operating system, SoundDevice may also require a system PortAudio installation.

## Installation

Clone the repository and create the locked environment:

```bash
uv sync
```

## Running the Application

Run the package entry point:

```bash
uv run python -m smartaudiocrop
```

The compatibility launcher is also available:

```bash
uv run python main.py
```

## Project Directory

A project is any directory containing at least one WAV file at its top level:

```text
recording-project/
├── take-001.wav
├── take-002.wav
└── take-003.WAV
```

Open it from **File > New Project...** and select the directory. Files in nested directories are ignored.

When the project is opened, SmartAudioCrop creates or reuses this file:

```text
recording-project/annotations.db
```

The original WAV files are only read. They are not changed by the application.

## Typical Workflow

1. Start SmartAudioCrop.
2. Select **File > New Project...**.
3. Choose a directory containing WAV recordings.
4. Review the automatic start and end markers.
5. Drag the editable waveform region to correct the selection when necessary.
6. Press **Space** or select **Play** to listen to the selected interval.
7. Use **Pause**, **Stop**, **Restart**, or **Loop** while validating its boundaries.
8. Press **Enter** to save the annotation and continue to the next recording, or use the navigation controls. The current annotation is saved automatically.
9. Select **File > Export Annotations...** to export the annotations already saved in SQLite.
10. Close the application when finished. The active annotation is saved before shutdown.

A dashed amber line marks each automatic detector boundary. Solid blue lines and a translucent blue region show the editable manual selection; the same solid blue boundaries are mirrored in the spectrogram.

A recording starts as `NOT_VIEWED` and becomes `VIEWED` when it is saved while navigating away, changing projects, or closing the application. The footer shows the current file position and the number of reviewed recordings in the project.

## Controls

| Action | Button or shortcut |
| --- | --- |
| Open a project | **File > New Project...** or the platform Open shortcut |
| Export saved annotations | **File > Export Annotations...** |
| Previous recording | **Prev** or **Left Arrow** |
| Next recording | **Next** or **Right Arrow** |
| Save annotation and continue | **Enter** or **Numpad Enter** |
| Play or pause selected interval | **Play**/**Pause** or **Space** |
| Resume paused playback | **Resume** or **Space** |
| Stop playback | **Stop** |
| Restart from current selection | **Restart** |
| Repeat current playback selection | **Loop** |
| Reset manual selection | **Reset**, **R**, or **Trim > Reset manual selection** |
| Move start boundary by 5 ms | **,** or **.** |
| Move start boundary by 25 ms | **Shift+,** or **Shift+.** |
| Move end boundary by 5 ms | **Ctrl+,** or **Ctrl+.** |
| Move end boundary by 25 ms | **Ctrl+Shift+,** or **Ctrl+Shift+.** |
| Run the detector again | **Trim > Run detector** |
| Configure the detector | **Trim > Settings...** |
| Exit | **File > Exit** |

Navigation buttons are disabled automatically at the first and last recordings.
At the last recording, **Enter** saves the annotation without navigating away.

Playback captures the current manual boundaries when **Play** or **Restart** is
pressed. Moving the boundaries during playback or pause does not change the
active interval; the new boundaries apply to the next **Play** or **Restart**.
Changing files stops playback and clears the previous playback position.

## Trim Detection

The detector estimates the noise floor from frame-level RMS values and uses separate thresholds for confirming and sustaining activity. This hysteresis helps preserve quieter endings while avoiding premature starts.

The available settings are:

| Setting | Default | Purpose |
| --- | ---: | --- |
| Noise percentile | 10% | Percentile used to estimate the noise floor |
| Start SNR | 8 dB | Margin above the noise floor required to confirm activity |
| End SNR | 2 dB | Lower margin used to sustain activity near the end |
| Window | 20 ms | RMS analysis window length |
| Hop | 5 ms | Distance between consecutive analysis windows |
| Start minimum activity | 30 ms | Continuous activity required to accept a start |
| End minimum activity | 20 ms | Activity required to confirm the ending region |
| Start padding | 50 ms | Audio retained before the detected start |
| End padding | 150 ms | Audio retained after the detected end |
| End hangover | 100 ms | Continuous inactivity required to end the utterance |
| Maximum end extension | 350 ms | Maximum extension after the last confirmed activity |

Accepting new settings reruns the detector for the currently open recording. Canceling the dialog leaves the configuration and current selection unchanged.

## Annotation Data

Each WAV filename has at most one row in `annotations.db`. Saving the same filename updates its existing row.

The stored data includes:

- Filename
- Audio duration
- Sample rate
- Automatic start and end times
- Manual start and end times
- Manual-to-automatic start and end differences in milliseconds
- Review status (`NOT_VIEWED` or `VIEWED`)
- Whether the manual boundaries differ from the automatic proposal (`is_modified`)
- Last update timestamp

All boundary values other than the millisecond differences are stored in seconds. Annotation persistence is project-local: each selected project directory has its own database.

`is_modified` is false when both manual boundaries match the automatic proposal within one microsecond. Resetting the manual selection to the automatic proposal therefore clears the modified state on the next save. Progress only counts `VIEWED` rows whose filenames still exist in the current project.

## Annotation Export

Use **File > Export Annotations...** after opening a project to create a CSV containing every annotation currently stored in the project's `annotations.db`. Unsaved changes to the visible selection are not persisted automatically by exporting and therefore are not included.

Rows are ordered by filename and contain:

- `filename`
- `duration`
- `sample_rate`
- `auto_start`
- `auto_end`
- `manual_start`
- `manual_end`
- `delta_start_ms`
- `delta_end_ms`
- `reviewed` (`true` when the stored status is `VIEWED`)
- `updated_at`

The four boundary columns and `duration` use seconds. Delta columns use milliseconds. Exporting reads SQLite without modifying annotations or WAV files. If the database contains no annotations, the application reports it without creating an empty export.

## Development Checks

Run the regression and architecture tests with:

```bash
uv run python -m unittest discover -s tests -v
```

The suite covers annotation and review-state persistence, audio loading, spectrogram output, project discovery and navigation, project progress, project switching, initial UI state, and dependency boundaries.

## Source Layout

```text
smartaudiocrop/
├── annotations/   # SQLite annotation persistence
├── audio/         # Loading, playback, and spectrogram analysis
├── project/       # Active project state and navigation
├── trim/          # Detector configuration and algorithm
└── ui/            # Qt windows, dialogs, and audio visualization
```

`main.py` remains a compatibility launcher. The primary package entry point is `smartaudiocrop/__main__.py`.
