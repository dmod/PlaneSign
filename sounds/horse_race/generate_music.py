#!/usr/bin/python3
# -*- coding: utf-8 -*-

###
# Generates the chiptune backing tracks for the horse race mode.
# Everything is synthesised from square / triangle / noise channels, the way an old
# arcade cabinet or a MIDI soundfont would have done it.
#
#   python3 sounds/horse_race/generate_music.py
#
# Writes post_call.mp3, race_gallop.mp3 and win_fanfare.mp3 next to this script.
###

import os
import subprocess
import tempfile
import wave

import numpy as np

SR = 44100
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

SEMITONES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def hz(name):
    """ "A4" / "G#5" -> frequency in Hz."""
    octave = int(name[-1])
    midi = (octave + 1) * 12 + SEMITONES[name[:-1]]
    return 440.0 * 2 ** ((midi - 69) / 12.0)


def _envelope(n, attack=0.004, release=0.025, decay=0.0):
    env = np.ones(n)
    attack_n = min(int(SR * attack), n)
    release_n = min(int(SR * release), n - attack_n)
    if attack_n:
        env[:attack_n] = np.linspace(0.0, 1.0, attack_n)
    if release_n:
        env[n - release_n :] = np.linspace(1.0, 0.0, release_n)
    if decay:
        env *= np.exp(-decay * np.arange(n) / SR)
    return env


def square(freq, dur, vol=0.25, duty=0.5, vibrato=0.0, decay=0.0):
    n = max(1, int(SR * dur))
    t = np.arange(n) / SR
    phase = freq * t
    if vibrato:
        phase = phase + vibrato * np.sin(2 * np.pi * 5.5 * t)
    wave_data = np.where((phase % 1.0) < duty, 1.0, -1.0)
    return wave_data * _envelope(n, decay=decay) * vol


def triangle(freq, dur, vol=0.3, decay=0.0):
    n = max(1, int(SR * dur))
    t = np.arange(n) / SR
    phase = (freq * t) % 1.0
    wave_data = 4.0 * np.abs(phase - 0.5) - 1.0
    return wave_data * _envelope(n, decay=decay) * vol


def noise(dur, vol=0.2, decay=14.0, smooth=1):
    n = max(1, int(SR * dur))
    wave_data = np.random.uniform(-1.0, 1.0, n)
    if smooth > 1:
        wave_data = np.convolve(wave_data, np.ones(smooth) / smooth, mode="same")
    return wave_data * np.exp(-decay * np.arange(n) / SR) * vol


def kick(dur=0.14, vol=0.55):
    n = int(SR * dur)
    t = np.arange(n) / SR
    sweep = 130.0 * np.exp(-24.0 * t) + 45.0
    return np.sin(2 * np.pi * np.cumsum(sweep) / SR) * np.exp(-13.0 * t) * vol


def snare(vol=0.26):
    return noise(0.11, vol=vol, decay=34.0) + np.pad(np.sin(2 * np.pi * 190 * np.arange(int(SR * 0.05)) / SR) * np.exp(-40 * np.arange(int(SR * 0.05)) / SR) * vol * 0.5, (0, int(SR * 0.11) - int(SR * 0.05)))


def hat(vol=0.055):
    return noise(0.035, vol=vol, decay=90.0)


def clop(vol=0.22):
    """Wood block style hoof beat."""
    n = int(SR * 0.06)
    t = np.arange(n) / SR
    tone = np.sin(2 * np.pi * (900.0 * np.exp(-45.0 * t) + 320.0) * t)
    return (tone * 0.8 + np.random.uniform(-1, 1, n) * 0.2) * np.exp(-55.0 * t) * vol


def crowd(dur, vol=0.09):
    """Filtered noise swell, stands in for a grandstand."""
    n = int(SR * dur)
    wave_data = np.convolve(np.random.uniform(-1.0, 1.0, n), np.ones(160) / 160, mode="same")
    swell = 0.55 + 0.45 * np.sin(2 * np.pi * np.arange(n) / SR * 0.4)
    return wave_data * swell * vol


class Track:
    def __init__(self, duration):
        self.buffer = np.zeros(int(SR * duration))

    def add(self, at, samples):
        start = int(SR * at)
        if start >= len(self.buffer):
            return
        end = min(len(self.buffer), start + len(samples))
        self.buffer[start:end] += samples[: end - start]

    def render(self, path, peak=0.89):
        data = self.buffer
        high = np.max(np.abs(data))
        if high > 0:
            data = data / high * peak
        # Gentle bit crush for that cartridge era grit
        data = np.round(data * 127.0) / 127.0
        write_mp3(path, data)


