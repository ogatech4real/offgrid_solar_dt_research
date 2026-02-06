"""NASA POWER API client for physics-based solar irradiance (GHI).

All solar energy and power calculations in the digital twin use data from NASA POWER
(surface shortwave downwelling radiation / GHI). This keeps the system free,
reproducible, and scientifically defensible for academic use.

OpenWeather is used only for user location selection and contextual weather display;
it is not used for irradiance or PV estimates.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple, Union

import requests

from .openweather import IrradiancePoint

LOG = logging.getLogger("offgrid_dt")

NASA_POWER_BASE = "https://power.larc.nasa.gov/api/temporal/hourly/point"
PARAM_GHI = "ALLSKY_SFC_SW_DWN"  # All-sky surface shortwave downward irradiance (W/m² or Wh/m² per hour)


def fetch_ghi_hourly(
    lat: float,
    lon: float,
    start_date: datetime,
    end_date: Optional[datetime] = None,
    time_standard: str = "UTC",
    timeout_seconds: int = 30,
) -> List[IrradiancePoint]:
    """Fetch hourly GHI (ALLSKY_SFC_SW_DWN) from NASA POWER for the given date range.

    The API returns hourly values; keys are YYYYMMDDHH and values are in Wh/m²
    (hourly energy), which equals average irradiance in W/m² over that hour.

    Args:
        lat: Latitude (degrees).
        lon: Longitude (degrees).
        start_date: First day (00:00–24:00) in UTC. Only the date part is used.
        end_date: Last day inclusive (UTC). If None, only start_date is requested.
        time_standard: "UTC" or "LST".
        timeout_seconds: Request timeout.

    Returns:
        List of IrradiancePoint (ts in UTC, ghi_wm2 in W/m²) for each hour in the range.
        Hours are ordered from start_date 00:00 through end_date 23:00.
    """
    if start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    start_str = start_date.strftime("%Y%m%d")
    if end_date is None:
        end_date = start_date
    elif end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)
    end_str = end_date.strftime("%Y%m%d")

    params = {
        "parameters": PARAM_GHI,
        "community": "RE",
        "longitude": lon,
        "latitude": lat,
        "start": start_str,
        "end": end_str,
        "format": "JSON",
        "time-standard": time_standard,
    }
    r = requests.get(NASA_POWER_BASE, params=params, timeout=timeout_seconds)
    r.raise_for_status()
    data = r.json()

    points = _parse_nasa_power_ghi(data)
    if not points:
        LOG.warning("NASA POWER returned no GHI points for %s–%s", start_str, end_str)
    return points


def _parse_nasa_power_ghi(data: dict) -> List[IrradiancePoint]:
    """Parse NASA POWER JSON response into IrradiancePoint list.

    Expects properties.parameter.ALLSKY_SFC_SW_DWN with keys YYYYMMDDHH (UTC).
    Values are Wh/m² per hour (equivalent to W/m² average over the hour).
    """
    points: List[IrradiancePoint] = []
    try:
        params = (data.get("properties") or {}).get("parameter") or {}
        ghi_data = params.get(PARAM_GHI)
        if not ghi_data or not isinstance(ghi_data, dict):
            return points
        # Sort by key so order is chronological
        for key in sorted(ghi_data.keys()):
            try:
                # key format: YYYYMMDDHH
                if len(key) != 10:
                    continue
                year = int(key[0:4])
                month = int(key[4:6])
                day = int(key[6:8])
                hour = int(key[8:10])
                ts = datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)
                val = ghi_data[key]
                if val is None:
                    continue
                ghi = float(val)
                # API uses -999 as fill; treat as 0
                if ghi < 0:
                    ghi = 0.0
                points.append(IrradiancePoint(ts=ts, ghi_wm2=ghi))
            except (ValueError, TypeError, IndexError):
                continue
    except Exception as e:
        LOG.warning("Failed to parse NASA POWER response: %s", e)
    return points


def _parse_nasa_power_ghi_valid_only(data: dict) -> List[IrradiancePoint]:
    """Parse NASA POWER JSON; include only hours with valid GHI (exclude -999 and any negative as missing)."""
    points: List[IrradiancePoint] = []
    try:
        params = (data.get("properties") or {}).get("parameter") or {}
        ghi_data = params.get(PARAM_GHI)
        if not ghi_data or not isinstance(ghi_data, dict):
            return points
        for key in sorted(ghi_data.keys()):
            try:
                if len(key) != 10:
                    continue
                year = int(key[0:4])
                month = int(key[4:6])
                day = int(key[6:8])
                hour = int(key[8:10])
                ts = datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)
                val = ghi_data[key]
                if val is None:
                    continue
                ghi = float(val)
                if ghi < 0:
                    continue
                points.append(IrradiancePoint(ts=ts, ghi_wm2=ghi))
            except (ValueError, TypeError, IndexError):
                continue
    except Exception as e:
        LOG.warning("Failed to parse NASA POWER response: %s", e)
    return points


def fetch_nasa_power_hourly_ghi(
    lat: float,
    lon: float,
    start_date: Union[date, datetime],
    end_date: Union[date, datetime],
    time_standard: str = "UTC",
    timeout_seconds: int = 30,
) -> List[IrradiancePoint]:
    """Fetch hourly GHI from NASA POWER for the given date range; return only valid samples (no fill).

    -999 and any negative values are treated as missing and excluded from the result.
    Returns list of (ts_utc, ghi) as IrradiancePoint for each hour with valid data.
    """
    if isinstance(start_date, date) and not isinstance(start_date, datetime):
        start_dt = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0, tzinfo=timezone.utc)
    else:
        start_dt = start_date
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
    if isinstance(end_date, date) and not isinstance(end_date, datetime):
        end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)
    else:
        end_dt = end_date
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
    start_str = start_dt.strftime("%Y%m%d")
    end_str = end_dt.strftime("%Y%m%d")
    params = {
        "parameters": PARAM_GHI,
        "community": "RE",
        "longitude": lon,
        "latitude": lat,
        "start": start_str,
        "end": end_str,
        "format": "JSON",
        "time-standard": time_standard,
    }
    r = requests.get(NASA_POWER_BASE, params=params, timeout=timeout_seconds)
    r.raise_for_status()
    data = r.json()
    return _parse_nasa_power_ghi_valid_only(data)


def build_hourly_profile_mean(points: List[IrradiancePoint]) -> List[float]:
    """Build 24-hour profile: for each hour 0..23, average all valid samples; if none, 0.0."""
    by_hour: List[List[float]] = [[] for _ in range(24)]
    for p in points:
        h = p.ts.hour
        if 0 <= h < 24:
            by_hour[h].append(float(p.ghi_wm2))
    return [sum(vals) / len(vals) if vals else 0.0 for vals in by_hour]


# Plausibility thresholds for expected GHI profile (do not label invalid as NASA-based).
_MIN_PEAK_GHI_WM2_EXPECTED = 5.0
_MIN_GHI_SPREAD_WM2_EXPECTED = 1.0


def _is_valid_expected_profile(profile_24: List[float]) -> bool:
    """True if profile has usable solar: max >= 5 W/m², sum > 0, and diurnal spread (not flat)."""
    if not profile_24 or len(profile_24) != 24:
        return False
    s = sum(profile_24)
    mx = max(profile_24)
    mn = min(profile_24)
    return (
        s > 0
        and mx >= _MIN_PEAK_GHI_WM2_EXPECTED
        and (mx - mn) >= _MIN_GHI_SPREAD_WM2_EXPECTED
    )


def expected_ghi_profile_doy_last_year(
    lat: float,
    lon: float,
    reference_utc: Optional[datetime] = None,
    doy_window: int = 3,
    time_standard: str = "UTC",
    timeout_seconds: int = 30,
) -> List[IrradiancePoint]:
    """Primary: expected 24h GHI from same day last year with DOY ± doy_window days (7-day mean).

    target_date = (today_utc - 365 days).date(); window = target_date ± doy_window.
    Fill values (-999 / negative) are excluded; build mean per hour 0..23. Returns 24 points or [].
    """
    if reference_utc is None:
        reference_utc = datetime.now(tz=timezone.utc)
    if reference_utc.tzinfo is None:
        reference_utc = reference_utc.replace(tzinfo=timezone.utc)
    today = reference_utc.date()
    target_date = today - timedelta(days=365)
    start_date = target_date - timedelta(days=doy_window)
    end_date = target_date + timedelta(days=doy_window)
    try:
        points = fetch_nasa_power_hourly_ghi(
            lat, lon, start_date, end_date,
            time_standard=time_standard, timeout_seconds=timeout_seconds,
        )
    except Exception as e:
        LOG.warning("NASA POWER DOY fetch failed (%s); trying fallback.", e)
        return []
    if not points:
        return []
    profile_24 = build_hourly_profile_mean(points)
    if not _is_valid_expected_profile(profile_24):
        LOG.warning(
            "NASA POWER DOY±%d last year invalid (range %s–%s, %d points, max=%.1f); using fallback.",
            doy_window, start_date.isoformat(), end_date.isoformat(), len(points), max(profile_24),
        )
        return []
    nominal_day = today + timedelta(days=1)
    out = _mean_profile_to_points(profile_24, nominal_day)
    LOG.info(
        "Solar source: NASA POWER (DOY±%d last year), range %s–%s, %d valid points.",
        doy_window, start_date.isoformat(), end_date.isoformat(), len(points),
    )
    return out


def expected_ghi_profile_yesterday(
    lat: float,
    lon: float,
    reference_utc: Optional[datetime] = None,
    time_standard: str = "UTC",
    timeout_seconds: int = 30,
) -> List[IrradiancePoint]:
    """Fallback: expected 24h GHI from yesterday 00–24 UTC. Uses that day's data directly or mean profile."""
    if reference_utc is None:
        reference_utc = datetime.now(tz=timezone.utc)
    if reference_utc.tzinfo is None:
        reference_utc = reference_utc.replace(tzinfo=timezone.utc)
    yesterday = reference_utc.date() - timedelta(days=1)
    start_dt = datetime(yesterday.year, yesterday.month, yesterday.day, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59, tzinfo=timezone.utc)
    try:
        points = fetch_nasa_power_hourly_ghi(
            lat, lon, start_dt, end_dt,
            time_standard=time_standard, timeout_seconds=timeout_seconds,
        )
    except Exception as e:
        LOG.warning("NASA POWER yesterday fetch failed (%s); using synthetic.", e)
        return []
    if not points:
        return []
    profile_24 = build_hourly_profile_mean(points)
    if not _is_valid_expected_profile(profile_24):
        LOG.warning(
            "NASA POWER yesterday invalid (date %s, %d points, max=%.1f); using synthetic.",
            yesterday.isoformat(), len(points), max(profile_24),
        )
        return []
    nominal_day = reference_utc.date() + timedelta(days=1)
    out = _mean_profile_to_points(profile_24, nominal_day)
    LOG.info(
        "Solar source: NASA POWER (yesterday), date %s, %d valid points.",
        yesterday.isoformat(), len(points),
    )
    return out


