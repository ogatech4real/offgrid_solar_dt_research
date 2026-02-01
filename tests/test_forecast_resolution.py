from datetime import datetime, timezone

from offgrid_dt.forecast.openweather import synthetic_irradiance_forecast


def test_synthetic_irradiance_matches_step_resolution():
    start = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
    pts = synthetic_irradiance_forecast(start=start, hours=48, step_minutes=15)
    assert len(pts) == 48 * 4
    # monotonic timestamps
    assert pts[1].ts > pts[0].ts