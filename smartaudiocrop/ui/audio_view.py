"""Waveform, spectrogram, and trim-selection view."""

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from smartaudiocrop.audio.analysis import spectrogram


_AUTO_COLOR = "#E69F00"
_MANUAL_COLOR = "#0072B2"


class AudioView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.selection_legend = QWidget()
        legend_layout = QHBoxLayout(self.selection_legend)
        legend_layout.setContentsMargins(0, 0, 0, 0)

        auto_swatch = QFrame()
        auto_swatch.setFixedSize(28, 8)
        auto_swatch.setStyleSheet(
            f"border-top: 2px dashed {_AUTO_COLOR};"
        )
        legend_layout.addWidget(auto_swatch)
        legend_layout.addWidget(QLabel("Automatic proposal"))

        manual_swatch = QFrame()
        manual_swatch.setFixedSize(28, 8)
        manual_swatch.setStyleSheet(
            f"border-top: 2px solid {_MANUAL_COLOR};"
        )
        legend_layout.addWidget(manual_swatch)
        legend_layout.addWidget(QLabel("Manual selection"))
        legend_layout.addStretch()

        auto_pen = pg.mkPen(
            _AUTO_COLOR,
            width=2,
            style=Qt.PenStyle.DashLine,
        )
        manual_pen = pg.mkPen(_MANUAL_COLOR, width=2)
        manual_hover_pen = pg.mkPen(_MANUAL_COLOR, width=3)

        self.plot = pg.PlotWidget()
        self.waveform_curve = self.plot.plot()
        self.plot.setLabel("bottom", "Time", units="s")

        self.region = pg.LinearRegionItem(
            pen=manual_pen,
            hoverPen=manual_hover_pen,
            brush=pg.mkBrush(0, 114, 178, 45),
            hoverBrush=pg.mkBrush(0, 114, 178, 75),
        )
        self.region.setZValue(10)
        self.plot.addItem(self.region)

        self.auto_start_line = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=auto_pen,
        )
        self.auto_end_line = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=auto_pen,
        )
        self.auto_start_line.setZValue(20)
        self.auto_end_line.setZValue(20)
        self.plot.addItem(self.auto_start_line)
        self.plot.addItem(self.auto_end_line)

        self.spec_plot = pg.PlotWidget()
        self.spec_image = pg.ImageItem()
        self.spec_plot.addItem(self.spec_image)
        self.spec_plot.setXLink(self.plot)
        self.spec_plot.setLabel("bottom", "Time", units="s")
        self.spec_plot.setLabel("left", "Frequency", units="Hz")

        self.plot.getAxis("left").setWidth(60)
        self.spec_plot.getAxis("left").setWidth(60)

        self.spec_start_line = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=manual_pen,
        )
        self.spec_end_line = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=manual_pen,
        )
        self.spec_start_line.setZValue(10)
        self.spec_end_line.setZValue(10)
        self.spec_plot.addItem(self.spec_start_line)
        self.spec_plot.addItem(self.spec_end_line)

        cmap = pg.colormap.get("inferno")
        self.spec_image.setLookupTable(cmap.getLookupTable())

        layout.addWidget(self.selection_legend)
        layout.addWidget(self.plot)
        layout.addWidget(self.spec_plot)

    def connect_region_changed(self, callback):
        self.region.sigRegionChangeFinished.connect(callback)

    def clear(self):
        self.waveform_curve.setData([], [])
        self.spec_image.clear()
        self.plot.setTitle("Open a project to begin")
        self.spec_plot.setTitle("")

        self.region.hide()
        self.auto_start_line.hide()
        self.auto_end_line.hide()
        self.spec_start_line.hide()
        self.spec_end_line.hide()
        self.selection_legend.hide()

    def show_audio(
        self,
        audio: np.ndarray,
        sample_rate: int,
        duration: float,
    ):
        self.region.show()
        self.auto_start_line.show()
        self.auto_end_line.show()
        self.spec_start_line.show()
        self.spec_end_line.show()
        self.selection_legend.show()
        self.plot.setTitle("")

        time = np.arange(len(audio)) / sample_rate
        self.waveform_curve.setData(time, audio)
        self.region.setBounds([0, duration])
        self.plot.setXRange(0, duration, padding=0)

        spec, _times, _frequencies = spectrogram(
            audio,
            sample_rate,
        )
        self.spec_image.setImage(
            spec,
            autoLevels=False,
            levels=[-80, 0],
        )
        self.spec_image.setRect(
            QRectF(
                0,
                0,
                duration,
                sample_rate / 2,
            )
        )
        self.spec_plot.setXRange(0, duration, padding=0)
        self.spec_plot.setYRange(
            0,
            sample_rate / 2,
            padding=0,
        )

    def set_auto_bounds(self, start: float, end: float):
        self.auto_start_line.setPos(start)
        self.auto_end_line.setPos(end)
        self.region.setRegion([start, end])

    def set_manual_bounds(self, start: float, end: float):
        self.region.setRegion([start, end])

    def manual_bounds(self) -> tuple[float, float]:
        start, end = self.region.getRegion()
        return float(start), float(end)

    def sync_selection_markers(self):
        start, end = self.region.getRegion()
        self.spec_start_line.setPos(start)
        self.spec_end_line.setPos(end)
