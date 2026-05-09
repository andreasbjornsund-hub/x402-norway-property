"""Norwegian municipality codes (SSB Klass 131, post-2024 reform).

Top ~50 by population. SSB queries take 4-digit codes. We provide both
name → code lookup (with fuzzy matching) and the inverse.

Codes reflect the 2024 county/municipality reform. Some changed from
pre-2024 codes (e.g. Bergen was 1201, now 4601). If callers send an old
code we just don't match and they can use the name.
"""
from difflib import get_close_matches


# (canonical_name, code, county_name)
_TABLE: list[tuple[str, str, str]] = [
    ("oslo",          "0301", "Oslo"),
    ("bergen",        "4601", "Vestland"),
    ("trondheim",     "5001", "Trøndelag"),
    ("stavanger",     "1103", "Rogaland"),
    ("bærum",         "3201", "Akershus"),
    ("kristiansand",  "4204", "Agder"),
    ("drammen",       "3301", "Buskerud"),
    ("asker",         "3203", "Akershus"),
    ("lillestrøm",    "3205", "Akershus"),
    ("fredrikstad",   "3107", "Østfold"),
    ("sandnes",       "1108", "Rogaland"),
    ("tromsø",        "5501", "Troms"),
    ("sarpsborg",     "3105", "Østfold"),
    ("skien",         "4003", "Telemark"),
    ("nordre follo",  "3207", "Akershus"),
    ("ålesund",       "1508", "Møre og Romsdal"),
    ("sandefjord",    "3911", "Vestfold"),
    ("haugesund",     "1106", "Rogaland"),
    ("tønsberg",      "3905", "Vestfold"),
    ("moss",          "3103", "Østfold"),
    ("porsgrunn",     "4001", "Telemark"),
    ("bodø",          "1804", "Nordland"),
    ("arendal",       "4203", "Agder"),
    ("hamar",         "3403", "Innlandet"),
    ("ullensaker",    "3209", "Akershus"),
    ("larvik",        "3909", "Vestfold"),
    ("halden",        "3101", "Østfold"),
    ("lillehammer",   "3405", "Innlandet"),
    ("molde",         "1506", "Møre og Romsdal"),
    ("indre østfold", "3118", "Østfold"),
    ("harstad",       "5503", "Troms"),
    ("askøy",         "4627", "Vestland"),
    ("rana",          "1833", "Nordland"),
    ("kongsberg",     "3303", "Buskerud"),
    ("gjøvik",        "3407", "Innlandet"),
    ("ringsaker",     "3411", "Innlandet"),
    ("horten",        "3901", "Vestfold"),
    ("kristiansund",  "1505", "Møre og Romsdal"),
    ("narvik",        "1806", "Nordland"),
    ("alta",          "5601", "Finnmark"),
    ("elverum",       "3420", "Innlandet"),
    ("kongsvinger",   "3401", "Innlandet"),
    ("steinkjer",     "5006", "Trøndelag"),
    ("ås",            "3214", "Akershus"),
    ("levanger",      "5037", "Trøndelag"),
    ("vestby",        "3216", "Akershus"),
    ("ringerike",     "3305", "Buskerud"),
    ("nordreisa",     "5520", "Troms"),
    ("eidsvoll",      "3240", "Akershus"),
    ("nesodden",      "3212", "Akershus"),
]

# ASCII fallbacks for diacritic names so callers without IME can hit us.
_ASCII_FALLBACK = {
    "tromso": "tromsø",
    "alesund": "ålesund",
    "tonsberg": "tønsberg",
    "bodo": "bodø",
    "askoy": "askøy",
    "gjovik": "gjøvik",
    "as": "ås",
    "indre ostfold": "indre østfold",
    "barum": "bærum",
    "lillestrom": "lillestrøm",
}


def _by_name() -> dict[str, tuple[str, str, str]]:
    out: dict[str, tuple[str, str, str]] = {}
    for name, code, county in _TABLE:
        out[name] = (name, code, county)
    for ascii_key, canonical in _ASCII_FALLBACK.items():
        for name, code, county in _TABLE:
            if name == canonical:
                out[ascii_key] = (canonical, code, county)
                break
    return out


def _by_code() -> dict[str, tuple[str, str, str]]:
    return {code: (name, code, county) for name, code, county in _TABLE}


_BY_NAME = _by_name()
_BY_CODE = _by_code()


def lookup(query: str) -> tuple[str, str, str] | None:
    """Resolve a name OR 4-digit code to (canonical_name, code, county).

    Tries: exact code, exact lowercase name, ASCII fallback, fuzzy.
    """
    if not query:
        return None
    q = query.strip()
    if q in _BY_CODE:
        return _BY_CODE[q]
    qlow = q.lower()
    if qlow in _BY_NAME:
        return _BY_NAME[qlow]
    # Fuzzy: cutoff 0.75 against canonical names + fallbacks
    matches = get_close_matches(qlow, list(_BY_NAME.keys()), n=1, cutoff=0.75)
    if matches:
        return _BY_NAME[matches[0]]
    return None


def all_municipalities() -> list[dict]:
    return [
        {"name": name, "code": code, "county": county}
        for name, code, county in _TABLE
    ]
