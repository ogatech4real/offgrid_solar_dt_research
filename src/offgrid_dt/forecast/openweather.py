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


def synthetic_irradiance_forecast(start: datetime, hours: int = 24, peak_ghi_wm2: float = 850.0) -> List[IrradiancePoint]:
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    points: List[IrradiancePoint] = []
    for h in range(hours):
        ts = start + timedelta(hours=h)
        hour = ts.hour
        if 6 <= hour <= 18:
            x = (hour - 6) / 12.0
            ghi = peak_ghi_wm2 * (4 * x * (1 - x))
        else:
            ghi = 0.0
        points.append(IrradiancePoint(ts=ts, ghi_wm2=float(max(0.0, ghi))))
    return points