def fetch_ghi_next_planning_days(
    lat: float,
    lon: float,
    days: int = 1,
    reference_utc: Optional[datetime] = None,
) -> List[IrradiancePoint]:
    """Fetch hourly GHI for the next planning day(s): 00:00–24:00 each calendar day.

    'Next planning day' is defined as the first full calendar day at or after
    reference_utc (default: now UTC). For a 2-day run, returns day1 (00:00–24:00)
    and day2 (00:00–24:00), etc.

    Args:
        lat: Latitude (from user-selected location, e.g. OpenWeather geocoding).
        lon: Longitude.
        days: Number of consecutive calendar days to fetch.
        reference_utc: Reference time (UTC). If None, uses now UTC.

    Returns:
        Hourly IrradiancePoint list for the requested days (24 * days points).
    """
    if reference_utc is None:
        reference_utc = datetime.now(tz=timezone.utc)
    if reference_utc.tzinfo is None:
        reference_utc = reference_utc.replace(tzinfo=timezone.utc)

    # Next planning day = first full calendar day after today (00:00–24:00 UTC)
    today = reference_utc.date()
    first_planning_day = today + timedelta(days=1)
    last_planning_day = today + timedelta(days=days)
    start_dt = datetime(first_planning_day.year, first_planning_day.month, first_planning_day.day, 0, 0, 0, tzinfo=timezone.utc)
    end_date = datetime(last_planning_day.year, last_planning_day.month, last_planning_day.day, 23, 59, 59, tzinfo=timezone.utc)

    return fetch_ghi_hourly(lat, lon, start_dt, end_date, time_standard="UTC")


