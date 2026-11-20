"""North Margin: local lunar observations beside an ecliptic-north orbital chart."""

import logging
import math
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import datasources
import network
import numpy as np
import psclock
import shared_config
import utilities
from modes import DisplayMode, planesign_mode_handler
from moon_scene import MoonScene, MoonView, orbit_layout
from PIL import Image
from requests import RequestException
from rgbmatrix import graphics
from skyfield import almanac
from skyfield.api import PlanetaryConstants, wgs84
from skyfield.framelib import ecliptic_J2000_frame
from skyfield.trigonometry import position_angle_of


def phase_name(degrees):
    # Give each instantaneous principal phase a small display window.
    for angle, name in ((0, "New Moon"), (90, "First Quarter"), (180, "Full Moon"), (270, "Last Quarter")):
        if abs((degrees - angle + 180) % 360 - 180) < 6:
            return name
    return ("Waxing Crescent", "Waxing Gibbous", "Waning Gibbous", "Waning Crescent")[int(degrees // 90)]


class MoonSky:
    def __init__(self, resources, latitude, longitude, zone):
        self.eph = datasources.load_ephemeris()
        resources.callback(self.eph.close)
        self.ts = datasources.timescale()
        self.zone = zone
        self.sun, self.earth, self.moon = (self.eph[name] for name in ("sun", "earth", "moon"))
        self.observer = self.earth + wgs84.latlon(latitude, longitude)
        self.annual = self.earth - self.sun
        self.lunar = self.moon - self.earth
        pc = PlanetaryConstants()
        for name in ("moon_080317.tf", "pck00008.tpc"):
            with open(datasources.ensure(name), "rb") as kernel:
                pc.read_text(kernel)
        pc.read_binary(resources.enter_context(open(datasources.ensure("moon_pa_de421_1900-2050.bpc"), "rb")))  # noqa: SIM115 - read lazily until mode exit
        self.pole = self.moon + pc.build_latlon_degrees(pc.build_frame_named("MOON_ME_DE421"), 90, 0)
        self.phases = almanac.moon_phases(self.eph)
        self.year = None
        self.full_window = None

    def view(self, now):
        t = self.ts.from_datetime(now)
        year = now.astimezone(self.zone).year
        if year != self.year:
            start, end = (self.ts.from_datetime(datetime(y, 1, 1, tzinfo=self.zone)) for y in (year, year + 1))
            samples = self.ts.linspace(start, end, 100)
            self.year_path = self.annual.at(samples).frame_xyz(ecliptic_J2000_frame).au[:2]
            self.year = year

        if self.full_window is None or not self.full_window[0] <= t.tt < self.full_window[1].tt:
            times, kinds = almanac.find_discrete(t, t + 32, self.phases)
            self.full_window = (t.tt, times[kinds == 2][0])

        earth = self.annual.at(t).frame_xyz(ecliptic_J2000_frame).au[:2]
        moon = self.lunar.at(t).frame_xyz(ecliptic_J2000_frame).km
        # A sidereal month's geocentric track, not a circle inferred from today's phase.
        path = self.lunar.at(t + np.linspace(-27.32166, 0, 80)).frame_xyz(ecliptic_J2000_frame).km[:2]
        layout = orbit_layout(self.year_path, earth, moon[:2], path)

        observer = self.observer.at(t)
        apparent = observer.observe(self.moon).apparent()
        horizon = apparent.altaz()
        limb = position_angle_of(horizon, observer.observe(self.sun).apparent().altaz()).radians
        pole = position_angle_of(horizon, observer.observe(self.pole).apparent().altaz()).degrees
        angle = apparent.phase_angle(self.sun).radians
        altitude, azimuth, _ = apparent.altaz(temperature_C="standard", pressure_mbar="standard")
        return MoonView(
            layout=layout,
            phase=phase_name(almanac.moon_phase(self.eph, t).degrees),
            phase_angle=angle,
            limb_angle=limb,
            pole_angle=pole,
            direction=utilities.direction_lookup(azimuth.degrees),
            altitude=round(altitude.degrees),
            distance=round(np.linalg.norm(moon)),
            full_date=self.full_window[1].astimezone(self.zone).strftime("%m/%d"),
        )


def draw_moon_frame(sign, scene, elapsed):
    sign.canvas.SetImage(scene.frame(elapsed))
    view = scene.view
    pale = graphics.Color(220, 220, 204)
    graphics.DrawText(sign.canvas, sign.font46, 1, 6, pale, view.phase.upper())
    graphics.DrawText(sign.canvas, sign.font57, 29, 15, graphics.Color(222, 164, 87), f"{(1 + math.cos(view.phase_angle)) / 2:.0%} LIT")
    graphics.DrawText(sign.canvas, sign.font46, 29, 23, graphics.Color(75, 141, 211), f"{view.distance}km")
    graphics.DrawText(sign.canvas, sign.font46, 1, 31, graphics.Color(147, 161, 181), f"FULL {view.full_date}")
    graphics.DrawText(sign.canvas, sign.font46, 44, 31, pale, f"{view.direction} {view.altitude}°")


def notice(sign, message):
    sign.canvas.Clear()
    graphics.DrawText(sign.canvas, sign.font57, 3, 19, graphics.Color(180, 177, 154), message)
    sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)


@planesign_mode_handler(DisplayMode.MOON)
def moon(sign):
    notice(sign, "Loading lunar sky...")
    with ExitStack() as resources:
        try:
            sky = MoonSky(resources, float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"]), shared_config.local_timezone)
            with Image.open(Path(shared_config.icons_dir) / "moon/moon.png") as atlas:
                # The bundled near-side portrait needs -75 degrees to put lunar north up.
                texture = atlas.convert("L").rotate(-75, Image.Resampling.BICUBIC).crop((25, 25, 275, 275))

            now = psclock.now(UTC)
            scene = MoonScene(sky.view(now), texture)
            last_sample = now
            start = deadline = time.monotonic()
            while shared_config.shared_mode.value == DisplayMode.MOON.value:
                now = psclock.now(UTC)
                if abs((now - last_sample).total_seconds()) >= 5:
                    scene = MoonScene(sky.view(now), texture)
                    last_sample = now
                draw_moon_frame(sign, scene, time.monotonic() - start)
                sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
                deadline = max(deadline + 0.1, time.monotonic())
                if sign.wait_loop(max(0, deadline - time.monotonic())):
                    return
        except (OSError, ValueError, RequestException) as error:
            if network.is_offline_error(error):
                raise
            logging.exception("Moon mode could not load or compute the lunar sky")
            notice(sign, "Lunar data unavailable")
            sign.wait_loop(30)
