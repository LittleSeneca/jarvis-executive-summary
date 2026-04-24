# Weather Plugin

Fetches current conditions and a two-day forecast from [Open-Meteo](https://open-meteo.com/) — **no API key required**.

ZIP codes are resolved to coordinates via [Nominatim](https://nominatim.openstreetmap.org/) (OpenStreetMap's free geocoding service, also keyless).

## Credentials

None. No API keys, no sign-up, no rate-limit tokens.

## Configuration

| Env var | Required | Notes |
|---------|----------|-------|
| `WEATHER_ZIP_CODE` | Yes | US ZIP or international postal code |
| `WEATHER_COUNTRY_CODE` | No | ISO 3166-1 alpha-2; default `US` |
| `WEATHER_UNITS` | No | `imperial` (°F, mph) or `metric` (°C, m/s); default `imperial` |

## What it fetches

Two HTTP calls per run (no API key on either):

1. **Nominatim geocoding** — resolves the ZIP code to latitude/longitude and a human-readable city name.
2. **Open-Meteo forecast** — single call returning current conditions + today/tomorrow daily summary.

Open-Meteo returns WMO weather codes; the plugin maps them to plain-English descriptions (`"Light rain"`, `"Partly cloudy"`, etc.).

## Payload shape

```json
{
  "location":  { "zip": "43017", "city": "Dublin", "country": "US" },
  "units":     { "temp": "F", "wind": "mph" },
  "now":       { "temp": 58, "feels_like": 54, "conditions": "Light rain", "wind": 12, "humidity": 81 },
  "today":     { "high": 64, "low": 46, "precip_chance": 0.75, "summary": "Moderate rain" },
  "tomorrow":  { "high": 71, "low": 52, "precip_chance": 0.10, "summary": "Mainly clear" }
}
```

## Provider swap

To swap back to OpenWeatherMap or another provider, rewrite `plugin.py` and `auth.py` — the payload shape above is the contract the rest of the pipeline depends on.
