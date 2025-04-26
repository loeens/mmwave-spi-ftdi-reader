"""
This module provides a class for reading and parsing radar cube data
from TI mmWave radar sensors via SPI using an FTDI adapter.
It acts as an iterator yielding RadarCube objects.
"""
import sys
import numpy as np
from pyftdi.usbtools import UsbToolsError

from spi_ftdi_frame_reader import SpiFtdiFrameReader
from data_types import RadarCube1D

class RadarCubeReader:
    """
    Reads and parses radar cube data via SPI from TI mmWave radar sensors using an underlying
    SpiFtdiFrameReader. Acts as an iterator, yielding RadarCube objects frame by frame.

    Handles synchronization and data parsing from raw bytes into structured RadarCube1D objects.

    Usage:
        reader = RadarCubeReader(num_tx_antennas=2,
                                num_rx_antennas=3,
                                num_range_bins=64,
                                num_chirps_per_frame=8,
                                spi_uri="ftdi://ftdi:232h/1?latency=1")

        try:
            for cube in reader:
                print(f"Read cube with shape: {cube.data.shape}")
                # Process the radar cube data
        except RuntimeError as e:
            print(f"An error occurred during reading: {e}")
        finally:
            reader.close() # Ensure cleanup even if errors occur

    """
    def __init__(self,
                num_tx_antennas: int,
                num_rx_antennas: int,
                num_range_bins: int,
                num_chirps_per_frame: int,
                spi_uri: str = "ftdi://ftdi:232h/1?latency=1",
                spi_cs: int = 0,
                spi_freq: float = 30e6,
                spi_mode: int = 0,
                spi_max_chunk_size: int = 65024
               ):
        """
        Initializes the RadarCubeReader and the underlying SpiFtdiFrameReader.

        Args:
            num_tx_antennas (int)   : Number of enabled TX antennas.
            num_rx_antennas (int)   : Number of enabled RX antennas.
            num_range_bins (int)    : Number of range bins per chirp. Must be divisible by 4
                                      (due to underlying SPI data format).
            num_chirps_per_frame (int): Number of chirps per frame.
            spi_uri: (str)          : SPI FTDI URI (defaults to ftdi://ftdi:232h/1?latency=1)
            spi_cs: (int)           : SPI Chip Select (defaults to 0)
            spi_freq: (float)       : SPI frequency in Hz (defaults to 30e6 = 30 MHz)
            spi_mode: (int)         : SPI mode (defaults to 0)
            spi_max_chunk_size: (int): SPI max chunk size the SPI USB chip supports in one transfer,
                                            minus required overhead (defaults to 65024).
                                            Must be divisable by 4.

        Raises:
            ValueError: If input parameters are invalid or result in inconsistent dimensions
                        (e.g., not divisible by required values).
            RuntimeError: If the underlying SpiFtdiFrameReader cannot be initialized.
        """

        # Validate inputs
        if num_tx_antennas <= 0 or num_rx_antennas <= 0 or num_range_bins <= 0 or num_chirps_per_frame <= 0:
             raise ValueError("Antenna counts, range bins, and chirps per frame must be positive.")
        if num_chirps_per_frame % num_tx_antennas != 0:
            raise ValueError("num_chirps_per_frame must be divisible by num_tx_antennas.")
        # Add validation that num_range_bins is divisible by 4, consistent with SpiFtdiFrameReader
        if num_range_bins % 4 != 0:
             raise ValueError("num_range_bins must be divisible by 4.")


        # calculate derived parameters
        self.num_range_bins     = num_range_bins
        self.num_virt_antennas  = num_tx_antennas * num_rx_antennas
        self.num_doppler_chirps = num_chirps_per_frame // num_tx_antennas # Use // for integer division
        # radar cube element is stored as cmplx16ImRe_t which is equivalent to 4 Bytes (2 int16)
        self.radar_cube_n_bytes   = self.num_virt_antennas * self.num_range_bins * self.num_doppler_chirps * 4
        print(f"Expected radar cube size is set to {self.radar_cube_n_bytes} Bytes")

        # open the SpiFtdiFrameReader
        self._spi_reader: SpiFtdiFrameReader = None
        try:
            self._spi_reader = SpiFtdiFrameReader(
                frame_length = self.radar_cube_n_bytes,
                uri = spi_uri,
                cs = spi_cs,
                freq = spi_freq,
                mode = spi_mode,
                max_chunk_size = spi_max_chunk_size
            )
        except UsbToolsError as e:
            raise RuntimeError(f"No FTDI device with the supplied FTDI URI '{spi_uri}' found, make sure the device is connected.") from e
        except Exception as e:
            # ensure cleanup if reader was partially initialized
            if self._spi_reader:
                 try:
                    self.close()
                 except Exception:
                    pass
            raise RuntimeError(f"Failed to open SPI FTDI Frame Reader: {e}") from e

    def _parse_frame(self, raw_frame_bytes: bytes) -> RadarCube1D:
        """
        Parses the raw byte data into a RadarCube1D object.

        Args:
            raw_frame_bytes (bytes): The raw data received from SPI.

        Returns:
            RadarCube1D: The parsed radar cube data.

        Raises:
            ValueError: If the received data length doesn't match expected length
                        or if parsing with numpy/reshaping fails.
        """
        received_len = len(raw_frame_bytes)
        if received_len != self.radar_cube_n_bytes:
            # this should ideally be caught by the SpiFtdiFrameReader, but check defensively.
            raise ValueError(f"Data length mismatch during parsing: Expected {self.radar_cube_n_bytes} bytes, received {received_len} bytes.")

        try:
            # cast into int16, since one radar cube value is of type cmplx16ImRe_t, which is made up of two int16
            #   so two subsequent Bytes transferred are transformed into one int16 (little-endian assumed by default)
            data_int16 = np.frombuffer(raw_frame_bytes, dtype=np.int16)

            # the number of int16 values should be exactly twice the number of complex samples
            expected_int16_count = self.num_doppler_chirps * self.num_virt_antennas * self.num_range_bins * 2
            if len(data_int16) != expected_int16_count:
                 raise ValueError(f"Integer conversion mismatch: Expected {expected_int16_count} int16 values, got {len(data_int16)}.")

            # reshape the array of int16 into pairs of real, imag components
            num_complex_samples = self.num_doppler_chirps * self.num_virt_antennas * self.num_range_bins
            data_int16_reshaped = data_int16.reshape((num_complex_samples, 2))

            # convert the int16 into actual complex values (using float32 for intermediate precision)
            data_float32 = data_int16_reshaped.astype(np.float32)
            cmplx_data_flat = data_float32[:, 0] + 1j * data_float32[:, 1]

            # reshape 1D cmplx_data_flat array into MMWAVE-L-SDK data format order:
            #   Cube[chirp][antenna][range] (num_doppler_chirps, num_virt_antennas, num_range_bins)
            radar_cube_data_sdk_format = cmplx_data_flat.reshape((
                self.num_doppler_chirps,
                self.num_virt_antennas,
                self.num_range_bins
            ))

            # the radar cube is already interleaved by Rangeproc DPU. Although it arrives in SDK dimension order,
            # it is interleaved in (Range, Virtual Antenna, Doppler Chirp) order.
            # To create an appropriate RadarCube1D object with interleaved=True, it needs to be transposed
            # to match that logical order.
            # SDK order (chirp, antenna, range) -> Interleaved order (range, antenna, chirp)
            radar_cube_data_interleaved = np.transpose(radar_cube_data_sdk_format, axes=(2, 1, 0))

            # create RadarCube1D object and return it
            cube = RadarCube1D(radar_cube_data_interleaved, interleaved=True)
            return cube

        except Exception as e:
            # catch any numpy/reshaping errors during parsing
            raise ValueError(f"Failed to parse raw bytes into RadarCube: {e}") from e

    def __iter__(self):
        """
        Returns the iterator object itself for use in loops.

        Returns:
            RadarCubeReader: The instance itself.

        Raises:
             RuntimeError: If the RadarCubeReader was not initialized correctly or has been closed.
        """
        if self._spi_reader is None:
             raise RuntimeError("RadarCubeReader is not initialized or has been closed.")
        return self

    def __next__(self) -> RadarCube1D:
        """
        Reads the next raw frame from the underlying SPI reader, parses it,
        and returns a RadarCube1D object.

        This call will block until a full frame's worth of data is available from SPI.

        Returns:
            RadarCube1D: The next available radar cube.

        Raises:
            StopIteration: When the underlying SpiFtdiFrameReader indicates there are no more frames.
                           This signals the natural end of the iteration.
            RuntimeError: If an error occurs during the read (from the underlying reader)
                          or parsing process that prevents getting the next frame.
                          Also raised if the reader is used after being closed.
        """
        if self._spi_reader is None:
            raise RuntimeError("Cannot call __next__ on a closed RadarCubeReader.")

        try:
            # get the next raw frame from the underlying reader.
            # This call will block until the full frame (radar_cube_n_bytes) is read.
            raw_frame_bytes = next(self._spi_reader)

            # parse the raw bytes into a RadarCube1D object
            radar_cube = self._parse_frame(raw_frame_bytes)

            return radar_cube
        except StopIteration:
            self.close()
            raise
        except ValueError as e:
            self.close()
            raise RuntimeError(f"Error parsing frame: {e}") from e
        except Exception as e:
            self.close()
            raise RuntimeError(f"Unexpected error during radar cube iteration: {e}") from e


    def close(self) -> None:
        """
        Closes the underlying SpiFtdiFrameReader and releases resources.

        Ensures resources are cleaned up even if closing the SPI reader fails.
        Prints a message indicating the close attempt and any errors during the underlying close.
        """
        if self._spi_reader:
            print("Closing RadarCubeReader...")
            # Use try...finally to ensure self._spi_reader is set to None
            try:
                 self._spi_reader.close()
            except Exception as e:
                 print(f"Error while closing underlying SpiFtdiFrameReader: {e}", file=sys.stderr)
            finally:
                self._spi_reader = None
        else:
             print("RadarCubeReader already closed or was not initialized.")