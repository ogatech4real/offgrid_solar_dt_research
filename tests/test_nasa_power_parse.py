"""Minimal test for NASA POWER response parsing (no network)."""
from offgrid_dt.forecast.nasa_power import _parse_nasa_power_ghi

SAMPLE = {
    "properties": {
        "parameter": {
            "ALLSKY_SFC_SW_DWN": {"2025020208": 65.78, "2025020209": 186.1},
        },
    },
}


def test_parse_nasa_power_ghi():
    pts = _parse_nasa_power_ghi(SAMPLE)
    assert len(pts) == 2
    assert pts[0].ghi_wm2 == 65.78
    assert pts[1].ghi_wm2 == 186.1
    assert pts[0].ts.year == 2025 and pts[0].ts.month == 2 and pts[0].ts.day == 2 and pts[0].ts.hour == 8
    assert pts[1].ts.hour == 9
