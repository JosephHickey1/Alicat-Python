#!/usr/bin/env python
# coding: utf-8

"""Install parameters for python import"""
from setuptools import setup

with open('README.md', 'r') as in_file:
    long_description = in_file.read()

setup(
    name="Alicat",
    version="0.2.0-alpha",
    description="Python driver for Alicat mass flow and pressure devices",
    long_description=long_description,
    long_description_content_type='text/markdown',
    url="https://github.com/JosephHickey1/Alicat-Python",
    author="Joseph Hickey",
    packages=["Alicat"],
    install_requires=["pyserial","pickle","minimalmodbus"],
    entry_points={
        "console_scripts": [("Alicat = Alicat:run")]
    },
    license="MIT License",
    classifiers=[
        "License :: MIT License",
        "Natural Language :: English",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Topic :: Scientific/Engineering :: Human Machine Interfaces"
    ]
)