def fetch_ghi_historical_window(
    lat: float,
    lon: float,
    reference_utc: Optional[datetime] = None,
    window_days: int = 7,
    lag_days: int = 10,
    time_standard: str = "UTC",
    timeout_seconds: int = 30,
) -> List[IrradiancePoint]:
    """Fetch hourly GHI for a past window (behind NASA POWER solar latency).

    Uses end_date = reference_utc - lag_days, start_date = end_date - (window_days - 1),
    so all requested dates are in the past and within API availability.

    Returns:
        List of IrradiancePoint for each hour in the window (chronological).
    """
    if reference_utc is None:
        reference_utc = datetime.now(tz=timezone.utc)
    if reference_utc.tzinfo is None:
        reference_utc = reference_utc.replace(tzinfo=timezone.utc)
    end_date = reference_utc.date() - timedelta(days=lag_days)
    start_date = end_date - timedelta(days=window_days - 1)
    start_dt = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)
    return fetch_ghi_hourly(lat, lon, start_dt, end_dt, time_standard=time_standard)


def build_hourly_ghi_profile(points: List[IrradiancePoint]) -> Tuple[List[float], List[float], List[float]]:
    """Build hour-of-day mean, min, max from a list of hourly GHI points.

    Returns:
        (mean_24, min_24, max_24) — each a list of 24 floats for hour 0..23.
        If an hour has no data, that hour is 0.0.
    """
    by_hour: List[List[float]] = [[] for _ in range(24)]
    for p in points:
        h = p.ts.hour
        if 0 <= h < 24:
            by_hour[h].append(float(p.ghi_wm2))
    mean_24: List[float] = []
    min_24: List[float] = []
    max_24: List[float] = []
    for h in range(24):
        vals = by_hour[h]
        if vals:
            mean_24.append(sum(vals) / len(vals))
            min_24.append(min(vals))
            max_24.append(max(vals))
        else:
            mean_24.append(0.0)
            min_24.append(0.0)
            max_24.append(0.0)
    return (mean_24, min_24, max_24)