def write_mp3(path, data):
    pcm = np.clip(data, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    try:
        with wave.open(wav_path, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(SR)
            handle.writeframes(pcm.tobytes())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav_path, "-codec:a", "libmp3lame", "-b:a", "160k", "-ac", "1", path], check=True)
    finally:
        os.unlink(wav_path)
    print(f"wrote {path} ({len(data) / SR:.1f}s)")


# --- 1. the call to post, played over the 3 / 2 / 1 countdown ----------------


def build_post_call():
    track = Track(2.95)
    track.add(0.0, crowd(2.95, vol=0.07))

    # Bugle call. Two square channels a beat apart make it ring like a brass pair.
    call = [(0.00, "G4", 0.14), (0.15, "C5", 0.14), (0.30, "E5", 0.28), (0.60, "C5", 0.13), (0.75, "E5", 0.13), (0.90, "G5", 0.42), (1.35, "E5", 0.13), (1.50, "C5", 0.13), (1.65, "E5", 0.13), (1.80, "G5", 0.55), (2.40, "G5", 0.20), (2.65, "G5", 0.28)]
    for at, note, dur in call:
        track.add(at, square(hz(note), dur, vol=0.30, duty=0.5, vibrato=0.006 if dur > 0.3 else 0.0))
        track.add(at, square(hz(note) / 2, dur, vol=0.13, duty=0.25))
        track.add(at, triangle(hz(note) / 4, dur, vol=0.18))

    # Hooves shuffling at the gate, then a roll into the off
    for i in range(9):
        track.add(0.1 + i * 0.3, clop(vol=0.11))
    for i in range(14):
        track.add(2.0 + i * 0.048, noise(0.05, vol=0.04 + i * 0.006, decay=60.0))
    track.add(2.65, snare(vol=0.3))
    track.add(2.65, kick(vol=0.5))
    return track


# --- 2. the race loop -------------------------------------------------------

BPM = 170.0
BEAT = 60.0 / BPM
BAR = BEAT * 4

# One chord per bar, the loop is 14 bars long which lands just under the 20 second race
CHORDS = [("A2", "E3"), ("A2", "E3"), ("F2", "C3"), ("G2", "D3"), ("A2", "E3"), ("A2", "E3"), ("F2", "C3"), ("E2", "B2"), ("A2", "E3"), ("C3", "G3"), ("F2", "C3"), ("G2", "D3"), ("A2", "E3"), ("E2", "B2")]

# (note, length in beats) per bar, None is a rest
MELODY = [
    [("A4", 0.5), ("C5", 0.5), ("E5", 0.5), ("A5", 0.5), ("G5", 0.5), ("E5", 0.5), ("C5", 1.0)],
    [("E5", 0.5), ("A5", 0.5), ("C6", 1.0), ("B5", 0.5), ("A5", 0.5), ("E5", 1.0)],
    [("F5", 0.5), ("A5", 0.5), ("C6", 0.5), ("A5", 0.5), ("F5", 1.0), ("E5", 1.0)],
    [("G5", 0.5), ("B5", 0.5), ("D6", 0.5), ("B5", 0.5), ("G5", 1.0), ("D5", 1.0)],
    [("A5", 0.5), ("E5", 0.5), ("A5", 0.5), ("C6", 0.5), ("B5", 0.5), ("A5", 0.5), ("G5", 1.0)],
    [("E5", 0.5), ("G5", 0.5), ("A5", 1.0), ("E5", 0.5), ("C5", 0.5), ("A4", 1.0)],
    [("F5", 0.5), ("C6", 0.5), ("A5", 0.5), ("F5", 0.5), ("G5", 1.0), ("E5", 1.0)],
    [("E5", 0.5), ("G#5", 0.5), ("B5", 0.5), ("E6", 0.5), ("B5", 1.0), ("G#5", 1.0)],
    [("A5", 0.25), ("A5", 0.25), ("G5", 0.5), ("E5", 0.5), ("A5", 0.5), ("C6", 1.0), ("A5", 1.0)],
    [("C6", 0.5), ("B5", 0.5), ("G5", 0.5), ("E5", 0.5), ("G5", 1.0), ("C6", 1.0)],
    [("A5", 0.5), ("F5", 0.5), ("C6", 0.5), ("A5", 0.5), ("F5", 2.0)],
    [("B5", 0.5), ("G5", 0.5), ("D6", 0.5), ("B5", 0.5), ("D6", 1.0), ("G5", 1.0)],
    [("A5", 0.5), ("C6", 0.5), ("E6", 0.5), ("C6", 0.5), ("A5", 2.0)],
    [("E5", 0.5), ("B5", 0.5), ("G#5", 0.5), ("B5", 0.5), ("E6", 1.0), (None, 1.0)],
]


