import time
import numpy as np
import xarray as xr 

class RadarCube:
    """
    Base class for radar cube data, leveraging xarray for named-axis handling.

    This class is intended to be a non-instantiable parent class.
    It provides the core functionality for wrapping a NumPy array
    into an xarray.DataArray with specified dimensions and attributes.

    Attributes:
        data (xr.DataArray):
            Complex-valued xarray.DataArray holding the radar cube data.
            The dimensions and coordinates are defined by the subclass.
            The raw NumPy data can be accessed via `cube.data.values`.
            Global attributes, such as the timestamp, are stored in
            `cube.data.attrs`.

    Usage:
        This class should not be instantiated directly. Use subclasses
        like RadarCube1D.
    """

    def __init__(self,
                 data: np.ndarray,
                 dims: tuple[str, ...],
                 xdarr_name: str,
                 timestamp: float = None,
                 ):
        """
        Initializes the RadarCube with radar data, creating an xarray.DataArray.
        This constructor is intended for use by subclasses.

        Args:
            data (np.ndarray):
                Complex-valued NumPy array holding the raw cube data.
                Expected shape must match the provided dims tuple.
            dims (tuple[str, ...]):
                A tuple of strings specifying the names of the dimensions
                for the xarray.DataArray.
            xdarr_name (str):
                Name of the xarray.               
            timestamp (float, optional):
                Epoch time in seconds when this frame was captured.
                Defaults to the current time if None.
        """
        # ensure that class is not instantiated directly
        if self.__class__ == RadarCube:
            raise TypeError("RadarCube is a base class and should not be instantiated directly. Use subclasses like RadarCube1D.")

        # ensure input data is numpy array
        if not isinstance(data, np.ndarray):
            raise TypeError("Input 'data' must be a NumPy array.")

        # ensure the input data has the expected number of dimensions
        if data.ndim != len(dims):
            raise ValueError(f"Input data must be {len(dims)}D with shape corresponding to {dims}, but got shape {data.shape}")

        # create the xarray DataArray from the numpy data
        self.data = xr.DataArray(
            data,
            dims = dims,
            name = xdarr_name
        )

        # add timestamp to xarray .attrs metadata dict
        current_timestamp = timestamp or time.time()
        self.data.attrs['timestamp'] = current_timestamp

class RadarCube1D(RadarCube):
    """
    Represents a 1D radar cube (after Range-FFT processing),
    handling both interleaved and non-interleaved formats.

    Stores radar data as an xarray.DataArray with dimensions depending
    on the 'interleaved' flag:
    - Interleaved: ('rangebin', 'virt_antenna', 'doppler_chirp')
    - Non-interleaved: ('chirp', 'rx_antenna', 'rangebin')

    Attributes:
        data (xr.DataArray):
            Complex-valued xarray.DataArray holding the 1D radar cube data.
            Dimensions depend on the 'interleaved' flag.
            The raw NumPy data can be accessed via `cube.data.values`.
            Metadata attributes, including timestamp and interleaved status,
            are stored in `cube.data.attrs`.

    Usage:
        # Assume 'arr_interleaved' is a NumPy array (rangebin, virt_antenna, doppler_chirp)

        # Create an interleaved 1D radar cube
        cube = RadarCube1D(arr_interleaved, interleaved = True)

        # access radar cube data
        print(cube.data)        # get xarray data
        print(cube.data.values) # get data as numpy array
        print(cube.data.dims)   # get cube's dimension labels
        print(cube.data.attrs)  # get attributes (timestamp, interleaved status)


        # slice by (doppler_/)chirp / (virt_/rx_)antenna / rangebin
        # Examples:
        # get all rangebins across all antennas but from first chirp only
            chirp0      = cube.data.isel(doppler_chirp=0)
        # get all rangebins across all chirps but from second virtual antenna only
            ant1        = cube.data.isel(virt_antenna=1)
        # get 17th rangebin across all chirps and antennas
            rangebin16  = cube.data.isel(rangebin=16)
        # get range profile from first chirp and first antenna
            rangeprof0  = cube.data.isel(doppler_chirp=0, virt_antenna=0)
    """
    # define standard dimensions
    _DIMS_INTERLEAVED       = ("rangebin", "virt_antenna", "doppler_chirp")
    _DIMS_NON_INTERLEAVED   = ("chirp", "rx_antenna", "rangebin")
    # define xarray name of 1D radar cube
    _RADAR_CUBE_1D_XR_NAME = "radar_cube_1d"

    def __init__(self,
                 data: np.ndarray,
                 interleaved: bool,
                 timestamp: float = None):
        """
        Initializes the RadarCube1D with radar data.

        Args:
            data (np.ndarray):
                Complex-valued NumPy array holding the 1D radar cube data.
                Shape must match the dimensions corresponding to the
                'interleaved' flag.
            interleaved (bool):
                If True, data is assumed to be interleaved with dimensions
                ('rangebin', 'virt_antenna', 'doppler_chirp').
                If False, data is assumed to be non-interleaved with dimensions
                ('chirp', 'rx_antenna', 'rangebin').
            timestamp (float, optional):
                Epoch time in seconds when this frame was captured.
                Defaults to the current time if None.
        """
        self.interleaved = interleaved

        # determine the correct dimensions based on the interleaved flag
        if self.interleaved:
            dims_to_use = self._DIMS_INTERLEAVED
        else:
            dims_to_use = self._DIMS_NON_INTERLEAVED

        # call the parent class constructor with the data and selected dimensions
        super().__init__(data, dims_to_use, self._RADAR_CUBE_1D_XR_NAME, timestamp=timestamp)

        # add the interleaved status as an attribute to the DataArray
        self.data.attrs['interleaved'] = self.interleaved

