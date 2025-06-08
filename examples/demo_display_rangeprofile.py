"""
Demo script demonstrating how to use RadarCubeReader to stream radar cubes
via SPI, extract a range profile, and plot it live using matplotlib animation.

Make sure your FTDI device is connected and the IWRL6432BOOST is powered on
and configured to output radar cube data via SPI. Adjust the spi_uri
and radar parameters as needed.
"""

import time
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import threading
import sys

from mmwave_spi_ftdi_reader import RadarCubeReader
from mmwave_spi_ftdi_reader.data_types import RadarCube1D

# radar parameters
N_RANGE_BINS = 64
N_TX_ANTENNAS = 2
N_RX_ANTENNAS = 3
NUM_CHIRPS_PER_FRAME = 128 # total chirps per frame (num chirps per burst * num bursts per frame)

# SPI configuration
SPI_URI = "ftdi://ftdi:232h/1?latency=1"
SPI_CS = 0
SPI_FREQ = 30e6
SPI_MODE = 0
SPI_MAX_CHUNK_SIZE = 65280 # Must be divisible by 4

# physics constants for range calculation
C = 3e8                     # speed of light (m/s)
BANDWIDTH = 2700e6          # radar bandwidth in Hz
RANGE_RESOLUTION = C / (2 * BANDWIDTH)  # range resolution (meters per bin)

# create dict that holds the latest processed data and metadata from the SPI thread
shared_data_state = {
    "frame": None,
    "timestamp": None,
    "prev_timestamp": None,
    "frame_count": 0
}
frame_lock = threading.Lock()

# timestamp when the data streaming started (used for overall frame rate calculation)
start_time = None

def spi_read_thread(reader: RadarCubeReader):
    """
    Background thread that continuously reads radar cubes from the reader
    """
    global shared_data_state
    global start_time

    start_time = time.time()

    try:
        # iterate over the radar cubes provided by the reader
        for cube in reader:
            current_frame_timestamp = time.time()

            try:
                # only display first range profile in radar cube for demo purposes
                latest_frame_data = cube.data.isel(virt_antenna=0, doppler_chirp=0).values
            except Exception as e:
                print(f"Error slicing radar cube in thread: {e}")
                continue

            with frame_lock:
                # update shared vars
                shared_data_state["prev_timestamp"] = shared_data_state["timestamp"]
                shared_data_state["timestamp"] = current_frame_timestamp

                shared_data_state["frame"] = latest_frame_data
                shared_data_state["frame_count"] += 1

    except Exception as e:
        print(f"Error in SPI read thread: {e}")
    finally:
        print("SPI read thread finished.")


# set up the figure and axes
fig, (ax_fft, ax_time) = plt.subplots(2, 1, figsize=(10, 8))
plt.tight_layout(rect=[0, 0, 1, 0.95], pad=3.0)

# x-axis data for plotting
x_axis_fft = np.arange(N_RANGE_BINS) * RANGE_RESOLUTION
x_axis_time = np.arange(N_RANGE_BINS)

# initialize plot lines
line_fft, = ax_fft.plot([], [], lw=2)
line_real, = ax_time.plot([], [], lw=2, color='blue', label='Real')
line_imag, = ax_time.plot([], [], lw=2, color='red', label='Imaginary')

# set initial plot limits and labels
ax_fft.set_xlim(0, x_axis_fft[-1])
ax_fft.set_ylim(0, 5000) 
ax_fft.set_xlabel("Range (meters)")
ax_fft.set_ylabel("Magnitude")
ax_fft.set_title("Range FFT Magnitude")

ax_time.set_xlim(0, N_RANGE_BINS - 1)
ax_time.set_ylim(-3000, 3000)
ax_time.set_xlabel("Range bin index")
ax_time.set_ylabel("Amplitude Value")
ax_time.set_title("Range FFT Real & Imaginary Components")
ax_time.legend(loc='upper right')

# add text elements for displaying frame rate metrics
frame_rate_text = ax_fft.text(0.02, 0.98, '', transform=ax_fft.transAxes, ha='left', va='top', fontsize=10, bbox=dict(boxstyle='round,pad=0.5', fc='wheat', alpha=0.5))
time_between_frames_text = ax_fft.text(0.98, 0.98, '', transform=ax_fft.transAxes, ha='right', va='top', fontsize=10, bbox=dict(boxstyle='round,pad=0.5', fc='wheat', alpha=0.5))


def init_plot():
    line_fft.set_data([], [])
    line_real.set_data([], [])
    line_imag.set_data([], [])
    frame_rate_text.set_text('')
    time_between_frames_text.set_text('')
    return line_fft, line_real, line_imag, frame_rate_text, time_between_frames_text


def update_plot(frame):
    """
    Updates the plot with the latest frame data and metrics.
    Called by the matplotlib animation framework.
    """
    global shared_data_state
    global start_time

    # Copy the shared state safely under the lock
    with frame_lock:
        current_frame_data = shared_data_state["frame"]
        frame_timestamp = shared_data_state["timestamp"]
        prev_timestamp = shared_data_state["prev_timestamp"]
        frame_count = shared_data_state["frame_count"]

    updated_artists = [line_fft, line_real, line_imag, frame_rate_text, time_between_frames_text]

    if current_frame_data is not None:
        # calculate magnitude
        fft_magnitude = np.abs(current_frame_data)
        line_fft.set_data(x_axis_fft, fft_magnitude)

        # update real and imaginary plots
        line_real.set_data(x_axis_time, current_frame_data.real)
        line_imag.set_data(x_axis_time, current_frame_data.imag)

        # update metrics
        current_plot_time = time.time()

        # calculate framerate
        elapsed_time = current_plot_time - start_time if start_time is not None else 0
        if elapsed_time > 0 and frame_count > 0:
            frame_rate = frame_count / elapsed_time
            frame_rate_text.set_text(f'Avg frame rate: {frame_rate:.2f} Hz')
        else:
            frame_rate_text.set_text('')

        # calculate time between frames
        if frame_timestamp is not None and prev_timestamp is not None:
            time_between_frames_ms = (frame_timestamp - prev_timestamp) * 1000
            time_between_frames_text.set_text(f'Time between Frames: {time_between_frames_ms:.1f} ms')
        else:
            time_between_frames_text.set_text('')

    return updated_artists


if __name__ == "__main__":
    reader = None
    thread = None
    try:
        # initialize the RadarCubeReader
        reader = RadarCubeReader(
            num_tx_antennas=N_TX_ANTENNAS,
            num_rx_antennas=N_RX_ANTENNAS,
            num_range_bins=N_RANGE_BINS,
            num_chirps_per_frame=NUM_CHIRPS_PER_FRAME,
            spi_uri=SPI_URI,
            spi_cs=SPI_CS,
            spi_freq=SPI_FREQ,
            spi_mode=SPI_MODE,
            spi_max_chunk_size=SPI_MAX_CHUNK_SIZE
        )

        # start the background thread to read data
        thread = threading.Thread(target=spi_read_thread, args=(reader,), daemon=True)
        thread.start()

        # create the matplotlib animation
        # blit=True: Optimizes rendering by only redrawing the parts of the plot that have changed
        ani = animation.FuncAnimation(
            fig,
            update_plot,
            init_func=init_plot,
            interval=50,
            blit=True,
            cache_frame_data=False 
        )

        plt.show()

    except Exception as e:
        print(f"Error during setup or plotting: {e}")

    finally:
        # ensure resources reader.close() is called
        if reader:
            reader.close()