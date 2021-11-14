#!/usr/bin/python3
# -*- coding: utf-8 -*-

import requests

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
                # Comma is in quote field, ignore it
                pass
            else:
                # Comma delimeter, so we are at the end of the field
                parts.append(field)
                field = ""

        else:
            # Not a special char, just add it
            field += c

    return parts


if __name__ == "__main__":
    # Get the raw CSV (without the first header line)
    data_request = requests.get('https://ourairports.com/data/airports.csv')
    data_request.encoding = 'utf-8'

    airport_lines = data_request.text.splitlines()[1:]

    print(f"Found {len(airport_lines)} static airport configurations")

    with open("airports.csv", "w") as f:

        for line in airport_lines:
            parts = csv_superparser(line)
            type = parts[2]
            name = parts[3]
            lat = parts[4]
            lon = parts[5]
            code = parts[13]

            # If there is acutally a code to look up, then write this config
            if code:
                f.write(f'{code},{name},{lat},{lon}\n')


    satdaturl = "https://www.ucsusa.org/media/11490"
    file = requests.get(satdaturl, stream=True, allow_redirects=True)
    if file.status_code == requests.codes.ok:
        sat_lines = file.text.splitlines()[1:]
        print(f"Found static data for {len(sat_lines)} satellites")
        with open("/home/pi/PlaneSign/satdat.txt", 'wb') as f:
            f.write(file.content)