def build_race_gallop():
    bars = len(CHORDS)
    track = Track(bars * BAR)
    track.add(0.0, crowd(bars * BAR, vol=0.035))

    for bar in range(bars):
        bar_at = bar * BAR
        root, fifth = CHORDS[bar]

        for beat in range(4):
            beat_at = bar_at + beat * BEAT

            # Galloping bass: two sixteenths and an eighth, over and over
            track.add(beat_at, triangle(hz(root), BEAT * 0.22, vol=0.34, decay=6.0))
            track.add(beat_at + BEAT * 0.25, triangle(hz(root), BEAT * 0.22, vol=0.26, decay=6.0))
            track.add(beat_at + BEAT * 0.5, triangle(hz(fifth), BEAT * 0.45, vol=0.30, decay=4.0))

            # Drum kit
            if beat in (0, 2):
                track.add(beat_at, kick())
            else:
                track.add(beat_at, snare())
            track.add(beat_at, hat())
            track.add(beat_at + BEAT * 0.25, hat(vol=0.03))
            track.add(beat_at + BEAT * 0.5, hat(vol=0.045))
            track.add(beat_at + BEAT * 0.75, hat(vol=0.03))

            # Hoof beats riding on top of the groove
            track.add(beat_at + BEAT * 0.5, clop(vol=0.09))
            track.add(beat_at + BEAT * 0.75, clop(vol=0.07))

        # Lead line, plus a quiet chord stab channel underneath it
        cursor = bar_at
        for note, length in MELODY[bar]:
            dur = length * BEAT * 0.92
            if note is not None:
                track.add(cursor, square(hz(note), dur, vol=0.32, duty=0.25))
                track.add(cursor, square(hz(note) / 2, dur, vol=0.10, duty=0.5))
            cursor += length * BEAT

        for offset in (BEAT * 1.5, BEAT * 3.5):
            track.add(bar_at + offset, square(hz(fifth) * 2, BEAT * 0.3, vol=0.09, duty=0.125, decay=8.0))

    return track


# --- 3. the winner fanfare --------------------------------------------------


def build_win_fanfare():
    track = Track(4.2)
    track.add(0.0, crowd(4.2, vol=0.16))

    fanfare = [(0.00, "G4", 0.13), (0.13, "C5", 0.13), (0.26, "E5", 0.13), (0.39, "G5", 0.26), (0.65, "E5", 0.13), (0.78, "G5", 0.55), (1.40, "C6", 0.20), (1.60, "B5", 0.20), (1.80, "C6", 0.90)]
    for at, note, dur in fanfare:
        track.add(at, square(hz(note), dur, vol=0.28, duty=0.5, vibrato=0.008 if dur > 0.4 else 0.0))
        track.add(at, square(hz(note) * 1.2599, dur, vol=0.12, duty=0.25))  # major third above
        track.add(at, triangle(hz(note) / 2, dur, vol=0.20))

    # Final chord, held and shimmering
    for note, vol in (("C4", 0.20), ("E4", 0.15), ("G4", 0.15), ("C5", 0.18)):
        track.add(2.85, square(hz(note), 1.30, vol=vol, duty=0.5, vibrato=0.012, decay=1.1))
    track.add(2.85, triangle(hz("C3"), 1.30, vol=0.26, decay=1.0))

    # Celebration blips and a drum flourish
    for i, note in enumerate(["C5", "E5", "G5", "C6", "E6", "G6"]):
        track.add(2.85 + i * 0.05, square(hz(note), 0.12, vol=0.11, duty=0.125, decay=12.0))
    for i in range(8):
        track.add(2.45 + i * 0.05, noise(0.06, vol=0.10 + i * 0.012, decay=55.0))
    for at in (0.0, 0.78, 1.40, 1.80, 2.85):
        track.add(at, kick())
    track.add(2.85, snare(vol=0.4))
    return track


if __name__ == "__main__":
    np.random.seed(1969)
    build_post_call().render(os.path.join(OUT_DIR, "post_call.mp3"))
    build_race_gallop().render(os.path.join(OUT_DIR, "race_gallop.mp3"))
    build_win_fanfare().render(os.path.join(OUT_DIR, "win_fanfare.mp3"))
