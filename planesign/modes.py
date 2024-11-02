from enum import Enum, auto

class DisplayMode(Enum):
    SIGN_OFF = auto()              # Sign off
    TIME_ONLY = auto()             # Time only
    PLANES_ALERT = auto()          # Show planes when in alert radius
    PLANES_ALWAYS = auto()         # Always show closest plane
    WEATHER = auto()               # Weather display
    WELCOME = auto()               # Welcome screen
    PONG = auto()                  # Pong game
    SATELLITE = auto()             # Satellite tracking
    MANDELBROT = auto()            # Mandelbrot visualization
    LIGHTNING = auto()              # Lighting effects
    FINANCE = auto()               # Finance display
    SNOWFALL = auto()              # Snowfall animation
    SANTA = auto()                 # Santa tracker
    COUNTDOWN = auto()             # Countdown display
    AQUARIUM = auto()              # Aquarium display
    FIREWORKS = auto()             # Fireworks display
    TRACK_A_FLIGHT = auto()        # Track a flight
    CCA = auto()                   # Cellular automaton
    CGOL = auto()                  # Conway's Game of Life
    MOON = auto()                  # Moon phase display
    CUSTOM_MESSAGE = auto()        # Custom message display
