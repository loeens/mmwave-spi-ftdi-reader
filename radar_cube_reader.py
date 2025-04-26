from spi_ftdi_frame_reader import SpiFtdiFrameReader
from data_types import RadarCube1D

from pyftdi.usbtools import UsbToolsError
import time
import numpy as np


class RadarCubeReader:
    """
    Reads and parses radar cube data via SPI from TI mmWave radar sensors using an underlying 
    SpiFtdiFrameReader. Acts as an iterator, yielding RadarCube objects.

    Usage:
        reader = RadarCubeReader(num_tx_antennas=2,
                        num_rx_antennas=3,
                        num_range_bins=64,
                        num_chirps_per_frame=8,
                        spi_uri="ftdi://ftdi:232h/1?latency=1")

        for cube in reader:
            print(cube.data)

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
        Args:
            num_tx_antennas (int)   : Number of enabled TX antennas.
            num_rx_antennas (int)   : Number of enabled RX antennas.
            n_rangebins (int)       : Number of range bins per chirp.
            num_chirps_per_frame (int): Number of chirps per frame.
            spi_uri: (str)          : SPI FTDI URI (defaults to ftdi://ftdi:232h/1?latency=1)
            spi_cs: (int)           : SPI Chip Select (defaults to 0)
            spi_freq: (float)       : SPI frequency in Hz (defaults to 30e6 = 30 MHz)
            spi_mode: (int)         : SPI mode (defaults to 0)
            spi_max_chunk_size: (int): SPI max chunk size the SPI USB chip supports in one transfer, 
                                            minus required overhead (defaults to 65024). 
                                            Must be divisable by 4.
        Raises:
            ValueError: If parameters result in non-integer dimensions or invalid configurations.
            RuntimeError: If the underlying SpiFtdiFrameReader cannot be initialized.                
        """

        # validate inputs, TODO: implement full parameter sanity checks
        if num_tx_antennas <= 0 or num_rx_antennas <= 0 or num_range_bins <= 0 or num_chirps_per_frame <= 0:
             raise ValueError("Antenna counts, range bins, and chirps per frame must be positive.")
        if num_chirps_per_frame % num_tx_antennas != 0:
            raise ValueError("num_chirps_per_frame must be divisible by num_tx_antennas.")

        # calculate actually important parameters from the provided parameters
        self.num_range_bins     = num_range_bins
        self.num_virt_antennas  = int(num_tx_antennas * num_rx_antennas)
        self.num_doppler_chirps = int(num_chirps_per_frame / num_tx_antennas)
        # radar cube elemt is stored as cmplx16ReIm_t which is equivalent to 4 Bytes 
        self.radar_cube_n_bytes   = int(self.num_virt_antennas * self.num_range_bins * self.num_doppler_chirps * 4)
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
            raise RuntimeError(f"No FTDI device with the supplied FTDI URI {spi_uri} found, make sure the device is connected.") from e
        except Exception as e:
            if self._spi_reader:
                self.close()
            raise RuntimeError(f"Failed to open SPI FTDI Frame Reader: {e}") from e
    
    def _parse_frame(self, raw_frame_bytes: bytes) -> RadarCube1D:
        """
        Parses the raw byte data into a RadarCube1D object.

        Args:
            raw_frame_bytes (bytes): The raw data received from SPI.

        Returns:
            RadarCube: The parsed radar cube data.

        Raises:
            ValueError: If the received data length doesn't match expected length
                        or if parsing fails.
        """
        received_len = len(raw_frame_bytes)
        if received_len != self.radar_cube_n_bytes:
            raise ValueError(f"Data length mismatch: Expected {self.radar_cube_n_bytes} bytes, received {received_len} bytes.")

        try:
            # cast into int16, since one radar cube value is of type cmplx16ImRe_t, which is made up of two int16
            #   so two subsequent Bytes transferred are transformed into one int16
            data_int16 = np.frombuffer(raw_frame_bytes, dtype=np.int16)

            # reshape the array of int16 into pairs of real, imag components
            num_complex_samples = self.num_doppler_chirps * self.num_virt_antennas * self.num_range_bins
            data_int16_reshaped = data_int16.reshape((num_complex_samples, 2))

            # convert the int16 into actual complex values
            data_float32 = data_int16_reshaped.astype(np.float32)
            cmplx_data_flat = data_float32[:, 0] + 1j * data_float32[:, 1]

            # reshape 1D cmplx_data_flat array into RadarCube SDK data format
            #   MMWAVE-L-SDK format is Cube[chirp][antenna][range]
            radar_cube_data_sdk_format = cmplx_data_flat.reshape((
                self.num_doppler_chirps,
                self.num_virt_antennas,
                self.num_range_bins
            ))

            # the radar cube is already interleaved by Rangeproc DPU, although it isnn't in the interleaved
            #   dimension order ("rangebin", "virt_antenna", "doppler_chirp")
            #   therefore it needs to be reshaped in order to create an appropiate RadarCube1D object
            radar_cube_data_interleaved = np.transpose(radar_cube_data_sdk_format, axes=(2, 1, 0))

            # create RadarCube1D object and return it
            cube = RadarCube1D(radar_cube_data_interleaved, interleaved=True)
            return cube

        except Exception as e:
            raise ValueError(f"Failed to parse raw bytes into RadarCube: {e}") from e
    
    def __iter__(self):
        """
        Returns the iterator object itself.
        """
        if self._spi_reader is None:
             raise RuntimeError("RadarCubeReader is not initialized or has been closed.")
        return self

    def __next__(self) -> RadarCube1D:
        """
        Reads the next raw frame from the SPI reader, parses it, and returns a RadarCube object.

        Returns:
            RadarCube: The next available radar cube.

        Raises:
            StopIteration: If the underlying SpiFtdiFrameReader stops or an error occurs during read/parse.
            RuntimeError: If the reader is used after being closed.
        """
        if self._spi_reader is None:
            raise RuntimeError("RadarCubeReader has been closed.")
        
        try:
            # get the next raw frame from the underlying reader
            # this call will block until SPI_BUSY goes low and data is read
            raw_frame_bytes = next(self._spi_reader) # Equivalent to self._spi_reader.__next__()

            # parse the raw bytes into a RadarCube object
            radar_cube = self._parse_frame(raw_frame_bytes)

            return radar_cube
        except StopIteration:
            # propagate StopIteration from the underlying reader
            self.close()
            raise StopIteration
        except ValueError as e:
            # error during parsing
            print(f"Error parsing frame: {e}")
            self.close()
            raise StopIteration
        except Exception as e:
            # catch other potential errors
            print(f"Unexpected error during iteration: {e}")
            self.close()
            raise StopIteration

    def close(self) -> None:
        """
        Closes the underlying SpiFtdiFrameReader and releases resources.
        """
        if self._spi_reader:
            print("Closing RadarCubeReader...")
            try:
                self._spi_reader.close()
            except Exception as e:
                 print(f"Error while closing SpiFtdiFrameReader: {e}")
            finally:
                self._spi_reader = None
        else:
             print("RadarCubeReader already closed or was not initialized.")