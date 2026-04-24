"""Weather data-source plugin — current conditions and two-day outlook via Open-Meteo."""

import asyncio
import logging
import os
from datetime import UTC, datetime

import httpx

from jarvis.core.exceptions import PluginFetchError
from jarvis.core.plugin import DataSourcePlugin, FetchResult

from .auth import get_authenticated_client

__all__ = ["WeatherPlugin"]

log = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# WMO Weather Interpretation Codes → human-readable description
_WMO = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Light rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Light snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Light showers", 81: "Moderate showers", 82: "Heavy showers",
    85: "Light snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}

_IMPERIAL_LABELS = {"temp": "F", "wind": "mph"}
_METRIC_LABELS = {"temp": "C", "wind": "m/s"}


class WeatherPlugin(DataSourcePlugin):
    """Fetch current conditions and two-day forecast from Open-Meteo (no API key required)."""

    name = "weather"
    display_name = "Weather"
    required_env_vars = ["WEATHER_ZIP_CODE"]
    temperature = 0.3
    max_tokens = 150

    async def fetch(self, window_hours: int) -> FetchResult:
        """Pull current conditions and today/tomorrow forecast for the configured ZIP."""
        zip_code = os.environ.get("WEATHER_ZIP_CODE", "").strip()
        country = os.environ.get("WEATHER_COUNTRY_CODE", "US").strip() or "US"
        units = os.environ.get("WEATHER_UNITS", "imperial").strip().lower() or "imperial"

        if not zip_code:
            raise PluginFetchError("WEATHER_ZIP_CODE is not set")

        unit_labels = _IMPERIAL_LABELS if units == "imperial" else _METRIC_LABELS

        try:
            async with get_authenticated_client() as client:
                lat, lon, city = await _geocode(client, zip_code, country)
                data = await _fetch_weather(client, lat, lon, units)
        except PluginFetchError:
            raise
        except httpx.HTTPStatusError as exc:
            raise PluginFetchError("Weather API HTTP error %s" % exc.response.status_code) from exc
        except httpx.RequestError as exc:
            raise PluginFetchError("Network error fetching weather: %s" % exc) from exc
        except Exception as exc:
            log.exception("Unexpected error in weather fetch")
            raise PluginFetchError("Unexpected error in weather fetch: %s" % exc) from exc

        current = data["current"]
        daily = data["daily"]

        now_block = {
            "temp": round(current["temperature_2m"]),
            "feels_like": round(current["apparent_temperature"]),
            "conditions": _WMO.get(current["weather_code"], "Unknown"),
            "wind": round(current["wind_speed_10m"]),
            "humidity": current["relative_humidity_2m"],
        }

        # daily arrays are indexed [0]=today, [1]=tomorrow
        today_block = {
            "high": round(daily["temperature_2m_max"][0]),
            "low": round(daily["temperature_2m_min"][0]),
            "precip_chance": round(daily["precipitation_probability_max"][0] / 100, 2),
            "summary": _WMO.get(daily["weather_code"][0], "Unknown"),
        }
        tomorrow_block = {
            "high": round(daily["temperature_2m_max"][1]),
            "low": round(daily["temperature_2m_min"][1]),
            "precip_chance": round(daily["precipitation_probability_max"][1] / 100, 2),
            "summary": _WMO.get(daily["weather_code"][1], "Unknown"),
        }

        payload = {
            "location": {"zip": zip_code, "city": city, "country": country},
            "units": unit_labels,
            "now": now_block,
            "today": today_block,
            "tomorrow": tomorrow_block,
        }

        log.info("Weather fetch complete for %s (%s, %s)", zip_code, city, country)
        return FetchResult(
            source_name=self.display_name,
            raw_payload=payload,
            metadata={
                "zip": zip_code,
                "city": city,
                "units": units,
                "fetched_at": datetime.now(UTC).isoformat(),
            },
        )


async def _geocode(client: httpx.AsyncClient, zip_code: str, country: str) -> tuple[float, float, str]:
    """Resolve a ZIP code to (lat, lon, city) via Nominatim."""
    resp = await client.get(
        _NOMINATIM_URL,
        params={
            "postalcode": zip_code,
            "countrycodes": country.lower(),
            "format": "json",
            "limit": 1,
            "addressdetails": 1,
        },
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        raise PluginFetchError("No geocoding results for ZIP %s" % zip_code)

    hit = results[0]
    lat = float(hit["lat"])
    lon = float(hit["lon"])

    addr = hit.get("address", {})
    city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("county") or zip_code

    return lat, lon, city


async def _fetch_weather(client: httpx.AsyncClient, lat: float, lon: float, units: str) -> dict:
    """Fetch current conditions and two-day daily forecast from Open-Meteo."""
    temp_unit = "fahrenheit" if units == "imperial" else "celsius"
    wind_unit = "mph" if units == "imperial" else "ms"

    resp = await client.get(
        _OPEN_METEO_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
            "temperature_unit": temp_unit,
            "wind_speed_unit": wind_unit,
            "timezone": "auto",
            "forecast_days": 2,
        },
    )
    resp.raise_for_status()
    return resp.json()
