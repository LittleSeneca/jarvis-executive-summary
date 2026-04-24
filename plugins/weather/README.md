# Weather Plugin

Fetches current conditions and a two-day forecast from [OpenWeatherMap](https://openweathermap.org/) and summarizes them in the morning brief.

## Credentials

| Env var | Required | Notes |
|---------|----------|-------|
| `WEATHER_ZIP_CODE` | Yes | US ZIP or international postal code |
| `WEATHER_API_KEY` | Yes | Free-tier OWM key is sufficient |
| `WEATHER_COUNTRY_CODE` | No | ISO 3166-1 alpha-2; default `US` |
| `WEATHER_UNITS` | No | `imperial` (°F, mph) or `metric` (°C, m/s); default `imperial` |

### Getting an API key

1. Sign up at <https://home.openweathermap.org/users/sign_up> (free tier).
2. Under **API keys**, copy your default key or generate a new one.
3. Free tier allows 60 calls/minute and 1,000,000 calls/month — more than enough for a once-daily run.

## What it fetches

Two OpenWeatherMap API calls per run:

- `/data/2.5/weather` — current conditions (temperature, feels-like, humidity, wind, description)
- `/data/2.5/forecast` — 5-day / 3-hour forecast; reduced by the plugin to today and tomorrow day summaries (high, low, max precipitation probability, representative description)

## Payload shape

```json
{
  "location":  { "zip": "43017", "city": "Dublin", "country": "US" },
  "units":     { "temp": "F", "wind": "mph" },
  "now":       { "temp": 58, "feels_like": 54, "conditions": "Light rain", "wind": 12, "humidity": 81 },
  "today":     { "high": 64, "low": 46, "precip_chance": 0.75, "summary": "Showers clearing by evening" },
  "tomorrow":  { "high": 71, "low": 52, "precip_chance": 0.10, "summary": "Mostly sunny" }
}
```

## Notes

- If Jarvis runs before the day's first forecast bucket appears (rare edge case near midnight UTC), today's summary may show `null` fields; tomorrow will still be populated.
- To swap providers (NOAA, Open-Meteo, WeatherAPI), rewrite `plugin.py` and `auth.py` while keeping the payload shape above unchanged.