# Minimum plausible peak GHI (W/m²) for a valid historical profile; below this we treat as no data.
_MIN_PEAK_GHI_WM2 = 5.0
# Minimum spread (max - min) over 24h in W/m²; if GHI is constant over the day we treat as inconsistent/fill.
_MIN_GHI_SPREAD_WM2 = 1.0


def _is_valid_mean_profile(mean_24: List[float]) -> bool:
    """True if the 24h mean profile has usable solar and diurnal variation (not all-zero or flat)."""
    if not mean_24 or len(mean_24) != 24:
        return False
    sum_ghi = sum(mean_24)
    max_ghi = max(mean_24)
    min_ghi = min(mean_24)
    spread = max_ghi - min_ghi
    return (
        sum_ghi > 0
        and max_ghi >= _MIN_PEAK_GHI_WM2
        and spread >= _MIN_GHI_SPREAD_WM2
    )


def _mean_profile_to_points(mean_24: List[float], nominal_day: date) -> List[IrradiancePoint]:
    """Build 24 IrradiancePoint for hour 0..23 with given mean GHI and nominal day (UTC)."""
    out: List[IrradiancePoint] = []
    for h in range(24):
        ts = datetime(
            nominal_day.year,
            nominal_day.month,
            nominal_day.day,
            h,
            0,
            0,
            tzinfo=timezone.utc,
        )
        out.append(IrradiancePoint(ts=ts, ghi_wm2=mean_24[h]))
    return out


