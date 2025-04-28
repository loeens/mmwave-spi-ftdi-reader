"""
Example script demonstrating how to use RadarCubeReader to stream radar cubes
via SPI, extract a range profile, and plot it live using matplotlib animation.

This script utilizes threading to read data in the background while the main
thread handles the GUI and plotting. It displays the approximate
overall frame rate and the time elapsed *between* the last two processed frames.

Requires:
    - numpy
    - matplotlib
    - pyftdi (installed as part of your project dependencies)
    - Your local radar_cube_reader.py and data_types.py files.

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

from radar_cube_reader import RadarCubeReader
from data_types import RadarCube1D

# --- Configuration ---
# radar parameters - Adjust these to match your sensor configuration
N_RANGE_BINS = 64
N_TX_ANTENNAS = 2
N_RX_ANTENNAS = 3
NUM_CHIRPS_PER_FRAME = 128 # total chirps per frame (num chirps per burst * num bursts per frame)

# SPI Configuration - Adjust the URI for your FTDI device if necessary
SPI_URI = "ftdi://ftdi:232h/1?latency=1"
SPI_CS = 0
SPI_FREQ = 30e6
SPI_MODE = 0
SPI_MAX_CHUNK_SIZE = 65280 # Must be divisible by 4

# physics constants for range calculation
C = 3e8                     # Speed of light (m/s)
BANDWIDTH = 2700e6          # Radar bandwidth in Hz
RANGE_RESOLUTION = C / (2 * BANDWIDTH)  # Range resolution (meters per bin)


# --- Shared State for Thread Communication ---
# holds the latest processed data and metadata from the SPI thread.
# Access to this dictionary is protected by frame_lock.
shared_data_state = {
    "frame": None,          # holds the latest numpy array for plotting
    "timestamp": None,      # timestamp when the *current* frame was received/processed
    "prev_timestamp": None, # timestamp when the *previous* frame was received/processed
    "frame_count": 0        # counter for the number of frames processed
}
frame_lock = threading.Lock()

# timestamp when the data streaming started (used for overall frame rate calculation)
start_time = None


# --- Data Reading Thread ---
def spi_read_thread(reader: RadarCubeReader):
    """
    Background thread that continuously reads radar cubes from the reader.
    Updates the shared_data_state with the latest frame and its timestamp,
    and also stores the previous frame's timestamp.
    """
    global shared_data_state
    global start_time

    print("SPI read thread started.")
    start_time = time.time()

    try:
        # iterate over the radar cubes provided by the reader
        for cube in reader:
            current_frame_timestamp = time.time()

            try:
                # select first range profile in radar cube for demo purposes
                latest_frame_data = cube.data.isel(virt_antenna=0, doppler_chirp=0).values

            except Exception as e:
                print(f"Error slicing radar cube in thread: {e}", file=sys.stderr)
                continue # skip this frame but continue reading

            with frame_lock:
                # store the current 'timestamp' as 'prev_timestamp' before updating 'timestamp'
                shared_data_state["prev_timestamp"] = shared_data_state["timestamp"]
                shared_data_state["timestamp"] = current_frame_timestamp

                shared_data_state["frame"] = latest_frame_data
                shared_data_state["frame_count"] += 1

    except Exception as e:
        print(f"Error in SPI read thread: {e}", file=sys.stderr)
    finally:
        print("SPI read thread finished.")

# --- Matplotlib Animation ---

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

# add text elements for displaying metrics
frame_rate_text = ax_fft.text(0.02, 0.98, '', transform=ax_fft.transAxes, ha='left', va='top', fontsize=10, bbox=dict(boxstyle='round,pad=0.5', fc='wheat', alpha=0.5))
time_between_frames_text = ax_fft.text(0.98, 0.98, '', transform=ax_fft.transAxes, ha='right', va='top', fontsize=10, bbox=dict(boxstyle='round,pad=0.5', fc='wheat', alpha=0.5))


def init_plot():
    """Initializes the plot elements for the animation."""
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
        # --- Update Plot Lines ---
        # calculate magnitude
        fft_magnitude = np.abs(current_frame_data)
        line_fft.set_data(x_axis_fft, fft_magnitude)

        # update real and imaginary plots
        line_real.set_data(x_axis_time, current_frame_data.real)
        line_imag.set_data(x_axis_time, current_frame_data.imag)

        # --- Update Metrics Text ---
        current_plot_time = time.time()

        # overall Frame Rate calculation
        elapsed_time = current_plot_time - start_time if start_time is not None else 0
        if elapsed_time > 0 and frame_count > 0:
            frame_rate = frame_count / elapsed_time
            frame_rate_text.set_text(f'Overall Frame Rate: {frame_rate:.2f} Hz')
        else:
            frame_rate_text.set_text('Overall Frame Rate: N/A')

        # Time Between Frames calculation
        if frame_timestamp is not None and prev_timestamp is not None:
            # calculate difference in milliseconds between the last two frame timestamps
            time_between_frames_ms = (frame_timestamp - prev_timestamp) * 1000
            time_between_frames_text.set_text(f'Time between Frames: {time_between_frames_ms:.1f} ms')
        else:
            time_between_frames_text.set_text('Time between Frames: N/A')

    return updated_artists


# --- Main Execution ---
if __name__ == "__main__":

    reader = None
    thread = None
    try:
        # initialize the RadarCubeReader
        print(f"Initializing RadarCubeReader with URI: {SPI_URI}")
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
        print("RadarCubeReader initialized successfully.")

        # start the background thread to read data
        thread = threading.Thread(target=spi_read_thread, args=(reader,), daemon=True)
        thread.start()
        print("Background SPI read thread started.")

        # create the matplotlib animation
        # interval: Delay between frames in milliseconds. Adjust based on desired plot update rate.
        # blit=True: Optimizes rendering by only redrawing the parts of the plot that have changed. Requires returning artists from update_plot.
        ani = animation.FuncAnimation(
            fig,
            update_plot,
            init_func=init_plot,
            interval=50,
            blit=True,
            cache_frame_data=False 
        )

        print("Showing plot. Close the plot window to exit.")
        plt.show()

    except Exception as e:
        print(f"\nAn error occurred during setup or plotting: {e}", file=sys.stderr)

    finally:
        # ensure resources are cleaned up when the plot window is closed or an error occurs
        print("Cleaning up resources.")
        if reader:
            reader.close()
        print("Exiting.")