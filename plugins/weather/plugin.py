"""Weather data-source plugin — current conditions and two-day outlook."""

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

import httpx

from jarvis.core.exceptions import PluginAuthError, PluginFetchError
from jarvis.core.plugin import DataSourcePlugin, FetchResult

from .auth import get_authenticated_client

__all__ = ["WeatherPlugin"]

log = logging.getLogger(__name__)

_IMPERIAL_LABELS = {"temp": "F", "wind": "mph"}
_METRIC_LABELS = {"temp": "C", "wind": "m/s"}


class WeatherPlugin(DataSourcePlugin):
    """Fetch current conditions and two-day forecast from OpenWeatherMap."""

    name = "weather"
    display_name = "Weather"
    required_env_vars = ["WEATHER_ZIP_CODE", "WEATHER_API_KEY"]
    temperature = 0.3
    max_tokens = 150

    async def fetch(self, window_hours: int) -> FetchResult:
        """Pull current conditions and today/tomorrow forecast for the configured ZIP."""
        zip_code = os.environ.get("WEATHER_ZIP_CODE", "").strip()
        country = os.environ.get("WEATHER_COUNTRY_CODE", "US").strip() or "US"
        units = os.environ.get("WEATHER_UNITS", "imperial").strip().lower() or "imperial"

        if not zip_code:
            raise PluginAuthError("WEATHER_ZIP_CODE is not set")

        location_q = f"{zip_code},{country}"
        unit_labels = _IMPERIAL_LABELS if units == "imperial" else _METRIC_LABELS

        try:
            client = get_authenticated_client()
        except PluginAuthError:
            raise

        try:
            async with client:
                current, forecast = await _fetch_both(client, location_q, units)
        except PluginAuthError:
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise PluginAuthError("OpenWeatherMap rejected the API key (401)") from exc
            raise PluginFetchError(
                "OpenWeatherMap HTTP error %s" % exc.response.status_code
            ) from exc
        except httpx.RequestError as exc:
            raise PluginFetchError("Network error reaching OpenWeatherMap: %s" % exc) from exc
        except Exception as exc:
            log.exception("Unexpected error in weather fetch")
            raise PluginFetchError("Unexpected error in weather fetch: %s" % exc) from exc

        city = current.get("name", zip_code)
        sys_info = current.get("sys", {})
        resolved_country = sys_info.get("country", country)

        now_main = current.get("main", {})
        now_wind = current.get("wind", {})
        now_weather = current.get("weather", [{}])[0]

        now_block = {
            "temp": round(now_main.get("temp", 0)),
            "feels_like": round(now_main.get("feels_like", 0)),
            "conditions": now_weather.get("description", "").capitalize(),
            "wind": round(now_wind.get("speed", 0)),
            "humidity": now_main.get("humidity", 0),
        }

        today_block, tomorrow_block = _build_day_buckets(forecast.get("list", []))

        payload = {
            "location": {"zip": zip_code, "city": city, "country": resolved_country},
            "units": unit_labels,
            "now": now_block,
            "today": today_block,
            "tomorrow": tomorrow_block,
        }

        log.info("Weather fetch complete for %s, %s", zip_code, resolved_country)
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


async def _fetch_both(
    client: httpx.AsyncClient, location_q: str, units: str
) -> tuple[dict, dict]:
    """Fetch current weather and forecast in parallel."""
    params = {"zip": location_q, "units": units}

    async def _get_current():
        resp = await client.get("/data/2.5/weather", params=params)
        resp.raise_for_status()
        return resp.json()

    async def _get_forecast():
        resp = await client.get("/data/2.5/forecast", params=params)
        resp.raise_for_status()
        return resp.json()

    current, forecast = await asyncio.gather(_get_current(), _get_forecast())
    return current, forecast


def _build_day_buckets(forecast_list: list[dict]) -> tuple[dict, dict]:
    """Reduce 3-hour forecast slots into today and tomorrow day summaries."""
    now_utc = datetime.now(UTC)
    today_date = now_utc.date()
    tomorrow_date = today_date + timedelta(days=1)

    today_slots: list[dict] = []
    tomorrow_slots: list[dict] = []

    for slot in forecast_list:
        dt = datetime.fromtimestamp(slot["dt"], tz=UTC)
        if dt.date() == today_date:
            today_slots.append(slot)
        elif dt.date() == tomorrow_date:
            tomorrow_slots.append(slot)

    return _summarise_slots(today_slots, fallback_label="today"), _summarise_slots(
        tomorrow_slots, fallback_label="tomorrow"
    )


def _summarise_slots(slots: list[dict], fallback_label: str) -> dict:
    """Collapse a list of 3-hour forecast slots into a single day summary."""
    if not slots:
        return {"high": None, "low": None, "precip_chance": None, "summary": "No data"}

    temps = [s["main"]["temp"] for s in slots]
    pop_values = [s.get("pop", 0.0) for s in slots]
    descriptions = [s["weather"][0]["description"] for s in slots if s.get("weather")]

    high = round(max(temps))
    low = round(min(temps))
    precip_chance = round(max(pop_values), 2)

    # Pick the most representative description (mode of midday slots, then fallback to first)
    midday_slots = [s for s in slots if 10 <= datetime.fromtimestamp(s["dt"], tz=UTC).hour <= 15]
    if midday_slots:
        summary = midday_slots[0]["weather"][0]["description"].capitalize()
    elif descriptions:
        summary = descriptions[len(descriptions) // 2].capitalize()
    else:
        summary = "Unknown"

    return {
        "high": high,
        "low": low,
        "precip_chance": precip_chance,
        "summary": summary,
    }
