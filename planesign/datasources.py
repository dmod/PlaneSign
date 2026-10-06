"""Reference data files kept in datafiles/ and downloaded from their source the first time a mode needs them."""

import logging
import os
import shutil

import network
import shared_config
from skyfield.api import Loader, load_file

DE421 = "de421.bsp"

# filename: (service, source URL)
SOURCES = {
    DE421: ("NASA JPL ephemeris download", "https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de421.bsp"),
    "moon_080317.tf": ("NASA NAIF kernel download", "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/fk/satellites/moon_080317.tf"),
    "pck00008.tpc": ("NASA NAIF kernel download", "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/a_old_versions/pck00008.tpc"),
    "moon_pa_de421_1900-2050.bpc": ("NASA NAIF kernel download", "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/moon_pa_de421_1900-2050.bpc"),
    "satdat.txt": ("UCS satellite database", "https://www.ucsusa.org/media/11490"),
}


def path(filename):
    return os.path.join(shared_config.datafiles_dir, filename)


def source_url(filename):
    return SOURCES[filename][1]


def ensure(filename):
    """Return the local path to a SOURCES file, downloading it first if it is missing.

    Connection failures propagate as network errors (see network.is_offline_error); an error status raises requests.HTTPError.
    """
    destination = path(filename)
    if os.path.isfile(destination):
        return destination
    # Older versions kept these files in the working directory.
    if os.path.isfile(filename):
        logging.debug(f"Moving {filename} to datafiles directory")
        os.makedirs(shared_config.datafiles_dir, exist_ok=True)
        shutil.move(filename, destination)
        return destination
    service, url = SOURCES[filename]
    network.download(service, url, destination)
    return destination


def load_ephemeris():
    """The DE421 planetary ephemeris shared by the astronomy modes."""
    return load_file(ensure(DE421))


def timescale():
    return Loader(shared_config.datafiles_dir).timescale(builtin=True)