def expected_ghi_profile_from_history(
    lat: float,
    lon: float,
    reference_utc: Optional[datetime] = None,
    window_days: int = 7,
    lag_days: int = 10,
) -> List[IrradiancePoint]:
    """Build expected 24h GHI profile (mean by hour-of-day) from recent historical window.

    Fetches historical GHI, computes mean per hour 0..23, returns 24 IrradiancePoint
    with nominal timestamps (next calendar day 00:00..23:00 UTC) for use by the
    simulator. If fetch fails, returns no data, or profile is invalid (all-zero),
    returns empty list.

    Returns:
        List of 24 IrradiancePoint (hour 0..23, mean GHI), or [].
    """
    if reference_utc is None:
        reference_utc = datetime.now(tz=timezone.utc)
    if reference_utc.tzinfo is None:
        reference_utc = reference_utc.replace(tzinfo=timezone.utc)
    end_date = reference_utc.date() - timedelta(days=lag_days)
    start_date = end_date - timedelta(days=window_days - 1)
    points = fetch_ghi_historical_window(
        lat=lat,
        lon=lon,
        reference_utc=reference_utc,
        window_days=window_days,
        lag_days=lag_days,
    )
    if not points:
        return []
    mean_24, _, _ = build_hourly_ghi_profile(points)
    max_ghi = max(mean_24) if mean_24 else 0.0
    spread = max_ghi - min(mean_24) if mean_24 else 0.0
    if not _is_valid_mean_profile(mean_24):
        LOG.warning(
            "NASA POWER historical window had no usable GHI (range %s–%s, %d points, max=%.1f W/m², spread=%.1f); using fallback.",
            start_date.isoformat(),
            end_date.isoformat(),
            len(points),
            max_ghi,
            spread,
        )
        return []
    LOG.info(
        "NASA POWER historical GHI: range %s–%s, %d points, max(mean_24)=%.1f W/m²",
        start_date.isoformat(),
        end_date.isoformat(),
        len(points),
        max_ghi,
    )
    nominal_day = reference_utc.date() + timedelta(days=1)
    return _mean_profile_to_points(mean_24, nominal_day)


def _same_day_last_year(ref_date: date) -> date:
    """Same calendar day previous year; if ref_date is Feb 29 and last year is not leap, return Feb 28."""
    try:
        return ref_date.replace(year=ref_date.year - 1)
    except ValueError:
        return date(ref_date.year - 1, 2, 28)


def expected_ghi_profile_from_doy(
    lat: float,
    lon: float,
    reference_utc: Optional[datetime] = None,
    half_window_days: int = 3,
    time_standard: str = "UTC",
    timeout_seconds: int = 30,
) -> List[IrradiancePoint]:
    """Build expected 24h GHI profile from same day-of-year last year (center ± half_window_days), 7-day mean.

    Used as fallback when recent historical window has no usable data. Same validation as primary
    (non-zero, plausible peak, diurnal spread). Returns 24 IrradiancePoint or [].
    """
    if reference_utc is None:
        reference_utc = datetime.now(tz=timezone.utc)
    if reference_utc.tzinfo is None:
        reference_utc = reference_utc.replace(tzinfo=timezone.utc)
    ref_date = reference_utc.date()
    center = _same_day_last_year(ref_date)
    start_date = center - timedelta(days=half_window_days)
    end_date = center + timedelta(days=half_window_days)
    start_dt = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)
    try:
        points = fetch_ghi_hourly(lat, lon, start_dt, end_dt, time_standard=time_standard, timeout_seconds=timeout_seconds)
    except Exception as e:
        LOG.warning("NASA POWER DOY fallback fetch failed (%s); using synthetic.", e)
        return []
    if not points:
        return []
    mean_24, _, _ = build_hourly_ghi_profile(points)
    max_ghi = max(mean_24) if mean_24 else 0.0
    spread = max_ghi - min(mean_24) if mean_24 else 0.0
    if not _is_valid_mean_profile(mean_24):
        LOG.warning(
            "NASA POWER DOY window had no usable GHI (range %s–%s, %d points, max=%.1f W/m², spread=%.1f); using synthetic.",
            start_date.isoformat(),
            end_date.isoformat(),
            len(points),
            max_ghi,
            spread,
        )
        return []
    LOG.info(
        "NASA POWER DOY fallback: range %s–%s, %d points, max(mean_24)=%.1f W/m²",
        start_date.isoformat(),
        end_date.isoformat(),
        len(points),
        max_ghi,
    )
    nominal_day = reference_utc.date() + timedelta(days=1)
    return _mean_profile_to_points(mean_24, nominal_day)
