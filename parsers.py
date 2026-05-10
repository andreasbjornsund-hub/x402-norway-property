"""Parsers for Kartverket response shapes.

Pure functions over plain dicts — easy to test without httpx.
"""
from typing import Any


def _coord(rep: dict | None, key_lat: str = "lat", key_lon: str = "lon") -> tuple[float | None, float | None]:
    """Pull (lat, lon) from various Kartverket coordinate shapes.

    Common shapes:
      {"representasjonspunkt": {"lat": ..., "lon": ...}}
      {"representasjonspunkt": {"nord": ..., "ost": ...}}     (UTM-style)
      {"punkt": {"coordinates": [lon, lat]}}                  (GeoJSON)
    """
    if not rep:
        return None, None
    if key_lat in rep and key_lon in rep:
        return rep.get(key_lat), rep.get(key_lon)
    if "nord" in rep and "ost" in rep:
        return rep.get("nord"), rep.get("ost")
    coords = rep.get("coordinates")
    if isinstance(coords, list) and len(coords) >= 2:
        return coords[1], coords[0]
    return None, None


def parse_address_search(data: dict, limit: int = 10) -> dict:
    """Kartverket /adresser/v1/sok response → flat list."""
    if not isinstance(data, dict):
        return {"results": [], "total": 0}
    rows = data.get("adresser") or []
    meta = data.get("metadata") or {}
    results: list[dict] = []
    for r in rows[:limit]:
        rep = r.get("representasjonspunkt") or {}
        lat, lon = _coord(rep)
        results.append({
            "address": r.get("adressetekst", ""),
            "postal_code": r.get("postnummer", ""),
            "city": r.get("poststed", ""),
            "municipality": r.get("kommunenavn", ""),
            "municipality_code": r.get("kommunenummer", ""),
            "lat": lat,
            "lon": lon,
        })
    return {"results": results, "total": meta.get("totaltAntallTreff", len(results))}


def parse_address_reverse(data: dict, query_lat: float, query_lon: float) -> dict:
    """Kartverket /adresser/v1/punkt response → single nearest hit."""
    rows = (data or {}).get("adresser") or []
    if not rows:
        return {"address": None}
    r = rows[0]
    rep = r.get("representasjonspunkt") or {}
    lat, lon = _coord(rep)
    distance_m: float | None = None
    if lat is not None and lon is not None:
        from distance import haversine_km
        distance_m = round(haversine_km(query_lat, query_lon, lat, lon) * 1000, 1)
    return {
        "address": r.get("adressetekst", ""),
        "postal_code": r.get("postnummer", ""),
        "city": r.get("poststed", ""),
        "municipality": r.get("kommunenavn", ""),
        "municipality_code": r.get("kommunenummer", ""),
        "lat": lat,
        "lon": lon,
        "distance_m": distance_m,
    }


def parse_place_search(data: dict, limit: int = 10) -> dict:
    """Kartverket /stedsnavn/v1/navn response → flat list of place names."""
    if not isinstance(data, dict):
        return {"results": [], "total": 0}
    rows = data.get("navn") or []
    meta = data.get("metadata") or {}
    results: list[dict] = []
    for r in rows[:limit]:
        rep = r.get("representasjonspunkt") or {}
        lat, lon = _coord(rep)
        # Norwegian place-name type lives at navneobjekttype OR stedsnavntype
        place_type = (
            r.get("navneobjekttype")
            or r.get("stedsnavntype")
            or r.get("type")
            or ""
        )
        # Municipality may be a list (a place can sit in multiple)
        kommune = r.get("kommuner") or r.get("kommune") or []
        if isinstance(kommune, list) and kommune:
            municipality = kommune[0].get("kommunenavn") or kommune[0].get("navn") or ""
            municipality_code = kommune[0].get("kommunenummer") or ""
            county = kommune[0].get("fylkesnavn") or ""
        elif isinstance(kommune, dict):
            municipality = kommune.get("kommunenavn") or kommune.get("navn") or ""
            municipality_code = kommune.get("kommunenummer") or ""
            county = kommune.get("fylkesnavn") or ""
        else:
            municipality = ""
            municipality_code = ""
            county = ""
        results.append({
            "name": r.get("skrivemåte") or r.get("stedsnavn") or r.get("navn", ""),
            "type": place_type,
            "municipality": municipality,
            "municipality_code": municipality_code,
            "county": county,
            "lat": lat,
            "lon": lon,
        })
    return {"results": results, "total": meta.get("totaltAntallTreff", len(results))}


def parse_elevation(data: dict, lat: float, lon: float) -> dict:
    """Kartverket /hoydedata/v1/punkt response → flat elevation dict."""
    rows = (data or {}).get("punkter") or []
    if not rows:
        return {"lat": lat, "lon": lon, "elevation_m": None, "source": ""}
    r = rows[0]
    elev = r.get("z") if "z" in r else r.get("hoyde", r.get("elevation"))
    return {
        "lat": lat,
        "lon": lon,
        "elevation_m": elev,
        "source": r.get("datakilde", r.get("terreng", "")),
    }


def parse_property(data: dict, knr: str, gnr: int, bnr: int) -> dict | None:
    """Kartverket /eiendom/v1/geokoding GeoJSON FeatureCollection → flat dict.

    Returns None when there are no features — the caller should map that to
    a 404 (so the x402 SDK skips settlement and the user isn't charged).

    The new API returns less than the old /eiendomsinfo/v1/eiendom: no
    address, no area, no property type. Those fields aren't surfaced here.
    Coordinates are point-of-representation (typically the parcel centroid).
    A property may have several `Teig` features (multiple parcels under one
    matrikkel) — we surface the one with `hovedområde=true` if present,
    else features[0].
    """
    if not isinstance(data, dict):
        return None
    features = data.get("features") or []
    if not features:
        return None
    # Prefer the hovedområde (main parcel) when multiple features exist.
    primary = next((f for f in features if (f.get("properties") or {}).get("hovedområde")), features[0])
    props = primary.get("properties") or {}
    geom = primary.get("geometry") or {}
    coords = geom.get("coordinates") or []
    lat = coords[1] if len(coords) > 1 else None
    lon = coords[0] if len(coords) > 0 else None
    return {
        "municipality_code": props.get("kommunenummer", knr),
        "gnr": props.get("gardsnummer", gnr),
        "bnr": props.get("bruksnummer", bnr),
        "festenummer": props.get("festenummer", 0),
        "seksjonsnummer": props.get("seksjonsnummer", 0),
        "matrikkelnummer": props.get("matrikkelnummertekst", f"{gnr}/{bnr}"),
        "lokalid": props.get("lokalid"),
        "object_type": props.get("objekttype", ""),
        "updated_at": props.get("oppdateringsdato", ""),
        "is_primary_parcel": bool(props.get("hovedområde")),
        "lat": lat,
        "lon": lon,
    }


# Norway/Scandinavia coordinate bounds — generous so coastal/marine queries pass.
NORWAY_LAT_MIN = 55.0
NORWAY_LAT_MAX = 81.0
NORWAY_LON_MIN = -10.0
NORWAY_LON_MAX = 35.0


def in_norway(lat: float, lon: float) -> bool:
    return NORWAY_LAT_MIN <= lat <= NORWAY_LAT_MAX and NORWAY_LON_MIN <= lon <= NORWAY_LON_MAX
