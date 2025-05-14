from setuptools import setup, find_packages

setup(
    name="mmwave-spi-ftdi-reader",
    version="0.1.0",
    description="Unofficial SPI via FTDI USB cable data reader Python module for TI mmWave sensors",
    author="Leon Braungardt",
    packages=find_packages(exclude=["examples", "images"]),
    install_requires=[
        "numpy",
        "pyftdi"
    ],
    python_requires=">=3.10",
)