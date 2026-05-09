"""Haversine distance + initial bearing between two WGS84 points.

Pure Python, no upstream calls, no external deps.
"""
import math


_EARTH_RADIUS_KM = 6371.0088  # mean Earth radius


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return _EARTH_RADIUS_KM * c


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing (forward azimuth) from point 1 to point 2 in degrees,
    normalized to 0–360 with 0° = north, 90° = east."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlmb = math.radians(lon2 - lon1)
    y = math.sin(dlmb) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlmb)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360.0) % 360.0
