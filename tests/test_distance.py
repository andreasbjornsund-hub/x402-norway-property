"""Tests for haversine distance + bearing."""


def test_zero_distance(distance_module):
    assert distance_module.haversine_km(59.91, 10.75, 59.91, 10.75) == 0.0


def test_oslo_to_bergen_approximately(distance_module):
    # Oslo (59.91, 10.75) → Bergen (60.39, 5.32): ~305 km great-circle
    d = distance_module.haversine_km(59.91, 10.75, 60.39, 5.32)
    assert 300.0 < d < 320.0


def test_north_bearing(distance_module):
    # Going due north: bearing should be 0
    b = distance_module.initial_bearing_deg(60.0, 10.0, 61.0, 10.0)
    assert -1.0 < b < 1.0 or b > 359.0


def test_east_bearing(distance_module):
    # Going due east at low latitude: bearing should be ~90
    b = distance_module.initial_bearing_deg(0.0, 0.0, 0.0, 1.0)
    assert 89.0 < b < 91.0


def test_oslo_to_bergen_bearing_is_west_ish(distance_module):
    # Bergen is west-southwest of Oslo, bearing roughly 260-280 degrees
    b = distance_module.initial_bearing_deg(59.91, 10.75, 60.39, 5.32)
    assert 250.0 < b < 290.0


def test_bearing_is_normalized(distance_module):
    """Bearing must always be in [0, 360)."""
    for (lat1, lon1, lat2, lon2) in [
        (59.91, 10.75, 60.39, 5.32),
        (60.0, 10.0, 59.0, 11.0),
        (0.0, 0.0, 0.0, -1.0),
    ]:
        b = distance_module.initial_bearing_deg(lat1, lon1, lat2, lon2)
        assert 0.0 <= b < 360.0
