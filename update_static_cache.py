#!/usr/bin/python3

import csv
import io
import re

import requests

COUNTRY_CODES_URL = "https://raw.githubusercontent.com/datasets/country-codes/main/data/country-codes.csv"
COUNTRY_NAME_COLUMNS = ["official_name_en", "CLDR display name", "UNTERM English Short", "UNTERM English Formal"]

# Names used by the UCS satellite database and the CelesTrak/N2YO owner list that the ISO dataset does not contain
EXTRA_COUNTRY_NAMES = {"GBR": ["United Kingdom", "Great Britain"], "MAR": ["Morroco"], "NPL": ["Federal Democratic Republic of Nepal"], "SDN": ["Republic of Sudan"], "SGP": ["Sinapore"], "TUR": ["Turkey"], "USA": ["United States", "USA"], "VAT": ["Vatican City State"], "XKX": ["Kosovo"]}


# Remove quotes and handle commas in fields
# 6369,"TIST","medium_airport","Cyril E. King Airport",18.337299346923828,-64.97339630126953,23,"NA","VI","VI-U-A","Charlotte Amalie, Harry S. Truman Airport","yes","TIST","STT","STT","http://www.viport.com/airports.html","https://en.wikipedia.org/wiki/Cyril_E._King_Airport",
def csv_superparser(csv_line):
    parts = []
    field = ""
    in_quote_field = False
    for c in csv_line:
        if c == '"':
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


def update_country_names():
    data_request = requests.get(COUNTRY_CODES_URL, timeout=30)
    if data_request.status_code != requests.codes.ok:
        print(f"Failed to download country names: HTTP {data_request.status_code}")
        return

    data_request.encoding = "utf-8"

    country_names = {}
    for row in csv.DictReader(io.StringIO(data_request.text)):
        code = row["ISO3166-1-Alpha-3"].strip()
        if code:
            names = country_names.setdefault(code, [])
            for column in COUNTRY_NAME_COLUMNS:
                # UNTERM names look like "Bahamas (the)", "the Commonwealth of the Bahamas" or "Holy See (the) *"
                name = re.sub(r"\(the\)|\*", "", row[column]).strip()
                name = re.sub(r"^the ", "", name)
                names.append(name)

    for code, names in EXTRA_COUNTRY_NAMES.items():
        country_names.setdefault(code, []).extend(names)

    lines = 0
    with open("datafiles/country_names.csv", "w", encoding="utf-8") as f:
        for code, names in sorted(country_names.items()):
            seen = set()
            for name in names:
                if name and name.casefold() not in seen:
                    seen.add(name.casefold())
                    f.write(f"{code},{name}\n")
                    lines += 1

    print(f"Found {lines} names for {len(country_names)} countries")


if __name__ == "__main__":
    # Get the raw CSV (without the first header line)
    data_request = requests.get("https://raw.githubusercontent.com/davidmegginson/ourairports-data/refs/heads/main/airports.csv")
    data_request.encoding = "utf-8"

    airport_lines = data_request.text.splitlines()[1:]

    print(f"Found {len(airport_lines)} static airport configurations")

    with open("datafiles/airports.csv", "w") as f:
        for line in airport_lines:
            parts = csv_superparser(line)
            type = parts[2]
            name = parts[3]
            lat = parts[4]
            lon = parts[5]
            code = parts[13]

            # If there is acutally a code to look up, then write this config
            if code and code != "0":
                f.write(f"{code},{name},{lat},{lon}\n")

    update_country_names()

    satdaturl = "https://www.ucsusa.org/media/11490"
    file = requests.get(satdaturl, stream=True, allow_redirects=True)
    if file.status_code == requests.codes.ok:
        sat_lines = file.text.splitlines()[1:]
        print(f"Found static data for {len(sat_lines)} satellites")
        with open("datafiles/satdat.txt", "wb") as f:
            f.write(file.content)
