"""Map jolpica's nationality strings to ISO country codes and flag emoji.

jolpica/Ergast nationalities are demonyms ("British", "Italian"). We map them
to 2-letter ISO codes and then to regional-indicator unicode (the flag emoji).
"""

# Demonym -> ISO 3166-1 alpha-2.
_NATIONALITY_TO_CODE: dict[str, str] = {
    "American": "US",
    "Argentine": "AR",
    "Argentinian": "AR",
    "Australian": "AU",
    "Austrian": "AT",
    "Belgian": "BE",
    "Brazilian": "BR",
    "British": "GB",
    "Canadian": "CA",
    "Chilean": "CL",
    "Chinese": "CN",
    "Colombian": "CO",
    "Czech": "CZ",
    "Danish": "DK",
    "Dutch": "NL",
    "East German": "DE",
    "Filipino": "PH",
    "Finnish": "FI",
    "French": "FR",
    "German": "DE",
    "Hungarian": "HU",
    "Indian": "IN",
    "Indonesian": "ID",
    "Irish": "IE",
    "Italian": "IT",
    "Japanese": "JP",
    "Liechtensteiner": "LI",
    "Malaysian": "MY",
    "Mexican": "MX",
    "Monegasque": "MC",
    "Monégasque": "MC",
    "New Zealander": "NZ",
    "Polish": "PL",
    "Portuguese": "PT",
    "Rhodesian": "ZW",
    "Russian": "RU",
    "South African": "ZA",
    "Spanish": "ES",
    "Swedish": "SE",
    "Swiss": "CH",
    "Thai": "TH",
    "Uruguayan": "UY",
    "Venezuelan": "VE",
}


def country_code(nationality: str) -> str:
    """Return the 2-letter ISO code for a jolpica nationality, or ''."""
    if not nationality:
        return ""
    return _NATIONALITY_TO_CODE.get(nationality.strip(), "")


def flag_emoji(nationality: str) -> str:
    """Return the flag emoji for a jolpica nationality, or '' if unknown."""
    code = country_code(nationality)
    if not code or len(code) != 2:
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code.upper())
