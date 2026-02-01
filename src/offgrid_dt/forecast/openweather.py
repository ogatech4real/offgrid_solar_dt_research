from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests


@dataclass
class IrradiancePoint:
    ts: datetime
    ghi_wm2: float


class OpenWeatherSolarClient:
    def __init__(self, api_key: str, base_url: str = "https://api.openweathermap.org"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def geocode(self, query: str, limit: int = 5) -> List[dict]:
        """Resolve a place name to candidate coordinates using OpenWeather Geocoding API.

        Returns a list of dicts with keys like: name, lat, lon, country, state.
        """
        url = f"{self.base_url}/geo/1.0/direct"
        r = requests.get(url, params={"q": query, "limit": limit, "appid": self.api_key}, timeout=20)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

    def reverse_geocode(self, lat: float, lon: float, limit: int = 1) -> List[dict]:
        """Resolve coordinates to a human-readable location."""
        url = f"{self.base_url}/geo/1.0/reverse"
        r = requests.get(url, params={"lat": lat, "lon": lon, "limit": limit, "appid": self.api_key}, timeout=20)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

    def current_weather(self, lat: float, lon: float, units: str = "metric") -> dict:
        """Fetch current weather conditions using OpenWeather Current Weather endpoint.

        Returns a dict with keys:
          - description, main, icon
          - temperature_c, humidity_pct, cloud_cover_pct
          - wind_speed_mps
          - sunrise_ts, sunset_ts (unix)
        """
        url = f"{self.base_url}/data/2.5/weather"
        r = requests.get(url, params={
            "lat": lat,
            "lon": lon,
            "appid": self.api_key,
            "units": units,
        }, timeout=20)
        r.raise_for_status()
        data = r.json()
        weather0 = (data.get("weather") or [{}])[0]
        main = data.get("main") or {}
        wind = data.get("wind") or {}
        clouds = data.get("clouds") or {}
        sys = data.get("sys") or {}
        return {
            "main": weather0.get("main", ""),
            "description": weather0.get("description", ""),
            "icon": weather0.get("icon", ""),
            "temperature_c": float(main.get("temp", 0.0) or 0.0),
            "humidity_pct": float(main.get("humidity", 0.0) or 0.0),
            "cloud_cover_pct": float(clouds.get("all", 0.0) or 0.0),
            "wind_speed_mps": float(wind.get("speed", 0.0) or 0.0),
            "sunrise_ts": int(sys.get("sunrise", 0) or 0),
            "sunset_ts": int(sys.get("sunset", 0) or 0),
        }

    def fetch_irradiance_forecast(self, lat: float, lon: float, hours: int = 24) -> List[IrradiancePoint]:
        candidates = [
            f"{self.base_url}/data/2.5/solar/forecast",
            f"{self.base_url}/data/2.5/solar",
            f"{self.base_url}/energy/1.0/solar/forecast",
        ]
        last_err: Optional[Exception] = None
        for url in candidates:
            try:
                r = requests.get(
                    url,
                    params={"lat": lat, "lon": lon, "appid": self.api_key, "hours": hours},
                    timeout=20,
                )
                if r.status_code >= 400:
                    continue
                data = r.json()
                points = _parse_openweather_irradiance(data)
                if points:
                    return points
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError("Unable to retrieve irradiance forecast from OpenWeather.") from last_err


def _parse_openweather_irradiance(data: dict) -> List[IrradiancePoint]:
    points: List[IrradiancePoint] = []
    if isinstance(data, dict) and "list" in data and isinstance(data["list"], list):
        for item in data["list"]:
            ts = _ts_from_any(item.get("dt"))
            ghi = item.get("ghi") or item.get("GHI") or item.get("global_horizontal_irradiance")
            if ts and ghi is not None:
                points.append(IrradiancePoint(ts=ts, ghi_wm2=float(ghi)))
        return points

    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
        for item in data["data"]:
            ts = _ts_from_any(item.get("date") or item.get("dt"))
            irr = item.get("irradiance", {}) if isinstance(item, dict) else {}
            ghi = irr.get("ghi") if isinstance(irr, dict) else None
            if ts and ghi is not None:
                points.append(IrradiancePoint(ts=ts, ghi_wm2=float(ghi)))
        return points

    return points


def _ts_from_any(v) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(float(v), tz=timezone.utc)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None
    return None


def synthetic_irradiance_forecast(
    start: datetime,
    hours: int = 24,
    step_minutes: int = 60,
    peak_ghi_wm2: float = 850.0,
) -> List[IrradiancePoint]:
    """Generate a deterministic, reproducible irradiance forecast.

    Important: the simulator typically runs at 15-min resolution. This function therefore
    supports arbitrary step sizes. If you request 24 hours with step_minutes=15,
    you'll get 96 points.
    """
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    step_minutes = max(1, int(step_minutes))
    total_steps = int(round((hours * 60) / step_minutes))
    points: List[IrradiancePoint] = []
    for i in range(total_steps):
        ts = start + timedelta(minutes=i * step_minutes)

        # Simple bell-shaped daytime curve (06:00–18:00) at *time-of-day* resolution.
        hour = ts.hour + ts.minute / 60.0
        if 6.0 <= hour <= 18.0:
            x = (hour - 6.0) / 12.0
            ghi = peak_ghi_wm2 * (4.0 * x * (1.0 - x))
        else:
            ghi = 0.0

        points.append(IrradiancePoint(ts=ts, ghi_wm2=float(max(0.0, ghi))))
    return points
