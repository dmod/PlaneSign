import math
from datetime import tzinfo, timedelta, datetime
import pytz

NUM_STEPS = 40

local_tz = pytz.timezone('America/New_York')

def get_distance(coord1, coord2):
    R = 3958.8  # Earth radius in meters
    lat1, lon1 = coord1
    lat2, lon2 = coord2

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi/2)**2 + math.cos(phi1) * \
        math.cos(phi2)*math.sin(dlambda/2)**2

    return (2*R*math.atan2(math.sqrt(a), math.sqrt(1 - a)))

def convert_unix_to_local_time(unix_timestamp):
    utc_time = datetime.fromtimestamp(unix_timestamp, tz=pytz.utc)
    local_time = utc_time.astimezone(local_tz)
    return local_time

def interpolate(num1, num2):
    if (num1 == 0):
        num1 = num2

    if num2 > num1:
        thing = float((num2 - num1)) / NUM_STEPS
        interpolated = [num1]
        for _ in range(NUM_STEPS):
            interpolated.append(interpolated[-1] + thing)
    else:
        thing = float((num1 - num2)) / NUM_STEPS
        interpolated = [num1]
        for _ in range(NUM_STEPS):
            interpolated.append(interpolated[-1] - thing)

    return interpolated[1:]

# Remove quotes and handle commas in fields
# 6369,"TIST","medium_airport","Cyril E. King Airport",18.337299346923828,-64.97339630126953,23,"NA","VI","VI-U-A","Charlotte Amalie, Harry S. Truman Airport","yes","TIST","STT","STT","http://www.viport.com/airports.html","https://en.wikipedia.org/wiki/Cyril_E._King_Airport",
def csv_superparser(csv_line):
    parts = []
    field = ""
    in_quote_field = False
    for c in csv_line:
        if c == "\"":
            if in_quote_field:
                # Found quote but already in field, so it's the end of the quote field
                in_quote_field = False
            else:
                # Start of quote field
                in_quote_field = True

        elif c == ",":
            if in_quote_field:
                # Comma is in quote field, just add it like normal
                field += c
            else:
                # Comma delimeter, so we are at the end of the field
                parts.append(field)
                field = ""

        else:
            # Not a special char, just add it
            field += c

    return parts