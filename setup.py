from setuptools import setup, find_packages

setup(
    name="mmwave-spi-ftdi-reader",
    version="0.1.0",
    description="An unofficial Python library for streaming and parsing 1D Radar Cube data from TI mmWave sensors via SPI using an FTDI adapter",
    author="Leon Braungardt",
    packages=find_packages(exclude=["examples", "images"]),
    install_requires=[
        "numpy",
        "pyftdi",
        "xarray"
    ],
    python_requires=">=3.10",
)