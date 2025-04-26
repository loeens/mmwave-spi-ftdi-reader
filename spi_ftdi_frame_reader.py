"""
A module for reading SPI data frames from an IWRL6432BOOST board
using an FTDI USB-to-SPI adapter (like the C232HM-DDHSL-0),
synchronized via a GPIO pin.
"""
import sys
from pyftdi.spi import SpiController
from pyftdi.usbtools import UsbToolsError
from pyftdi.gpio import GpioPort


# Use GPIO pin for synchronization with the MCU. SPI_BUSY pin is 1 and goes to 0 when
#   data can be read.
# Define the FTDI ADBUS pin connected to SPI_BUSY (DCA_LP_HOST_INTR_1) which refers
#   to the GPIO_LED_BASE_ADDR Pin / PAD_AV/J10 on the IWRL6432's MCU.
#   Based on the datasheet of the C232HM-DDHSL-0, the grey wire is connected
#   to ADBUS4 (pin index 4) on the FTDI chip.
SPI_BUSY_ADBUS_PIN_INDEX    = 4
SPI_BUSY_PIN_MASK           = (1 << SPI_BUSY_ADBUS_PIN_INDEX)

class SpiFtdiFrameReader:
    """
    A SPI data reader for reading data from a IWRL6432BOOST via C232HM-DDHSL-0 FTDI USB cable
    to a host computer. It uses the SPI_BUSY GPIO pin on the IWRL6432BOOST for synchronization.
    Repeatedly reads frame_length number of Bytes in chunks, each chunk is read when SPI_BUSY
    changes to low state.
    """
    def __init__(self,
                frame_length: int,
                uri: str = "ftdi://ftdi:232h/1?latency=1",
                cs: int = 0,
                freq: float = 30e6,
                mode: int = 0,
                max_chunk_size: int = 65024):
        """
        Args:
            frame_length (int)  : Number of bytes that each call to `__next__()` will return. Must match the frame length
                                    set in the MCU (radar cube size or ADC samples size of one frame). Must be divisible by 4.
            uri: (str)          : SPI FTDI URI (defaults to ftdi://ftdi:232h/1?latency=1)
            cs: (int)           : SPI Chip Select (defaults to 0)
            freq: (float)       : SPI frequency in Hz (defaults to 30e6 = 30 MHz)
            mode: (int)         : SPI mode (defaults to 0)
            max_chunk_size: (int): SPI max chunk size the SPI USB chip supports in one transfer,
                                    minus required overhead (defaults to 65024).
                                    Must be divisable by 4.

        Raises:
            ValueError: If frame_length or max_chunk_size are not divisible by 4.
            UsbToolsError: If PyFtdi is unable to open the FTDI device with the supplied URI.
            RuntimeError: If FTDI GPIO cannot be initialized
        """
        # ensure both frame_length and max_chunk_size are divisible by 4
        if frame_length % 4 != 0:
             raise ValueError("frame_length must be divisible by 4 (datasize in Bytes of SPI transaction).")
        if max_chunk_size % 4 != 0:
            raise ValueError("max_chunk_size must be divisible by 4 (datasize in Bytes of SPI transaction).")

        self.frame_length   = frame_length
        self.max_chunk_size = max_chunk_size
        self._spi           = SpiController(turbo=True)
        self._gpio_port: GpioPort = None
        self._port          = None

        try:
            # configure SPI controller and get the SPI port
            self._spi.configure(uri)
            self._port = self._spi.get_port(cs=cs, freq=freq, mode=mode)

            # configure GPIO port of the FTDI device used for reading the SPI_BUSY pin (0x00 = input)
            self._gpio_port = self._spi.get_gpio()
            self._gpio_port.set_direction(SPI_BUSY_PIN_MASK, 0x00)

        except UsbToolsError as e:
            e.args = (f"SpiFtdiFrameReader is unable to open the provided FTDI URI via PyFtdi'{uri}': {e}",)
            raise

        except Exception as e:
            # catch any other configuration errors
            if self._spi:
                self._spi.terminate()
            raise RuntimeError(f"Failed to configure FTDI or GPIO: {e}") from e


    def __iter__(self):
        """Return the iterator object itself."""
        return self

    def __next__(self) -> bytes:
        """
        Reads the next frame synchronized by the SPI_busy pin.
        Waits for the SPI_busy pin (ADBUS4) to go low before reading a chunk.

        Returns:
            bytes: The full frame data of length self.frame_length.

        Raises:
            StopIteration: If an error occurs during reading that prevents further iteration.
        """
        # read the entire frame, splitting into chunks if the frame_length exceeds max_chunk_size
        remaining_bytes = self.frame_length
        frame_data = bytearray()

        try:
            while remaining_bytes > 0:
                # poll _gpio_port to check if it has gone low, indicating that a chunk of data can be read
                while True:
                    try:
                        gpio_state = self._gpio_port.read()
                        if (gpio_state & SPI_BUSY_PIN_MASK) == 0:
                            # pin is low, data is ready to be read
                            break
                    except Exception as e:
                        raise StopIteration(f"Error during busy wait for SPI_BUSY signal: {e}") from e

                try:
                    # once the SPI_BUSY signal is low, read the expected chunk length
                    chunk_size = min(remaining_bytes, self.max_chunk_size)
                    # ensure port is available
                    if self._port is None:
                        raise StopIteration("SPI port not initialized or was closed prematurely.")

                    chunk = self._port.read(chunk_size)

                    if not chunk:
                        raise StopIteration(f"Error: No data received after SPI_BUSY signal changed to low, expected {chunk_size} bytes.")

                    # verify the received chunk size matches the requested size
                    if len(chunk) != chunk_size:
                         raise StopIteration(f"Error: Received chunk size mismatch. Expected {chunk_size} bytes, but got {len(chunk)}.")

                except Exception as e:
                    raise StopIteration(f"Error during SPI chunk read: {e}") from e

                # Each set of 4 Byte arrives in Byte order [Byte_D, Byte_C, Byte_B, Byte_A], so order needs to be switched
                #   before adding it to frame_data.
                #   (It is guaranteed that chunk_size is a multiple of 4 because max_chunk_size
                #   and frame_length are validated in __init__.)
                for i in range(0, chunk_size, 4):
                    byte_D = chunk[i]
                    byte_C = chunk[i + 1]
                    byte_B = chunk[i + 2]
                    byte_A = chunk[i + 3]

                    frame_data.append(byte_A)
                    frame_data.append(byte_B)
                    frame_data.append(byte_C)
                    frame_data.append(byte_D)

                remaining_bytes -= chunk_size
        except Exception as e:
            # Any other unexpected error during frame read process stops iteration
             raise StopIteration(f"An unexpected error occurred during frame reading: {e}") from e

        # return the full frame as immutable bytes
        return frame_data

    def close(self) -> None:
        """
        Gracefully terminates the FTDI controller and cleans up resources.
        """
        try:
            if self._spi:
                 self._spi.terminate()
        finally:
            self._gpio_port = None
            self._port      = None
            self._spi       = None