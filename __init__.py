"""
mmwave_spi_reader
Unofficial SPI data reader for TI mmWave sensors via FTDI.
As of now only supports C232HM-DDHSL-0 USB-cable, TI IWRL6432BOOST and working together with the custom MCU code in this repo).
Work in progress.
"""

__version__ = "0.1.0"

from .spi_ftdi_frame_reader import SpiFtdiFrameReader
from .data_types.radar_cube import RadarCube

__all__ = ["SpiFtdiFrameReader", "RadarCube"]