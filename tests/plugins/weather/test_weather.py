"""Tests for the weather plugin."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from jarvis.core.exceptions import PluginAuthError, PluginFetchError
from plugins.weather.plugin import WeatherPlugin, _build_day_buckets, _summarise_slots

_FIXTURES = Path(__file__).parents[3] / "plugins" / "weather" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


@pytest.fixture
def current_fixture():
    return _load("current_weather.json")


@pytest.fixture
def forecast_fixture():
    return _load("forecast.json")


@pytest.fixture
def plugin():
    return WeatherPlugin()


def test_plugin_attributes(plugin):
    assert plugin.name == "weather"
    assert plugin.display_name == "Weather"
    assert "WEATHER_ZIP_CODE" in plugin.required_env_vars
    assert "WEATHER_API_KEY" in plugin.required_env_vars
    assert plugin.temperature == 0.3
    assert plugin.max_tokens == 150


def test_prompt_template_loads(plugin):
    template = plugin.prompt_template()
    assert "{{ payload }}" in template
    assert "{{ metadata }}" in template
    assert "{{ window_hours }}" in template
    assert "{{ today }}" in template


async def test_fetch_returns_correct_shape(plugin, current_fixture, forecast_fixture, monkeypatch):
    monkeypatch.setenv("WEATHER_ZIP_CODE", "43017")
    monkeypatch.setenv("WEATHER_API_KEY", "test_key")

    mock_response_current = MagicMock()
    mock_response_current.raise_for_status = MagicMock()
    mock_response_current.json = MagicMock(return_value=current_fixture)

    mock_response_forecast = MagicMock()
    mock_response_forecast.raise_for_status = MagicMock()
    mock_response_forecast.json = MagicMock(return_value=forecast_fixture)

    call_count = 0

    async def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if "forecast" in url:
            return mock_response_forecast
        return mock_response_current

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("plugins.weather.plugin.get_authenticated_client", return_value=mock_client):
        result = await plugin.fetch(window_hours=24)

    assert result.source_name == "Weather"
    payload = result.raw_payload
    assert "location" in payload
    assert "units" in payload
    assert "now" in payload
    assert "today" in payload
    assert "tomorrow" in payload
    assert payload["location"]["zip"] == "43017"
    assert payload["location"]["city"] == "Dublin"
    assert isinstance(payload["now"]["temp"], int)
    assert isinstance(payload["now"]["humidity"], int)


async def test_fetch_raises_auth_error_on_missing_key(plugin, monkeypatch):
    monkeypatch.delenv("WEATHER_API_KEY", raising=False)
    with pytest.raises(PluginAuthError):
        await plugin.fetch(window_hours=24)


async def test_fetch_raises_auth_error_on_missing_zip(plugin, monkeypatch):
    monkeypatch.setenv("WEATHER_API_KEY", "test_key")
    monkeypatch.delenv("WEATHER_ZIP_CODE", raising=False)
    with pytest.raises(PluginAuthError):
        await plugin.fetch(window_hours=24)


async def test_fetch_raises_fetch_error_on_401(plugin, monkeypatch):
    monkeypatch.setenv("WEATHER_ZIP_CODE", "43017")
    monkeypatch.setenv("WEATHER_API_KEY", "bad_key")

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    http_error = httpx.HTTPStatusError("401", request=MagicMock(), response=mock_resp)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=http_error)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("plugins.weather.plugin.get_authenticated_client", return_value=mock_client):
        with pytest.raises(PluginAuthError):
            await plugin.fetch(window_hours=24)


async def test_fetch_raises_fetch_error_on_network_failure(plugin, monkeypatch):
    monkeypatch.setenv("WEATHER_ZIP_CODE", "43017")
    monkeypatch.setenv("WEATHER_API_KEY", "test_key")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("plugins.weather.plugin.get_authenticated_client", return_value=mock_client):
        with pytest.raises(PluginFetchError):
            await plugin.fetch(window_hours=24)


def test_summarise_slots_empty():
    result = _summarise_slots([], fallback_label="today")
    assert result["high"] is None
    assert result["low"] is None
    assert result["summary"] == "No data"


def test_summarise_slots_picks_midday(forecast_fixture):
    slots = forecast_fixture["list"][:4]
    result = _summarise_slots(slots, fallback_label="today")
    assert result["high"] >= result["low"]
    assert 0.0 <= result["precip_chance"] <= 1.0
    assert isinstance(result["summary"], str)


def test_redact_is_identity(plugin):
    payload = {"location": {"zip": "43017"}, "now": {"temp": 58}}
    assert plugin.redact(payload) == payload
